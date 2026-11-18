"""Build the automatic benchmark benches (docs/sap/bench_auto/hb_<id>) from a checkout of the benchmark. No model is called.

Source: timkoehne/LLM-Benchmark-ABAP-Code-Generation (MIT). The checkout must hold dataset/abap_canonical_solution, dataset/abap_unittests
and dataset/prompts. The runtime folder must hold project/ (db/<id>/ for erp_ tasks) and libs/; a tmp/ work area is made inside it.

Usage:
    python scripts/make_benchmark_bench.py --benchmark DIR --runtime DIR [--private DIR] [--tools DIR] [--lint-deps DIR] ID [ID ...]
    e.g. python scripts/make_benchmark_bench.py --benchmark D:/src/LLM-Benchmark-ABAP-Code-Generation --runtime D:/bench/runtime 0 104 erp_000

Env instead of flags: SAP_BENCHMARK_DIR (checkout), SAP_BENCH_RUNTIME (runtime), SAP_BENCH_PRIVATE (private folder).
Defaults, where <base> is env SAP_LOOP_BASE, else the parent of this repository: private <base>/bench_private,
tools <base>/abap_tools, lint deps <base>/bench/libs/abaplint-deps.
ID is a task number (0-179) or erp_NNN. Writes docs/sap/bench_auto/hb_<id>/ and abap_work/hb_<id>/ in this repository. The reference
solution and its changed lines go only to the private folder. The gate records base_fails and heldout_fails_on_base.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("SAP_LOOP_BASE") or REPO.parent)
sys.path.insert(0, str(REPO / "scripts" / "source"))
import abap_transpile_run as t  # noqa: E402
import sap_auto_controls as ac  # noqa: E402

D = B = PRIVATE = TOOLS = LINT_DEPS = None      # dataset, runtime, private, tools, lint deps: set by main()

METHOD = re.compile(r"^[ \t]*METHOD\s+([\w~]+)\s*\.[^\n]*\n(.*?)^[ \t]*ENDMETHOD\s*\.[^\n]*\n?", re.M | re.S | re.I)
LINT = {"global": {"files": "/src/**/*.*", "skipGeneratedGatewayClasses": True, "skipGeneratedPersistentClasses": True, "skipGeneratedFunctionGroups": True},
        "dependencies": [{"folder": "/lint_deps", "files": "/src/**/*.*"}],
        "syntax": {"version": "v758", "errorNamespace": "."}, "rules": {"parser_error": True}}


def cname(i):
    return f"z_humaneval_erp_{i[4:]}" if i.startswith("erp_") else f"z_humaneval_{int(i):03d}"


def read(p):
    return p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def stub_of(src):
    """(stub text, public implemented methods, reference body lines)."""
    cut = re.search(r"^[ \t]*ENDCLASS\s*\.[^\n]*\n", src, re.M | re.I)
    head, impl = src[:cut.end()], src[cut.end():]
    sect = re.search(r"^[ \t]*(PROTECTED|PRIVATE)\s+SECTION\s*\.", head, re.M | re.I)
    public = head[:sect.start()] if sect else head[:cut.start()]
    head2 = public.rstrip() + "\n  PROTECTED SECTION.\n  PRIVATE SECTION.\nENDCLASS.\n"
    allowed, body = [], []

    def repl(m):
        body.extend(x.strip() for x in m.group(2).splitlines() if x.strip())
        if re.search(rf"\b{re.escape(m.group(1))}\b", public, re.I):
            allowed.append(m.group(1).lower())
            return f"  METHOD {m.group(1)}.\n  ENDMETHOD.\n\n"
        return ""
    return head2 + METHOD.sub(repl, impl), allowed, body


def build(i):
    n, bid = cname(i), "hb_" + i
    bench = REPO / "docs/sap/bench_auto" / bid
    proj = B / "proj" / bid
    shutil.rmtree(proj, ignore_errors=True)
    shutil.copytree(B / ("db/" + i if i.startswith("erp_") else "project"), proj)
    (proj / "abaplint.json").write_text(json.dumps(LINT), encoding="utf-8")
    sol, test = read(D / f"abap_canonical_solution/{n}.abap"), read(D / f"abap_unittests/{n}_test.abap")
    stub, allowed, body = stub_of(sol)
    if not allowed:
        return {"id": i, "ok": False, "why": "no public method found"}
    rel, trel = f"src/{n}.clas.abap", f"src/{n}.clas.testclasses.abap"
    tmp = B / "tmp" / bid
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "s.abap").write_bytes(stub.encode())
    (tmp / "t.abap").write_bytes(test.encode())
    (tmp / "f.abap").write_bytes(sol.encode())
    cfg = {"project": str(proj), "project_dir": str(proj), "libs_dir": str(B / "libs"), "tools_dir": str(TOOLS), "config": "abap_transpile.json",
           "lint_deps_dir": str(LINT_DEPS), "only_object": n.upper()}
    try:
        base = t.run_abap_tests(cfg, {rel: tmp / "s.abap", trel: tmp / "t.abap"}, timeout_s=120)
        fixed = t.run_abap_tests(cfg, {rel: tmp / "f.abap", trel: tmp / "t.abap"}, timeout_s=120)
    except Exception as e:
        return {"id": i, "ok": False, "why": f"{type(e).__name__}: {str(e)[:200]}"}
    if any(v != "PASS" for v in fixed.values()):
        return {"id": i, "ok": False, "why": "reference solution fails"}
    fails = {k.split("->")[-1].lower() for k, v in base.items() if v != "PASS"}
    names = [k.split("->")[-1].lower() for k in base]
    order = sorted(names, key=lambda x: (re.search(rf"\b{x}\b", test, re.I).start() if re.search(rf"\b{x}\b", test, re.I) else 10**9))
    first = next((x for x in order if x in fails), None)
    if len(order) < 2 or first is None:
        return {"id": i, "ok": False, "why": f"{len(order)} tests, {len(fails)} fail on the empty class"}
    rest = [x for x in order if x != first]
    held = rest[0::2]
    if not [x for x in order if x not in held and x in fails]:
        return {"id": i, "ok": False, "why": "no acceptance test fails on the empty class"}
    shutil.rmtree(bench, ignore_errors=True)
    (bench / "tests_upstream").mkdir(parents=True)
    work = REPO / "abap_work" / bid / f"{n}.clas.abap"
    work.parent.mkdir(parents=True, exist_ok=True)
    work.write_bytes(stub.encode())
    tb = test.encode()
    (bench / "tests_upstream" / f"{n}.clas.testclasses.abap").write_bytes(tb)
    prompt = read(D / f"prompts/{i}.txt").strip()
    (bench / "ticket.md").write_text(prompt + f"\n\nTARGET: implement this in the ABAP class {n.upper()} in the given file. Its public section is already correct and must stay as it is: "
                                     "the methods there are the ones to implement, their bodies are empty now. Private helper methods may be added. "
                                     "If the text above is written in another language or names another class or method, its behaviour is what counts.\n", encoding="utf-8")
    p = PRIVATE / bid
    p.mkdir(parents=True, exist_ok=True)
    (p / "fixed.abap").write_bytes(sol.encode())
    (p / "fixed_lines.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    m = {"schema": 1, "id": bid, "repo": "timkoehne/LLM-Benchmark-ABAP-Code-Generation", "pr": 0, "base_sha": "6898edf", "merge_sha": "6898edf", "label": "BENCHMARK", "ticket_source": "benchmark_prompt",
         "production_file": rel, "work_file": f"abap_work/{bid}/{n}.clas.abap", "original_sha256": hashlib.sha256(stub.encode()).hexdigest(),
         "test_files": [{"path": trel, "stored": f"tests_upstream/{n}.clas.testclasses.abap", "sha256": hashlib.sha256(tb).hexdigest(), "new_methods": order, "heldout_methods": held}],
         "allowed_methods": allowed, "runner": cfg,
         "gate": {"base_transpiles": True, "base_fails": sorted(fails), "heldout_fails_on_base": all(h in fails for h in held), "heldout_failing_methods": sorted(h for h in held if h in fails), "fix_passes": True,
                  "checked_utc": datetime.now(timezone.utc).isoformat()},
         "created_utc": datetime.now(timezone.utc).isoformat()}
    (bench / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    ac.load_manifest(bench / "manifest.json")
    return {"id": i, "ok": True, "bench": bid, "tests": len(order), "acceptance": len(order) - len(held), "heldout": len(held), "fail_on_empty": len(fails), "methods": allowed}


def main(argv=None):
    global D, B, PRIVATE, TOOLS, LINT_DEPS
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser(description="Build hb_* automatic benches from a benchmark checkout (no model call).")
    ap.add_argument("ids", nargs="+", help="task numbers (0-179) or erp_NNN")
    ap.add_argument("--benchmark", default=os.environ.get("SAP_BENCHMARK_DIR"), help="benchmark checkout (holds dataset/)")
    ap.add_argument("--runtime", default=os.environ.get("SAP_BENCH_RUNTIME"), help="runtime folder (holds project/, db/, libs/)")
    ap.add_argument("--private", default=os.environ.get("SAP_BENCH_PRIVATE") or str(BASE / "bench_private"), help="private folder (reference solutions)")
    ap.add_argument("--tools", default=str(BASE / "abap_tools"), help="ABAP tools folder")
    ap.add_argument("--lint-deps", default=str(BASE / "bench" / "libs" / "abaplint-deps"), help="abaplint dependency folder")
    a = ap.parse_args(argv)
    if not a.benchmark or not a.runtime:
        ap.error("--benchmark and --runtime (or SAP_BENCHMARK_DIR and SAP_BENCH_RUNTIME) are required")
    D, B, PRIVATE = Path(a.benchmark) / "dataset", Path(a.runtime), Path(a.private)
    TOOLS, LINT_DEPS = Path(a.tools), Path(a.lint_deps)
    with ThreadPoolExecutor(3) as ex:
        for r in ex.map(build, a.ids):
            print(json.dumps(r), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
