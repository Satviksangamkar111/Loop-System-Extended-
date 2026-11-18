"""Shared pieces of the automatic bench (manifest helpers, outside-the-allowed-methods check) and the generic negative controls.

See docs/sap/AUTO_BENCH_CONTRACT.md, section 2 "B". Used by tests/acceptance/sap_auto_acceptance.py and by
sap_heldout.run_manifest. generic_controls(manifest) writes the control files under tests/controls_auto/<id>/
and returns negative_controls entries in the job-file format.
"""
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCEPT = "tests/acceptance/sap_auto_acceptance.py"
CONTROLS_ROOT_ENV = "SAP_AUTO_CONTROLS_ROOT"  # test hook; default tests/controls_auto
TIMEOUT_S = 240

try:
    import abap_transpile_run as t
except ImportError:  # imported by path from elsewhere
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import abap_transpile_run as t  # noqa: E402


class ControlsError(ValueError):
    """The manifest or the original file does not allow the controls to be built."""


# ---------------------------------------------------------------- manifest helpers
_REQUIRED = ("id", "production_file", "work_file", "original_sha256", "test_files", "allowed_methods", "runner")


def load_manifest(path) -> dict:
    """Read manifest.json (only the contract's keys) and check the held-out set (non-empty proper subset of new_methods)."""
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if k not in m]
    if missing:
        raise ControlsError(f"manifest lacks keys: {missing}")
    new_all = []
    for tf in m["test_files"]:
        new = [x.lower() for x in tf["new_methods"]]
        held = [x.lower() for x in tf["heldout_methods"]]
        # 2026-11-17 rule (docs/sap/PASS_RULE.md): intake chooses the held-out set; it must be a non-empty proper subset of the new methods
        if not held or not set(held) <= set(new) or set(held) == set(new):
            raise ControlsError(f"heldout_methods of {tf['path']} must be a non-empty proper subset of its new methods")
        new_all += new
    if len(new_all) < 2:
        raise ControlsError("a bench needs at least two new test methods")
    return m


def _lower(xs):
    return [x.lower() for x in xs]


def new_methods(m) -> list[str]:
    return [x for tf in m["test_files"] for x in _lower(tf["new_methods"])]


def heldout_methods(m) -> list[str]:
    return [x for tf in m["test_files"] for x in _lower(tf["heldout_methods"])]


def acceptance_methods(m) -> list[str]:
    held = set(heldout_methods(m))
    return [x for x in new_methods(m) if x not in held]


def work_path(m) -> Path:
    return ROOT / m["work_file"]


def controls_dir(m) -> Path:
    return Path(os.environ.get(CONTROLS_ROOT_ENV) or ROOT / "tests" / "controls_auto") / m["id"]


def original_path(m) -> Path:
    return controls_dir(m) / "original.abap"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def class_name(m) -> str:
    return Path(m["production_file"]).name.split(".")[0].upper()


def runner_cfg(m) -> dict:
    """The transpile runner config. runner.project is a dict of the config keys, or the path (repo-relative or absolute) of a runner.json; other runner keys override it."""
    r = dict(m["runner"])
    proj = r.pop("project", None)
    base = {}
    if isinstance(proj, dict):
        base = dict(proj)
    elif isinstance(proj, str) and "project_dir" not in r:      # 2026-11-17: intake writes a full config (project_dir...) and "project" is then only a label/folder
        p = Path(proj)
        base = json.loads((p if p.is_absolute() else ROOT / p).read_text(encoding="utf-8"))
    cfg = {**base, **r}
    cfg.pop("only_methods", None)
    cfg.setdefault("only_object", class_name(m))
    return cfg


def stored_tests(m, bench_dir) -> dict:
    """{test file path inside the repo: stored text}, each checked against its manifest sha256."""
    out = {}
    for tf in m["test_files"]:
        p = Path(bench_dir) / tf["stored"]
        data = p.read_bytes()
        if sha256(data) != tf["sha256"]:
            raise ControlsError(f"stored test file {tf['stored']} does not match its sha256")
        out[tf["path"]] = data.decode("utf-8")
    return out


_NOT_NAMES = {"final", "short", "medium", "long", "harmless", "critical", "dangerous"}


