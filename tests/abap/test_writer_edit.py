"""SAP extension (2026-11-16): a job with writer_edit makes its fresh write as SEARCH/REPLACE edits of the original files; its size gate has no
per-file or per-unit line limit (only a file over 200,000 characters is refused); a repair prompt shows the source around a `<file>.abap:<n>`
position of the failing tests. Fakes only: no model call, no Docker, no network."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
import fix_loop as fl  # noqa: E402
import openrouter_call as oc  # noqa: E402
import p1b_production as pm  # noqa: E402
import p1b_routing as p1b  # noqa: E402

NL = "\n"
CALC, TEST_CALC = "pieces/calc.py", "pieces/test_calc.py"
FILES = [CALC, TEST_CALC]
ORIG = "def calculate_total(prices):" + NL + "    return 0" + NL
TEST_TEXT = "def test_placeholder():" + NL + "    pass" + NL
SUMMED = "def calculate_total(prices):" + NL + "    return sum(prices)" + NL
WHOLE = "def calculate_total(prices):" + NL + "    return sum(prices)" + NL      # a whole-file reply's calc.py
EDIT_OK = ("FILE: pieces/calc.py" + NL + "<<<<<<< SEARCH" + NL + "    return 0" + NL + "=======" + NL + "    return sum(prices)" + NL
           + ">>>>>>> REPLACE" + NL)
EDIT_BAD = EDIT_OK.replace("    return 0", "    return 99")          # its SEARCH text is not in the file: refused
ACC = "tests/acceptance/test_calc_acceptance.py"
ORIG_TEST_ROOT_FILES = {
    "specs/s.md": "calculate_total(prices) returns the sum of the prices.",
    ACC: "from pieces.calc import calculate_total" + NL + "def test_sums_two_prices():" + NL + "    assert calculate_total([20, 30]) == 50" + NL,
    "tests/controls/calc_returns_none.py": "def calculate_total(prices):" + NL + "    return None" + NL,
    "tests/controls/calc_returns_constant.py": "def calculate_total(prices):" + NL + "    return 50" + NL,
}
BUDGET = {"free_requests": 40, "review_usd": 0.05, "paid_usd": 0}


class Client:
    """Stands in for the OpenRouter client: `replies` in call order (an exception item is raised instead); keeps every user text."""

    def __init__(self, replies):
        self.replies, self.users, self.calls = list(replies), [], []
        self.requests, self.failed_attempts, self.retry_log = [], [], []
        self.budget = oc.JobBudget(40, 0.05)

    def begin_job(self):
        pass

    def set_job_deadline(self, seconds):
        pass

    def call(self, role, system, user, kind, effort=None):
        self.users.append(user)
        self.calls.append(oc.ROLES[role])
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        self.requests.append({"model": oc.ROLES[role], "status": 200, "failed": False, "seconds": 0.0, "finish_reason": "stop",
                              "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "reasoning_tokens": None})
        return item, {}


class NoSandbox:
    """Stands in for the Docker sandbox: selftest passes, and a negative control run reports the acceptance test failing, as a control must."""

    def selftest(self):
        return []

    def run(self, root, targets, overlay=None, readonly=(), timeout_s=600):
        junit = ('<testsuites><testsuite><testcase classname="tests.acceptance.test_calc_acceptance" name="test_sums_two_prices" '
                 'file="tests/acceptance/test_calc_acceptance.py"><failure message="assert 0 == 50">E   AssertionError: assert 0 == 50</failure></testcase></testsuite></testsuites>')
        return SimpleNamespace(output="", junit=junit, returncode=1, timed_out=False)


@pytest.fixture
def writer_a(monkeypatch):
    """The production roster (SATVIK_PROFILE is read per call); returns the writer_a model id, the first writer."""
    monkeypatch.setenv("SATVIK_PROFILE", "production")
    return oc.roster_state()["ROLES"]["writer_a"]


def unit_job(**over):
    job = {"name": "calc", "spec": "specs/s.md", "files": list(FILES), "tests": [TEST_CALC], "acceptance_tests": [], "writer_edit": True}
    job.update(over)
    return job


def unit_root(tmp_path, calc=ORIG):
    root = tmp_path / "repo"
    for rel in list(FILES) + ["specs/s.md"]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / CALC).write_text(calc, encoding="utf-8")
    (root / TEST_CALC).write_text(TEST_TEXT, encoding="utf-8")
    (root / "specs" / "s.md").write_text(ORIG_TEST_ROOT_FILES["specs/s.md"], encoding="utf-8")
    return root


def models(root, client, job, parse_files=lambda text: ({}, [])):
    return pm.Production(job, root, client, None, protected=[], acceptance_lock=None, originals={}, parse_files=parse_files,
                         check_path=lambda rel: None, content_problem=lambda rel, content: None, history=None, job_dir=root / "_loop" / "calc")


def test_fresh_write_with_writer_edit_applies_the_edit_and_returns_every_job_file(tmp_path, writer_a):
    root = unit_root(tmp_path)
    client = Client([EDIT_OK])
    reply = models(root, client, unit_job()).call(writer_a, "write", FILES)
    assert set(reply) == set(FILES), "every job file is returned, so the routing check (set(reply) == wanted) passes"
    assert reply[CALC] == SUMMED
    assert reply[TEST_CALC] == (root / TEST_CALC).read_bytes().decode("utf-8"), "a file the edits did not touch is filled in from disk, unchanged"
    assert (root / CALC).read_text(encoding="utf-8") == ORIG, "the runner returns the reply; it writes nothing itself"
    assert "fresh write against the original files" in client.users[0]
    assert "byte-for-byte" in client.users[0]
    assert "SEARCH/REPLACE" in client.users[0]


def test_a_refused_edit_is_asked_again_once_then_falls_back_to_the_whole_file(tmp_path, writer_a):
    root = unit_root(tmp_path)
    client = Client([EDIT_BAD, EDIT_BAD, "whole-file reply"])
    m = models(root, client, unit_job(), parse_files=lambda text: ({CALC: WHOLE, TEST_CALC: TEST_TEXT}, []))
    reply = m.call(writer_a, "write", FILES)
    assert len(client.users) == 3, "first edit, one re-ask, then the whole-file request"
    assert "Your edits were refused" not in client.users[0]
    assert "Your edits were refused" in client.users[1]
    assert "Your edits were refused" not in client.users[2] and "fresh write" not in client.users[2]
    assert reply == {CALC: WHOLE, TEST_CALC: TEST_TEXT}
    assert [s["mode"] for s in m.steps].count("failed") == 2, "each refused reply is a failed call kept in the history"


def test_an_edit_that_would_leave_a_job_file_missing_is_refused_and_asked_again(tmp_path, writer_a):
    root = unit_root(tmp_path)
    (root / TEST_CALC).unlink()                               # test_calc.py is new: the edits do not touch it and cannot create it
    client = Client([EDIT_OK, EDIT_OK, "whole-file reply"])
    m = models(root, client, unit_job(), parse_files=lambda text: ({CALC: WHOLE, TEST_CALC: TEST_TEXT}, []))
    m.call(writer_a, "write", FILES)
    assert "edits cannot create it" in client.users[1]


def test_a_whole_file_reply_to_the_edit_request_is_filled_in_for_a_fresh_write(tmp_path, writer_a):
    root = unit_root(tmp_path)
    client = Client(["whole-file reply with calc.py only"])
    m = models(root, client, unit_job(), parse_files=lambda text: ({CALC: WHOLE}, []))
    reply = m.call(writer_a, "write", FILES)
    assert reply == {CALC: WHOLE, TEST_CALC: (root / TEST_CALC).read_bytes().decode("utf-8")}


def test_error_context_appears_for_an_abap_position_in_the_repair_digest_only(tmp_path, writer_a):
    src = "src/zcl_x.clas.abap"
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "pieces").mkdir()
    (root / "specs").mkdir()
    (root / "specs" / "s.md").write_text("spec", encoding="utf-8")
    (root / src).write_text(NL.join(f"line {i}" for i in range(1, 31)) + NL, encoding="utf-8")
    (root / TEST_CALC).write_text(TEST_TEXT, encoding="utf-8")
    job = unit_job(files=[src, TEST_CALC], writer_edit=False)
    with_position = ('<testsuites><testsuite><testcase classname="pieces.test_calc" name="test_parse" file="pieces/test_calc.py">'
                     '<failure message="parse error">E   parse error at src/zcl_x.clas.abap:12</failure></testcase></testsuite></testsuites>')
    without = ('<testsuites><testsuite><testcase classname="pieces.test_calc" name="test_sum" file="pieces/test_calc.py">'
               '<failure message="assert 0 == 50">E   AssertionError</failure></testcase></testsuite></testsuites>')
    m = models(root, Client([]), job)
    m.last_junit = with_position
    repair = m._writer_user("repair")
    assert pm.ERROR_CONTEXT_HEAD in repair and "FAILING TESTS" in repair
    assert f"{src}:12" in repair and "    12 > line 12" in repair
    assert "     7   line 7" in repair and "    17   line 17" in repair, "lines n-5 to n+5 are shown"
    assert "     6   line 6" not in repair and "    18   line 18" not in repair
    assert pm.ERROR_CONTEXT_HEAD not in m._writer_user("write"), "the block is for repairs only"
    m.last_junit = without
    assert pm.ERROR_CONTEXT_HEAD not in m._writer_user("repair"), "no position, no block"


def gate_root(tmp_path, calc_text):
    root = tmp_path / "repo"
    for d in ("specs", "pieces", "_loop/jobs", "tests/acceptance", "tests/controls"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for rel, text in ORIG_TEST_ROOT_FILES.items():
        (root / rel).write_text(text, encoding="utf-8")
    (root / CALC).write_text(calc_text, encoding="utf-8")
    (root / TEST_CALC).write_text(TEST_TEXT, encoding="utf-8")
    return root


def gate_job(writer_edit):
    """The production job shape of the P1b tests, with the flag under test."""
    job = {"name": "calc", "profile": "production", "visibility": "public", "spec": "specs/s.md", "files": list(FILES), "tests": [TEST_CALC],
           "reference": [], "fixers": ["writer_a", "writer_b"], "reviewers": "by_lineage", "budget": dict(BUDGET), "deadline_min": 60,
           "review": True, "acceptance_tests": [ACC],
           "negative_controls": [
               {"name": "returns None", "replace": {CALC: "tests/controls/calc_returns_none.py"},
                "must_fail": [ACC + "::test_sums_two_prices"]},
               {"name": "returns a constant", "replace": {CALC: "tests/controls/calc_returns_constant.py"},
                "must_fail": [ACC + "::test_sums_two_prices"]}]}
    if writer_edit is not None:
        job["writer_edit"] = writer_edit
    return job


def run_gate(tmp_path, calc_text, writer_edit):
    root = gate_root(tmp_path, calc_text)
    path = root / "_loop" / "jobs" / "calc.json"
    path.write_text(json.dumps(gate_job(writer_edit)), encoding="utf-8")
    loaded = fl.load_job(path)
    client = Client([oc.QuotaExhausted("free requests for today are used up")])     # the first writer call ends the run: the gate has passed
    result = fl.run_job(loaded, root, sandbox=NoSandbox(), openrouter=client, scrub_keys=[])
    return result, client


def long_file(lines=1600):
    return NL.join(f"# line {i}" for i in range(1, lines + 1)) + NL


def test_a_1600_line_file_passes_the_size_gate_only_with_writer_edit_on(tmp_path, writer_a, monkeypatch):
    monkeypatch.setattr(p1b, "FILE_LINES", 800)               # the default limits, whatever SAP_FILE_LINES or SAP_UNIT_LINES says
    monkeypatch.setattr(p1b, "UNIT_LINES", 1500)
    result, client = run_gate(tmp_path, long_file(), writer_edit=True)
    assert result["state"] == "quota-exhausted", result                # past the gate: the writer was called
    assert len(client.users) == 1

    result, client = run_gate(tmp_path / "off", long_file(), writer_edit=False)
    assert result["state"] == "job-too-large", result
    assert client.users == [], "refused before any model call"


def test_writer_edit_still_refuses_a_file_over_200000_characters(tmp_path, writer_a):
    result, client = run_gate(tmp_path, ("x = '" + "a" * 80000 + "'" + NL) * 3, writer_edit=True)
    assert result["state"] == "job-too-large", result
    assert "characters" in json.dumps(result["problems"]) and "200000" in json.dumps(result["problems"])
    assert client.users == []


def test_writer_edit_defaults_to_off_in_the_schema():
    assert fl.JOB_SCHEMA["properties"]["writer_edit"] == {"type": "boolean", "default": False}
