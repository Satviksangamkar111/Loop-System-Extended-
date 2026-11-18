"""Locked acceptance tests of an automatic bench: the PR's own new test methods, run through the confined transpile runner.

The manifest path comes from env SAP_BENCH_MANIFEST (see docs/sap/AUTO_BENCH_CONTRACT.md). Tests generated here:
  test_new_<method>                              one per acceptance (non-held-out) new test method
  test_old_behaviour_unchanged                   the pre-existing test methods of the PR's test files
  test_no_abaplint_issues_in_the_edited_file
  test_nothing_outside_allowed_methods_changed
Held-out methods are never run here. One transpile+run per pytest process (cached, failures too).
Optional env SAP_BENCH_NEW_METHODS: comma list of new helper methods the planner's unit announced (allowed to be added).
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import sap_auto_controls as ac  # noqa: E402

_PATH = os.environ.get("SAP_BENCH_MANIFEST")
if not _PATH:      # 2026-11-17: the ABAP sandbox passes no SAP_BENCH_* variable; sap_solve leaves a pointer file (a repo-relative path) in tests/controls_auto
    _PTR = ROOT / "tests" / "controls_auto" / "ACTIVE_MANIFEST.txt"
    if _PTR.is_file():
        _PATH = str(ROOT / _PTR.read_text(encoding="utf-8").strip())
if not _PATH:
    pytest.skip("SAP_BENCH_MANIFEST is not set", allow_module_level=True)

M = ac.load_manifest(_PATH)
BENCH_DIR = Path(_PATH).resolve().parent
TARGET = ac.work_path(M)
REL_CLASS = M["production_file"]
_CACHE = {}


def _original_text() -> str:
    p = ac.original_path(M)
    assert p.exists(), f"{p} is missing: run sap_auto_controls.generic_controls(manifest) before the job"
    data = p.read_bytes()
    assert ac.sha256(data) == M["original_sha256"], "controls_auto original.abap does not match original_sha256"
    return data.decode("utf-8")


def _check_new_text():
    """Refuse only the lines the writer ADDED to the original (as in the hand-built benches)."""
    problems = ac.t.check_abap_text(ac.new_risky_lines(_original_text(), TARGET.read_text(encoding="utf-8")))
    if problems:
        raise ac.t.AbapTextRefused("; ".join(problems))


def results():
    if "r" not in _CACHE and "err" not in _CACHE:
        methods = ac.acceptance_methods(M) + ac.old_methods(M, BENCH_DIR)
        try:
            _check_new_text()
            _CACHE["r"] = ac.run_methods(M, BENCH_DIR, TARGET, methods)
        except (ac.t.AbapTextRefused, ac.t.RunnerError) as exc:
            _CACHE["err"] = f"the ABAP could not be run: {type(exc).__name__}: {exc}"
    if "err" in _CACHE:
        raise AssertionError(_CACHE["err"])
    return _CACHE["r"]


def _passes(name):
    status = ac.method_status(results(), name)  # only this method's status: the whole dict would hide the reason
    assert status == "PASS", f"{name}: {status}"


def _make(name):
    def test():
        _passes(name)

    test.__name__ = test.__qualname__ = f"test_new_{name}"
    return test


for _name in ac.acceptance_methods(M):
    globals()[f"test_new_{_name}"] = _make(_name)


def test_old_behaviour_unchanged():
    old = ac.old_methods(M, BENCH_DIR)
    bad = [f"{n}: {s}" for n in old if (s := ac.method_status(results(), n)) != "PASS"]
    assert not bad, bad


def test_nothing_outside_allowed_methods_changed():
    _nm = os.environ.get("SAP_BENCH_NEW_METHODS", "")
    _nmf = ROOT / "tests" / "controls_auto" / "ACTIVE_NEW_METHODS.txt"       # the sandbox drops environment variables; sap_solve leaves the unit's list here
    if not _nm and _nmf.is_file():
        _nm = _nmf.read_text(encoding="utf-8").strip()
    announced = [x for x in _nm.split(",") if x.strip()]
    problems = ac.outside_problems(_original_text(), TARGET.read_text(encoding="utf-8"), M["allowed_methods"], [x.strip() for x in announced])
    assert not problems, problems


def test_no_abaplint_issues_in_the_edited_file():
    try:
        _check_new_text()
        issues = ac.t.run_abaplint(ac.runner_cfg(M), {REL_CLASS: TARGET}, timeout_s=ac.TIMEOUT_S, trusted=(REL_CLASS,))
    except (ac.t.AbapTextRefused, ac.t.RunnerError) as exc:
        raise AssertionError(f"abaplint could not be run: {type(exc).__name__}: {exc}") from None
    assert issues == [], issues
