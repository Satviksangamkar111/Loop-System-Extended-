"""Tie-break arbiter (owner design 2026-11-16) and the served-by record (2026-11-16), with fakes only: no network, no model call, no process.

Routing: both panel reviewers always give a verdict; both READY passes; both FIX FIRST merge; one READY and one FIX FIRST goes to an arbiter (the first
optional arbiter role whose family differs from the panel's and the code's contributors). A roster with no arbiter roles keeps the old rule (the first
FIX FIRST goes straight to repair). The production runner writes ARBITER.md and an "arbiter" event for each decision and names x-served-by per call."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
sys.path.insert(0, str(REPO / "pieces"))
import event_log  # noqa: E402
import fix_loop as fl  # noqa: E402
import opus_repair as opus  # noqa: E402
import openrouter_call as oc  # noqa: E402
import p0_gates as gates  # noqa: E402
import p1b_production as pm  # noqa: E402
import p1b_routing as p1b  # noqa: E402
from test_p0_acceptance import make_prod_root, prod_job, GOOD_CODE, GOOD_TEST, NL  # noqa: E402
import prod_harness as ph  # noqa: E402

# The production roster's models (config/roster.json), written out so a changed roster fails the fixture below
DOTS = "dots-studio/dots-3-note-preview:free"             # writer_a
XING = "xingchen-agi/xing4.0-29b-a4b:free"               # writer_b
NORTH = "nvidia/nemotron-3-ultra-550b-a55b:free"         # reviewer_b (the free reviewer, its family nvidia)
GLM = "z-ai/glm-5.3-flash"                                # reviewer_a (the paid reviewer, its family z-ai)
GPT = "gpt-6-luna"                                        # an arbiter of another family (openai)
ANTHROPIC = p1b.ANTHROPIC
FILES = ["pieces/calc.py", "pieces/test_calc.py"]
PACKAGE = {"files": {"pieces/calc.py": 40, "pieces/test_calc.py": 40}, "spec_count": 5,
           "spec": ["Adds two prices.", "Returns an int.", "The total must include tax.", "Empty input returns 0.", "Prices are not negative."],
           "checks": [f"CHECK {n}: check text." for n in range(1, 6)]}
READY = "Looks right.\n## Verdict: READY"
FIX_ONE = "pieces/calc.py:12 breaks SPEC 3: the sum leaves out tax.\n## Verdict: FIX FIRST"
FIX_TWO = "pieces/calc.py:12 breaks SPEC 3: the sum leaves out tax.\npieces/calc.py:20 breaks SPEC 1: empty input fails.\n## Verdict: FIX FIRST"
FIX_TWO_OTHER = "pieces/calc.py:12 breaks SPEC 3: the sum leaves out tax.\n## Verdict: FIX FIRST"


@pytest.fixture(autouse=True)
def _production_profile(monkeypatch):
    """The production roster of config/roster.json (no arbiter roles), the Opus switch off, and no real Claude command."""
    monkeypatch.setenv("SATVIK_PROFILE", "production")
    monkeypatch.setattr(opus, "OPUS_ENABLED", False)
    roles = oc.roster_state()["ROLES"]
    assert (roles["writer_a"], roles["writer_b"], roles["reviewer_b"], roles["reviewer_a"]) == (DOTS, XING, NORTH, GLM)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Fake:
    """Scripted models: each (model, mode) queue holds replies or exceptions in call order. Records the arbiter's calls and rejected replies."""

    def __init__(self, script, tests=()):
        self.script = {key: list(items) for key, items in script.items()}
        self.tests_results = list(tests)
        self.log = []                               # (model, mode, slot) per call
        self.package = PACKAGE
        self.claims = []                            # the claims each arbiter call was given
        self.rejected = []                          # (model, mode, reason)
        self.records = []                           # the decision records handed to arbitrated()
        self.fixes = []

    def call(self, model, mode, files, slot=None, claims=None):
        self.log.append((model, mode, slot))
        if mode == "arbiter":
            self.claims.append(claims)
        queue = self.script.get((model, mode))
        if not queue:
            raise AssertionError(f"unscripted call {mode} {model}")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def reject(self, model, mode, reason):
        self.rejected.append((model, mode, reason))

    def arbitrated(self, record):
        self.records.append(record)

    def stage_fix(self, findings):
        self.fixes.append(list(findings))

    def tests(self, files):
        return self.tests_results.pop(0)

    def write(self, reply):
        pass

    def restore(self):
        pass

    def restore_green(self):
        pass

    def contract_check(self, *args):
        pass

    def calls(self, model=None, mode=None):
        return [c for c in self.log if (model is None or c[0] == model) and (mode is None or c[1] == mode)]


