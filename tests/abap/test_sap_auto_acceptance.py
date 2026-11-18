"""Tests for the automatic bench's generic acceptance, controls and held-out runner (fake manifest, fake runner results; no network, no model)."""
import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import sap_auto_controls as ac  # noqa: E402
import sap_heldout as h  # noqa: E402

CLASS = """CLASS zcl_demo DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    CLASS-METHODS add IMPORTING a TYPE i RETURNING VALUE(r) TYPE i.
    CLASS-METHODS keep RETURNING VALUE(r) TYPE i.
ENDCLASS.

CLASS zcl_demo IMPLEMENTATION.
  METHOD add.
    r = a.
  ENDMETHOD.

  METHOD keep.
    r = 1.
  ENDMETHOD.
ENDCLASS.
"""

TESTS = """CLASS ltcl_demo DEFINITION FINAL FOR TESTING DURATION SHORT RISK LEVEL HARMLESS.
  PRIVATE SECTION.
    METHODS:
      old_one FOR TESTING RAISING cx_static_check,
      new_a FOR TESTING RAISING cx_static_check,
      new_b FOR TESTING RAISING cx_static_check.
    METHODS new_c FOR TESTING.
    METHODS new_d FOR TESTING.
ENDCLASS.
"""


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def bench(tmp_path, monkeypatch):
    monkeypatch.setenv(ac.CONTROLS_ROOT_ENV, str(tmp_path / "controls"))
    work = tmp_path / "work" / "zcl_demo.clas.abap"
    work.parent.mkdir()
    work.write_text(CLASS, encoding="utf-8", newline="\n")
    bdir = tmp_path / "bench"
    (bdir / "tests_upstream").mkdir(parents=True)
    (bdir / "tests_upstream" / "t.abap").write_text(TESTS, encoding="utf-8", newline="\n")
    m = {
        "schema": 1, "id": "demo_1", "production_file": "src/zcl_demo.clas.abap", "work_file": str(work),
        "original_sha256": sha(CLASS),
        "test_files": [{"path": "src/zcl_demo.clas.testclasses.abap", "stored": "tests_upstream/t.abap", "sha256": sha(TESTS),
                        "new_methods": ["new_a", "new_b", "new_c", "new_d"], "heldout_methods": ["new_b", "new_d"]}],
        "allowed_methods": ["add"],
        "runner": {"project": {"project_dir": "P", "libs_dir": "L", "tools_dir": "T", "config": "c.json", "lint_deps_dir": "D"}},
        "gate": {"base_fails": ["ltcl_demo->new_a", "new_b"]},
    }
    (bdir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return m, bdir, work


# ---------------------------------------------------------------- manifest helpers
def test_manifest_sets_and_old_methods(bench):
    m, bdir, _ = bench
    assert ac.acceptance_methods(m) == ["new_a", "new_c"]
    assert ac.heldout_methods(m) == ["new_b", "new_d"]
    assert ac.old_methods(m, bdir) == ["old_one"]
    assert ac.listed_test_methods(m, bdir) == ["old_one", "new_a", "new_b", "new_c", "new_d"]


def test_heldout_rule_is_enforced(bench):
    m, bdir, _ = bench
    m["test_files"][0]["heldout_methods"] = ["new_a", "not_a_new_method"]      # 2026-11-17: any non-empty proper subset of the new methods is valid; an unknown name is not
    p = bdir / "bad.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ac.ControlsError):
        ac.load_manifest(p)


def test_tampered_stored_test_file_is_refused(bench):
    m, bdir, _ = bench
    (bdir / "tests_upstream" / "t.abap").write_text(TESTS + "\n* x\n", encoding="utf-8")
    with pytest.raises(ac.ControlsError):
        ac.old_methods(m, bdir)


def test_runner_cfg_inline_and_default_object(bench):
    m, _, _ = bench
    cfg = ac.runner_cfg(m)
    assert cfg["project_dir"] == "P" and cfg["only_object"] == "ZCL_DEMO" and "only_methods" not in cfg


# ---------------------------------------------------------------- outside-the-allowed-methods check
def test_outside_allowed_changes_pass_and_fail():
    ok = CLASS.replace("r = a.", "r = a + 1.")
    assert ac.outside_problems(CLASS, ok, ["add"]) == []
    bad = CLASS.replace("r = 1.", "r = 2.")
    assert ac.outside_problems(CLASS, bad, ["add"]) == ["method keep changed"]


def test_new_helper_only_when_listed():
    helper = CLASS.replace("    CLASS-METHODS keep", "    CLASS-METHODS helper RETURNING VALUE(r) TYPE i.\n    CLASS-METHODS keep").replace(
        "  METHOD keep.", "  METHOD helper.\n    r = 3.\n  ENDMETHOD.\n\n  METHOD keep.")
    assert any("helper" in p for p in ac.outside_problems(CLASS, helper, ["add"]))
    assert ac.outside_problems(CLASS, helper, ["add"], ["helper"]) == []


def test_definition_change_outside_allowed_is_caught():
    bad = CLASS.replace("    CLASS-METHODS keep", "    CLASS-DATA gv TYPE i.\n    CLASS-METHODS keep")
    assert ac.outside_problems(CLASS, bad, ["add"]) == ["the class definition changed outside the allowed methods"]


# ---------------------------------------------------------------- generic controls
def test_generic_controls_files_and_entries(bench):
    m, _, work = bench
    entries = ac.generic_controls(m)
    assert [e["name"] for e in entries] == ["no_op", "kernel_poc", "collateral", "syntax_broken"]
    by = {e["name"]: e for e in entries}
    cdir = ac.controls_dir(m)
    assert (cdir / "no_op.abap").read_text(encoding="utf-8") == CLASS
    assert (cdir / "original.abap").read_bytes() == CLASS.encode()
    assert "@KERNEL" in (cdir / "kernel_poc.abap").read_text(encoding="utf-8")
    assert "THIS IS NOT ABAP" in (cdir / "syntax_broken.abap").read_text(encoding="utf-8")
    prefix = ac.ACCEPT + "::"
    assert by["no_op"]["must_fail"] == [prefix + "test_new_new_a"]  # new_b is held out, new_c passes on the base
    assert prefix + "test_no_abaplint_issues_in_the_edited_file" in by["kernel_poc"]["must_fail"]
    assert by["collateral"]["must_fail"] == [prefix + "test_nothing_outside_allowed_methods_changed"]
    assert set(by["no_op"]["replace"]) == {m["work_file"]}
    # the collateral control really fails the outside check, the no-op passes it
    assert ac.outside_problems(CLASS, (cdir / "collateral.abap").read_text(encoding="utf-8"), ["add"])
    assert ac.outside_problems(CLASS, (cdir / "no_op.abap").read_text(encoding="utf-8"), ["add"]) == []
    # the kernel line is refused by the static check
    assert ac.t.check_abap_text(ac.new_risky_lines(CLASS, (cdir / "kernel_poc.abap").read_text(encoding="utf-8")))


def test_generic_controls_keep_crlf(bench):
    m, _, work = bench
    work.write_bytes(CLASS.replace("\n", "\r\n").encode())
    m["original_sha256"] = ac.sha256(work.read_bytes())
    ac.generic_controls(m)
    data = (ac.controls_dir(m) / "kernel_poc.abap").read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n")


def test_generic_controls_refuse_an_edited_work_file_and_a_bench_without_failing_acceptance(bench):
    m, _, work = bench
    work.write_text(CLASS + "\n* edited\n", encoding="utf-8")
    with pytest.raises(ac.ControlsError):
        ac.generic_controls(m)
    work.write_text(CLASS, encoding="utf-8", newline="\n")
    m["gate"]["base_fails"] = ["new_b"]  # only a held-out method fails on the base
    with pytest.raises(ac.ControlsError):
        ac.generic_controls(m)


def test_collateral_falls_back_to_the_definition_when_every_method_is_allowed(bench):
    m, _, _ = bench
    m["allowed_methods"] = ["add", "keep"]
    ac.generic_controls(m)
    text = (ac.controls_dir(m) / "collateral.abap").read_text(encoding="utf-8")
    assert "gv_collateral" in text
    assert ac.outside_problems(CLASS, text, ["add", "keep"])


# ---------------------------------------------------------------- the acceptance module (fake runner)
def load_acceptance(monkeypatch, bench, results=None, seen=None):
    m, bdir, work = bench
    ac.generic_controls(m)
    monkeypatch.setenv("SAP_BENCH_MANIFEST", str(bdir / "manifest.json"))

    def fake_run(cfg, edited, timeout_s=0, trusted=()):
        if seen is not None:
            seen.update(cfg=cfg, edited=edited)
        return results

    monkeypatch.setattr(ac.t, "run_abap_tests", fake_run)
    monkeypatch.setattr(ac.t, "run_abaplint", lambda cfg, edited, timeout_s=0, trusted=(): [])
    spec = importlib.util.spec_from_file_location("acc_fake", ROOT / "tests" / "acceptance" / "sap_auto_acceptance.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, work


def test_acceptance_generates_one_test_per_acceptance_method_only(monkeypatch, bench):
    seen = {}
    res = {"ltcl_demo->new_a": "PASS", "ltcl_demo->new_c": "FAIL: expected 1 actual 2", "ltcl_demo->old_one": "PASS"}
    mod, _ = load_acceptance(monkeypatch, bench, res, seen)
    names = {n for n in vars(mod) if n.startswith("test_")}
    assert {"test_new_new_a", "test_new_new_c", "test_old_behaviour_unchanged"} <= names
    assert "test_new_new_b" not in names and "test_new_new_d" not in names
    mod.test_new_new_a()
    with pytest.raises(AssertionError, match="new_c: FAIL: expected 1 actual 2"):
        mod.test_new_new_c()
    mod.test_old_behaviour_unchanged()
    assert seen["cfg"]["only_methods"] == ["new_a", "new_c", "old_one"]  # held-out methods are not run
    assert set(seen["edited"]) == {"src/zcl_demo.clas.abap", "src/zcl_demo.clas.testclasses.abap"}


def test_acceptance_old_behaviour_and_missing_result(monkeypatch, bench):
    mod, _ = load_acceptance(monkeypatch, bench, {"ltcl_demo->new_a": "PASS", "ltcl_demo->old_one": "FAIL: x"})
    with pytest.raises(AssertionError):
        mod.test_old_behaviour_unchanged()
    with pytest.raises(AssertionError, match="no result"):
        mod.test_new_new_c()


def test_acceptance_refuses_added_kernel_text_and_outside_changes(monkeypatch, bench):
    mod, work = load_acceptance(monkeypatch, bench, {"ltcl_demo->new_a": "PASS"})
    work.write_text(CLASS.replace("r = a.", "r = a.\n    WRITE '@KERNEL x'."), encoding="utf-8", newline="\n")
    with pytest.raises(AssertionError, match="refused construct"):
        mod.test_new_new_a()
    with pytest.raises(AssertionError, match="refused construct"):
        mod.test_no_abaplint_issues_in_the_edited_file()
    mod.test_nothing_outside_allowed_methods_changed()  # only the allowed method changed
    work.write_text(CLASS.replace("r = 1.", "r = 9."), encoding="utf-8", newline="\n")
    with pytest.raises(AssertionError, match="keep"):
        mod.test_nothing_outside_allowed_methods_changed()


def test_acceptance_skips_without_the_env(monkeypatch):
    monkeypatch.delenv("SAP_BENCH_MANIFEST", raising=False)
    spec = importlib.util.spec_from_file_location("acc_none", ROOT / "tests" / "acceptance" / "sap_auto_acceptance.py")
    with pytest.raises(pytest.skip.Exception):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))


