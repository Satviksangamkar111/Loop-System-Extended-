"""Frozen acceptance tests for scripts/source/sap_adt_logic.py (pure, no network; do not edit)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import sap_adt_logic as s

OK = "<runResult><program><testClasses><testClass><testMethods><testMethod name='a'/></testMethods></testClass></testClasses></program></runResult>"
NS = "<aunit:runResult xmlns:aunit='http://www.sap.com/adt/aunit'><program><testClasses><testClass><testMethods><testMethod/></testMethods></testClass></testClasses></program></aunit:runResult>"


def test_aunit_pass():
    assert s.evaluate_aunit(200, OK) == (True, [])
    assert s.evaluate_aunit(200, NS)[0] is True


def test_aunit_failures():
    assert s.evaluate_aunit(500, OK)[0] is False
    assert s.evaluate_aunit(200, "<broken")[0] is False
    assert s.evaluate_aunit(200, "<runResult/>")[0] is False
    nometh = "<runResult><program><testClasses><testClass/></testClasses></program></runResult>"
    assert s.evaluate_aunit(200, nometh)[0] is False
    for kind in ("failedAssertion", "exception", "aborted", "warning"):
        bad = OK.replace("<testMethod name='a'/>", f"<testMethod name='a'><alerts><alert kind='{kind}'/></alerts></testMethod>")
        ok, why = s.evaluate_aunit(200, bad)
        assert ok is False and why
    prog_alert = OK.replace("<program>", "<program><alerts><alert kind='info'/></alerts>")
    assert s.evaluate_aunit(200, prog_alert)[0] is False


def f(code="C1", msg="Variable X 12 unused", pri=3, line=10, uri="/o/a"):
    return {"obj_uri": uri, "check_id": code, "message_code": "M", "message": msg, "priority": pri, "line": line}


def test_atc_line_insensitive_and_normalized():
    base = [f(line=10), f(code="C2", msg="b", pri=2)]
    cand = [f(line=99, msg="variable  x 77 UNUSED"), f(code="C2", msg="b", pri=2, line=5)]
    assert s.evaluate_atc_delta(base, cand) == (True, [])


def test_atc_new_finding_fails():
    ok, why = s.evaluate_atc_delta([f()], [f(), f(code="C9")])
    assert ok is False and why
    ok, _ = s.evaluate_atc_delta([f()], [f(), f()])
    assert ok is False


def test_atc_fewer_findings_ok_and_severity_regression_fails():
    assert s.evaluate_atc_delta([f(), f(code="C2")], [f()])[0] is True
    assert s.evaluate_atc_delta([f(pri=3)], [f(pri=1)])[0] is False


def test_remote_states():
    c = s.classify_remote_state
    assert c("A", "I", "A", "I", "N", False) == "REMOTE_CLEAN_ORIGINAL"
    assert c("A", None, "A", None, "N", False) == "REMOTE_CLEAN_ORIGINAL"
    assert c("A", "I", "A", "N", "N", False) == "REMOTE_DIRTY_INACTIVE_CANDIDATE"
    assert c("A", "I", "N", "I", "N", False) == "REMOTE_ACTIVE_CANDIDATE_UNRESTORED"
    assert c("A", "I", "A", "I", "N", True) == "REMOTE_LOCKED_BY_CURRENT_OR_STALE_SESSION"
    assert c("A", "I", "HUMAN", "I", "N", False) == "REMOTE_CONFLICT_HUMAN_MODIFIED"
    assert c("A", "I", "A", "HUMAN", "N", False) == "REMOTE_CONFLICT_HUMAN_MODIFIED"


def test_aunit_stray_testmethod_outside_program_fails():
    assert s.evaluate_aunit(200, "<runResult><program/><testMethod/></runResult>")[0] is False


def test_aunit_bare_failure_element_fails():
    for kind in ("failedAssertion", "exception", "aborted", "warning"):
        bad = OK.replace("<testMethod name='a'/>", f"<testMethod name='a'><{kind}/></testMethod>")
        assert s.evaluate_aunit(200, bad)[0] is False


def test_atc_missing_priority_is_worst():
    nop = {"obj_uri": "/o/a", "check_id": "C1", "message_code": "M", "message": "Variable X 12 unused", "line": 1}
    assert s.evaluate_atc_delta([f(pri=3)], [nop])[0] is False


def test_remote_states_never_overwrite_human_edits():
    c = s.classify_remote_state
    assert c("A", "I", "A", None, "N", False) == "REMOTE_CONFLICT_HUMAN_MODIFIED"      # human removed the inactive version
    assert c("A", "I", "N", "HUMAN", "N", False) == "REMOTE_CONFLICT_HUMAN_MODIFIED"   # human edited inactive while active==candidate
    assert c("A", "I", "N", "N", "N", False) == "REMOTE_ACTIVE_CANDIDATE_UNRESTORED"
    assert c("A", "I", "N", None, "N", False) == "REMOTE_ACTIVE_CANDIDATE_UNRESTORED"
    assert c("A", "I", "N", "I", "N", False) == "REMOTE_ACTIVE_CANDIDATE_UNRESTORED"