def lineage_of(origin=DOTS):
    lineage = p1b.Lineage()
    for path in FILES:
        lineage.set(path, origin, origin)
    return lineage


def review(script, candidates, models=None):
    """One review round of the candidate written by Dots, with the given arbiter candidates."""
    models = models or Fake(script)
    original = p1b.arbiter_candidates
    p1b.arbiter_candidates = lambda: list(candidates)
    try:
        outcome = p1b._review(FILES, models, lineage_of(), set())
    finally:
        p1b.arbiter_candidates = original
    return outcome, models


CANDIDATES = [("arbiter_a", GPT)]


# ---- 1. the two panel reviewers: both always give a verdict

def test_both_ready_passes_and_no_arbiter_is_called():
    outcome, models = review({(NORTH, "review"): [READY], (GLM, "review"): [READY]}, CANDIDATES)
    assert outcome.status == "passed" and "READY from" in outcome.reason
    assert models.calls(mode="arbiter") == [] and models.records == []


def test_both_fix_first_merges_both_findings_once_each_and_no_arbiter_is_called():
    north = "pieces/calc.py:12 breaks SPEC 3: the sum leaves out tax.\n## Verdict: FIX FIRST"
    glm = "pieces/calc.py:12 breaks SPEC 3: the sum leaves out tax.\npieces/calc.py:20 breaks SPEC 1: empty input fails.\n## Verdict: FIX FIRST"
    outcome, models = review({(NORTH, "review"): [north], (GLM, "review"): [glm]}, CANDIDATES)
    assert outcome.status == "review-fix"
    assert len(outcome.findings) == 2                                    # the line both named is kept once
    assert outcome.findings[0].startswith("pieces/calc.py:12") and outcome.findings[1].startswith("pieces/calc.py:20")
    assert [c[0] for c in models.calls(mode="review")] == [NORTH, GLM]
    assert models.calls(mode="arbiter") == [] and models.records == []


def test_both_reviewers_are_asked_even_when_the_first_says_fix_first():
    outcome, models = review({(NORTH, "review"): [FIX_ONE], (GLM, "review"): [READY], (GPT, "arbiter"): [
        "- finding 1: UPHELD: the tax is missing.\n## Verdict: FIX FIRST"]}, CANDIDATES)
    assert [c[0] for c in models.calls(mode="review")] == [NORTH, GLM]


# ---- 2. one READY and one FIX FIRST: the arbiter rules on each finding

def test_the_arbiter_upholding_one_of_two_findings_returns_only_that_finding():
    arbiter_reply = "- finding 1: UPHELD: the tax is really missing.\n- finding 2: REJECTED: the caller guards empty input.\n## Verdict: FIX FIRST"
    outcome, models = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY], (GPT, "arbiter"): [arbiter_reply]}, CANDIDATES)
    assert outcome.status == "review-fix"
    assert len(outcome.findings) == 1 and outcome.findings[0].startswith("pieces/calc.py:12")
    assert "upheld 1 of 2" in outcome.reason
    assert models.calls(GPT, "arbiter") == [(GPT, "arbiter", "arbiter_a")]
    claims = models.claims[0]
    assert claims["fix_reviewer"] == NORTH and claims["ready_reviewer"] == GLM and len(claims["findings"]) == 2
    assert claims["ready_text"].strip() == READY


