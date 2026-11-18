"""Portable paths and packaging (audit defects 4, 5, 12, 16). Temp folders only; no model call, no network.

Default base folder: env SAP_LOOP_BASE, else the parent of the repository. Checked in a fresh interpreter, so the
environment seen at import is the one under test.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "scripts" / "source"
sys.path.insert(0, str(SRC))
import sap_intake as si  # noqa: E402
import sap_oracle_check as oc  # noqa: E402

MODULES = ["sap_intake", "sap_screen", "sap_mine", "sap_oracle_check"]


def _expected(base):
    b = Path(base)
    return {
        "sap_intake": {"DEFAULT_PRIVATE": b / "bench_private", "LIBS_DIR": b / "bench" / "libs", "TOOLS_DIR": b / "abap_tools",
                       "LINT_DEPS_DIR": b / "bench" / "libs" / "abaplint-deps", "MINE_ROOT": b / "work" / "mine"},
        "sap_screen": {"RESIDUE": b / "work" / "residue_2026-11-16", "PROJECTS": b / "work" / "intake_try2" / "projects",
                       "SATVIK_HOME": b / "satvik_home"},
        "sap_mine": {"DEFAULT_ROOT": b / "work" / "mine"},
        "sap_oracle_check": {"PRIVATE": b / "bench_private"},
    }


def _constants(module, base=None):
    """The base-derived module constants, read in a fresh interpreter with SAP_LOOP_BASE set to `base` (or unset when None)."""
    env = {k: v for k, v in os.environ.items() if k != "SAP_LOOP_BASE"}
    if base is not None:
        env["SAP_LOOP_BASE"] = str(base)
    names = list(_expected(ROOT)[module])
    code = (f"import sys, json; sys.path.insert(0, {str(SRC)!r}); import {module} as m; "
            f"print(json.dumps({{k: str(getattr(m, k)) for k in {names!r}}}))")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("module", MODULES)
def test_defaults_are_the_parent_of_the_repository(module):
    assert _constants(module) == {k: str(v) for k, v in _expected(ROOT.parent)[module].items()}


@pytest.mark.parametrize("module", MODULES)
def test_env_base_moves_every_derived_folder(module, tmp_path):
    base = tmp_path / "elsewhere"
    assert _constants(module, base) == {k: str(v) for k, v in _expected(base)[module].items()}


@pytest.mark.parametrize("module", MODULES)
def test_no_machine_path_literal_in_the_module(module):
    text = (SRC / f"{module}.py").read_text(encoding="utf-8")
    assert "C:/SAP Loop System" not in text and "C:\\SAP Loop System" not in text


def test_generator_has_no_machine_paths_and_records_the_held_out_flag():
    text = (ROOT / "scripts" / "make_benchmark_bench.py").read_text(encoding="utf-8")
    for bad in ("C:", "SAP Loop System", "problem_research", "Satvik"):
        assert bad not in text
    assert '"heldout_fails_on_base": all(h in fails for h in held)' in text
    assert '"heldout_failing_methods": sorted(h for h in held if h in fails)' in text


def test_fixed_line_fingerprints_tells_a_missing_file_from_an_empty_list(tmp_path):
    priv = tmp_path / "priv"
    with pytest.raises(FileNotFoundError):
        si.fixed_line_fingerprints("b1", priv, strict=True)
    assert si.fixed_line_fingerprints("b1", priv) == frozenset()           # default callers unchanged
    (priv / "b1").mkdir(parents=True)
    (priv / "b1" / "fixed_lines.txt").write_text("\n* short\n", encoding="utf-8")
    assert si.fixed_line_fingerprints("b1", priv, strict=True) == frozenset()   # present, no usable line
    (priv / "b1" / "fixed_lines.txt").write_text("  DATA(total) = total + 1.\n", encoding="utf-8")
    assert si.fixed_line_fingerprints("b1", priv, strict=True) == frozenset({"data(total) = total + 1."})


def test_cli_sets_libs_and_tools_folders(monkeypatch, tmp_path):
    for name in ("LIBS_DIR", "TOOLS_DIR", "LINT_DEPS_DIR"):      # monkeypatch restores these after the test
        monkeypatch.setattr(si, name, getattr(si, name))
    seen = {}

    def fake(repo, pr, out, **kw):
        seen.update(libs=si.LIBS_DIR, tools=si.TOOLS_DIR, lint=si.LINT_DEPS_DIR)
        return {"id": "i", "label": "BLIND", "test_files": [{"new_methods": [], "heldout_methods": []}]}

    monkeypatch.setattr(si, "intake", fake)
    libs, tools = tmp_path / "libs", tmp_path / "tools"
    code = si.main(["owner/repo", "1", "--libs", str(libs), "--tools", str(tools), "--out", str(tmp_path / "out"),
                    "--private", str(tmp_path / "priv")])
    assert code == 0
    assert seen == {"libs": libs, "tools": tools, "lint": libs / "abaplint-deps"}


def test_oracle_check_default_private_folder_is_the_base_one(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "PRIVATE", tmp_path / "priv")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"id": "hb_x"}), encoding="utf-8")
    out = oc.check(manifest)
    assert out["ok"] is False and str(tmp_path / "priv" / "hb_x" / "fixed.abap") in out["reason"]


@pytest.mark.parametrize("path", sorted((ROOT / "docs" / "sap" / "bench_auto").glob("hb_*/manifest.json")), ids=lambda p: p.parent.name)
def test_hb_manifest_records_heldout_fails_on_base(path):
    m = json.loads(path.read_text(encoding="utf-8"))
    held = set(m["test_files"][0]["heldout_methods"])
    failing = sorted(set(m["gate"]["base_fails"]) & held)
    assert m["gate"]["heldout_failing_methods"] == failing
    assert m["gate"]["heldout_fails_on_base"] is (len(failing) == len(held))      # true or false, like the other benches


def test_requirements_pins_the_audited_versions():
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert lines == ["pytest==9.2.0", "PyYAML==6.0.3", "jsonschema==4.26.0", "fastapi==0.139.0", "starlette==1.3.1",
                     "httpx==0.28.1", "uvicorn==0.49.0"]
