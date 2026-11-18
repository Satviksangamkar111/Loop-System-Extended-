"""Tests for scripts/source/sap_heldout.py that do not start node (the held-out ABAP runs are checked by hand, see docs/sap/HELDOUT.md)."""
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import abap_transpile_run as t  # noqa: E402
import sap_heldout as h  # noqa: E402

CLI = ROOT / "scripts" / "source" / "sap_heldout.py"
EXPECTED_CASES = {"D": 8, "C": 11, "F": 11}


@pytest.mark.parametrize("bench", ["D", "C", "F"])
def test_payload_decodes_to_the_declared_test_class(bench):
    mod = h.load_heldout(bench)
    text = base64.b64decode(mod.HELDOUT_TESTS_B64).decode("utf-8")
    assert f"CLASS {mod.LOCAL_CLASS} DEFINITION" in text
    assert f"CLASS {mod.LOCAL_CLASS} IMPLEMENTATION" in text


@pytest.mark.parametrize("bench", ["D", "C", "F"])
def test_case_count_is_as_documented(bench):
    mod = h.load_heldout(bench)
    assert len(mod.CASES) == EXPECTED_CASES[bench]


@pytest.mark.parametrize("bench", ["D", "C", "F"])
def test_cases_match_the_test_methods_in_the_payload(bench):
    mod = h.load_heldout(bench)
    text = base64.b64decode(mod.HELDOUT_TESTS_B64).decode("utf-8")
    declared = re.findall(r"^\s+(?:METHODS\s+)?(\w+) FOR TESTING", text, re.M)
    assert sorted(declared) == sorted(name for name, _probe in mod.CASES)
    assert len(set(declared)) == len(declared)


@pytest.mark.parametrize("bench", ["D", "C", "F"])
def test_public_probes_are_one_line_and_unique(bench):
    mod = h.load_heldout(bench)
    probes = [probe for _name, probe in mod.CASES]
    assert all("\n" not in p and p.strip() for p in probes)
    assert len(set(probes)) == len(probes)


@pytest.mark.parametrize("bench", ["D", "C", "F"])
def test_upstream_and_original_pass_the_whole_file_scan(bench):
    # The CLI scans the whole candidate, so the reference candidates must not be refused.
    for name in (f"sap_{bench}_original.abap", f"sap_{bench}_upstream_fix.abap"):
        text = (ROOT / "tests" / "controls" / name).read_text(encoding="utf-8")
        assert t.check_abap_text(text) == [], name


def test_cli_refuses_a_candidate_with_kernel_text(tmp_path):
    original = (ROOT / "tests" / "controls" / "sap_D_original.abap").read_text(encoding="utf-8")
    candidate = tmp_path / "kernel.abap"
    candidate.write_text(original + "\n* x\n  WRITE '@KERNEL alert(1)'.\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "D", str(candidate)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 1
    assert "refused" in proc.stdout
    assert "@KERNEL" in proc.stdout
    last = proc.stdout.strip().splitlines()[-1]
    assert last.startswith("heldout: 0/8 passed (refused: ")
    assert "@KERNEL (raw JavaScript)" in last


def test_cli_usage_error_exit_code(tmp_path):
    proc = subprocess.run([sys.executable, str(CLI), "A", str(tmp_path / "x.abap")], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2


def test_summary_line_format():
    assert h.summary_line(3, 8) == "heldout: 3/8 passed"
    assert re.fullmatch(r"heldout: \d+/\d+ passed", h.summary_line(0, 11))
    assert h.summary_line(0, 8, "refused: x") == "heldout: 0/8 passed (refused: x)"


def test_case_lines_report_pass_fail_and_missing():
    cases = [("a_case", "probe a"), ("b_case", "probe b"), ("c_case", "probe c")]
    results = {"ltcl_x->a_case": "PASS", "ltcl_x->b_case": "FAIL: expected 1 got 2", "ltcl_x->other": "PASS"}
    passed, lines = h.case_lines(cases, results, "ltcl_x")
    assert passed == 1
    assert lines == [
        "  PASS a_case - probe a",
        "  FAIL b_case - probe b :: expected 1 got 2",
        "  FAIL c_case - probe c :: no result",
    ]


def test_build_cfg_drops_only_methods_and_keeps_the_rest():
    runner = json.loads((ROOT / "docs/sap/bench/C/runner.json").read_text(encoding="utf-8"))
    assert "only_methods" in runner
    cfg = h.build_cfg(runner)
    assert "only_methods" not in cfg
    assert cfg["only_object"] == runner["only_object"]
    assert "only_methods" in runner  # the input is not changed