def test_the_arbiter_upholding_no_finding_passes_and_the_reason_says_it_overruled_them():
    arbiter_reply = "- finding 1: REJECTED: the code is right.\n- finding 2: REJECTED: the caller guards it.\n## Verdict: READY"
    outcome, models = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY], (GPT, "arbiter"): [arbiter_reply]}, CANDIDATES)
    assert outcome.status == "passed" and outcome.findings == ()
    assert "overruled all 2 findings" in outcome.reason
    assert models.records[0]["outcome"] == "passed"


def test_the_arbiter_upholding_every_finding_returns_all_of_them():
    arbiter_reply = "- finding 1: UPHELD: the tax is missing.\n- finding 2: UPHELD: empty input fails.\n## Verdict: FIX FIRST"
    outcome, _ = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY], (GPT, "arbiter"): [arbiter_reply]}, CANDIDATES)
    assert outcome.status == "review-fix" and len(outcome.findings) == 2


def test_an_unparseable_arbiter_reply_leaves_the_fix_first_findings_standing():
    outcome, models = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY], (GPT, "arbiter"): ["I think they are both partly right."]},
                             CANDIDATES)
    assert outcome.status == "review-fix" and len(outcome.findings) == 2
    assert "arbiter reply unusable" in outcome.reason
    assert models.rejected and models.rejected[0][:2] == (GPT, "arbiter")


@pytest.mark.parametrize("reply", [
    "- finding 1: UPHELD: ok.\n## Verdict: FIX FIRST",                                              # finding 2 has no ruling
    "- finding 1: UPHELD: ok.\n- finding 1: REJECTED: twice.\n- finding 2: REJECTED: no.\n## Verdict: FIX FIRST",   # a finding ruled twice
    "- finding 1: UPHELD: ok.\n- finding 2: MAYBE: unsure.\n## Verdict: FIX FIRST",               # a ruling that is neither word
    "- finding 1: REJECTED: no.\n- finding 2: REJECTED: no.\n## Verdict: FIX FIRST",             # all rejected but the verdict says FIX FIRST
    "- finding 1: UPHELD: yes.\n- finding 2: REJECTED: no.\n## Verdict: READY",                  # one upheld but the verdict says READY
    "- finding 1: UPHELD: yes.\n- finding 2: REJECTED: no.\n- finding 3: REJECTED: extra.\n## Verdict: FIX FIRST",   # a finding that does not exist
])
def test_a_ruling_that_does_not_parse_or_does_not_match_the_verdict_is_unusable(reply):
    assert p1b.arbiter_rulings(reply, 2) is None


def test_a_consistent_ruling_is_read_line_by_line():
    reply = "- finding 1: UPHELD: yes, the tax is missing.\n- finding 2: REJECTED: no.\n## Verdict: FIX FIRST"
    assert p1b.arbiter_rulings(reply, 2) == [(1, "UPHELD", "yes, the tax is missing."), (2, "REJECTED", "no.")]


def test_a_failed_arbiter_call_leaves_the_findings_standing():
    outcome, models = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY], (GPT, "arbiter"): [p1b.ModelFailed("arbiter provider down")]},
                             CANDIDATES)
    assert outcome.status == "review-fix" and len(outcome.findings) == 2
    assert "arbiter unavailable" in outcome.reason and "arbiter provider down" in outcome.reason
    assert models.records[0]["outcome"] == "review-fix"


def test_no_eligible_arbiter_because_it_shares_a_family_with_the_author_leaves_the_findings_standing():
    dots_again = "dots-studio/dots-3-note-preview:free"
    outcome, models = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY]}, [("arbiter_a", dots_again)])
    assert outcome.status == "review-fix" and len(outcome.findings) == 2
    assert "arbiter unavailable" in outcome.reason
    assert models.calls(mode="arbiter") == []


def test_no_eligible_arbiter_because_it_shares_a_family_with_a_panel_reviewer_is_refused_too():
    nvidia_again = "nvidia/nemotron-3.5-super-vl:free"
    outcome, models = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY]}, [("arbiter_a", nvidia_again)])
    assert outcome.status == "review-fix" and "arbiter unavailable" in outcome.reason and models.calls(mode="arbiter") == []


