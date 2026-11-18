"""cli_exec roles (2026-11-16): a roster role whose "via" is "cli_exec" is one isolated coding-agent CLI call (scripts/source/exec_role.py).
Covered: the roster rules, the command built from config/exec_role.json, the runner's answer and its failures, the production path (the same
reply check and history record, nothing on the OpenRouter ledger), and the planner's envelope. Fakes only: no CLI, no model, no network."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
sys.path.insert(0, str(REPO / "pieces"))
import exec_role as er  # noqa: E402
import openrouter_call as oc  # noqa: E402
import p0_gates as gates  # noqa: E402
import p1b_production as pm  # noqa: E402
import plan_job as pj  # noqa: E402
from test_p1b_production_run import p1b_job, load, wp_h_root  # noqa: E402

FILES = ["pieces/calc.py", "pieces/test_calc.py"]
FILE_TEXT = "FILE: pieces/calc.py\n```python\nx = 1\n```\n"
GOOD_SPEC = {"model": "gpt-6-luna", "provider": None, "paid": False, "pricing": None, "effort": "high",
             "settings": {"temperature": None, "reasoning": None, "max_tokens": None, "timeout_s": 300, "sampling": None, "max_tokens_cap": None}}


# ---------------------------------------------------------------- 1. the roster rules and the command

def test_check_role_accepts_a_good_cli_exec_role_and_refuses_a_bad_effort_or_a_missing_model():
    assert er.check_role("production/writer_a", GOOD_SPEC) is None
    assert "effort" in er.check_role("p/w", dict(GOOD_SPEC, effort="max"))
    assert "effort" in er.check_role("p/w", dict(GOOD_SPEC, effort=None))
    assert "model" in er.check_role("p/w", dict(GOOD_SPEC, model=""))
    assert "model" in er.check_role("p/w", {k: v for k, v in GOOD_SPEC.items() if k != "model"})
    assert "paid" in er.check_role("p/w", dict(GOOD_SPEC, paid=True))
    assert "provider" in er.check_role("p/w", dict(GOOD_SPEC, provider={"name": "x", "slug": "x"}))


def test_the_command_comes_from_the_config_file_and_takes_the_model_effort_and_out_path(tmp_path):
    out = tmp_path / "answer.txt"
    cmd = er.build_command("gpt-6-luna", "medium", out)
    config = json.loads((REPO / "config" / "exec_role.json").read_text(encoding="utf-8"))
    assert cmd[0] == config["command"]
    assert cmd[cmd.index("-m") + 1] == "gpt-6-luna"
    assert "model_reasoning_effort=medium" in cmd and cmd[cmd.index("-o") + 1] == str(out)
    assert cmd[-1] == "-" and "--sandbox" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"


def test_the_roster_loads_a_cli_exec_role_and_refuses_a_bad_one(tmp_path):
    data = json.loads((REPO / "config" / "roster.json").read_text(encoding="utf-8"))
    data["profiles"]["production"]["roles"]["writer_a"] = dict(GOOD_SPEC, via="cli_exec")
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = oc.load_roster_data(path)["profiles"]["production"]["roles"]["writer_a"]
    assert oc.via_of(loaded) == "cli_exec" and loaded["model"] == "gpt-6-luna"
    data["profiles"]["production"]["roles"]["writer_a"] = dict(GOOD_SPEC, via="cli_exec", effort="max")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(oc.RosterRefused, match="effort"):
        oc.load_roster_data(path)
    assert "cli_exec" in oc.VIAS


def test_resolve_refuses_a_cli_exec_role_like_a_claude_code_role(monkeypatch):
    state = {"ROLES": {"writer_a": "gpt-6-luna"}, "VIA": {"writer_a": "cli_exec"}, "ALLOWED": frozenset(), "CATALOG_PAID": frozenset()}
    monkeypatch.setattr(oc, "roster_state", lambda profile=None: state)
    with pytest.raises(oc.ModelRefused, match="cli_exec"):
        oc.resolve("writer_a")


# ---------------------------------------------------------------- 2. the runner (a fake runner: no process)

def test_ask_role_joins_system_and_user_and_returns_the_answer_file_text():
    seen = {}

    def runner(cmd, input_text, timeout_s):
        seen.update(cmd=cmd, input_text=input_text, timeout_s=timeout_s)
        return 0, "THE ANSWER"

    assert er.ask_role(GOOD_SPEC, "SYSTEM", "USER", runner=runner) == "THE ANSWER"
    assert seen["input_text"].endswith("SYSTEM\n\nUSER") and er.TEXT_ONLY_NOTE in seen["input_text"] and seen["timeout_s"] == 300
    assert seen["cmd"][seen["cmd"].index("-m") + 1] == "gpt-6-luna"
    assert er.ask_role(dict(GOOD_SPEC, settings=None), "", "ONLY", runner=runner) == "THE ANSWER"
    assert seen["input_text"].endswith("ONLY") and seen["timeout_s"] == er.TIMEOUT_S


@pytest.mark.parametrize("answer", [(1, "some text"), (0, ""), (0, "   ")])
def test_a_non_zero_exit_or_an_empty_answer_is_a_failed_call(answer):
    with pytest.raises(er.ExecFailed):
        er.ask_role(GOOD_SPEC, "s", "u", runner=lambda cmd, text, t: answer)


def test_a_timeout_is_a_failed_call_marked_as_timed_out():
    def slow(cmd, text, timeout_s):
        raise subprocess.TimeoutExpired(cmd="x", timeout=timeout_s)

    with pytest.raises(er.ExecFailed) as caught:
        er.ask_role(GOOD_SPEC, "s", "u", runner=slow)
    assert caught.value.timed_out is True


def test_under_pytest_no_real_process_starts_without_an_injected_runner(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a process was started under pytest")

    monkeypatch.setattr(subprocess, "run", refuse)
    with pytest.raises(er.ExecFailed, match="refused"):
        er.ask_role(GOOD_SPEC, "s", "u")


# ---------------------------------------------------------------- 3. production: the same reply check and record, via cli_exec

class NoLedger:
    """Stands in for the OpenRouter client: a cli_exec role must never reach it."""
    requests, failed_attempts, retry_log = [], [], []

    def call(self, *args, **kwargs):
        raise AssertionError("a cli_exec role went to OpenRouter")


def roster_with_cli_writer(monkeypatch):
    monkeypatch.setenv("SATVIK_PROFILE", "production")         # the job's budget is the production profile's
    real = oc.roster_state()
    spec = dict(real["ROLE_SPECS"]["writer_a"], via="cli_exec", effort="high", provider=None, pricing=None, paid=False)
    state = dict(real, VIA=dict(real["VIA"], writer_a="cli_exec"), ROLE_SPECS=dict(real["ROLE_SPECS"], writer_a=spec))
    monkeypatch.setattr(oc, "roster_state", lambda profile=None: state)
    return spec


def production(root, claude_ask=None):
    job = load(root, p1b_job())
    history = root / "_loop" / "calc" / "history"
    history.mkdir(parents=True, exist_ok=True)
    models = pm.Production(job, root, NoLedger(), None, protected=[], acceptance_lock=gates.hash_paths(root, []), originals={},
                           parse_files=lambda text: ({"pieces/calc.py": "x = 1\n"} if oc.FILE_BLOCK.search(text) else {}, []),
                           check_path=lambda rel: None, content_problem=lambda rel, content: None, history=history,
                           job_dir=root / "_loop" / "calc")
    return models, history


def test_a_writer_on_cli_exec_gets_its_fake_answer_checked_and_recorded_with_via_cli_exec(tmp_path, monkeypatch):
    spec = roster_with_cli_writer(monkeypatch)
    seen = []

    def fake_ask_role(role_spec, system, user, timeout_s=None, runner=None):
        seen.append((role_spec["model"], role_spec["effort"], system, user))
        return FILE_TEXT

    monkeypatch.setattr(er, "ask_role", fake_ask_role)
    root = wp_h_root(tmp_path)
    models, history = production(root)
    reply = models.call("dots-studio/dots-3-note-preview:free", "write", FILES)
    assert reply == {"pieces/calc.py": "x = 1\n"}
    assert seen and seen[0][:2] == (spec["model"], "high")
    record = json.loads((history / "call_01.json").read_text(encoding="utf-8"))
    assert record["via"] == "cli_exec" and record["model"] == spec["model"] and record["status"] is None and record["failed"] is False
    assert (history / "reply_01.txt").read_text(encoding="utf-8") == FILE_TEXT


def test_a_cli_exec_failure_is_a_failed_call_for_the_model(tmp_path, monkeypatch):
    roster_with_cli_writer(monkeypatch)

    def failing(role_spec, system, user, timeout_s=None, runner=None):
        raise er.ExecFailed("exit code 2", exit_code=2)

    monkeypatch.setattr(er, "ask_role", failing)
    models, history = production(wp_h_root(tmp_path))
    with pytest.raises(pm.p1b.ModelFailed):
        models.call("dots-studio/dots-3-note-preview:free", "write", FILES)
    record = json.loads((history / "call_01.json").read_text(encoding="utf-8"))
    assert record["via"] == "cli_exec" and record["failed"] is True and record["status"] is None


# ---------------------------------------------------------------- 4. the planner's runner: the claude envelope shape

def test_the_planner_cli_runner_returns_an_envelope_with_the_answer(monkeypatch):
    monkeypatch.setattr(er, "ask_role", lambda spec, system, user, timeout_s=None, runner=None: '{"job": {}}')
    code, out = pj.cli_runner(GOOD_SPEC)("plan prompt", "/tmp/x", None, 5)
    envelope = json.loads(out)
    assert code == 0 and envelope["is_error"] is False and envelope["result"] == '{"job": {}}'


def test_the_planner_cli_runner_returns_an_error_envelope_when_the_call_fails(monkeypatch):
    def failing(spec, system, user, timeout_s=None, runner=None):
        raise er.ExecFailed("exit code 1")

    monkeypatch.setattr(er, "ask_role", failing)
    code, out = pj.cli_runner(GOOD_SPEC)("plan prompt", "/tmp/x", None, 5)
    assert code == 1 and json.loads(out)["is_error"] is True


def test_the_planner_cli_runner_lets_a_timeout_through_as_uncertain(monkeypatch):
    def timed_out(spec, system, user, timeout_s=None, runner=None):
        raise er.ExecFailed("the call did not finish", timed_out=True)

    monkeypatch.setattr(er, "ask_role", timed_out)
    with pytest.raises(subprocess.TimeoutExpired):
        pj.cli_runner(GOOD_SPEC)("plan prompt", "/tmp/x", None, 5)


# ---- 2026-11-16: the CLI's session log is audited for tool use (the CLI is an agent: it is offered a shell tool, and no switch removes it)

def _session(tmp_path, sid, items):
    folder = tmp_path / "sessions" / "2026" / "11" / "16"
    folder.mkdir(parents=True)
    lines = [json.dumps({"payload": {"type": "session_meta"}})]
    lines += [json.dumps({"payload": {"type": "item_completed", "item": {"type": kind}}}) for kind in items]
    lines.append(json.dumps({"payload": {"type": "token_count"}}))
    (folder / f"rollout-2026-11-16T14-00-00-{sid}.jsonl").write_text("\n".join(lines), encoding="utf-8")


SID = "01a1e37d-1adf-76d2-ae73-401be0af4229"


def test_a_text_only_session_has_no_tool_events(tmp_path):
    _session(tmp_path, SID, ["UserMessage", "Reasoning", "AgentMessage"])
    audit = er.audit_session("workdir: x" + chr(10) + f"session id: {SID}" + chr(10) + "--------", home=tmp_path)
    assert audit["session"] == SID and audit["tool_events"] == []


def test_a_session_with_a_command_item_is_a_tool_use(tmp_path):
    _session(tmp_path, SID, ["UserMessage", "CommandExecution", "AgentMessage"])
    assert er.audit_session(f"session id: {SID}", home=tmp_path)["tool_events"] == ["item CommandExecution"]


def test_a_missing_session_id_or_log_is_refused_not_trusted(tmp_path):
    import pytest
    with pytest.raises(er.ExecFailed, match="no session id"):
        er.audit_session("no id here", home=tmp_path)
    with pytest.raises(er.ExecFailed, match="not found"):
        er.audit_session(f"session id: {SID}", home=tmp_path)


def test_ask_role_refuses_an_answer_whose_session_used_a_tool(tmp_path, monkeypatch):
    import pytest
    _session(tmp_path, SID, ["UserMessage", "CommandExecution", "AgentMessage"])
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    spec = {"model": "m", "effort": "low", "settings": {}}
    with pytest.raises(er.ExecFailed, match="tool use detected"):
        er.ask_role(spec, "s", "u", runner=lambda c, t, s: (0, "## Verdict: READY", f"session id: {SID}"))


def test_ask_role_accepts_a_clean_session_and_records_the_audit(tmp_path, monkeypatch):
    _session(tmp_path, SID, ["UserMessage", "Reasoning", "AgentMessage"])
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    spec = {"model": "m", "effort": "low", "settings": {}}
    assert er.ask_role(spec, "s", "u", runner=lambda c, t, s: (0, "## Verdict: READY", f"session id: {SID}")).startswith("## Verdict")
    assert er.last_audit()["session"] == SID and er.last_audit()["tool_events"] == []


def test_the_prompt_tells_the_model_to_use_no_tool():
    seen = {}
    spec = {"model": "m", "effort": "low", "settings": {}}
    er.ask_role(spec, "s", "u", runner=lambda c, t, s: (seen.setdefault("prompt", t) and 0, "ok", None))
    assert "Do not run any command" in seen["prompt"]


def test_the_call_record_of_a_cli_exec_call_carries_the_session_audit(tmp_path, monkeypatch):
    spec = roster_with_cli_writer(monkeypatch)

    def fake_ask_role(role_spec, system, user, timeout_s=None, runner=None):
        er._LAST.clear()
        er._LAST.update({"session": "01a1e37d-1adf-76d2-ae73-401be0af4229", "log": "x", "tool_events": []})
        return FILE_TEXT

    monkeypatch.setattr(er, "ask_role", fake_ask_role)
    models, history = production(wp_h_root(tmp_path))
    models.call("dots-studio/dots-3-note-preview:free", "write", FILES)
    record = json.loads((history / "call_01.json").read_text(encoding="utf-8"))
    assert record["exec_session"] == "01a1e37d-1adf-76d2-ae73-401be0af4229" and record["tool_events"] == 0