def listed_test_methods(m, bench_dir) -> list[str]:
    """All FOR TESTING method names of the stored test files, lowercase, in file order."""
    names = []
    for text in stored_tests(m, bench_dir).values():
        for line in text.splitlines():
            hit = re.match(r"\s*(?:METHODS\s*:?\s+)?(\w+)\s+FOR\s+TESTING\b", t._strip_comments(line), re.I)
            if hit and hit.group(1).lower() not in _NOT_NAMES and hit.group(1).lower() not in names:
                names.append(hit.group(1).lower())
    return names


def old_methods(m, bench_dir) -> list[str]:
    new = set(new_methods(m))
    return [x for x in listed_test_methods(m, bench_dir) if x not in new]


def method_status(results: dict, name: str) -> str:
    """PASS, or the FAIL text, or 'no result' for a test method (the local class part of the key is ignored)."""
    hits = [v for k, v in results.items() if k.split("->", 1)[-1].lower() == name.lower()]
    if not hits:
        return "no result"
    return "PASS" if all(v == "PASS" for v in hits) else next(v for v in hits if v != "PASS")


def run_methods(m, bench_dir, candidate, methods, *, timeout_s=TIMEOUT_S) -> dict:
    """Transpile and run only `methods` of the PR's stored test files against candidate (callers refuse risky text first)."""
    cfg = runner_cfg(m)
    cfg["only_methods"] = list(methods)
    with tempfile.TemporaryDirectory() as tmp:
        edited = {m["production_file"]: Path(candidate)}
        for i, (rel, text) in enumerate(stored_tests(m, bench_dir).items()):
            p = Path(tmp) / f"t{i}.abap"
            p.write_text(text, encoding="utf-8", newline="\n")
            edited[rel] = p
        return t.run_abap_tests(cfg, edited, timeout_s=timeout_s, trusted=tuple(edited))


# ---------------------------------------------------------------- the outside-the-allowed-methods check
_METHOD_RE = re.compile(r"^[ \t]*METHOD\s+([\w~]+)\s*\.[ \t]*\n(.*?)^[ \t]*ENDMETHOD\s*\.[ \t]*(?:\n|$)", re.M | re.S | re.I)
_ENDCLASS_RE = re.compile(r"^[ \t]*ENDCLASS\s*\.[ \t]*$", re.M | re.I)


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def split_class(text: str):
    """(definition statements, implementation skeleton lines, {method: body}); definition = up to the first ENDCLASS."""
    text = _lf(text)
    end = _ENDCLASS_RE.search(text)
    if not end:
        raise ControlsError("no ENDCLASS. found")
    definition, impl = text[: end.end()], text[end.end():]
    bodies = {mm.group(1).lower(): mm.group(2) for mm in _METHOD_RE.finditer(impl)}
    skeleton = [ln.rstrip() for ln in _METHOD_RE.sub("", impl).split("\n") if ln.strip()]
    return _statements(definition), skeleton, bodies


def _statements(text: str) -> list[str]:
    # ponytail: dot-splitting that respects quotes; chained statements stay one statement
    out, cur = [], []
    for line in text.splitlines():
        q = None
        for ch in t._strip_comments(line):
            cur.append(ch)
            if q:
                q = None if ch == q else q
            elif ch in "'`|":
                q = ch
            elif ch == ".":
                out.append(" ".join("".join(cur).split()).lower())
                cur = []
        cur.append(" ")
    return out


def _is_free(stmt: str, free: set) -> bool:
    return bool(re.match(r"(class-)?methods\b", stmt)) and any(re.search(rf"(?<![\w~]){re.escape(n)}(?![\w~])", stmt) for n in free)


def outside_problems(original: str, candidate: str, allowed, new_allowed=()) -> list[str]:
    """Why `candidate` differs from `original` outside the allowed methods (empty list = nothing outside changed).

    Allowed method bodies and the declarations of allowed or new methods may change; any new method must be in
    allowed or new_allowed; every other method body, the implementation skeleton and every other definition statement are unchanged.
    """
    free = set(_lower(allowed)) | set(_lower(new_allowed))
    od, os_, ob = split_class(original)
    cd, cs, cb = split_class(candidate)
    problems = []
    for name in sorted(set(cb) - set(ob) - free):
        problems.append(f"method {name} was added but is not listed as new")
    for name in sorted(ob):
        if name in free:
            continue
        if name not in cb:
            problems.append(f"method {name} was removed")
        elif cb[name] != ob[name]:
            problems.append(f"method {name} changed")
    if cs != os_:
        problems.append("code outside the method bodies changed")
    if Counter(s for s in cd if not _is_free(s, free)) != Counter(s for s in od if not _is_free(s, free)):
        problems.append("the class definition changed outside the allowed methods")
    return problems


