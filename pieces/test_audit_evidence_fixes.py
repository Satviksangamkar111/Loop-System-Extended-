"""Audit 2026-11-18 evidence fixes (defects 3, 9, 17, 18, 19): one small test per fix, with fakes only. No model call, no network, no real claude
process (conftest keeps the Opus switch off), no secrets folder."""
import contextlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "source"))
import claude_code as cc  # noqa: E402
import openrouter_call as oc  # noqa: E402
import p1b_production as pm  # noqa: E402
import plan_review as pr  # noqa: E402

TICKET = "Subtract must borrow across months.\n"
READY = "## Verdict: READY"
SHARED_ROLES = {"writer_a": "model-w", "writer_b": "model-wb", "reviewer_a": "model-shared", "reviewer_b": "model-shared", "repair": "model-r"}


def _load_poc():
    spec = importlib.util.spec_from_file_location("sap_poc_run_audit", REPO / "scripts" / "sap_poc_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# defect 17: prompt_tokens counts the cache fields too; defect 3: the CLI's total_cost_usd is kept
def test_claude_prompt_tokens_count_cache_creation_and_cache_reads():
    out = json.dumps({"result": "x", "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1000,
                                               "cache_read_input_tokens": 3000, "output_tokens": 5}, "total_cost_usd": 0.02})
    facts = cc.envelope_facts(out)
    assert facts["usage"] == {"prompt_tokens": 4002, "completion_tokens": 5}
    assert facts["cost_usd"] == 0.02
    assert cc.envelope_facts(json.dumps({"result": "x"})) == {"reply_text": "x", "usage": {}, "cost_usd": None}


# defect 9: a Claude plan review keeps each raw envelope in the plan folder
def test_a_claude_plan_review_keeps_its_raw_envelope(tmp_path, monkeypatch):
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "SPEC.md").write_text("# Spec\n- KNOWN: Subtract borrows across months.\n", encoding="utf-8")
    (plan / "units.json").write_text("{}\n", encoding="utf-8")
    specs = {"reviewer_b": {"model": "model-rev", "via": "claude_code", "effort": "high"}, "planner": {"model": "model-plan"}}
    monkeypatch.setattr(pr.oc, "roster_state", lambda profile=None: {"ROLE_SPECS": specs})
    seen = []

    def fake_ask_role(role, system, user, kind, *, raw_sink=None, **kw):
        seen.append((role, kind))
        raw_sink(json.dumps({"result": READY, "is_error": False}))
        return READY
    monkeypatch.setattr(cc, "ask_role", fake_ask_role)
    assert pr.review_plan(plan, TICKET)["status"] == "passed"
    assert seen == [("reviewer_b", "reviewer")]
    assert json.loads((plan / "plan_review_01_raw.json").read_text(encoding="utf-8"))["result"] == READY


# defect 18: a review slot whose model is shared is logged as its own role, and its call runs as that role
def _production(monkeypatch, models=SHARED_ROLES):
    monkeypatch.setattr(pm.p1b, "_m", lambda role, snapshot=None: models[role])
    prod = pm.Production.__new__(pm.Production)
    prod.stop_check, prod.scrub_keys, prod.served = None, (), {}
    return prod


def test_a_shared_model_review_is_logged_under_its_slot(monkeypatch):
    prod = _production(monkeypatch)
    assert prod._role_of("model-shared", "review", "reviewer_a") == "reviewer_a"
    assert prod._role_of("model-shared", "review", "reviewer_b") == "reviewer_b"
    assert prod._role_of("model-w", "write") == "writer_a"


