"""sap_solve: the computed verdict, the Claude tool-use audit, the fixed-line pre-send guard. Fake folders and fakes only: no model, no network."""
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
sys.path.insert(0, str(REPO / "pieces"))
import exec_role as er  # noqa: E402
import p1b_routing as p1b  # noqa: E402
import sap_solve as ss  # noqa: E402
from test_exec_role import FILE_TEXT, production, roster_with_cli_writer  # noqa: E402
from test_p1b_production_run import wp_h_root  # noqa: E402

MANIFEST = {"id": "demo_1"}
GOOD_REPO = {"original_verified": True, "git_porcelain": ["?? docs/sap/bench_auto/demo_1/", " M docs/sap/run_log.jsonl"], "commit": "abc123"}
HELD = {"passed": 2, "total": 2}


def envelope(types_=("message",), result="ok"):
    return json.dumps({"result": result, "usage": {"iterations": [{"type": t} for t in types_]}})


def make_ev(tmp_path, reason="READY from: a, b (backup for c)", state="passed", raws=None, calls=None):
    ev = tmp_path / "ev"
    (ev / "history").mkdir(parents=True)
    (ev / "status.json").write_text(json.dumps({"state": state, "tests_passed": state == "passed", "reason": reason}), encoding="utf-8")
    for name, text in (raws or {}).items():
        (ev / "history" / name).write_text(text, encoding="utf-8")
    for name, rec in (calls or {}).items():
        (ev / "history" / name).write_text(json.dumps(rec), encoding="utf-8")
    return ev


def test_claude_tool_events_three_rules(tmp_path):
    ev = make_ev(tmp_path, raws={"repair_step_01_raw.json": envelope(("message", "advisor_message", "message")),
                                 "repair_step_02_raw.json": envelope(("message", "message")),
                                 "review_03_raw.json": envelope(result="I asked the Advisor"),
                                 "reply_04_raw.json": envelope(), "reply_05_raw.json": "not json"})
    got = {(e["file"], e["rule"]) for e in ss.claude_tool_events(ev / "history")}
    assert ("repair_step_01_raw.json", "iteration_type") in got and ("repair_step_01_raw.json", "multi_iteration") in got
    assert ("repair_step_02_raw.json", "multi_iteration") in got and ("repair_step_02_raw.json", "iteration_type") not in got
    assert ("review_03_raw.json", "advisor_text") in got
    assert ("reply_05_raw.json", "unreadable") in got
    assert not [e for e in got if e[0] == "reply_04_raw.json"]


def test_verdict_solved(tmp_path):
    ev = make_ev(tmp_path, raws={"repair_step_01_raw.json": envelope()},
                 calls={"call_01.json": {"via": "cli_exec", "tool_events": 0}, "call_02.json": {"via": "claude_code"}})
    (ev / "history" / "review_02_raw.json").write_text(envelope(), encoding="utf-8")
    v = ss.verdict(ev, MANIFEST, HELD, GOOD_REPO)
    assert v["solved"] is True and v["reasons"] == []


@pytest.mark.parametrize("change, key", [
    ({"state": "escalate"}, "state_passed"),
    ({"reason": "READY from: a"}, "two_valid_reviews"),
    ({"heldout": {"passed": 1, "total": 2}}, "heldout_all_pass"),
    ({"heldout": None}, "heldout_all_pass"),
    ({"repo": {**GOOD_REPO, "original_verified": False}}, "original_verified"),
    ({"repo": {**GOOD_REPO, "git_porcelain": [" M scripts/x.py"]}}, "clean_tree_and_commit"),
    ({"repo": {**GOOD_REPO, "commit": ""}}, "clean_tree_and_commit"),
    ({"codex": 2}, "no_tool_use"),
    ({"adv": True}, "no_tool_use"),
    ({"noraw": True}, "no_tool_use"),
])
def test_verdict_each_criterion_fails_alone(tmp_path, change, key):
    calls = {"call_01.json": {"via": "cli_exec", "tool_events": change.get("codex", 0)}}
    raws = {"repair_step_01_raw.json": envelope(("message", "advisor_message"))} if change.get("adv") else {}
    if change.get("noraw"):
        calls["call_02.json"] = {"via": "claude_code"}
    ev = make_ev(tmp_path, reason=change.get("reason", "READY from: a, b"), state=change.get("state", "passed"), raws=raws, calls=calls)
    v = ss.verdict(ev, MANIFEST, change.get("heldout", HELD) if "heldout" in change else HELD, change.get("repo", GOOD_REPO))
    assert v["solved"] is False and v["criteria"][key] is False and v["reasons"]


def test_arbiter_ruling_counts_as_second_review(tmp_path):
    ev = make_ev(tmp_path, reason="READY from: a; the arbiter z overruled all 2 findings of b (...)")
    assert ss.verdict(ev, MANIFEST, HELD, GOOD_REPO)["criteria"]["two_valid_reviews"] is True


