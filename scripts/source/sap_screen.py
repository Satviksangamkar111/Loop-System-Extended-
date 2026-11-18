"""Free screening of proof-set candidates BEFORE any paid run (no model call anywhere).

    python scripts/source/sap_screen.py [owner/repo:PR ...] [--only N] [--force] [--out docs/sap/bench_auto]

For each candidate, one at a time: intake (public GitHub + the sandbox) -> oracle check (the upstream fix must pass the
generated acceptance module and the held-out cases) -> free calibration rehearsal (SAP_STOP_AFTER_CALIBRATION=1: baseline and
negative controls only). A candidate that fails a step is rejected (REJECTED.md, no manifest.json). Network/sandbox/timeout
trouble is retried, then recorded as `error`, never as rejected. SCREEN.md / SCREEN.json are rewritten after EACH candidate.
Default list: the numbered `owner/repo #N` lines of docs/sap/PROOF_SET.md, in order.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

BASE = Path(os.environ.get("SAP_LOOP_BASE") or ROOT.parent)     # holds bench_private/, bench/, abap_tools/, satvik_home/, work/
OUT = ROOT / "docs" / "sap" / "bench_auto"
PROOF_SET = ROOT / "docs" / "sap" / "PROOF_SET.md"
MINED = OUT / "CANDIDATES_MINED.json"
RESIDUE = BASE / "work" / "residue_2026-11-16"
PROJECTS = BASE / "work" / "intake_try2" / "projects"
SATVIK_HOME = str(BASE / "satvik_home")
RETRIES, WAIT_S = 2, 20


def parse_proof_set(text):
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r"^\s*\d+\.\s+([\w.-]+/[\w.-]+)\s+#(\d+)", text, re.M)]


def bench_id(repo, pr):
    """pr is a PR number (int) or a commit sha (str): commit candidates are `owner/repo@sha`."""
    import sap_intake
    return sap_intake.make_commit_id(repo, pr) if isinstance(pr, str) else sap_intake.make_id(repo, pr)


def parse_candidate(text):
    """`owner/repo:PR` -> (repo, int); `owner/repo@sha` -> (repo, sha)."""
    if "@" in text:
        repo, sha = text.split("@", 1)
        return repo, sha.lower()
    repo, pr = text.rsplit(":", 1)
    return repo, int(pr)


def load_mined(path=None, limit=None):
    """Candidates of CANDIDATES_MINED.json, in file order (newest first)."""
    data = json.loads(Path(path or MINED).read_text(encoding="utf-8"))
    cands = [(c["repo"], c["sha"].lower()) for c in data["candidates"]]
    return cands[:limit] if limit else cands


# ---------------------------------------------------------------- default steps (real)

def default_intake(repo, pr, out):
    import sap_intake
    if isinstance(pr, str):
        return sap_intake.intake_commit(repo, pr, out, projects_root=PROJECTS)
    return sap_intake.intake(repo, pr, out, projects_root=PROJECTS)


def default_oracle(manifest_path):
    import sap_oracle_check
    return sap_oracle_check.check(manifest_path)


def default_rehearsal(manifest, bench_dir, timeout_s=1800):
    """Run the loop up to its free calibration. Returns (ok, problems text). The work file is always restored."""
    import sap_solve
    bid = manifest["id"]
    work = ROOT / manifest["work_file"]
    original = work.read_bytes()
    ctl = ROOT / "tests" / "controls_auto"
    pointer, newm = ctl / "ACTIVE_MANIFEST.txt", ctl / "ACTIVE_NEW_METHODS.txt"
    job_file = Path(bench_dir) / "rehearsal.job.json"
    mpath = Path(bench_dir) / "manifest.json"
    try:
        job_file.write_text(json.dumps(sap_solve._template(manifest, Path(bench_dir)), indent=2, sort_keys=True), encoding="utf-8")
        ctl.mkdir(parents=True, exist_ok=True)
        pointer.write_text(mpath.resolve().relative_to(ROOT).as_posix() + "\n", encoding="utf-8")
        newm.write_text("\n", encoding="utf-8")
        env = {**os.environ, "SATVIK_HOME": SATVIK_HOME, "PYTHONIOENCODING": "utf-8",
               "SAP_DIRECT_ROUTE": "nvidia_direct", "SAP_STOP_AFTER_CALIBRATION": "1",
               "SAP_BENCH_MANIFEST": str(mpath.resolve()), "SAP_BENCH_ID": bid}
        env.pop("SAP_ROSTER", None)
        env.pop("OPENROUTER_FREE_KEY", None)        # no key is needed and none is passed
        proc = subprocess.run([sys.executable, "scripts/sap_poc_run.py", job_file.resolve().relative_to(ROOT).as_posix()], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
        status = {}
        try:
            status = json.loads((ROOT / "_loop" / bid / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if status.get("state") == "calibration-passed":
            return True, ""
        probs = status.get("problems") or [(proc.stdout + proc.stderr)[-600:]]
        return False, f"state {status.get('state', 'no-status')}: " + "; ".join(str(p) for p in probs)[:900]
    finally:
        work.write_bytes(original)
        pointer.unlink(missing_ok=True)
        newm.unlink(missing_ok=True)
        stale = ROOT / "_loop" / bid
        if stale.exists():
            RESIDUE.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stale), str(RESIDUE / f"_loop_{bid}_screen_{int(time.time())}"))


# ---------------------------------------------------------------- screening

def _reject_file(bench_dir, repo, pr, reason):
    bench_dir.mkdir(parents=True, exist_ok=True)
    (bench_dir / "manifest.json").unlink(missing_ok=True)
    what = f"commit {pr[:8]}" if isinstance(pr, str) else f"PR {pr}"
    (bench_dir / "REJECTED.md").write_text(f"# Rejected: {repo} {what}\n\n{reason}\n", encoding="utf-8")


def screen_one(repo, pr, out, *, intake=default_intake, oracle=default_oracle, rehearsal=default_rehearsal, sleep=time.sleep):
    """-> row {id, repo, pr, label, admitted yes|no|error, reason, seconds}."""
    import sap_intake
    t0, bid = time.time(), bench_id(repo, pr)
    bench_dir = Path(out) / bid
    row = {"id": bid, "repo": repo, "pr": 0 if isinstance(pr, str) else pr, "label": "", "admitted": "no", "reason": ""}
    if isinstance(pr, str):
        row["commit"] = pr

    def done(admitted, reason):
        row.update(admitted=admitted, reason=reason, seconds=round(time.time() - t0, 1))
        return row

    manifest = None
    for attempt in range(RETRIES + 1):
        try:
            manifest = intake(repo, pr, out)
            break
        except sap_intake.Rejected as exc:
            return done("no", exc.reason)
        except (sap_intake.NetworkError, sap_intake.SandboxError, TimeoutError, subprocess.TimeoutExpired) as exc:
            if attempt == RETRIES:
                return done("error", f"{type(exc).__name__}: {exc}")
            sleep(WAIT_S)
    row["label"] = manifest.get("label", "")
    mpath = bench_dir / "manifest.json"
    try:
        res = oracle(mpath)
    except Exception as exc:                                  # a runner error is a failed check, never a pass
        res = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not res.get("ok"):
        why = res.get("reason") or f"acceptance exit {res.get('acceptance_exit')}, held-out {res.get('heldout')}; {str(res.get('acceptance_tail', ''))[-300:]}"
        reason = f"oracle check failed: the upstream fix fails its own generated acceptance/held-out: {why}"
        _reject_file(bench_dir, repo, pr, reason)
        return done("no", reason)
    try:
        ok, problems = rehearsal(manifest, bench_dir)
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        return done("error", f"rehearsal timed out: {exc}")
    if not ok:
        reason = f"calibration rehearsal failed: {problems}"
        _reject_file(bench_dir, repo, pr, reason)
        return done("no", reason)
    return done("yes", "intake, oracle check and calibration rehearsal all passed")


def write_screen(out, rows):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "SCREEN.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    lines = ["# Screening of proof-set candidates (no model call)", "", "| id | label | admitted | seconds | reason |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r.get('label') or '-'} | {r['admitted']} | {r.get('seconds', '')} | {str(r['reason']).replace('|', '/').replace(chr(10), ' ')[:300]} |")
    (out / "SCREEN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def screen(candidates, out=OUT, *, force=False, intake=default_intake, oracle=default_oracle, rehearsal=default_rehearsal, sleep=time.sleep,
           until_admitted=None, skip_decided=False):
    """until_admitted: stop once that many of these candidates are admitted (resumed ones count). skip_decided: a resumed run
    does not repeat candidates already rejected (rows with admitted `error` are always repeated)."""
    out = Path(out)
    try:
        rows = json.loads((out / "SCREEN.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    by_id = {r["id"]: r for r in rows}
    order = [r["id"] for r in rows]
    got = set()
    for repo, pr in candidates:                               # strictly one at a time
        if until_admitted is not None and len(got) >= until_admitted:
            break
        bid = bench_id(repo, pr)
        prev = by_id.get(bid, {}).get("admitted")
        if not force and (out / bid / "manifest.json").is_file() and prev == "yes":
            got.add(bid)
            continue
        if not force and skip_decided and prev == "no":
            continue
        by_id[bid] = screen_one(repo, pr, out, intake=intake, oracle=oracle, rehearsal=rehearsal, sleep=sleep)
        if bid not in order:
            order.append(bid)
        if by_id[bid]["admitted"] == "yes":
            got.add(bid)
        write_screen(out, [by_id[i] for i in order])
    return [by_id[i] for i in order]


def first_admitted(rows, n=5):
    return [r["id"] for r in rows if r["admitted"] == "yes"][:n]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Free screening of proof-set candidates.")
    ap.add_argument("candidates", nargs="*", help="owner/repo:PR or owner/repo@sha (default: PROOF_SET.md in order)")
    ap.add_argument("--mined", nargs="?", const=str(MINED), default=None, metavar="JSON", help="read candidates from CANDIDATES_MINED.json, in its order")
    ap.add_argument("--limit", type=int, help="with --mined: only the first N candidates")
    ap.add_argument("--until-admitted", type=int, metavar="K", help="stop once K candidates are admitted")
    ap.add_argument("--only", type=int, help="screen only the candidate(s) with this PR number")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    if a.mined:
        cands = load_mined(a.mined, a.limit)
    elif a.candidates:
        cands = [parse_candidate(c) for c in a.candidates]
    else:
        cands = parse_proof_set(PROOF_SET.read_text(encoding="utf-8"))
    if a.only is not None:
        cands = [c for c in cands if c[1] == a.only]
    if not cands:
        print("no candidates selected", file=sys.stderr)
        return 2
    rows = screen(cands, a.out, force=a.force, until_admitted=a.until_admitted, skip_decided=bool(a.mined))
    wanted = {bench_id(*c) for c in cands}
    for r in rows:
        if r["id"] in wanted:
            print(f"{r['id']}: {r['admitted']} ({r.get('label') or '-'}, {r.get('seconds')} s) {str(r['reason'])[:200]}")
    if a.mined:
        print("admitted in mined order:", ", ".join(r["id"] for r in rows if r["id"] in wanted and r["admitted"] == "yes") or "none")
    else:
        print("first five admitted:", ", ".join(first_admitted(rows)) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
