"""ABAP object adapter registry and attribute lifecycle analysis.

Standard-library-only module providing:
* an adapter capability registry (ADAPTER_REGISTRY / get_adapter),
* lifecycle analysis for ABAP class attributes (analyze_attribute_lifecycle).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class UnsupportedAbapCapabilityError(Exception):
    """Raised when an ABAP adapter does not support a requested capability."""


@dataclass(frozen=True)
class AdapterSpec:
    object_type: str
    uri_template: str
    lock_granularity: str
    patch_enabled: bool

    def require(self, capability: str) -> None:
        """Raise unless *capability* is supported by this adapter.

        The ``patch`` capability is compared case-insensitively after
        stripping surrounding whitespace.
        """
        if capability.strip().lower() == "patch" and not self.patch_enabled:
            raise UnsupportedAbapCapabilityError(
                f"adapter {self.object_type!r} does not support capability {capability!r}"
            )


_ADAPTER_ENTRIES: tuple[tuple[str, str, str, bool], ...] = (
    ("CLAS", "/sap/bc/adt/oo/classes/{name}", "CLASS_ROOT_AND_INCLUDES", True),
    ("INTF", "/sap/bc/adt/oo/interfaces/{name}", "INTERFACE_ROOT", False),
    ("PROG", "/sap/bc/adt/programs/programs/{name}", "PROGRAM_AND_INCLUDES", False),
    ("FUGR", "/sap/bc/adt/functions/groups/{name}", "FUNCTION_GROUP_TOP_AND_UXX", False),
    ("TABL", "/sap/bc/adt/ddic/tables/{name}", "DDIC_TABLE_CONVERSION_GUARD", False),
    ("DTEL", "/sap/bc/adt/ddic/dataelements/{name}", "DDIC_MASS_ACTIVATION", False),
    ("DOMA", "/sap/bc/adt/ddic/domains/{name}", "DDIC_MASS_ACTIVATION", False),
    ("DDLS", "/sap/bc/adt/ddic/ddl/sources/{name}", "CDS_HIERARCHY_GRAPH", False),
    ("DCLS", "/sap/bc/adt/acm/dcl/sources/{name}", "DCL_ACCESS_CONTROL", False),
    (
        "BDEF",
        "/sap/bc/adt/bo/behaviordefinitions/{name}",
        "RAP_BO_COORDINATED_ACTIVATION",
        False,
    ),
    ("SRVD", "/sap/bc/adt/ddic/srvd/sources/{name}", "RAP_SERVICE_BINDING", False),
)

ADAPTER_REGISTRY: dict[str, AdapterSpec] = {
    object_type: AdapterSpec(object_type, uri, lock, patch)
    for object_type, uri, lock, patch in _ADAPTER_ENTRIES
}


def get_adapter(object_type: str) -> AdapterSpec:
    key = object_type.strip().upper()
    try:
        return ADAPTER_REGISTRY[key]
    except KeyError as exc:
        raise UnsupportedAbapCapabilityError(
            f"unknown ABAP object type {object_type!r}"
        ) from exc


_SECTION_RE = re.compile(r"\b(PUBLIC|PROTECTED|PRIVATE)\s+SECTION\b", re.IGNORECASE)
_CLASS_DEF_RE = re.compile(
    r"\bCLASS\s+\w+\s+DEFINITION\b(?!\s+(?:DEFERRED|LOAD)\b)", re.IGNORECASE
)
_CLASS_IMPL_RE = re.compile(r"\bCLASS\s+\w+\s+IMPLEMENTATION\b", re.IGNORECASE)
_ENDCLASS_RE = re.compile(r"\bENDCLASS\b", re.IGNORECASE)
_DECL_START_RE = re.compile(r"^\s*(?:CLASS-DATA|DATA)\b", re.IGNORECASE)
_METHOD_RE = re.compile(r"^\s*METHOD\s+(\w+)\s*\.\s*$", re.IGNORECASE)
_ENDMETHOD_RE = re.compile(r"^\s*ENDMETHOD\b", re.IGNORECASE)


def _strip_abap_comment(line: str) -> str:
    """Return *line* with ABAP comments removed.

    A line whose first character is ``*`` is a full-line comment.  Otherwise a
    ``"`` starts a comment only when it is not inside a single-quoted,
    backquoted or pipe-delimited string literal.
    """
    if line.startswith("*"):
        return ""
    out: list[str] = []
    state = "normal"
    i = 0
    while i < len(line):
        ch = line[i]
        if state == "normal":
            if ch == "'":
                state = "sq"
                out.append(ch)
            elif ch == "`":
                state = "bq"
                out.append(ch)
            elif ch == "|":
                state = "pipe"
                out.append(ch)
            elif ch == '"':
                break
            else:
                out.append(ch)
            i += 1
        elif state == "sq":
            out.append(ch)
            if ch == "'":
                if i + 1 < len(line) and line[i + 1] == "'":
                    out.append(line[i + 1])
                    i += 2
                    continue
                state = "normal"
            i += 1
        elif state == "bq":
            out.append(ch)
            if ch == "`":
                state = "normal"
            i += 1
        else:  # state == "pipe"
            out.append(ch)
            if ch == "|":
                state = "normal"
            i += 1
    return "".join(out)


def analyze_attribute_lifecycle(source: str, name: str) -> dict:
    lines = source.splitlines()
    name_upper = name.upper()

    # --- locate DEFINITION / IMPLEMENTATION parts -------------------------
    def_start = def_end = impl_start = impl_end = None
    for i, raw in enumerate(lines):
        stripped = _strip_abap_comment(raw)
        if def_start is None and _CLASS_DEF_RE.search(stripped):
            def_start = i
        elif def_start is not None and def_end is None and _ENDCLASS_RE.search(stripped):
            def_end = i
        elif def_end is not None and impl_start is None and _CLASS_IMPL_RE.search(stripped):
            impl_start = i
        elif impl_start is not None and impl_end is None and _ENDCLASS_RE.search(stripped):
            impl_end = i
            break

    # --- attribute declaration inside the DEFINITION part -----------------
    section: str | None = None
    found = False
    type_part = ""
    if def_start is not None and def_end is not None:
        i = def_start + 1
        while i < def_end and not found:
            stripped = _strip_abap_comment(lines[i])
            sm = _SECTION_RE.search(stripped)
            if sm:
                section = sm.group(1).upper()
            dm = _DECL_START_RE.match(stripped)
            if dm:
                # A declaration statement may span several lines up to its period.
                stmt_lines = [stripped]
                k = i
                while k + 1 < def_end and "." not in stmt_lines[-1]:
                    k += 1
                    stmt_lines.append(_strip_abap_comment(lines[k]))
                stmt = " ".join(stmt_lines).strip()
                if stmt.endswith("."):
                    stmt = stmt[:-1].strip()
                km = re.match(r"\s*(?:CLASS-DATA|DATA)\s*", stmt, re.IGNORECASE)
                rest = stmt[km.end():]
                # Chained declarations use a colon and comma separation.
                if rest.startswith(":"):
                    parts = [p.strip() for p in rest[1:].split(",")]
                else:
                    parts = [rest.strip()]
                for part in parts:
                    if not part:
                        continue
                    pm = re.match(
                        r"^(\w+)\s+(?:TYPE|LIKE)\b\s*(.*)$",
                        part,
                        re.IGNORECASE,
                    )
                    if pm and pm.group(1).upper() == name_upper:
                        type_part = pm.group(2).strip()
                        found = True
                        break
            i += 1

    if not found:
        raise KeyError(name)

    # --- table kind (TYPE part only) --------------------------------------
    up = type_part.upper()
    if "HASHED TABLE" in up:
        table_kind = "HASHED"
    elif "SORTED TABLE" in up:
        table_kind = "SORTED"
    elif "STANDARD TABLE" in up:
        table_kind = "STANDARD"
    elif "TYPE TABLE OF" in up:
        table_kind = "STANDARD"
    elif "TABLE" in up:
        table_kind = "UNKNOWN"
    else:
        table_kind = "SCALAR"

    resolved_section = section if section is not None else "PUBLIC"
    subclass_accessible = resolved_section in ("PUBLIC", "PROTECTED")

    # --- whole-word symbol patterns ---------------------------------------
    lb = r"(?<![A-Za-z0-9_])"
    trail = r"(?!-)"
    nb = re.escape(name)

    insert_re = re.compile(
        lb + r"(?:\bAPPEND\b.*?\bTO\s+|\bINSERT\b.*?\bINTO\s+TABLE\s+)"
        + nb + trail,
        re.IGNORECASE,
    )
    read_re = re.compile(
        lb + r"(?:\bREAD\s+TABLE\s+|\bLOOP\s+AT\s+)" + nb + trail
        + r"|" + lb + nb + r"\s*\[",
        re.IGNORECASE,
    )
    mutate_re = re.compile(
        lb + r"\b(?:MODIFY\s+TABLE|DELETE\s+TABLE|MODIFY|DELETE|CLEAR|FREE|SORT)\s+"
        + nb + trail,
        re.IGNORECASE,
    )
    consumer_re = re.compile(lb + nb + trail, re.IGNORECASE)

    # --- scan the IMPLEMENTATION part -------------------------------------
    inserts: list[tuple[str, int]] = []
    reads: list[tuple[str, int]] = []
    mutations: list[tuple[str, int]] = []
    bodies: dict[str, list[str]] = {}
    current_method: str | None = None

    if impl_start is not None and impl_end is not None:
        for i in range(impl_start + 1, impl_end):
            stripped = _strip_abap_comment(lines[i])
            line_no = i + 1
            mm = _METHOD_RE.match(stripped)
            if mm:
                current_method = mm.group(1).lower()
                bodies.setdefault(current_method, [])
                continue
            if _ENDMETHOD_RE.match(stripped):
                current_method = None
                continue
            if current_method is None:
                continue
            bodies[current_method].append(stripped)
            if insert_re.search(stripped):
                inserts.append((current_method, line_no))
            if read_re.search(stripped):
                reads.append((current_method, line_no))
            if mutate_re.search(stripped):
                mutations.append((current_method, line_no))

    consumers = sorted(
        method
        for method, body_lines in bodies.items()
        if consumer_re.search("\n".join(body_lines))
    )

    return {
        "section": resolved_section,
        "subclass_accessible": subclass_accessible,
        "table_kind": table_kind,
        "inserts": inserts,
        "reads": reads,
        "mutations": mutations,
        "consumers": consumers,
    }
