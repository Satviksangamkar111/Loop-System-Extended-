"""Oracle check of an automatic bench (2026-11-17, advisor review): the GENERATED acceptance module and the held-out cases must pass on the upstream fix.
No model is called. If the upstream fix fails its own bench (a lint rule, the outside-allowed-methods test, a held-out case), every paid run on that bench
is wasted, so the bench is refused before any run.

    python scripts/source/sap_oracle_check.py docs/sap/bench_auto/<id>/manifest.json [--private DIR]
(default private folder: env SAP_LOOP_BASE, else the parent of this repository, plus bench_private)

Exit 0 when the upstream fix passes every acceptance test and every held-out case; 1 when it does not; 2 for a usage error. The work file is restored."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
BASE = Path(os.environ.get("SAP_LOOP_BASE") or ROOT.parent)     # holds bench_private/ and work/
PRIVATE = BASE / "bench_private"


def check(manifest_path, private_root=None):
    import sap_auto_controls as ac
    import sap_heldout
    mpath = Path(manifest_path).resolve()
    m = json.loads(mpath.read_text(encoding="utf-8"))
    fixed = Path(private_root or PRIVATE) / m["id"] / "fixed.abap"
    if not fixed.is_file():
        return {"ok": False, "reason": f"the upstream fix is not at {fixed}"}
    work = ac.work_path(m)
    original = work.read_bytes()
    ac.generic_controls(m)                         # writes tests/controls_auto/<id>/original.abap from the untouched work file
    pointer = ROOT / "tests" / "controls_auto" / "ACTIVE_MANIFEST.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(mpath.relative_to(ROOT).as_posix() + "\n", encoding="utf-8")
    try:
        work.write_bytes(fixed.read_bytes())
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/acceptance/sap_auto_acceptance.py"],
                              cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        full = proc.stdout + proc.stderr
        try:                                       # the whole output is kept for reading (the tail below is only a summary)
            (BASE / "work" / "results" / f"oracle_{m['id']}.log").write_text(full, encoding="utf-8")
        except OSError:
            pass
        tail = full[-1500:]
        held = sap_heldout.run_manifest(str(mpath), str(fixed))
    finally:
        work.write_bytes(original)
        pointer.unlink(missing_ok=True)
    ok = proc.returncode == 0 and bool(held.get("all_passed"))
    return {"ok": ok, "acceptance_exit": proc.returncode, "acceptance_tail": tail, "heldout": held.get("summary") or {k: held.get(k) for k in ("passed", "total")}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--private", default=str(PRIVATE))
    args = ap.parse_args(argv)
    try:
        out = check(args.manifest, args.private)
    except Exception as exc:                       # a missing file or a runner error is a failed check, never a pass
        out = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