def fake_intake(monkeypatch, lines):
    mod = types.ModuleType("sap_intake")
    mod.fixed_line_fingerprints = lambda bid: lines
    monkeypatch.setitem(sys.modules, "sap_intake", mod)


def test_fix_lines_leak(monkeypatch):
    fake_intake(monkeypatch, ["lv_a = lv_b + 1.", "lv_c = lv_a * 2.", "rv_out = lv_c.", "ENDIF."])
    run3 = "  lv_a = lv_b + 1.\n\n  lv_c = lv_a   * 2.\nrv_out = lv_c."
    assert ss.fix_lines_leak("x\n" + run3, "demo_1") is True
    assert ss.fix_lines_leak("lv_a = lv_b + 1.\nother\nlv_c = lv_a * 2.\nrv_out = lv_c.", "demo_1") is False   # run broken
    assert ss.fix_lines_leak("ENDIF.\nENDIF.\nENDIF.", "demo_1") is False                                      # too short to count


def test_fix_lines_leak_without_intake_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "sap_intake", None)      # import raises ImportError
    assert ss.fix_lines_leak("a\nb\nc", "demo_1") is False


def test_presend_guard_blocks_three_fix_lines(tmp_path, monkeypatch):
    roster_with_cli_writer(monkeypatch)
    sent = []
    monkeypatch.setattr(er, "ask_role", lambda *a, **k: sent.append(a) or FILE_TEXT)
    fake_intake(monkeypatch, ["lv_a = lv_b + 1.", "lv_c = lv_a * 2.", "rv_out = lv_c."])
    monkeypatch.setenv("SAP_BENCH_ID", "demo_1")
    models, _h = production(wp_h_root(tmp_path))
    with pytest.raises(p1b.Blocked, match="upstream fix"):
        models._ask("dots-studio/dots-3-note-preview:free", "system", "lv_a = lv_b + 1.\nlv_c = lv_a * 2.\nrv_out = lv_c.", kind="writer", mode="write")
    assert sent == []
    models._ask("dots-studio/dots-3-note-preview:free", "system", "lv_a = lv_b + 1.\nlv_c = lv_a * 2.", kind="writer", mode="write")
    assert len(sent) == 1


def test_solve_aborts_when_the_original_differs(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "ROOT", tmp_path)
    monkeypatch.setattr(ss, "WORK", tmp_path / "work")
    (tmp_path / "abap_work").mkdir()
    (tmp_path / "abap_work" / "c.abap").write_text("changed", encoding="utf-8")
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"id": "demo_1", "work_file": "abap_work/c.abap", "original_sha256": "0" * 64}), encoding="utf-8")
    assert ss.solve(m, series="s")["state"] == "abort-original-differs"


# ---------------------------------------------------------------- spend guard (2026-11-17): fakes only

def _bench(tmp_path, monkeypatch, units):
    import hashlib
    monkeypatch.setattr(ss, "ROOT", tmp_path)
    monkeypatch.setattr(ss, "WORK", tmp_path / "work")
    monkeypatch.setattr(ss, "EVIDENCE_ROOT", tmp_path / "ev")
    monkeypatch.setattr(ss, "_template", lambda m, d: {})
    monkeypatch.setitem(sys.modules, "plan_review", types.SimpleNamespace(review_plan=lambda *a, **k: {"status": "passed"}))
    (tmp_path / "abap_work").mkdir()
    (tmp_path / "docs" / "sap").mkdir(parents=True)
    (tmp_path / "abap_work" / "c.abap").write_text("orig", encoding="utf-8")
    bd = tmp_path / "b"
    bd.mkdir()
    (bd / "ticket.md").write_text("t", encoding="utf-8")
    m = bd / "manifest.json"
    m.write_text(json.dumps({"id": "demo_1", "work_file": "abap_work/c.abap", "original_sha256": hashlib.sha256(b"orig").hexdigest()}), encoding="utf-8")
    calls = {"plan": 0, "run": []}

    def plan_fn(tpl, ticket, plan_dir):
        calls["plan"] += 1
        (plan_dir / "units.json").write_text(json.dumps({"units": [{"name": n, "job": n + ".job.json"} for n in units]}), encoding="utf-8")
        return {"state": "planned"}

    def runner(job, env):
        name = Path(job).name.split(".")[0]
        d = tmp_path / "_loop" / name
        (d / "history").mkdir(parents=True)
        (d / "status.json").write_text(json.dumps({"state": "passed", "tests_passed": True}), encoding="utf-8")
        calls["run"].append(name)
        return 0, "ok"

    return m, plan_fn, runner, calls