def test_the_first_eligible_arbiter_is_used_and_an_ineligible_first_candidate_is_skipped():
    arbiter_reply = "- finding 1: REJECTED: no.\n- finding 2: REJECTED: no.\n## Verdict: READY"
    outcome, models = review({(NORTH, "review"): [FIX_TWO], (GLM, "review"): [READY], (GPT, "arbiter"): [arbiter_reply]},
                             [("arbiter_a", NORTH), ("arbiter_b", GPT)])
    assert outcome.status == "passed"
    assert models.calls(mode="arbiter") == [(GPT, "arbiter", "arbiter_b")]


def test_family_of_names_the_families_from_config_and_leaves_unknown_models_their_own_id():
    assert p1b.family_of(NORTH) == "nvidia" and p1b.family_of(DOTS) == "dots" and p1b.family_of(GPT) == "openai"
    assert p1b.family_of("haiku") == "anthropic" and p1b.family_of("sonnet") == "anthropic" and p1b.family_of("opus") == "anthropic"
    assert p1b.family_of(ANTHROPIC) == "anthropic"
    assert p1b.family_of(XING) == XING and p1b.family_of(GLM) == "z-ai/glm-5.3-flash"      # no family row: its own ID


# ---- 3. a roster without arbiter roles behaves as before

def test_config_roster_json_has_no_arbiter_role():
    assert p1b.arbiter_candidates() == []                       # config/roster.json, production profile: no arbiter role


def test_a_roster_without_arbiter_roles_sends_the_first_fix_first_straight_to_repair():
    tests = [p1b.Result(True, frozenset(), frozenset(), False), p1b.Result(True, frozenset(), frozenset(), False)]
    full = {"pieces/calc.py": "x = 1\n", "pieces/test_calc.py": "def test(): pass\n"}
    script = {(DOTS, "write"): [full], (NORTH, "review"): [FIX_ONE, READY], (DOTS, "repair"): [full], (GLM, "review"): [READY]}
    models = Fake(script, tests)
    outcome = p1b.walk({"files": FILES, "deadline_min": 60}, models, lineage_of(), Clock())
    assert outcome.status == "passed", outcome
    assert len(models.calls(GLM, "review")) == 1                       # GLM only after NORTH's READY, in the second round
    assert models.calls(mode="arbiter") == []
    assert [c[0] for c in models.log if c[1] in ("review", "repair")] == [NORTH, DOTS, NORTH, GLM]
    assert len(models.fixes) == 1                                       # the finding went to the repair step, not to an arbiter


# ---- 4. the production runner: ARBITER.md, the arbiter event, served_by

def bare_production(job_dir, scrub_keys=()):
    """A Production object for the record methods only (no client, no sandbox): the attributes arbitrated and _write_call read."""
    obj = object.__new__(pm.Production)
    obj.job_dir, obj.scrub_keys, obj.arbiter_decisions = Path(job_dir), tuple(scrub_keys), []
    obj.history, obj.calls_written, obj._attempt_open = None, 0, None
    return obj


def decision(outcome="review-fix"):
    return {"findings": ["pieces/calc.py:12 | SPEC 3: The total must include tax. | the sum leaves out tax."], "outcome": outcome,
            "reason": "arbiter x upheld 1 of 2", "fix": {"reviewer": NORTH, "text": FIX_TWO}, "ready": {"reviewer": GLM, "text": READY},
            "arbiter": {"model": GPT, "role": "arbiter_a"}, "reply": "- finding 1: UPHELD: yes.\n## Verdict: FIX FIRST",
            "rulings": [{"n": 1, "verdict": "UPHELD", "reason": "yes."}, {"n": 2, "verdict": "REJECTED", "reason": "no."}]}


