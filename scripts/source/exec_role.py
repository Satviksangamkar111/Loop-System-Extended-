"""Coding-agent CLI calls (2026-11-16): the runner for every roster role whose "via" is "cli_exec". The role's model and effort are read from
config/roster.json; the command and its fixed arguments live in config/exec_role.json (the names the CLI takes), not here.

Every call is one non-interactive run of the CLI in a read-only sandbox, from an empty temporary folder, with the prompt on stdin. The answer is
the text of the output file the CLI writes (its -o argument). stdout and stderr go to a temporary file, never a pipe. A non-zero exit, an empty
answer or a timeout is a failed call (ExecFailed). Under pytest no process starts unless the caller injects a runner.

Importing this module calls no model."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config" / "exec_role.json"
EFFORTS = ("low", "medium", "high")
TIMEOUT_S = 900                     # a role with no timeout_s in its roster settings gets this
ALLOWED_ITEMS = {"UserMessage", "Reasoning", "AgentMessage"}    # the only items a text-only answer leaves in the CLI's session log; anything else is a tool use
TEXT_ONLY_NOTE = ("You are a text-only reviewer: answer from the text given in this message alone. Do not run any command, do not open or list any file, "
                  "do not use any tool.")
_LAST = {}                          # the audit of the latest real call: session id, log path, tool events


class ExecFailed(Exception):
    """The call produced no usable answer: refused before it started, a non-zero exit, an empty answer or a timeout."""

    def __init__(self, message, exit_code=None, timed_out=False):
        super().__init__(message)
        self.exit_code = exit_code
        self.timed_out = timed_out


def check_role(where, spec):
    """The roster rules for a role with "via": "cli_exec": a non-empty model and an effort low, medium or high, not paid, with no OpenRouter
    provider and no prices. Returns the problem as text, or None."""
    model = spec.get("model")
    if not isinstance(model, str) or not model.strip():
        return f"{where}: a cli_exec role needs a non-empty model string"
    if spec.get("effort") not in EFFORTS:
        return f"{where}: a cli_exec role needs an effort, one of {', '.join(EFFORTS)}"
    if spec.get("paid") is not False:
        return f"{where}: a cli_exec role is not paid (paid must be false)"
    if spec.get("provider") is not None or spec.get("pricing") is not None:
        return f"{where}: a cli_exec role has no OpenRouter provider and no prices (provider and pricing are null)"
    return None


def real_call_refused():
    """Test guard: under pytest, or with SATVIK_NO_OPUS=1, no real coding-agent process starts (the tests inject a runner)."""
    return "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("SATVIK_NO_OPUS") == "1"


def build_command(model, effort, out_path, config=None):
    """The command list from config/exec_role.json, with {model}, {effort} and {out} filled in."""
    config = config or json.loads(CONFIG.read_text(encoding="utf-8"))
    args = [str(arg).format(model=model, effort=effort, out=out_path) for arg in config["args"]]
    return [config["command"]] + args


def audit_session(log_text, home=None):
    """Checks the CLI's own session log of one call for tool use. The call printed `session id: <id>`; the log of that session is
    <home>/sessions/**/rollout-*-<id>.jsonl. A text-only answer holds only the items in ALLOWED_ITEMS; any other item, or any event whose type
    names a call or a command, is a tool use. Returns {"session": id, "log": path, "tool_events": [..]}. Raises ExecFailed when the session id or
    its log cannot be found (the call cannot be verified, so it is not used)."""
    found = re.search(r"session id:\s*([0-9a-fA-F-]{36})", log_text or "")
    if not found:
        raise ExecFailed("the call printed no session id: tool use cannot be ruled out, so the answer is not used")
    sid = found.group(1)
    base = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    paths = sorted(base.rglob(f"rollout-*-{sid}.jsonl")) if base.is_dir() else []
    if not paths:
        raise ExecFailed(f"the session log of {sid} was not found under {base}: tool use cannot be ruled out, so the answer is not used")
    events = []
    for line in paths[0].read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line).get("payload") or {}
        except ValueError:
            continue
        kind = payload.get("type") or ""
        if kind == "item_completed":
            item = payload.get("item") or {}
            item_kind = item.get("type") if isinstance(item, dict) else str(item)
            if item_kind not in ALLOWED_ITEMS:
                events.append(f"item {item_kind}")
        elif re.search(r"(call|exec|command|shell|patch)", kind) and kind not in ("token_count", "token_usage_record"):
            events.append(kind)
    return {"session": sid, "log": str(paths[0]), "tool_events": events}


def last_audit():
    """The audit of the latest real call of this process (empty before the first one): the production runner records it in the call record."""
    return dict(_LAST)


def run(cmd, input_text, timeout_s, out_path):
    """The real call: runs cmd from an empty temporary folder with the prompt on stdin, and returns (exit code, text of out_path, the CLI's own
    stdout and stderr). A timeout raises subprocess.TimeoutExpired. The executable is found as name.cmd or name on the PATH (Windows)."""
    exe = shutil.which(cmd[0] + ".cmd") or shutil.which(cmd[0]) or cmd[0]
    with tempfile.TemporaryDirectory(prefix="exec_cwd_") as empty:
        with tempfile.TemporaryFile() as sink:
            proc = subprocess.run([exe] + list(cmd[1:]), input=input_text.encode("utf-8"), stdout=sink, stderr=sink, cwd=empty,
                                  timeout=timeout_s)
            sink.seek(0)
            log = sink.read().decode("utf-8", "replace")
    text = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    return proc.returncode, text, log


def ask_role(role_spec, system, user, timeout_s=None, runner=None):
    """The answer text of one isolated call for a cli_exec role: the role's model and effort, `system` then `user` joined into one prompt
    (system is skipped when empty), the role's roster timeout_s (TIMEOUT_S when it has none). `runner(cmd, input_text, timeout_s)` replaces
    run in tests and returns (exit code, output file text). Raises ExecFailed; nothing else is tried."""
    model, effort = role_spec.get("model"), role_spec.get("effort")
    if not isinstance(model, str) or not model.strip() or effort not in EFFORTS:
        raise ExecFailed(f"model {model!r} at effort {effort!r} is not a cli_exec role: no process was started")
    if runner is None and real_call_refused():
        raise ExecFailed("a real coding-agent command is refused under pytest or SATVIK_NO_OPUS=1: no process was started")
    if timeout_s is None:
        timeout_s = (role_spec.get("settings") or {}).get("timeout_s") or TIMEOUT_S
    prompt = f"{TEXT_ONLY_NOTE}\n\n{system}\n\n{user}" if system else f"{TEXT_ONLY_NOTE}\n\n{user}"
    with tempfile.TemporaryDirectory(prefix="exec_out_") as out_dir:
        out_path = Path(out_dir) / "answer.txt"
        cmd = build_command(model, effort, out_path)
        call = runner or (lambda c, text, t: run(c, text, t, out_path))
        try:
            out = call(cmd, prompt, timeout_s)
            code, text, log = out[0], out[1], (out[2] if len(out) > 2 else None)
        except subprocess.TimeoutExpired as exc:
            raise ExecFailed(f"the call did not finish in {timeout_s} s", timed_out=True) from exc
        except OSError as exc:
            raise ExecFailed(f"the command could not start: {exc}") from exc
    if code != 0:
        raise ExecFailed(f"exit code {code}", exit_code=code)
    if not isinstance(text, str) or not text.strip():
        raise ExecFailed("the answer file is empty or missing", exit_code=code)
    if log is not None:                                  # a real call (or a runner that returns its log): the CLI's session log must show no tool use
        audit = audit_session(log)
        _LAST.clear()
        _LAST.update(audit)
        if audit["tool_events"]:
            raise ExecFailed(f"tool use detected in session {audit['session']}: {', '.join(audit['tool_events'][:5])}; the answer is not used")
    return text
