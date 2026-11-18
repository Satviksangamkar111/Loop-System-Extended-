"""SAP runner under the shared loop home: file claims (ClaimConflict -> exit 4, released in finally), one result line per job in
job_results.jsonl, and key rotation shared through one ledger. Every test points SATVIK_HOME at a temp folder and the runner's ROOT at a temp repo;
no model call, no network, no real satvik_home, no real _loop."""
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
JOB = {"name": "bench-C", "files": ["abap_work/x.abap"], "tests": ["tests/acceptance/t.py"], "acceptance_tests": ["tests/acceptance/t.py"],
       "sandbox_include": ["scripts"]}


def _runner():
    spec = importlib.util.spec_from_file_location("sap_poc_run_under_test", REPO / "scripts" / "sap_poc_run.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", sys.path[:])            # the runner inserts folders into sys.path; undo that
    monkeypatch.setenv("SATVIK_PROFILE", "test")             # recorded even when unset, so teardown removes the value main() sets to production
    for p in (REPO / "scripts" / "source", REPO / "pieces"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import loop_home
    import p1_claims
    home, repo = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    (repo / "config").mkdir(parents=True)
    monkeypatch.setenv("SATVIK_HOME", str(home))
    return SimpleNamespace(home=home, repo=repo, p1=p1_claims, lh=loop_home, runner=_runner(), monkeypatch=monkeypatch)


def _main_world(w, monkeypatch, run_job):
    """Patch everything main() reads from the outside: the temp repo, the roster, the job, the sandbox, the keys and the run itself."""
    import abap_static_sandbox
    import fix_loop
    import openrouter_call
    r = w.runner
    monkeypatch.setattr(r, "ROOT", w.repo)
    monkeypatch.setattr(r, "role_rows", lambda path=None: [("writer_a", "m1", "openrouter", ""), ("writer_b", "m2", "openrouter", ""),
                                                          ("reviewer_a", "m3", "openrouter", ""), ("reviewer_b", "m4", "openrouter", ""),
                                                          ("repair", "m5", "openrouter", ""), ("planner", "m6", "openrouter", "")])
    monkeypatch.setattr(openrouter_call, "ROSTER_PATH", openrouter_call.ROSTER_PATH)   # restored at teardown; main sets it
    monkeypatch.setattr(fix_loop, "load_job", lambda path: dict(JOB))
    monkeypatch.setattr(fix_loop, "run_job", run_job)
    monkeypatch.setattr(abap_static_sandbox, "AbapStaticSandbox", lambda **kw: object())
    monkeypatch.setitem(sys.modules, "draft_source", SimpleNamespace(nt=SimpleNamespace(load_keys=lambda: [])))


def _claims(home):
    return json.loads((Path(home) / "claims.json").read_text(encoding="utf-8"))["claims"]


def test_a_second_claim_on_the_same_file_conflicts(world):
    store = world.p1.ClaimStore(world.home, world.repo)
    first = store.claim(["abap_work/x.abap"], world.lh.new_job_id("a", home_dir=world.home))
    with pytest.raises(world.p1.ClaimConflict, match="abap_work/x.abap"):
        store.claim(["abap_work/x.abap"], world.lh.new_job_id("b", home_dir=world.home))
    first.release()


def test_main_returns_4_and_names_the_file_on_a_claim_conflict(world, capsys):
    store = world.p1.ClaimStore(world.home, world.repo)
    other = store.claim(["abap_work/x.abap"], "other-job")                 # a live job holds the file
    ran = []
    _main_world(world, world.monkeypatch, lambda *a, **k: ran.append(1) or {"state": "passed"})
    code = world.runner.main(["docs/sap/bench/C/job.json"])
    other.release()
    assert code == 4 and ran == []
    out = capsys.readouterr().out
    assert out.startswith("claim-conflict") and "abap_work/x.abap" in out
    assert not (world.home / "job_results.jsonl").exists()                # a job that never ran logs nothing


def test_main_holds_the_claims_while_it_runs_and_releases_them_after(world):
    seen = set()

    def run(job, root, scrub_keys=None, sandbox=None):
        seen.update(k.casefold() for k in _claims(world.home))
        return {"state": "passed", "problems": []}

    _main_world(world, world.monkeypatch, run)
    assert world.runner.main(["docs/sap/bench/C/job.json"]) == 0
    assert {"abap_work/x.abap", "tests/acceptance/t.py", "_loop/bench-c"} <= seen      # the job's own paths were claimed during the run
    assert _claims(world.home) == {}                                                 # claims are empty after release


def test_a_failed_run_still_releases_claims_and_logs_error(world):
    def boom(job, root, scrub_keys=None, sandbox=None):
        raise RuntimeError("crash inside the loop")

    _main_world(world, world.monkeypatch, boom)
    with pytest.raises(RuntimeError):
        world.runner.main(["docs/sap/bench/C/job.json"])
    assert _claims(world.home) == {}
    assert json.loads((world.home / "job_results.jsonl").read_text(encoding="utf-8").splitlines()[0])["state"] == "error"


def test_the_shared_result_log_gets_one_well_formed_line_per_job(world):
    world.runner.log_result(world.home, "bench-C", "passed")
    world.runner.log_result(world.home, "bench-D", "stopped")
    lines = (world.home / "job_results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert [r["job"] for r in rows] == ["bench-C", "bench-D"] and [r["state"] for r in rows] == ["passed", "stopped"]
    for r in rows:
        assert set(r) == {"job", "state", "utc", "pid"} and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", r["utc"]) and r["pid"] > 0


def test_two_key_pools_on_one_ledger_never_hand_out_the_same_key_in_one_window(world):
    def would_wait(seconds):
        raise AssertionError("a wait: every key is used for this window")

    keys = ["key-one", "key-two", "key-three"]
    pool_a = world.p1.LedgerKeyPool(keys, world.home, offset=0, per_key=1, sleep=would_wait)
    pool_b = world.p1.LedgerKeyPool(keys, world.home, offset=1, per_key=1, sleep=would_wait)
    got = [pool_a.acquire()[1], pool_b.acquire()[1], pool_a.acquire()[1]]
    assert sorted(got) == sorted(keys)
    with pytest.raises(AssertionError, match="a wait"):
        pool_b.acquire()


def test_the_nvidia_pool_shares_the_same_ledger_across_processes(world):
    import nvidia_direct as nd

    def no_wait(seconds):
        raise AssertionError("a wait")

    world.monkeypatch.setattr(nd.time, "sleep", no_wait)
    keys = ["nvapi-one", "nvapi-two"]
    first, second = nd._pool(keys), nd._pool(keys)
    assert first is not None and second is not None
    a, b = first.acquire()[1], second.acquire()[1]
    assert a != b
    with pytest.raises(AssertionError, match="a wait"):
        first.acquire()