def test_the_call_of_a_shared_review_slot_runs_and_is_logged_as_that_slot(monkeypatch):
    monkeypatch.delenv("SAP_BENCH_ID", raising=False)
    monkeypatch.setattr(pm.oc, "roster_state", lambda profile=None: {"VIA": {"reviewer_a": "openrouter", "reviewer_b": "openrouter"}})
    monkeypatch.setattr(pm.oc, "effort_for_mode", lambda mode: None)
    prod = _production(monkeypatch)
    calls, attempts = [], []

    class Client:
        def call(self, name, system, user, kind="text", effort=None):
            calls.append(name)
            return READY, {}

    @contextlib.contextmanager
    def attempt(model, role, mode, via, effort=None, slot=None):
        attempts.append((role, mode, slot))
        yield {}
    prod.client, prod._attempt, prod._record_history = Client(), attempt, (lambda model, mode: None)
    assert prod._ask("model-shared", "system", "user", kind="reviewer", mode="review", slot="reviewer_a") == READY
    assert calls == ["reviewer_a"] and attempts == [("reviewer_a", "review", "reviewer_a")]


# defect 3: every OpenRouter request asks for usage accounting, and the reply's usage.cost is kept on its call record
def test_every_openrouter_request_asks_for_usage_and_keeps_its_cost(monkeypatch):
    sent = []

    def transport(method, url, headers, body, timeout):
        sent.append(json.loads(body))
        return 200, {}, json.dumps({"model": "model-a", "choices": [{"message": {"content": READY}, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": 3, "completion_tokens": 1, "cost": 0.0123}}).encode()
    client = object.__new__(oc.OpenRouter)
    client.keys, client.transport, client._secrets, client._stage, client.requests, client._endpoints = {"free": "k"}, transport, [], None, [], {}
    monkeypatch.setattr(oc.OpenRouter, "_settings_of", lambda self, model: {"temperature": 0, "reasoning": None, "sampling": {}, "max_tokens": 100})
    status, _headers, raw = client._post("model-a", "free", "system", "user", 100, False, 5)
    assert sent[0]["usage"] == {"include": True}
    client._keep_request("model-a", status, 0.5, oc.parse_response(status, raw)[1])
    assert client.requests[-1]["cost_usd"] == 0.0123


def test_a_call_record_carries_its_cost(tmp_path):
    prod = pm.Production.__new__(pm.Production)
    prod.calls_written, prod._attempt_open, prod.history, prod.scrub_keys = 0, None, tmp_path, ()
    prod._write_call({"model": "model-a", "via": "openrouter", "usage": {"prompt_tokens": 3, "completion_tokens": 1}, "cost_usd": 0.0123}, "review")
    prod._write_call({"model": "model-b", "via": "claude_code", "usage": {}, "cost_usd": 0.5}, "write")
    assert json.loads((tmp_path / "call_01.json").read_text(encoding="utf-8"))["cost_usd"] == 0.0123
    assert json.loads((tmp_path / "call_02.json").read_text(encoding="utf-8"))["cost_usd"] == 0.5


# defect 19: no "reviewer is skipped" warning under the duplicate-model switch; review-open is not a pass
def test_the_repair_warning_is_silent_under_the_duplicate_model_switch(monkeypatch, capsys):
    poc = _load_poc()
    rows = [("writer_a", "model-w", "openrouter", ""), ("writer_b", "model-wb", "openrouter", ""), ("reviewer_a", "model-r", "openrouter", ""),
            ("reviewer_b", "model-s", "openrouter", ""), ("repair", "model-r", "claude_code", "high"), ("planner", "model-p", "openrouter", "")]
    monkeypatch.setattr(poc, "role_rows", lambda path=None: rows)
    monkeypatch.setenv("SAP_ALLOW_DUPLICATE_MODELS", "1")
    assert poc.main(["--roles"]) == 0
    assert "skipped" not in capsys.readouterr().out
    monkeypatch.delenv("SAP_ALLOW_DUPLICATE_MODELS")
    assert poc.main(["--roles"]) == 0
    assert "skipped" in capsys.readouterr().out


def test_review_open_exits_non_zero():
    poc = _load_poc()
    assert poc.exit_code("passed") == 0
    assert poc.exit_code("review-open") == 1 and poc.exit_code("escalate") == 1