# ---------------------------------------------------------------- run_manifest (fake runner)
def test_run_manifest_runs_only_heldout_and_prints_the_summary(monkeypatch, bench, capsys):
    m, bdir, work = bench
    seen = {}

    def fake_run(cfg, edited, timeout_s=0, trusted=()):
        seen["only"] = cfg["only_methods"]
        return {"ltcl_demo->new_b": "PASS", "ltcl_demo->new_d": "FAIL: expected 1 actual 2"}

    monkeypatch.setattr(h.t, "run_abap_tests", fake_run)
    out = h.run_manifest(bdir / "manifest.json", work)
    assert seen["only"] == ["new_b", "new_d"]
    assert (out["passed"], out["total"], out["all_passed"]) == (1, 2, False)
    assert out["cases"] == {"new_b": "PASS", "new_d": "FAIL: expected 1 actual 2"}
    printed = capsys.readouterr().out.strip().splitlines()
    assert printed[-1] == "heldout: 1/2 passed" and "  FAIL new_d :: expected 1 actual 2" in printed


def test_run_manifest_refuses_kernel_text_and_reports_runner_errors(monkeypatch, bench):
    m, bdir, work = bench
    kernel = bdir / "k.abap"
    kernel.write_text(CLASS + "\n  WRITE '@KERNEL x'.\n", encoding="utf-8")
    out = h.run_manifest(bdir / "manifest.json", kernel)
    assert out["summary"].startswith("heldout: 0/2 passed (refused: ") and not out["all_passed"]

    def boom(*a, **k):
        raise h.t.RunnerError("no node")

    monkeypatch.setattr(h.t, "run_abap_tests", boom)
    out = h.run_manifest(bdir / "manifest.json", work)
    assert out["summary"].startswith("heldout: 0/2 passed (the ABAP could not be run: RunnerError: no node")