def test_the_production_runner_writes_arbiter_md_with_both_claims_the_arbiter_and_each_ruling(tmp_path):
    obj = bare_production(tmp_path)
    pm.Production.arbitrated(obj, decision())
    text = (tmp_path / "ARBITER.md").read_text(encoding="utf-8")
    assert "FIX FIRST claim (" + NORTH + ")" in text and "READY claim (" + GLM + ")" in text
    assert "Arbiter: " + GPT + " (arbiter_a)" in text
    assert "- finding 1: UPHELD: yes." in text and "- finding 2: REJECTED: no." in text
    assert "Reason: arbiter x upheld 1 of 2" in text
    pm.Production.arbitrated(obj, decision("passed"))                  # a second decision of the job is kept, in order
    text = (tmp_path / "ARBITER.md").read_text(encoding="utf-8")
    assert text.index("## Decision 1") < text.index("## Decision 2")


def test_an_arbiter_decision_writes_an_arbiter_event_when_the_event_log_takes_the_type(tmp_path, monkeypatch):
    monkeypatch.setattr(event_log, "TYPES", event_log.TYPES + ("arbiter",))   # the type is named by event_log; without it emit writes nothing
    obj = bare_production(tmp_path)
    pm.Production.arbitrated(obj, decision())
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    arbiter = [e for e in events if e["type"] == "arbiter"]
    assert len(arbiter) == 1 and arbiter[0]["upheld"] == 1 and arbiter[0]["rejected"] == 1 and arbiter[0]["arbiter"] == GPT


def test_an_arbiter_call_is_a_history_record_named_arbiter_with_its_reply_kept(tmp_path):
    obj = bare_production(tmp_path)
    obj.history = tmp_path
    obj.client = None
    request = {"model": GPT, "status": 200, "failed": False, "seconds": 1.0, "usage": {"prompt_tokens": 9, "completion_tokens": 3},
               "reply_text": "- finding 1: REJECTED: no.\n## Verdict: READY", "finish_reason": "stop"}
    pm.Production._write_call(obj, request, "arbiter")
    record = json.loads((tmp_path / "call_01.json").read_text(encoding="utf-8"))
    assert record["mode"] == "arbiter" and record["model"] == GPT and record["reply_file"] == "history/review_01.txt"


def test_a_call_record_names_the_served_by_header_and_is_null_without_it(tmp_path):
    obj = bare_production(tmp_path)
    obj.history = tmp_path
    pm.Production._write_call(obj, {"model": DOTS, "status": 200, "served_by": "host-a", "seconds": 1.0}, "write")
    pm.Production._write_call(obj, {"model": DOTS, "status": 200, "seconds": 1.0}, "write")      # an old request: no header
    first = json.loads((tmp_path / "call_01.json").read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "call_02.json").read_text(encoding="utf-8"))
    assert first["served_by"] == "host-a" and second["served_by"] is None


# ---- 5. the client keeps the x-served-by header of a reply (a fake transport)

