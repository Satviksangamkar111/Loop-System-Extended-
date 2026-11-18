"""A stand-in for the `claude` executable, used ONLY by the tests (P1c, 2026-11-02; every Claude Code role, 2026-11-03). It never calls a model.

It appends one line to FAKE_CLAUDE_LOG for each run (the arguments, the working folder and its entries, whether ANTHROPIC_API_KEY was in the
environment, the names of every ANTHROPIC_* or OPENROUTER* variable it saw, and stdin), then prints the file named by FAKE_CLAUDE_OUTPUT, or
sleeps when FAKE_CLAUDE_OUTPUT is 'sleep'."""
import json
import os
import sys
import time

log = os.environ["FAKE_CLAUDE_LOG"]
_a = sys.argv[1:]
_sp = open(_a[_a.index("--system-prompt-file") + 1], encoding="utf-8").read() if "--system-prompt-file" in _a else None   # the prompt travels as a file (claude.CMD cuts an argument at a newline)
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"args": sys.argv[1:], "system_prompt": _sp, "cwd": os.getcwd(), "cwd_entries": sorted(os.listdir(os.getcwd())),
                         "api_key_in_env": "ANTHROPIC_API_KEY" in os.environ,
                         "guarded_env": sorted(k for k in os.environ if k.upper().startswith(("ANTHROPIC_", "OPENROUTER"))),
                         "stdin": sys.stdin.read()}) + "\n")
mode = os.environ["FAKE_CLAUDE_OUTPUT"]
if mode == "sleep":
    time.sleep(60)
else:
    with open(mode, encoding="utf-8") as fh:
        sys.stdout.write(fh.read())