# ---------------------------------------------------------------- one real run, skipped when the bench project is missing
def _d_runner():
    return json.loads((ROOT / "docs/sap/bench/D/runner.json").read_text(encoding="utf-8"))


@pytest.mark.skipif(not Path(_d_runner()["project_dir"]).is_dir() or not Path(_d_runner()["tools_dir"]).is_dir(),
                    reason="bench D project / transpile tools not available")
def test_integration_heldout_on_bench_d_upstream_fix(tmp_path):
    spec = importlib.util.spec_from_file_location("sap_D_acc", ROOT / "tests" / "acceptance" / "sap_D_acceptance.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    tests = base64.b64decode(d.UPSTREAM_TESTS_B64).decode("utf-8")
    (tmp_path / "tests_upstream").mkdir()
    (tmp_path / "tests_upstream" / "t.abap").write_text(tests, encoding="utf-8", newline="\n")
    m = {
        "id": "d_demo", "production_file": d.REL_CLASS, "work_file": str(d.TARGET), "original_sha256": "x",
        "test_files": [{"path": d.REL_TESTS, "stored": "tests_upstream/t.abap", "sha256": sha(tests),
                        "new_methods": ["no_newline_marker_removed", "mixed_final_newline"], "heldout_methods": ["mixed_final_newline"]}],
        "allowed_methods": ["calculate_patch"], "runner": {"project": "docs/sap/bench/D/runner.json"},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    fixed = ROOT / "tests" / "controls" / "sap_D_upstream_fix.abap"
    out = h.run_manifest(tmp_path / "manifest.json", fixed)
    assert out["cases"] == {"mixed_final_newline": "PASS"}, out
