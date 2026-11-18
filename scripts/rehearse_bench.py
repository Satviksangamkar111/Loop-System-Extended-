"""Free calibration rehearsal of one automatic bench: no model is called. Usage: python scripts/rehearse_bench.py hb_0"""
import json, os, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, "scripts/source")
import sap_solve

bid = sys.argv[1]
root = Path.cwd()
bench = root / "docs/sap/bench_auto" / bid
mpath = bench / "manifest.json"
m = json.loads(mpath.read_text(encoding="utf-8"))
work = root / m["work_file"]
original = work.read_bytes()
ctl = root / "tests/controls_auto"
ctl.mkdir(parents=True, exist_ok=True)
pointer, new = ctl / "ACTIVE_MANIFEST.txt", ctl / "ACTIVE_NEW_METHODS.txt"
job = bench / "rehearsal.job.json"
env = {**os.environ, "SAP_STOP_AFTER_CALIBRATION": "1", "SAP_BENCH_MANIFEST": str(mpath), "SAP_BENCH_ID": bid, "PYTHONIOENCODING": "utf-8"}
env.pop("SAP_ROSTER", None)
try:
    job.write_text(json.dumps(sap_solve._template(m, bench), indent=2), encoding="utf-8")
    pointer.write_text(mpath.relative_to(root).as_posix() + "\n", encoding="utf-8")
    new.write_text("\n", encoding="utf-8")
    subprocess.run([sys.executable, "scripts/sap_poc_run.py", job.relative_to(root).as_posix()], cwd=root, env=env)
    print("state:", json.loads((root / "_loop" / bid / "status.json").read_text(encoding="utf-8"))["state"])
finally:
    work.write_bytes(original)
    for f in (pointer, new, job):
        f.unlink(missing_ok=True)
    shutil.rmtree(root / "_loop" / bid, ignore_errors=True)
