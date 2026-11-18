"""Roster switching guard of scripts/sap_poc_run.py."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("sap_poc_run", Path(__file__).resolve().parents[2] / "scripts" / "sap_poc_run.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_distinct_models_are_fine():
    assert m.duplicate_models({"writer_a": "a", "writer_b": "b", "reviewer_a": "c", "reviewer_b": "d"}) == []


def test_a_model_in_two_roles_is_reported():
    out = m.duplicate_models({"writer_a": "x", "writer_b": "x", "reviewer_a": "haiku", "reviewer_b": "haiku"})
    assert len(out) == 2 and "writer_a and writer_b" in out[0] and "reviewer_a and reviewer_b" in out[1]


def test_the_current_sap_roster_has_no_duplicates():
    assert m.duplicate_models({r: mod for r, mod, _v, _e in m.role_rows()}) == []


def test_importing_the_runner_changes_nothing():
    """Checked in a clean child process: other tests may leave SATVIK_PROFILE set in this one, and that says nothing about the import."""
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if k not in ("SATVIK_PROFILE", "SAP_ROSTER", "PYTEST_SAP_KEEP")}
    code = ("import importlib.util, os, sys; p = sys.argv[1]; s = importlib.util.spec_from_file_location('sap_poc_run', p); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "assert os.environ.get('SATVIK_PROFILE') != 'production', 'import set the profile'; "
            "oc = sys.modules.get('openrouter_call'); "
            "assert oc is None or 'roster_sap' not in str(oc.ROSTER_PATH), 'import switched the roster'")
    runner = Path(__file__).resolve().parents[2] / "scripts" / "sap_poc_run.py"
    result = subprocess.run([sys.executable, "-I", "-c", code, str(runner)], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-1500:]


def test_repair_sharing_a_model_with_a_reviewer_gets_a_warning():
    models = {"writer_a": "a", "writer_b": "b", "reviewer_a": "haiku", "reviewer_b": "d", "repair": "haiku"}
    assert len(m.repair_warnings(models)) == 1 and "reviewer_a" in m.repair_warnings(models)[0]
    models["repair"] = "other"
    assert m.repair_warnings(models) == []
