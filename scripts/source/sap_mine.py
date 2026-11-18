"""Mine fix-with-tests candidates from the LOCAL git history of public ABAP repos (no GitHub API for discovery).

    python scripts/source/sap_mine.py [--root DIR] [--out docs/sap/bench_auto]
                                       [--months 24] [--repos owner/name ...] [--no-fetch]

A candidate is a non-merge commit within the window whose diff changes exactly two .abap files: one production
`<x>.clas.abap` (modified) and its sibling `<x>.clas.testclasses.abap`, with >= 2 ADDED test methods
(`METHODS <n> FOR TESTING`), no @KERNEL in the class, and a message that looks like a fix.
Output: CANDIDATES_MINED.json / .md, ordered NEWEST FIRST (a fixed order; it is the proof-set rule, never re-ranked).
Clones are `git clone --filter=blob:none --no-checkout` (history only, blobs on demand). No model, no key.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

BASE = Path(os.environ.get("SAP_LOOP_BASE") or ROOT.parent)     # holds work/ (the local clones live in work/mine)
DEFAULT_ROOT = BASE / "work" / "mine"
DEFAULT_OUT = ROOT / "docs" / "sap" / "bench_auto"

# Public ABAP repos, each verified to exist with `git ls-remote` (2026-11-17).
REPOS = [
    "abapGit/abapGit", "sbcgua/ajson", "sbcgua/abap-string-map", "sbcgua/mockup_loader", "abap2xlsx/abap2xlsx",
    "open-abap/open-abap-core", "larshp/abapOpenChecks", "abap2UI5/abap2UI5", "oblomov-dev/abap2UI5",
    "SAP/code-pal-for-abap", "SAP/abap-file-formats", "SAP/abap-file-formats-tools", "SAP/abap-atc-cr-cv-s4hc-tools",
    "ABAP-Logger/ABAP-Logger", "abap-openapi/abap-openapi-client", "abap-openapi/abap-openapi",
    "abaplint/abaplint-sci-client", "open-abap/open-abap-gui", "open-abap/open-abap-seo",
    "Marc-Bernard-Tools/MBT-Base", "abapGit/ADT_Backend", "abapGit/abapGit-plugins", "abapGit/background_modes",
    "abapGit/CI", "sbcgua/benchmarks", "sbcgua/abapmerge", "SAP-samples/abap-cheat-sheets",
    "SAP-samples/abap-platform-refscen-flight", "SAP-samples/abap-platform-rap-opensap",
    "SAP-samples/abap-platform-rap-workshops", "SAP-samples/abap-platform-fiori-feature-showcase",
    "SAP-samples/cloud-abap-rap", "abapinho/abak", "Marc-Bernard-Tools/MBT-Listcube", "Marc-Bernard-Tools/MBT-Command-Field",
]

FIX_RE = re.compile(r"\b(fix(?:e[sd]|ing)?|bug|bugs|wrong|incorrect|errors?|issues?\s*#?\d+|close[sd]?\s+#\d+|resolve[sd]?|regression|broken)\b", re.I)
ISSUE_RE = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|issue|bug)\s*:?\s+(?:https?://github\.com/([\w.-]+/[\w.-]+)/issues/|([\w.-]+/[\w.-]+)?#)(\d+)", re.I)


def git(cwd, *args, check=True):
    """Run git and return stdout text (utf-8, errors replaced). Raises RuntimeError when check and it failed."""
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=_env(), timeout=1800)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.decode('utf-8', 'replace')[-300:]}")
    return p.stdout.decode("utf-8", errors="replace")


def _env():
    import os
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def clone_dir(root, repo):
    return Path(root) / repo.split("/")[-1]


def ensure_clone(repo, root, *, fetch=True, run=git):
    """Blobless, checkout-less clone into <root>/<name>; fetched again when it exists. Returns the path or None."""
    d = clone_dir(root, repo)
    Path(root).mkdir(parents=True, exist_ok=True)
    try:
        if (d / ".git").exists() or (d / "HEAD").exists():
            if fetch:
                run(d, "fetch", "--quiet", "origin")
        else:
            run(Path(root), "clone", "--quiet", "--filter=blob:none", "--no-checkout", f"https://github.com/{repo}.git", d.name)
    except (RuntimeError, subprocess.TimeoutExpired, OSError):
        return None
    return d


def parse_log(text):
    """Parse `git log --name-status --no-renames --format=%x01%H%x1f%P%x1f%cI%x1f%B%x1e` into dicts."""
    out = []
    for chunk in text.split("\x01"):
        if "\x1e" not in chunk:
            continue
        head, rest = chunk.split("\x1e", 1)
        parts = head.split("\x1f", 3)
        if len(parts) < 4:
            continue
        sha, parents, date, msg = parts
        files = []
        for line in rest.splitlines():
            bits = line.split("\t")
            if len(bits) >= 2 and bits[0]:
                files.append((bits[0][0], bits[-1]))
        out.append({"sha": sha.strip(), "parents": parents.split(), "date": date.strip(), "message": msg.strip(), "files": files})
    return out


def classify(files):
    """files [(status, path)] -> (prod_path, test_path) when exactly one modified .clas.abap and its sibling testclasses changed."""
    abap = [(s, p) for s, p in files if p.endswith(".abap")]
    tests = [(s, p) for s, p in abap if p.endswith(".testclasses.abap")]
    prods = [(s, p) for s, p in abap if not p.endswith(".testclasses.abap")]
    if len(prods) != 1 or len(tests) != 1:
        return None
    (ps, pp), (ts, tp) = prods[0], tests[0]
    m = re.fullmatch(r"(.*/)?([\w#]+)\.clas\.abap", pp)
    if not m or ps != "M" or ts not in "MA":
        return None
    if tp != f"{m.group(1) or ''}{m.group(2)}.clas.testclasses.abap":
        return None
    if pp.startswith("test/") or "/test/" in pp:
        return None
    return pp, tp


def looks_like_fix(message):
    return bool(FIX_RE.search(message))


def issue_ref(message):
    m = ISSUE_RE.search(message)
    return (f"{m.group(1) or m.group(2) or ''}#{m.group(3)}") if m else ""


def mine_repo(repo, root, since, *, run=git, stats=None):
    """Candidates of one repo (newest first as git prints them). `stats` (dict) collects counts per filter stage."""
    import sap_intake as si
    st = stats if stats is not None else {}
    d = clone_dir(root, repo)
    log = run(d, "log", "--no-merges", "--no-renames", f"--since={since}", "--name-status",
              "--format=%x01%H%x1f%P%x1f%cI%x1f%B%x1e", "HEAD")

    def show(sha, path):
        return run(d, "show", f"{sha}:{path}", check=False)

    out = []
    for c in parse_log(log):
        st["commits"] = st.get("commits", 0) + 1
        if len(c["parents"]) != 1:
            continue
        pair = classify(c["files"])
        if not pair:
            continue
        st["one_class_and_tests"] = st.get("one_class_and_tests", 0) + 1
        if not looks_like_fix(c["message"]):
            continue
        st["fix_message"] = st.get("fix_message", 0) + 1
        prod, test = pair
        new_test, old_test = show(c["sha"], test), show(c["parents"][0], test)
        added = [m for m in si.test_methods(new_test) if m not in si.test_methods(old_test)]
        if len(added) < 2:
            continue
        st["two_new_tests"] = st.get("two_new_tests", 0) + 1
        new_prod = show(c["sha"], prod)
        if re.search(r"@\s*KERNEL", new_prod + show(c["parents"][0], prod), re.I) or re.search(r"@\s*KERNEL", new_test, re.I):
            st["kernel"] = st.get("kernel", 0) + 1
            continue
        subject = c["message"].splitlines()[0] if c["message"] else ""
        out.append({"repo": repo, "sha": c["sha"], "parent": c["parents"][0], "date": c["date"], "message": subject,
                    "issue": issue_ref(c["message"]), "class": prod.rsplit("/", 1)[-1].split(".")[0],
                    "production_file": prod, "test_file": test, "added_tests": len(added),
                    "class_lines": new_prod.count("\n") + 1})
    return out


def mine(repos, root, *, months=72, fetch=True, run=git, now=None):
    """All candidates, newest first. -> (candidates, per-repo stats)."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=round(months * 30.44))).date().isoformat()
    cut24 = (now - timedelta(days=round(24 * 30.44))).date().isoformat()
    cands, stats = [], {}
    for repo in repos:
        if ensure_clone(repo, root, fetch=fetch, run=run) is None:
            stats[repo] = {"error": "clone or fetch failed"}
            continue
        st = {}
        try:
            cands += mine_repo(repo, root, since, run=run, stats=st)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            st["error"] = str(exc)[:200]
        stats[repo] = st
    seen, uniq = set(), []                       # renamed or mirrored repos (abap2UI5, open-abap) share commits
    for c in cands:
        if c["sha"] not in seen:
            seen.add(c["sha"])
            uniq.append(c)
    cands = sorted(uniq, key=lambda c: (c["date"], c["sha"]), reverse=True)
    for i, c in enumerate(cands, 1):
        c["rank"] = i
        c["within_24m"] = c["date"][:10] >= cut24
        c["ref"] = f"{c['repo']}@{c['sha']}"
    return cands, stats, since


