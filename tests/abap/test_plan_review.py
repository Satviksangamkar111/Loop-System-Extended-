"""scripts/source/plan_review.py with FAKE `ask` replies only: no model call, no network."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
import exec_role as er  # noqa: E402
import openrouter_call as oc  # noqa: E402
import plan_review as pr  # noqa: E402

TICKET = "Subtract must borrow across months.\n"
SPEC = "# Spec\n- KNOWN: Subtract borrows across months.\n- KNOWN: Result is a timestamp.\n"
READY = "## Verdict: READY"
BAD = "- SPEC.md:3: the ticket never asks for a timestamp result.\n## Verdict: FIX FIRST"


@pytest.fixture
def plan_dir(tmp_path):
    d = tmp_path / "plan"
    d.mkdir()
    (d / "SPEC.md").write_text(SPEC, encoding="utf-8")
    (d / "units.json").write_text('{\n "units": []\n}\n', encoding="utf-8")
    (d / "u1.SPEC.md").write_text("# u1\n- KNOWN: Subtract borrows across months.\n", encoding="utf-8")
    return d


class Ask:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, role, system, user):
        self.calls.append((role, system, user))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_a_clean_plan_passes(plan_dir):
    ask = Ask(READY)
    out = pr.review_plan(plan_dir, TICKET, ask=ask)
    assert out["status"] == "passed" and out["findings"] == []
    assert "3| - KNOWN: Result is a timestamp." in ask.calls[0][2] and "ticket" in ask.calls[0][2].lower()   # numbered lines, ticket present


def test_an_unsupported_line_gets_revise_and_the_hook_runs_once(plan_dir):
    out = pr.review_plan(plan_dir, TICKET, ask=Ask(BAD))
    assert out["status"] == "revise" and out["findings"][0].startswith("SPEC.md:3")
    seen = []
    ask = Ask(BAD, READY)
    out = pr.review_plan(plan_dir, TICKET, ask=ask, revise=lambda f: seen.append(f) or True)
    assert out["status"] == "passed" and len(seen) == 1 and seen[0][0].startswith("SPEC.md:3")


def test_a_citation_of_a_missing_line_or_file_does_not_count(plan_dir):
    ask = Ask("- SPEC.md:99: x\n- other.md:1: y\n## Verdict: FIX FIRST", READY)      # no valid finding: asked again, then READY
    assert pr.review_plan(plan_dir, TICKET, ask=ask)["status"] == "passed" and len(ask.calls) == 2


def test_an_assumed_line_is_recorded_as_a_note_but_does_not_fail_a_plan_the_reviewer_passed(plan_dir):
    (plan_dir / "SPEC.md").write_text(SPEC + "- ASSUMED: Blanks are kept.\n", encoding="utf-8")
    out = pr.review_plan(plan_dir, TICKET, ask=Ask(READY))
    assert out["status"] == "passed" and out["findings"][0].startswith("SPEC.md:4 ASSUMED")


def test_still_failing_after_three_revisions_ends_open_and_calls_no_writer(plan_dir):
    calls = []
    out = pr.review_plan(plan_dir, TICKET, ask=Ask(BAD, BAD, BAD, BAD), revise=lambda f: calls.append(f) or True)
    assert out["status"] == "open" and out["rounds"] == 4 and len(calls) == 3      # three revisions at most; the caller sees open, so no writer runs


def test_a_later_revision_can_pass(plan_dir):
    calls = []
    out = pr.review_plan(plan_dir, TICKET, ask=Ask(BAD, BAD, READY), revise=lambda f: calls.append(f) or True)
    assert out["status"] == "passed" and out["rounds"] == 3 and len(calls) == 2


def test_a_malformed_reply_is_asked_once_more_then_open(plan_dir):
    ask = Ask("looks fine to me", "still no verdict")
    out = pr.review_plan(plan_dir, TICKET, ask=ask)
    assert out["status"] == "open" and len(ask.calls) == 2
    assert pr.review_plan(plan_dir, TICKET, ask=Ask("no verdict", READY))["status"] == "passed"


def test_tool_use_in_the_codex_session_fails_the_review(plan_dir):
    ask = Ask(er.ExecFailed("tool use detected in session x: item command_execution; the answer is not used"))
    out = pr.review_plan(plan_dir, TICKET, ask=ask)
    assert out["status"] == "open" and "tool use" in out["findings"][0]


def test_the_default_ask_is_luna_at_the_set_effort_and_never_reviews_its_own_plan(plan_dir, monkeypatch):
    specs = {"reviewer_b": {"model": "gpt-6-luna", "via": "cli_exec", "effort": "low"}, "planner": {"model": "haiku", "via": "claude_code"}}
    monkeypatch.setattr(oc, "roster_state", lambda profile=None: {"ROLE_SPECS": specs})
    got = []
    monkeypatch.setattr(er, "ask_role", lambda spec, system, user, **k: got.append(spec) or READY)
    assert pr.review_plan(plan_dir, TICKET)["status"] == "passed"
    assert got[0]["model"] == "gpt-6-luna" and got[0]["effort"] == pr.EFFORT == "medium"
    specs["planner"] = {"model": "gpt-6-luna"}
    assert pr.review_plan(plan_dir, TICKET)["status"] == "open" and len(got) == 1      # no second call
