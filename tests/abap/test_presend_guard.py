"""Pre-send guard (2026-11-16, company data rule): nothing that holds a credential shape (an API key, a bearer token, an authorization header) is sent to
any model. Two layers: a job whose files, spec or reference hold one ends `blocked` before any model call, and every single request is scanned once more
before it is sent. Fakes only: no model, no network."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
sys.path.insert(0, str(REPO / "pieces"))
import exec_role as er  # noqa: E402
import p1b_routing as p1b  # noqa: E402
from test_exec_role import FILES, FILE_TEXT, production, roster_with_cli_writer  # noqa: E402
from test_p1b_production_run import FakeClient, FakeSandbox, load, make_prod_root, p1b_job, wp_h_root, wp_h_status  # noqa: E402
import fix_loop as fl  # noqa: E402

FAKE_KEY = "sk-or-v1-" + "a1b2c3d4e5f6" * 4


def test_a_request_holding_a_key_shape_is_refused_before_anything_is_sent(tmp_path, monkeypatch):
    roster_with_cli_writer(monkeypatch)
    sent = []
    monkeypatch.setattr(er, "ask_role", lambda *a, **k: sent.append(a) or FILE_TEXT)
    models, _history = production(wp_h_root(tmp_path))
    with pytest.raises(p1b.Blocked, match="credential-shaped"):
        models._ask("dots-studio/dots-3-note-preview:free", "system", f"please use this key {FAKE_KEY}", kind="writer", mode="write")
    assert sent == []


def test_a_clean_request_is_sent(tmp_path, monkeypatch):
    roster_with_cli_writer(monkeypatch)
    sent = []
    monkeypatch.setattr(er, "ask_role", lambda *a, **k: sent.append(a) or FILE_TEXT)
    models, _history = production(wp_h_root(tmp_path))
    models._ask("dots-studio/dots-3-note-preview:free", "system", "fix the method", kind="writer", mode="write")
    assert len(sent) == 1


def test_a_job_whose_spec_holds_a_key_shape_ends_blocked_with_no_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("SATVIK_PROFILE", "production")      # the job's budget is the production profile's
    root = wp_h_root(tmp_path)
    (root / "specs").mkdir(exist_ok=True)
    (root / "specs" / "s.md").write_text(f"KNOWN: the token is Bearer {FAKE_KEY}\n", encoding="utf-8")
    client = FakeClient([])
    result = fl.run_job(load(root, p1b_job()), root, sandbox=FakeSandbox({}), openrouter=client, scrub_keys=[])
    assert result["state"] == "blocked" and client.calls == []
    assert (root / "_loop" / "calc" / "BLOCKED.md").is_file() and wp_h_status(root)["state"] == "blocked"