def test_the_client_keeps_the_served_by_header_of_a_reply_and_leaves_it_out_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("SATVIK_PROFILE", "test")
    monkeypatch.setenv("SATVIK_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    replies = [{"X-Served-By": " dots-host-1 "}, {}]
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append(url)
        payload = {"id": "gen", "model": DOTS, "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
        return 200, replies.pop(0), json.dumps(payload).encode()

    client = oc.OpenRouter({"free": "sk-or-v1-FREETEST000000000000"}, tmp_path / "ledger", transport=transport, clock=Clock(),
                           sleep=lambda s: None, rand=lambda: 0.0)
    text, _info = client.call("writer_a", "system", "user", kind="text")
    assert text == "ok" and client.requests[-1]["served_by"] == "dots-host-1"
    client.call("writer_a", "system", "user", kind="text")
    assert "served_by" not in client.requests[-1]                      # an old-style reply without the header stays valid


# ---- 6. end to end: a production job through fl.run_job, with an arbiter role on a temp roster and fakes only

ORIG_CODE = "def calculate_total(prices):" + NL + "    return 0" + NL
ORIG_TEST = "def test_placeholder():" + NL + "    pass" + NL
ACC_IDS = ["tests/acceptance/test_calc_acceptance.py::test_sums_two_prices", "tests/acceptance/test_calc_acceptance.py::test_sums_three_prices",
           "tests/acceptance/test_calc_acceptance.py::test_empty_is_zero"]


class EndClient:
    """The OpenRouter client stand-in: replies are popped in call order; every call's role is recorded."""

    def __init__(self, queue):
        self.queue, self.calls, self.retry_log, self.failed_attempts, self.requests = list(queue), [], [], [], []
        self.budget = oc.JobBudget(40, 0.05)

    def begin_job(self):
        pass

    def set_job_deadline(self, seconds):
        pass

    def call(self, role, system, user, kind, effort=None):
        self.calls.append(oc.ROLES[role])
        self.requests.append({"model": oc.ROLES[role], "status": 200, "failed": False, "seconds": 1.0, "finish_reason": "stop",
                              "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
        return self.queue.pop(0), {}


class EndSandbox:
    """Runs no pytest: every expected test passes (the same XML shape the real sandbox returns)."""

    def selftest(self):
        return []

    def run(self, root, targets, readonly=(), timeout_s=600, overlay=None):
        cases, failed = [], overlay is not None           # a negative control (overlay) must fail every expected test, as the real one does
        for rel, ids in sorted(gates.expected_test_ids(root, targets).items()):
            for tid in sorted(ids or ()):
                name, cls = f'name="{tid}" file="{rel}"', rel[:-3].replace("/", ".")
                cases.append(f'<testcase classname="{cls}" {name}><failure message="assert False">E   AssertionError: assert False</failure></testcase>' if failed else f'<testcase classname="{cls}" {name}/>')
        xml = "<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>"
        return SimpleNamespace(output="fake", junit=xml, returncode=1 if failed else 0, timed_out=False)


def test_a_production_job_with_an_arbiter_role_writes_arbiter_md_and_passes_when_the_arbiter_overrules(tmp_path, monkeypatch):
    data = json.loads((REPO / "config" / "roster.json").read_text(encoding="utf-8"))
    roles = data["profiles"]["production"]["roles"]
    roles["arbiter_a"] = {"model": XING, "provider": None, "paid": False, "pricing": None, "settings": dict(roles["writer_b"]["settings"])}
    roster = tmp_path / "roster.json"
    roster.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(oc, "ROSTER_PATH", roster)
    monkeypatch.setattr(oc, "_ROSTER_STATE", {})
    assert p1b.arbiter_candidates() == [("arbiter_a", XING)]          # Xing wrote nothing in this job: its family is free to arbitrate
    root = make_prod_root(tmp_path)
    (root / "pieces" / "calc.py").write_text(ORIG_CODE, encoding="utf-8")
    (root / "pieces" / "test_calc.py").write_text(ORIG_TEST, encoding="utf-8")
    job = prod_job(budget={"free_requests": 40, "review_usd": 0.05, "paid_usd": 0})
    client = EndClient([
        ph.file_reply(("pieces/calc.py", GOOD_CODE), ("pieces/test_calc.py", GOOD_TEST)),           # Dots writes; the tests pass
        "pieces/calc.py:1 breaks SPEC 1: the total is wrong.\n## Verdict: FIX FIRST",             # Nemotron (reviewer_b) finds one
        READY,                                                                                       # GLM (reviewer_a) says READY
        "- finding 1: REJECTED: the code is right.\n## Verdict: READY",                              # the arbiter overrules it
    ])
    result = fl.run_job(job, root, sandbox=EndSandbox(), openrouter=client, scrub_keys=[])
    assert result["state"] == "passed", result
    assert client.calls == [DOTS, NORTH, GLM, XING]
    text = (root / "_loop" / "calc" / "ARBITER.md").read_text(encoding="utf-8")
    assert "FIX FIRST claim (" + NORTH + ")" in text and "READY claim (" + GLM + ")" in text
    assert "- finding 1: REJECTED: the code is right." in text
    history = sorted((root / "_loop" / "calc" / "history").glob("call_*.json"))
    assert json.loads(history[-1].read_text(encoding="utf-8"))["mode"] == "arbiter"
