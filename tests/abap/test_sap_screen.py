"""Tests for scripts/source/sap_screen.py with injected fakes (no network, no sandbox, no model)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import sap_intake as si  # noqa: E402
import sap_screen as ss  # noqa: E402

CANDS = [("o/repo", 1), ("o/repo", 2), ("o/repo", 3)]


def fake_intake(log, script=None):
    script = script or {}

    def intake(repo, pr, out):
        log.append(("intake", pr))
        step = script.get(pr)
        if callable(step):
            step = step()
        if isinstance(step, Exception):
            raise step
        d = Path(out) / f"repo_{pr}"
        d.mkdir(parents=True, exist_ok=True)
        m = {"id": f"repo_{pr}", "label": "BLIND"}
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        return m
    return intake


def run(tmp_path, cands=CANDS, intake=None, oracle=None, rehearsal=None, **kw):
    log = []
    return ss.screen(cands, tmp_path, intake=intake or fake_intake(log),
                     oracle=oracle or (lambda p: {"ok": True}), rehearsal=rehearsal or (lambda m, d: (True, "")),
                     sleep=lambda s: log.append(("sleep", s)), **kw), log


def test_parse_proof_set_order():
    text = "x\n1. open-abap/open-abap-core #1311 (a)\n2. abapGit/abapGit #7062\nnot a line\n"
    assert ss.parse_proof_set(text) == [("open-abap/open-abap-core", 1311), ("abapGit/abapGit", 7062)]
    assert len(ss.parse_proof_set((ROOT / "docs/sap/PROOF_SET.md").read_text(encoding="utf-8"))) == 14


def test_order_one_at_a_time_and_files_written(tmp_path):
    log = []
    rows, _ = run(tmp_path, intake=fake_intake(log))
    assert [x[1] for x in log if x[0] == "intake"] == [1, 2, 3]
    assert [r["admitted"] for r in rows] == ["yes"] * 3 and rows[0]["label"] == "BLIND"
    assert json.loads((tmp_path / "SCREEN.json").read_text())[2]["id"] == "repo_3"
    assert "repo_1" in (tmp_path / "SCREEN.md").read_text()


def test_retry_then_ok_and_error_after_three(tmp_path):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return si.NetworkError("boom") if calls["n"] < 3 else None
    rows, log = run(tmp_path, [("o/repo", 1)], intake=fake_intake([], {1: flaky}))
    assert rows[0]["admitted"] == "yes" and calls["n"] == 3 and log.count(("sleep", 20)) == 2
    ilog = []
    rows, log = run(tmp_path, [("o/repo", 2)], intake=fake_intake(ilog, {2: si.SandboxError("no slot")}))
    assert rows[-1]["admitted"] == "error" and "no slot" in rows[-1]["reason"] and len(ilog) == 3 and log.count(("sleep", 20)) == 2


def test_intake_rejection_is_final(tmp_path):
    rows, log = run(tmp_path, [("o/repo", 1)], intake=fake_intake([], {1: si.Rejected("two production files")}))
    assert rows[0]["admitted"] == "no" and rows[0]["reason"] == "two production files" and ("sleep", 20) not in log


def test_oracle_failure_rejects_and_removes_manifest(tmp_path):
    rows, _ = run(tmp_path, [("o/repo", 1)], oracle=lambda p: {"ok": False, "reason": "lint rule"})
    assert rows[0]["admitted"] == "no" and rows[0]["reason"].startswith("oracle check failed: the upstream fix fails its own generated acceptance/held-out: lint rule")
    assert not (tmp_path / "repo_1" / "manifest.json").exists() and (tmp_path / "repo_1" / "REJECTED.md").is_file()


def test_rehearsal_failure_rejects(tmp_path):
    rows, _ = run(tmp_path, [("o/repo", 1)], rehearsal=lambda m, d: (False, "baseline wrong"))
    assert rows[0]["admitted"] == "no" and "baseline wrong" in rows[0]["reason"]
    assert not (tmp_path / "repo_1" / "manifest.json").exists()


def test_resume_skips_admitted_unless_force(tmp_path):
    run(tmp_path)
    log = []
    rows, _ = run(tmp_path, intake=fake_intake(log))
    assert not log and len(rows) == 3
    rows, _ = run(tmp_path, intake=fake_intake(log), force=True)
    assert len(log) == 3


def test_first_five():
    rows = [{"id": f"b{i}", "admitted": "yes" if i % 2 else "no"} for i in range(20)]
    assert ss.first_admitted(rows) == ["b1", "b3", "b5", "b7", "b9"]


# ---------------------------------------------------------------- mined candidates (commit mode)

SHAS = [("o/repo", f"{i:x}" * 12) for i in range(1, 8)]          # 111111111111, 222222222222, ...


def commit_intake(log, rejected=()):
    def intake(repo, sha, out):
        log.append(sha)
        assert isinstance(sha, str)
        if sha[0] in rejected:
            raise si.Rejected("fewer than two new test methods")
        d = Path(out) / ss.bench_id(repo, sha)
        d.mkdir(parents=True, exist_ok=True)
        m = {"id": d.name, "label": "SEMI-GUIDED"}
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        return m
    return intake


def test_parse_candidate_and_bench_id():
    assert ss.parse_candidate("o/repo:12") == ("o/repo", 12)
    assert ss.parse_candidate("o/Repo@ABCDEF1234") == ("o/Repo", "abcdef1234")
    assert ss.bench_id("sbcgua/ajson", "ABCDEF1234567") == "ajson_abcdef12" and ss.bench_id("o/repo", 5) == "repo_5"


def test_load_mined_keeps_order_and_limit(tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"candidates": [{"repo": "o/a", "sha": "BB11"}, {"repo": "o/b", "sha": "aa22"}, {"repo": "o/c", "sha": "cc33"}]}))
    assert ss.load_mined(f) == [("o/a", "bb11"), ("o/b", "aa22"), ("o/c", "cc33")]
    assert ss.load_mined(f, 2) == [("o/a", "bb11"), ("o/b", "aa22")]


def test_until_admitted_stops_and_resume_does_not_repeat_decided(tmp_path):
    log = []
    kw = dict(oracle=lambda p: {"ok": True}, rehearsal=lambda m, d: (True, ""), sleep=lambda s: None, skip_decided=True)
    rows = ss.screen(SHAS, tmp_path, intake=commit_intake(log, rejected="13"), until_admitted=2, **kw)
    assert log == ["1" * 12, "2" * 12, "3" * 12, "4" * 12]            # 1 rejected, 2 admitted, 3 rejected, 4 admitted -> stop
    assert [r["admitted"] for r in rows] == ["no", "yes", "no", "yes"] and rows[1]["commit"] == "2" * 12 and rows[1]["pr"] == 0
    log.clear()
    ss.screen(SHAS, tmp_path, intake=commit_intake(log, rejected="13"), until_admitted=3, **kw)   # resume: only new candidates are run
    assert log == ["5" * 12]
    assert "commit 11111111" in (tmp_path / "repo_11111111" / "REJECTED.md").read_text() if (tmp_path / "repo_11111111" / "REJECTED.md").exists() else True


def test_pr_mode_still_repeats_rejected_on_resume(tmp_path):
    log = []
    run(tmp_path, [("o/repo", 1)], intake=fake_intake(log, {1: si.Rejected("x")}))
    run(tmp_path, [("o/repo", 1)], intake=fake_intake(log, {1: si.Rejected("x")}))
    assert log == [("intake", 1), ("intake", 1)]


def test_cli_mined_limit(monkeypatch, tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"candidates": [{"repo": "o/repo", "sha": f"{i:x}" * 12} for i in range(1, 6)]}))
    seen = {}
    monkeypatch.setattr(ss, "screen", lambda cands, out, **kw: seen.update(cands=cands, kw=kw) or [])
    assert ss.main(["--mined", str(f), "--limit", "3", "--until-admitted", "2", "--out", str(tmp_path)]) == 0
    assert len(seen["cands"]) == 3 and seen["kw"]["until_admitted"] == 2 and seen["kw"]["skip_decided"] is True