def write_outputs(cands, stats, since, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "CANDIDATES_MINED.json").write_text(json.dumps({"since": since, "candidates": cands, "stats": stats}, indent=1) + "\n", encoding="utf-8")
    per = {}
    for c in cands:
        per[c["repo"]] = per.get(c["repo"], 0) + 1
    lines = ["# Mined candidates (local git history, newest first; fixed order, never re-ranked)", "",
             f"Window: commits since {since}. {len(cands)} candidates. A candidate: non-merge commit, exactly one modified `.clas.abap` plus its "
             "sibling `.clas.testclasses.abap`, >= 2 added test methods, no @KERNEL, fix-like message. Screening (sap_screen.py --mined) decides admission.", "",
             "Per repo: " + ", ".join(f"{r} {n}" for r, n in sorted(per.items(), key=lambda x: -x[1])), "",
             "| # | repo | commit | date | issue | class | new tests | class lines | message |", "|---|---|---|---|---|---|---|---|---|"]
    for c in cands:
        lines.append(f"| {c['rank']} | {c['repo']} | {c['sha'][:8]} (parent {c['parent'][:8]}) | {c['date'][:10]} | {c['issue'] or '-'} | {c['class']} | "
                     f"{c['added_tests']} | {c['class_lines']} | {'' if c['within_24m'] else '(older than 24 months) '}{c['message'].replace('|', '/')[:100]} |")
    lines += ["", "## Funnel per repo", "", "| repo | commits | one class + tests | fix message | >=2 new tests | @KERNEL dropped | note |", "|---|---|---|---|---|---|---|"]
    for r, s in stats.items():
        lines.append(f"| {r} | {s.get('commits', 0)} | {s.get('one_class_and_tests', 0)} | {s.get('fix_message', 0)} | {s.get('two_new_tests', 0)} | {s.get('kernel', 0)} | {s.get('error', '')} |")
    (out / "CANDIDATES_MINED.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mine fix-with-tests candidates from local git history.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--months", type=int, default=72, help="window; commits within the last 24 months come first (newest-first order), older ones follow")
    ap.add_argument("--repos", nargs="*", default=REPOS)
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    cands, stats, since = mine(a.repos, a.root, months=a.months, fetch=not a.no_fetch)
    write_outputs(cands, stats, since, a.out)
    print(f"{len(cands)} candidates since {since}")
    for r, s in stats.items():
        print(f"  {r}: {sum(1 for c in cands if c['repo'] == r)} ({s})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
