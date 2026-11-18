"""Statically evaluate a tiny subset of ABAP boolean conditions.

Standard library only (re). No eval/exec/compile.
"""

import re

__all__ = ["ExprError", "eval_condition", "branch_rule"]


class ExprError(ValueError):
    """Raised when a condition cannot be parsed or evaluated."""


_KEYWORDS = frozenset({"and", "or", "not", "eq", "ne", "ca", "na"})
_COMPARISON_OPS = frozenset({"eq", "ne", "ca", "na"})


def _tokenize(expr):
    """Convert a condition string into a list of tokens.

    Tokens are tuples: ("ref",), ("lit", value), ("op", "eq|ne|ca|na"),
    ("kw", "and|or|not"), ("lp",), ("rp",).
    """
    tokens = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            tokens.append(("lp",))
            i += 1
            continue
        if c == ")":
            tokens.append(("rp",))
            i += 1
            continue
        if c == "=":
            tokens.append(("op", "eq"))
            i += 1
            continue
        if c == "<":
            if i + 1 < n and expr[i + 1] == ">":
                tokens.append(("op", "ne"))
                i += 2
                continue
            raise ExprError(f"unexpected character {c!r}")
        if c == "'":
            j = i + 1
            chars = []
            closed = False
            while j < n:
                if expr[j] == "'":
                    if j + 1 < n and expr[j + 1] == "'":
                        chars.append("'")
                        j += 2
                        continue
                    else:
                        closed = True
                        j += 1
                        break
                chars.append(expr[j])
                j += 1
            if not closed:
                raise ExprError("unterminated string literal")
            tokens.append(("lit", "".join(chars)))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (
                expr[j].isalpha() or expr[j].isdigit() or expr[j] == "_"
            ):
                j += 1
            word = expr[i:j]
            low = word.lower()
            k = j
            while k < n and expr[k].isspace():
                k += 1
            if low == "mv_package" and k < n and expr[k] == "(":
                l = k + 1
                while l < n and expr[l].isspace():
                    l += 1
                m = l
                while m < n and expr[m].isdigit():
                    m += 1
                if m == l:
                    raise ExprError("mv_package requires an offset")
                offset = expr[l:m]
                while m < n and expr[m].isspace():
                    m += 1
                if m >= n or expr[m] != ")":
                    raise ExprError("mv_package( offset ) expected")
                if offset != "1":
                    raise ExprError("only mv_package(1) is supported")
                tokens.append(("ref",))
                i = m + 1
                continue
            if low in _KEYWORDS:
                if low in _COMPARISON_OPS:
                    tokens.append(("op", low))
                else:
                    tokens.append(("kw", low))
                i = j
                continue
            raise ExprError(f"unsupported identifier {word!r}")
        raise ExprError(f"unexpected character {c!r}")
    return tokens


def _parse(tokens):
    """Recursive descent parser: OR > AND > NOT > comparison > atom."""
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def consume():
        nonlocal pos
        if pos >= len(tokens):
            raise ExprError("unexpected end of condition")
        tok = tokens[pos]
        pos += 1
        return tok

    def parse_or():
        node = parse_and()
        while (t := peek()) is not None and t[0] == "kw" and t[1] == "or":
            consume()
            node = ("or", node, parse_and())
        return node

    def parse_and():
        node = parse_not()
        while (t := peek()) is not None and t[0] == "kw" and t[1] == "and":
            consume()
            node = ("and", node, parse_not())
        return node

    def parse_not():
        t = peek()
        if t is not None and t[0] == "kw" and t[1] == "not":
            consume()
            return ("not", parse_not())
        return parse_cmp()

    def parse_cmp():
        left = parse_atom()
        t = peek()
        if t is not None and t[0] == "op":
            consume()
            right = parse_atom()
            return ("cmp", t[1], left, right)
        return left

    def parse_atom():
        t = peek()
        if t is None:
            raise ExprError("expected an operand")
        if t[0] == "lp":
            consume()
            node = parse_or()
            if peek() is None or peek()[0] != "rp":
                raise ExprError("unbalanced parentheses")
            consume()
            return node
        if t[0] in ("ref", "lit"):
            consume()
            return t
        raise ExprError("expected an operand")

    node = parse_or()
    if pos != len(tokens):
        raise ExprError("leftover tokens")
    return node