def new_risky_lines(original: str, candidate: str) -> str:
    """The lines the candidate added to the original (multiset difference), for the static refusal check."""
    orig = _lf(original).split("\n")
    added = []
    for line in _lf(candidate).split("\n"):
        if line in orig:
            orig.remove(line)
        else:
            added.append(line)
    return "\n".join(added)


# ---------------------------------------------------------------- controls
def _insert_after_method(text: str, prefer, avoid=()):
    """Insert-position helper: index of the line after a METHOD line (prefer those in `prefer`, skip those in `avoid`), or None."""
    lines = text.splitlines(keepends=True)
    hits = [(i, mm.group(1).lower()) for i, ln in enumerate(lines) if (mm := re.match(r"\s*METHOD\s+([\w~]+)\s*\.", ln, re.I))]
    hits = [h for h in hits if h[1] not in avoid]
    pick = next((h for h in hits if h[1] in prefer), hits[0] if hits else None)
    return lines, (pick[0] + 1 if pick else None)


def _insert(text: str, extra: str, prefer=(), avoid=()) -> str:
    lines, at = _insert_after_method(text, set(prefer), set(avoid))
    if at is None:
        raise ControlsError("no method to put the control line into")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines.insert(at, extra + eol)
    return "".join(lines)


def _collateral(text: str, free: set) -> str:
    """A change outside the allowed methods: a line in a method that is not allowed, else a new statement in the class definition."""
    try:
        return _insert(text, "    DATA lv_collateral TYPE i.", avoid=free)
    except ControlsError:
        end = _ENDCLASS_RE.search(text)
        eol = "\r\n" if "\r\n" in text else "\n"
        return text[: end.start()] + "    CLASS-DATA gv_collateral TYPE i." + eol + text[end.start():]


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    return (p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).as_posix()


def generic_controls(manifest) -> list[dict]:
    """Write the control files and return the negative_controls entries (no_op, kernel_poc, collateral, syntax_broken)."""
    m = load_manifest(manifest) if isinstance(manifest, (str, Path)) else manifest
    cdir = controls_dir(m)
    cdir.mkdir(parents=True, exist_ok=True)
    orig_file = original_path(m)
    if orig_file.exists() and sha256(orig_file.read_bytes()) == m["original_sha256"]:
        data = orig_file.read_bytes()
    else:
        data = work_path(m).read_bytes()
        if sha256(data) != m["original_sha256"]:
            raise ControlsError("work_file is not the original (sha256 differs); controls need the untouched file")
        orig_file.write_bytes(data)
    original = data.decode("utf-8")

    base_fails = {str(x).split("->")[-1].strip().lower() for x in (m.get("gate") or {}).get("base_fails", [])}
    fails_now = [f"{ACCEPT}::test_new_{x}" for x in acceptance_methods(m) if x in base_fails]
    if not fails_now:
        raise ControlsError("no acceptance (non-held-out) new test fails on the base; the bench cannot tell a no-op from a fix")
    free = set(_lower(m["allowed_methods"]))
    lint = f"{ACCEPT}::test_no_abaplint_issues_in_the_edited_file"
    outside = f"{ACCEPT}::test_nothing_outside_allowed_methods_changed"

    files = {
        "no_op": original,
        "kernel_poc": _insert(original, "    WRITE '@KERNEL console.log(1);'.", prefer=free),
        "collateral": _collateral(original, free),
        "syntax_broken": _insert(original, "    THIS IS NOT ABAP AT ALL.", prefer=free),
    }
    must = {"no_op": fails_now, "kernel_poc": [lint] + fails_now, "collateral": [outside], "syntax_broken": [lint]}
    entries = []
    for name, text in files.items():
        p = cdir / f"{name}.abap"
        p.write_bytes(text.encode("utf-8"))
        entries.append({"name": name, "must_fail": must[name], "replace": {m["work_file"]: _rel(p)}})
    return entries
