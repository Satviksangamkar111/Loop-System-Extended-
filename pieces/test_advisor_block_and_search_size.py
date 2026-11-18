"""2026-11-17: the Claude CLI command blocks the advisor tool; a SEARCH text of a whole method is refused so the writer is asked for short edits."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "source"))
import claude_code  # noqa: E402
import p1b_production as pm  # noqa: E402


def test_the_claude_command_blocks_the_advisor_tool():
    src = Path(claude_code.__file__).read_text(encoding="utf-8")
    assert '"--disallowed-tools", "advisor"' in src and '"--safe-mode"' in src and '"--tools", ""' in src


def test_a_search_text_over_the_line_limit_is_refused_and_a_short_one_is_applied():
    body = "\n".join(f"line {i}" for i in range(60))
    big = f"FILE: a.abap\n<<<<<<< SEARCH\n{body}\n=======\nx\n>>>>>>> REPLACE"
    changed, why = pm.apply_edits(big, {"a.abap": body + "\n"}, pm.MAX_SEARCH_LINES)
    assert changed == {} and any("over" in r and "lines" in r for r in why)
    assert pm.apply_edits(big, {"a.abap": body + "\n"})[0] != {}      # a fresh write has no cap
    small = "FILE: a.abap\n<<<<<<< SEARCH\nline 3\n=======\nthree\n>>>>>>> REPLACE"
    changed, why = pm.apply_edits(small, {"a.abap": body + "\n"})
    assert why == [] and "three" in changed["a.abap"]