def _runlog_lines(tmp_path):
    return [json.loads(l) for l in (tmp_path / "docs" / "sap" / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]


def test_failed_role_aborts_before_planning(tmp_path, monkeypatch):
    m, plan_fn, runner, calls = _bench(tmp_path, monkeypatch, ["u1"])
    bad = lambda: {"ok": False, "roles": {"planner": {"ok": False}, "writer_a": {"ok": True}}, "key": {}, "failed": ["planner"]}
    r = ss.solve(m, series="s", plan_fn=plan_fn, runner=runner, heldout_fn=lambda *a: HELD, preflight_fn=bad)
    assert r["state"] == "preflight-failed" and r["failed_roles"] == ["planner"] and not r["solved"]
    assert calls["plan"] == 0 and calls["run"] == []
    assert _runlog_lines(tmp_path)[-1]["state"] == "preflight-failed"


def test_spend_is_recorded(tmp_path, monkeypatch):
    m, plan_fn, runner, calls = _bench(tmp_path, monkeypatch, ["u1"])
    usage = iter([10.0, 10.25])
    ok = lambda: {"ok": True, "roles": {}, "key": {"usage": next(usage), "limit_remaining": 50, "credits_left": 20}}
    r = ss.solve(m, series="s", plan_fn=plan_fn, runner=runner, heldout_fn=lambda *a: HELD, preflight_fn=ok,
                 key_info_fn=lambda: {"usage": 10.25, "limit_remaining": 49.75, "credits_left": 19.75})
    assert r["spend_usd"] == 0.25 and r["credits_after"] == 19.75
    assert _runlog_lines(tmp_path)[-1]["spend_usd"] == 0.25


def test_low_remaining_stops_between_units(tmp_path, monkeypatch):
    m, plan_fn, runner, calls = _bench(tmp_path, monkeypatch, ["u1", "u2"])
    ok = lambda: {"ok": True, "roles": {}, "key": {"usage": 1.0, "limit_remaining": 50, "credits_left": 20}}
    r = ss.solve(m, series="s", plan_fn=plan_fn, runner=runner, heldout_fn=lambda *a: HELD, preflight_fn=ok,
                 key_info_fn=lambda: {"usage": 49.5, "limit_remaining": 0.5, "credits_left": 20})
    assert r["state"] == "budget-guard" and not r["solved"] and calls["run"] == ["u1"]


# ---------------------------------------------------------------- 2026-11-18 audit fixes (defects 1, 2, 3, 4, 5, 7, 10, 12, 23): fakes only

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("SAP_ROSTER", "PAR_SATVIK_HOME", "SATVIK_HOME", "SAP_ALLOW_DUPLICATE_MODELS"):
        monkeypatch.delenv(name, raising=False)


def _ok_preflight():
    return {"ok": True, "roles": {}, "key": {}, "key_checked": False}


def test_existing_evidence_folder_refuses_the_run(tmp_path, monkeypatch):      # defect 1
    m, plan_fn, runner, calls = _bench(tmp_path, monkeypatch, ["u1"])
    (tmp_path / "ev" / "s-u1").mkdir(parents=True)                             # an earlier run's evidence under the same series name
    r = ss.solve(m, series="s", plan_fn=plan_fn, runner=runner, heldout_fn=lambda *a: HELD, preflight_fn=_ok_preflight)
    assert r["state"] == "evidence-exists" and r["units"] == ["u1"] and not r["solved"]
    assert calls["run"] == [] and not (tmp_path / "_loop").exists() and not list((tmp_path / "ev" / "s-u1").iterdir())


def test_job_without_loop_folder_gives_no_status(tmp_path, monkeypatch):      # defect 1
    m, plan_fn, _runner, _calls = _bench(tmp_path, monkeypatch, ["u1"])
    r = ss.solve(m, series="s", plan_fn=plan_fn, runner=lambda job, env: (0, "wrote nothing"), heldout_fn=lambda *a: HELD, preflight_fn=_ok_preflight)
    assert r["verdicts"][0]["state"] == "no-status" and not r["solved"]
    assert not (tmp_path / "ev" / "s-u1").exists()


@pytest.mark.parametrize("roster_env, expected", [(None, "roster_sap.json"), ("roster_sap_claude.json", "roster_sap_claude.json")])
def test_job_gets_the_same_roster_as_the_planner(tmp_path, monkeypatch, roster_env, expected):      # defect 2
    if roster_env is not None:
        monkeypatch.setenv("SAP_ROSTER", roster_env)
    m, plan_fn, runner, _calls = _bench(tmp_path, monkeypatch, ["u1"])
    seen = []
    r = ss.solve(m, series="s", plan_fn=plan_fn, runner=lambda job, env: seen.append(env) or runner(job, env), heldout_fn=lambda *a: HELD,
                 preflight_fn=_ok_preflight)
    assert seen[0]["SAP_ROSTER"] == expected and r["roster"] == expected


def test_claude_tool_use_beyond_the_roster_alias_or_iterations_fails(tmp_path):      # defect 10
    two_iterations = envelope(("message", "message"))
    ok_env = json.dumps({"result": "ok", "usage": {"iterations": [{"type": "message"}]}, "modelUsage": {"claude-haiku-5-5": {}}})
    leak = json.dumps({"result": "ok", "usage": {"iterations": [{"type": "message"}]}, "modelUsage": {"claude-haiku-5-5": {}, "claude-opus-5-5": {}}})
    ev = make_ev(tmp_path, raws={"reply_01_raw.json": ok_env, "review_02_raw.json": leak, "repair_step_03_raw.json": two_iterations})
    rules = {(e["file"], e["rule"]) for e in ss.claude_tool_events(ev / "history")}
    assert ("review_02_raw.json", "model_family") in rules and ("repair_step_03_raw.json", "multi_iteration") in rules
    assert not [e for e in rules if e[0] == "reply_01_raw.json"]
    v = ss.verdict(ev, MANIFEST, HELD, GOOD_REPO)
    assert v["criteria"]["no_tool_use"] is False and v["solved"] is False


def test_original_verified_comes_from_the_hash_check(tmp_path, monkeypatch):      # defect 21
    m, plan_fn, runner, _calls = _bench(tmp_path, monkeypatch, ["u1"])
    work = tmp_path / "abap_work" / "c.abap"
    work.write_text("changed after the manifest was made", encoding="utf-8")       # not the manifest's original_sha256
    (tmp_path / "work" / "results").mkdir(parents=True)
    manifest = json.loads(m.read_text(encoding="utf-8"))
    out = ss._solve_run(m, manifest, "s", "s-demo_1", work, m.parent, tmp_path / "work" / "results", runner, plan_fn, lambda *a: HELD, None)
    assert out["verdicts"][0]["criteria"]["original_verified"] is False and out["verdicts"][0]["solved"] is False


def test_satvik_home_comes_from_par_then_satvik_then_beside_the_repo(tmp_path, monkeypatch):      # defect 4
    m, plan_fn, _runner, _calls = _bench(tmp_path, monkeypatch, ["u1"])
    seen = []
    monkeypatch.setenv("PAR_SATVIK_HOME", "")                 # an empty PAR_SATVIK_HOME is not set
    monkeypatch.setenv("SATVIK_HOME", str(tmp_path / "shared"))
    ss.solve(m, series="s", plan_fn=plan_fn, runner=lambda job, env: seen.append(env) or (0, "ok"), heldout_fn=lambda *a: HELD, preflight_fn=_ok_preflight)
    assert seen[0]["SATVIK_HOME"] == str(tmp_path / "shared")
    monkeypatch.delenv("SATVIK_HOME")
    ss.solve(m, series="t", plan_fn=plan_fn, runner=lambda job, env: seen.append(env) or (0, "ok"), heldout_fn=lambda *a: HELD, preflight_fn=_ok_preflight)
    assert seen[1]["SATVIK_HOME"] == str(tmp_path.parent / "satvik_home")


def test_leak_guard_is_recorded_as_active_or_inactive(tmp_path, monkeypatch):      # defect 12
    import hashlib
    monkeypatch.setattr(ss, "ROOT", tmp_path)
    monkeypatch.setattr(ss, "WORK", tmp_path / "work")
    (tmp_path / "abap_work").mkdir()
    (tmp_path / "abap_work" / "c.abap").write_text("changed", encoding="utf-8")
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"id": "demo_1", "work_file": "abap_work/c.abap", "original_sha256": hashlib.sha256(b"orig").hexdigest()}), encoding="utf-8")
    fake_intake(monkeypatch, ["lv_a = lv_b + 1."])
    assert ss.solve(m, series="s")["leak_guard"] == "active"
    monkeypatch.setitem(sys.modules, "sap_intake", None)      # the module is missing: the guard is inactive, and the run still goes ahead
    r = ss.solve(m, series="s")
    assert r["leak_guard"] == "inactive" and r["state"] == "abort-original-differs" and r["roster"] == "roster_sap.json"


def test_run_claude_only_uses_the_normal_preflight(monkeypatch):      # defect 23
    import runpy
    seen = {}

    def fake_solve(manifest, series, **kwargs):
        seen.update(manifest=manifest, series=series, kwargs=kwargs)
        return {"state": "fake"}
    monkeypatch.setattr(ss, "solve", fake_solve)
    monkeypatch.setattr(sys, "argv", ["run_claude_only.py", "s1", "m.json"])
    runpy.run_path(str(REPO / "scripts" / "run_claude_only.py"), run_name="__main__")
    assert seen == {"manifest": "m.json", "series": "s1", "kwargs": {}}
