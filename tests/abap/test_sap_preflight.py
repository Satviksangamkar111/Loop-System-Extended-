"""sap_preflight with fakes: no model call, no network."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
import sap_preflight as sp  # noqa: E402

ROLES = {"planner": {"model": "m1"}, "writer_a": {"model": "m2"}, "reviewer_a": {"via": "claude_code", "model": "haiku", "effort": "medium"},
         "repair": {"via": "claude_code", "model": "haiku", "effort": "low"}, "reviewer_b": {"model": "m1"}}
GOOD = lambda: {"limit_remaining": 50.0, "usage": 3.0, "credits_left": 20.0}


def test_one_call_per_distinct_model_and_all_ok():
    seen = []
    r = sp.preflight(ROLES, ask=lambda role, spec: seen.append(role), key_info=GOOD)
    assert r["ok"] and len(seen) == 4 and set(r["roles"]) == set(ROLES) and r["key"]["usage"] == 3.0


def test_failed_role_fails():
    def ask(role, spec):
        if spec["model"] == "m2":
            raise RuntimeError("HTTP 401")
    r = sp.preflight(ROLES, ask=ask, key_info=GOOD)
    assert not r["ok"] and r["failed"] == ["writer_a"] and "401" in r["roles"]["writer_a"]["error"]


def test_low_key_or_credits_fail(monkeypatch):
    monkeypatch.delenv("SAP_MIN_KEY_USD", raising=False)
    ok = lambda role, spec: None
    assert not sp.preflight(ROLES, ask=ok, key_info=lambda: {"limit_remaining": 0.5, "usage": 1, "credits_left": 20})["ok"]
    assert not sp.preflight(ROLES, ask=ok, key_info=lambda: {"limit_remaining": 50, "usage": 1, "credits_left": 0.2})["ok"]
    monkeypatch.setenv("SAP_MIN_KEY_USD", "0.1")
    assert sp.preflight(ROLES, ask=ok, key_info=lambda: {"limit_remaining": 0.5, "usage": 1, "credits_left": 20})["ok"]
    assert sp.preflight(ROLES, ask=ok, key_info=lambda: {"limit_remaining": None, "usage": 1, "credits_left": None})["ok"]


def test_unreadable_key_fails():
    def boom():
        raise RuntimeError("down")
    assert not sp.preflight(ROLES, ask=lambda r, s: None, key_info=boom)["ok"]


def test_claude_only_roster_reads_no_key():           # 2026-11-18 (defect 23): no OpenRouter role, so no key is needed or read
    claude_only = {"planner": {"via": "claude_code", "model": "haiku", "effort": "high"}, "reviewer_a": {"via": "claude_code", "model": "haiku", "effort": "high"}}

    def no_key():
        raise AssertionError("no OpenRouter key is read for a Claude-only roster")
    r = sp.preflight(claude_only, ask=lambda role, spec: None, key_info=no_key)
    assert r["ok"] and r["key_checked"] is False and r["key_problems"] == []
