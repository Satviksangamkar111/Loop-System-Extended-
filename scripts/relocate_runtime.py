"""Point every bench at this machine's ABAP runtime. Usage: python scripts/relocate_runtime.py <ABAP_RUNTIME folder>"""
import json
import sys
from pathlib import Path

rt = Path(sys.argv[1]).resolve()


def fix(r):
    project = r["project_dir"].replace(chr(92), "/").rstrip("/").split("/")[-1]
    base = rt / "benchmark" / "proj" if project.startswith("hb_") else rt / "projects"
    r["project_dir"] = str(base / project)
    if "project" in r:
        r["project"] = r["project_dir"]
    r["libs_dir"], r["tools_dir"] = str(rt / "libs"), str(rt / "abap_tools")
    r["lint_deps_dir"] = str(rt / "libs" / "abaplint-deps")


for p in Path("docs/sap/bench").glob("*/runner.json"):
    d = json.loads(p.read_text(encoding="utf-8"))
    fix(d)
    p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
for p in Path("docs/sap/bench_auto").glob("*/manifest.json"):
    d = json.loads(p.read_text(encoding="utf-8"))
    fix(d["runner"])
    p.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")
print("runner paths now point at", rt)
