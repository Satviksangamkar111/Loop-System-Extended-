"""Run ONE SAP/ABAP job through the Satvik Loop with the ABAP static sandbox: no Docker, no SAP, no network except the model calls.

    python scripts/sap_poc_run.py docs/sap/poc1/sap-6505.json [--dry-run]
    python scripts/sap_poc_run.py --roles          (show the roster's roles and check them; changes nothing)

Same planner/writer/reviewer/fix-loop code as `fix_loop.py --solo`; the only difference is the injected sandbox (abap_static_sandbox), which runs the
job's locked acceptance tests against the ABAP the models wrote. Models come from config/roster_sap.json (SAP_ROSTER=<file in config/> picks another).
Keys: OPENROUTER_FREE_KEY. Importing this module changes nothing (no environment, no roster, no loop imports): everything is set up inside main()."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITE_AND_REVIEW_ROLES = ("writer_a", "writer_b", "reviewer_a", "reviewer_b")
ALL_ROLES = ("writer_a", "writer_b", "reviewer_a", "reviewer_b", "repair", "planner")


def roster_path():
    return ROOT / "config" / os.environ.get("SAP_ROSTER", "roster_sap.json")


def duplicate_models(models):
    """models: {role: model id}. The loop finds a role from a model id, so two of the four writer/reviewer roles must never share one."""
    seen, dup = {}, []
    for role in WRITE_AND_REVIEW_ROLES:
        m = models[role]
        if m in seen:
            dup.append(f"{seen[m]} and {role} both use {m}")
        seen[m] = role
    return dup


def repair_warnings(models):
    """The repair step may share a model with a reviewer, but then that reviewer cannot review code the repair wrote (the loop bars it), so the panel loses a reviewer."""
    return [f"repair and {role} both use {models[role]}: that reviewer is skipped whenever the repair step ran" for role in ("reviewer_a", "reviewer_b") if models[role] == models["repair"]]


def role_rows(path=None):
    """[(role, model, via, effort)] read straight from the roster file's production slot (no loop imports, no global state)."""
    data = json.loads(Path(path or roster_path()).read_text(encoding="utf-8"))
    roles = data["profiles"]["production"]["roles"]
    return [(r, roles[r]["model"], roles[r].get("via", "openrouter"), roles[r].get("effort", "")) for r in ALL_ROLES]


def _p1():
    """pieces/p1_claims.py (claims, leases, reconcile, FileLock), imported when a function needs it, never at import time."""
    pieces = str(ROOT / "pieces")
    if pieces not in sys.path:
        sys.path.insert(0, pieces)
    import p1_claims
    return p1_claims


def claim_paths(job):
    """Repo-relative paths a real run writes or reads: the job's files, its tests, and its own _loop folder (reconcile_stale looks for that key)."""
    paths = list(job.get("files", [])) + list(job.get("tests", [])) + list(job.get("acceptance_tests", [])) + [f"_loop/{job['name']}"]
    return list(dict.fromkeys(paths))


def log_result(home, name, state):
    """One JSON line per finished job in <home>/job_results.jsonl, written under a FileLock so parallel jobs never interleave."""
    line = json.dumps({"job": name, "state": state, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pid": os.getpid()})
    p1 = _p1()
    with p1.FileLock(Path(home) / "job_results.lock"):
        with open(Path(home) / "job_results.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def exit_code(state):
    """The runner's exit code for a job's end state: 0 only when the job passed. review-open is not a pass (audit defect 19: it used to exit 0)."""
    return 0 if state == "passed" else 1


def main(argv):
    rows = role_rows()
    models = {r: m for r, m, _v, _e in rows}
    allow = os.environ.get("SAP_ALLOW_DUPLICATE_MODELS") == "1"
    dups = duplicate_models(models)
    warns = [] if allow else repair_warnings(models)       # 2026-11-18 (audit defect 19): under the test switch the "reviewer is skipped" warning is false, so it is not printed
    if "--roles" in argv:
        for row in rows:
            print("%-11s %-44s via=%-11s %s" % row)
        print("duplicate models:", dups or "none")
        for w in warns:
            print("warning:", w)
        return 2 if dups else 0
    if dups and allow:      # 2026-11-18: owner's testing exception; the run log must say so
        print("warning: duplicate models allowed for this test run: " + "; ".join(dups))
        dups = []
    if dups:
        print("refused: " + "; ".join(dups) + " (use a different model for each of writer_a, writer_b, reviewer_a, reviewer_b)")
        return 2
    for w in warns:
        print("warning:", w)
    # setup happens here, not at import: the SAP roster lives in the production slot of its own file, config/roster.json is never touched
    os.environ["SATVIK_PROFILE"] = "production"
    sys.path.insert(0, str(ROOT / "scripts" / "source"))
    import openrouter_call
    openrouter_call.ROSTER_PATH = roster_path()
    import abap_static_sandbox
    import fix_loop
    dry = "--dry-run" in argv
    path = next(a for a in argv if not a.startswith("--"))
    job = fix_loop.load_job(ROOT / path)
    sandbox = abap_static_sandbox.AbapStaticSandbox(editable=job["files"], include=job["sandbox_include"])
    if dry:
        print("dry-run: job ok, sandbox selftest:", sandbox.selftest() or "ok")
        return 0
    import loop_home
    p1 = _p1()
    try:
        home = loop_home.home(fallback=ROOT / "_loop")
    except loop_home.LoopHomeError as exc:
        print(f"refused: {exc}")
        return 2
    p1.reconcile_stale(ROOT, claims_dir=home, note="sap_poc_run")
    try:
        claim = p1.ClaimStore(home, ROOT).claim(claim_paths(job), loop_home.new_job_id(job["name"], home_dir=home))
    except p1.ClaimConflict as exc:
        print(f"claim-conflict: {exc}")
        return 4
    state = "error"
    try:
        import draft_source
        result = fix_loop.run_job(job, ROOT, scrub_keys=draft_source.nt.load_keys(), sandbox=sandbox)
        state = result["state"]
        print(state, result.get("problems") or "")
        return exit_code(state)
    finally:
        log_result(home, job["name"], state)
        claim.release()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