def _eval(node, char):
    kind = node[0]
    if kind == "ref":
        return char
    if kind == "lit":
        return node[1]
    if kind == "cmp":
        op = node[1]
        left = node[2]
        right = node[3]
        if left[0] != "ref" or right[0] != "lit":
            raise ExprError("comparison operands must be mv_package(1) and a string literal")
        left_value = _eval(left, char)
        right_value = _eval(right, char)
        if op == "eq":
            return left_value.rstrip(" ") == right_value.rstrip(" ")
        if op == "ne":
            return left_value.rstrip(" ") != right_value.rstrip(" ")
        if op == "ca":
            return left_value in right_value
        if op == "na":
            return left_value not in right_value
        raise ExprError(f"unsupported operator {op!r}")
    if kind == "not":
        value = _eval(node[1], char)
        if not isinstance(value, bool):
            raise ExprError("NOT requires a boolean operand")
        return not value
    if kind == "and":
        left_value = _eval(node[1], char)
        right_value = _eval(node[2], char)
        if not isinstance(left_value, bool) or not isinstance(right_value, bool):
            raise ExprError("AND requires boolean operands")
        return left_value and right_value
    if kind == "or":
        left_value = _eval(node[1], char)
        right_value = _eval(node[2], char)
        if not isinstance(left_value, bool) or not isinstance(right_value, bool):
            raise ExprError("OR requires boolean operands")
        return left_value or right_value
    raise ExprError("invalid condition")


def eval_condition(expr: str, mv_package: str) -> bool:
    """Statically evaluate a boolean condition about mv_package(1)."""
    char = mv_package[0] if mv_package else " "
    tokens = _tokenize(expr)
    if not tokens:
        raise ExprError("empty condition")
    ast = _parse(tokens)
    result = _eval(ast, char)
    if not isinstance(result, bool):
        raise ExprError("condition does not evaluate to a boolean")
    return bool(result)


_METHOD_RE = re.compile(r"\bMETHOD\s+([A-Za-z0-9_~]+)\.", re.IGNORECASE)
_ENDMETHOD_RE = re.compile(r"\bENDMETHOD\.", re.IGNORECASE)


def branch_rule(source: str, method: str, when: int) -> str:
    """Extract the boolc( ... ) condition of a WHEN branch in a method.

    Raises ExprError if the method, branch, or boolc( is not found.
    """
    method_l = method.lower()
    start = end = None
    for m in _METHOD_RE.finditer(source):
        name = m.group(1).lower()
        if name == method_l or name.endswith("~" + method_l):
            start = m.start()
            em = _ENDMETHOD_RE.search(source, start)
            if em is None:
                raise ExprError(f"method {method!r} has no ENDMETHOD")
            end = em.end()
            break
    if start is None:
        raise ExprError(f"method {method!r} not found")

    block = source[start:end]
    when_re = re.compile(
        r"\bWHEN\s+" + re.escape(str(when)) + r"\.", re.IGNORECASE
    )
    wm = when_re.search(block)
    if wm is None:
        raise ExprError(f"WHEN {when} branch not found")

    rest = block[wm.end():]
    end_offset = None
    for pat in (r"\bWHEN\b", r"\bENDCASE\b"):
        mm = re.search(pat, rest, re.IGNORECASE)
        if mm is not None and (end_offset is None or mm.start() < end_offset):
            end_offset = mm.start()
    branch = rest if end_offset is None else rest[:end_offset]

    bm = re.search(r"boolc\s*\(", branch)
    if bm is None:
        raise ExprError("no boolc( in branch")

    i = bm.end()
    depth = 1
    in_literal = False
    while i < len(branch):
        c = branch[i]
        if in_literal:
            if c == "'":
                if i + 1 < len(branch) and branch[i + 1] == "'":
                    i += 2
                    continue
                in_literal = False
            i += 1
            continue
        if c == "'":
            in_literal = True
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                inner = branch[bm.end():i]
                return " ".join(inner.split())
        i += 1
    raise ExprError("unbalanced parentheses in boolc(")
