"""Run the held-out ABAP unit tests of a benchmark candidate, after a job ends.

Usage: python scripts/source/sap_heldout.py <D|C|F> <candidate .abap file>

The candidate is checked with abap_transpile_run.check_abap_text (whole file), then copied
into the bench project through the same confined transpile-and-run path as the acceptance
tests, with the held-out test class in place of the project's test file. Prints one line per
case and `heldout: N/M passed`. Exit 0 when all pass, 1 otherwise (also on refusal or a run error).
The cases live in tests/heldout/sap_<X>_heldout.py (ABAP as base64), not in the loop's view.
"""
import base64
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import abap_transpile_run as t  # noqa: E402

BENCHES = ("D", "C", "F")
TIMEOUT_S = 240


def load_heldout(bench: str):
    """Import tests/heldout/sap_<bench>_heldout.py as a module."""
    path = ROOT / "tests" / "heldout" / f"sap_{bench}_heldout.py"
    spec = importlib.util.spec_from_file_location(f"sap_{bench}_heldout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_cfg(runner: dict) -> dict:
    """The bench runner config without only_methods: the held-out class needs all its methods run."""
    cfg = dict(runner)
    cfg.pop("only_methods", None)
    return cfg


def summary_line(passed: int, total: int, note: str = "") -> str:
    """The overall result line: `heldout: N/M passed`, with an optional note in brackets."""
    line = f"heldout: {passed}/{total} passed"
    return f"{line} ({note})" if note else line


def case_lines(cases, results: dict, local_class: str) -> tuple[int, list[str]]:
    """One line per case (PASS or FAIL with the reason); returns (passed count, lines)."""
    passed = 0
    lines: list[str] = []
    for name, probe in cases:
        status = results.get(f"{local_class}->{name}")
        if status == "PASS":
            passed += 1
            lines.append(f"  PASS {name} - {probe}")
        else:
            reason = (status or "FAIL: no result").removeprefix("FAIL: ")
            lines.append(f"  FAIL {name} - {probe} :: {reason}")
    return passed, lines


def run(bench: str, candidate: Path) -> tuple[int, list[str]]:
    """Return (exit code, output lines) for one candidate."""
    mod = load_heldout(bench)
    total = len(mod.CASES)
    runner = json.loads((ROOT / mod.RUNNER).read_text(encoding="utf-8"))
    cfg = build_cfg(runner)

    text = candidate.read_text(encoding="utf-8")
    problems = t.check_abap_text(text)
    if problems:
        return 1, [summary_line(0, total, "refused: " + "; ".join(problems))]

    with tempfile.TemporaryDirectory() as tmp:
        hidden = Path(tmp) / "heldout.testclasses.abap"
        hidden.write_bytes(base64.b64decode(mod.HELDOUT_TESTS_B64))
        try:
            results = t.run_abap_tests(
                cfg,
                {mod.REL_CLASS: candidate, mod.REL_TESTS: hidden},
                timeout_s=TIMEOUT_S,
                trusted=(mod.REL_TESTS, mod.REL_CLASS),  # candidate checked above; hidden file is locked here
            )
        except (t.AbapTextRefused, t.RunnerError) as exc:
            return 1, [summary_line(0, total, f"the ABAP could not be run: {type(exc).__name__}: {exc}")]

    passed, lines = case_lines(mod.CASES, results, mod.LOCAL_CLASS)
    lines.append(summary_line(passed, total))
    return (0 if passed == total else 1), lines


def run_manifest(manifest_path, candidate_path) -> dict:
    """Run ONLY the held-out methods of an automatic bench's PR test files against a candidate; print the usual lines.

    Returns {"passed", "total", "all_passed", "summary", "lines", "cases": {method: PASS | reason}}.
    """
    import sap_auto_controls as ac

    m = ac.load_manifest(manifest_path)
    held = ac.heldout_methods(m)
    candidate = Path(candidate_path)
    cases: dict[str, str] = {}
    note = ""
    problems = t.check_abap_text(candidate.read_text(encoding="utf-8"))
    if problems:
        note = "refused: " + "; ".join(problems)
    else:
        try:
            results = ac.run_methods(m, Path(manifest_path).resolve().parent, candidate, held, timeout_s=TIMEOUT_S)
            cases = {name: ac.method_status(results, name) for name in held}
        except (t.AbapTextRefused, t.RunnerError, ac.ControlsError) as exc:
            note = f"the ABAP could not be run: {type(exc).__name__}: {exc}"
    cases = {name: cases.get(name, "no result") for name in held}
    passed = sum(v == "PASS" for v in cases.values())
    lines = [f"  PASS {n}" if v == "PASS" else f"  FAIL {n} :: {v.removeprefix('FAIL: ')}" for n, v in cases.items()]
    summary = summary_line(passed, len(held), note)
    lines.append(summary)
    for line in lines:
        print(line)
    return {"passed": passed, "total": len(held), "all_passed": bool(held) and passed == len(held),
            "summary": summary, "lines": lines, "cases": cases}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in BENCHES:
        print("usage: python scripts/source/sap_heldout.py <D|C|F> <candidate .abap file>", file=sys.stderr)
        return 2
    code, lines = run(argv[0], Path(argv[1]))
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
