import sys, json, time
from pathlib import Path
sys.path.insert(0, "scripts/source")
import abap_static_sandbox as s, p0_gates as g
root = Path(".").resolve()
T = "tests/acceptance/sap_C_acceptance.py"
box = s.AbapStaticSandbox(editable=["abap_work/abap2xlsx_C/zcl_excel_common.clas.abap"], include=["scripts", "tests", "abap_work", "config", "docs"])
print("selftest:", box.selftest() or "ok", flush=True)
which = sys.argv[1:]
for name in which:
    t0 = time.time()
    r = box.run(root, [T], overlay={"abap_work/abap2xlsx_C/zcl_excel_common.clas.abap": root / f"tests/controls/sap_C_{name}.abap"}, timeout_s=600)
    import xml.etree.ElementTree as ET
    cases = []
    if r.junit:
        for c in ET.fromstring(r.junit).iter("testcase"):
            cases.append(c.get("name") + ("=FAIL" if (c.find("failure") is not None or c.find("error") is not None) else "=ok"))
    print(f"{name}: rc={r.returncode} timed_out={r.timed_out} {int(time.time()-t0)}s ->", cases, flush=True)
    if r.junit is None: print(r.output[-500:])
