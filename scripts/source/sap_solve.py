"""One command for an automatic bench (docs/sap/AUTO_BENCH_CONTRACT.md, section 2 C): plan, run the loop job, evidence pack, held-out, COMPUTED verdict.

    python scripts/source/sap_solve.py docs/sap/bench_auto/<id>/manifest.json --series <tag>

verdict() is the pass rule (docs/sap/PASS_RULE.md, both amendments) as code: every input is explicit, nothing is read but the evidence folder, so it
is tested with fake folders. claude_tool_events() / codex tool events are the tool-use audit. fix_lines_leak() is the pre-send guard's check
(called from p1b_production.Models._ask when SAP_BENCH_ID is set). Top-level imports are stdlib only: the guard imports this module on every call.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT.parent / "work"                      # results/, residue_2026-11-16/ as run_job.sh used them
EVIDENCE_ROOT = ROOT.parent / "loop_evidence"
SETTLE_S, SETTLE_TRIES = 20, 15                         # key-usage settle poll after a run (production only)
NOISE_PATHS = ("docs/sap/run_log.jsonl",)        # the run log is appended after the verdict


def roster_name():
    """The roster file the planner and the job both use (2026-11-18, defect 2): SAP_ROSTER, else roster_sap.json."""
    return os.environ.get("SAP_ROSTER") or "roster_sap.json"


def _claude_aliases():
    """The Claude Code models the production roster's claude_code roles call (the only model names a Claude call may report). An unreadable
    roster gives none, so every reported model fails the tool-use audit (fail closed)."""
    try:
        roles = json.loads((ROOT / "config" / roster_name()).read_text(encoding="utf-8"))["profiles"]["production"]["roles"]
        return sorted({spec["model"] for spec in roles.values() if spec.get("via") == "claude_code"})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


# ---------------------------------------------------------------- pre-send guard

def _norm(line):
    return " ".join(line.split())


def _fingerprints(bench_id):
    """The normalized fingerprints of bench `bench_id` from sap_intake, or None when the guard is inactive (module or function missing, or none
    come back). 2026-11-18 (defect 12): this is what tells "no leak" apart from "guard inactive"."""
    try:
        import sap_intake
        fps = {_norm(f) for f in sap_intake.fixed_line_fingerprints(bench_id) or []}
    except (ImportError, AttributeError, OSError, ValueError):
        return None
    return fps or None


def leak_guard_state(bench_id):
    """"active" when the pre-send guard has fingerprints for this bench, else "inactive". solve() records it; an inactive guard does not block a run."""
    return "active" if _fingerprints(bench_id) else "inactive"


def fix_lines_leak(text, bench_id, run=3):
    """True when `text` holds `run` or more consecutive (blank lines skipped) lines that are fingerprinted upstream-fix lines of bench `bench_id`.
    The fingerprints come from sap_intake (agent A), imported lazily; when the guard is inactive (see leak_guard_state) this is False. It may
    return normalized lines or their sha256 hex digests. Lines shorter than 8 characters never count (`ENDIF.` is not a fingerprint)."""
    fps = _fingerprints(bench_id)
    if not fps:
        return False
    streak = 0
    for line in text.splitlines():
        n = _norm(line)
        if not n:
            continue
        if len(n) >= 8 and (n in fps or hashlib.sha256(n.encode("utf-8")).hexdigest() in fps):
            streak += 1
            if streak >= run:
                return True
        else:
            streak = 0
    return False


# ---------------------------------------------------------------- tool-use audit

def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _name_tokens(model_id):
    """The lowercase words of a model name: claude-x-5-5 -> {claude, x, 5}."""
    return set(re.split(r"[^a-z0-9]+", str(model_id).lower()))


def claude_tool_events(history_dir, models=None):
    """Tool use of Claude calls, from every raw envelope in history/ (`*_raw.json`: repair_step_NN, review_NN / reply_NN, plan). Returns a list of
    {"file", "rule", "detail"}. Rules: "iteration_type" (a usage.iterations entry whose type is not "message", e.g. advisor_message),
    "multi_iteration" (more than one iteration in one call: a timed-out advisor call showed ['message','message']), "model_family" (a modelUsage
    entry whose name has none of `models`, the Claude aliases the roster calls, default the roster's own: `claude-x-5-5` has the word x), "advisor_text" (the
    substring 'advisor' in the result text, a warning only), "unreadable" (the envelope cannot be read, so it cannot be cleared). An envelope
    with no modelUsage is not checked for models (2026-11-18: no such envelope exists in the counted series)."""
    models = _claude_aliases() if models is None else models
    events = []
    for path in sorted(Path(history_dir).glob("*_raw.json")):
        env = _load(path)
        if not isinstance(env, dict):
            events.append({"file": path.name, "rule": "unreadable", "detail": "not a JSON object"})
            continue
        usage = env.get("usage") if isinstance(env.get("usage"), dict) else {}
        its = usage.get("iterations") if isinstance(usage.get("iterations"), list) else []
        types = [i.get("type") if isinstance(i, dict) else None for i in its]
        odd = [t for t in types if t != "message"]
        if odd:
            events.append({"file": path.name, "rule": "iteration_type", "detail": f"iteration types {types}"})
        if len(its) > 1:
            events.append({"file": path.name, "rule": "multi_iteration", "detail": f"{len(its)} iterations {types}"})
        reported = env.get("modelUsage") if isinstance(env.get("modelUsage"), dict) else {}
        other = sorted(m for m in reported if not any(a in _name_tokens(m) for a in models))
        if other:
            events.append({"file": path.name, "rule": "model_family", "detail": f"modelUsage reports {other}; expected {list(models)}"})
        if "advisor" in str(env.get("result") or "").lower():
            events.append({"file": path.name, "rule": "advisor_text", "detail": "the result text mentions the advisor"})
    return events


def codex_tool_events(history_dir):
    """Total tool events recorded in history/call_NN.json of cli_exec (Codex) calls, and the Claude call records that have no raw envelope."""
    total, unchecked = 0, []
    hist = Path(history_dir)
    for path in sorted(hist.glob("call_[0-9]*.json")):
        rec = _load(path)
        if not isinstance(rec, dict):
            continue
        if rec.get("via") == "cli_exec":
            total += int(rec.get("tool_events") or 0)
        elif rec.get("via") == "claude_code":
            num = re.search(r"call_(\d+)", path.name).group(1)
            if not list(hist.glob(f"*_{num}_raw.json")):
                unchecked.append(path.name)
    return total, unchecked


# ---------------------------------------------------------------- verdict

def _ready_names(reason):
    m = re.match(r"\s*READY from: (.*?)(?:;|$)", reason or "")
    if not m:
        return []
    return sorted({re.sub(r"\s*\(.*?\)\s*$", "", n).strip() for n in m.group(1).split(",") if n.strip()})


def _porcelain_dirty(lines, manifest):
    keep = (f"docs/sap/bench_auto/{manifest['id']}", f"tests/controls_auto/{manifest['id']}", "tests/controls_auto/ACTIVE_",f"abap_work/{manifest['id']}") + NOISE_PATHS
    dirty = []
    for line in lines:
        path = line[3:].strip().strip('"').replace("\\", "/")
        if not any(path.startswith(k) for k in keep):
            dirty.append(line)
    return dirty


TOOL_FAIL_RULES = ("iteration_type", "multi_iteration", "model_family", "unreadable")   # 2026-11-18 (defect 10): these fail a run; advisor_text only warns


def verdict(evidence_dir, manifest, heldout_result, repo_state, claude_models=None):
    """The COMPUTED pass-rule verdict {"solved", "criteria", "reasons"}.
    heldout_result: {"passed": N, "total": M} (None when the held-out run did not happen). repo_state: {"original_verified": bool,
    "git_porcelain": [lines of `git status --porcelain`], "commit": hash}. Porcelain lines inside the bench folder, the manifest's controls and work
    folders and the run log are ignored. claude_models: the Claude aliases the roster's Claude calls use (solve passes the production roster's)."""
    ev = Path(evidence_dir)
    hist = ev / "history"
    status = _load(ev / "status.json")
    status = status if isinstance(status, dict) else {}
    crit, why = {}, []

    crit["state_passed"] = status.get("state") == "passed" and status.get("tests_passed") is True
    if not crit["state_passed"]:
        why.append(f"loop state is {status.get('state')!r}, not passed")

    names, reason = _ready_names(status.get("reason")), str(status.get("reason") or "")
    crit["two_valid_reviews"] = len(names) >= 2 or (len(names) >= 1 and "overruled all" in reason)
    if not crit["two_valid_reviews"]:
        why.append(f"fewer than two valid reviews and no arbiter ruling (reason: {reason[:120]!r})")

    codex, unchecked = codex_tool_events(hist)
    claude = claude_tool_events(hist, claude_models)
    # 2026-11-18 (defect 10): a Claude envelope fails the run on an iteration type other than "message", on more than one iteration, on a modelUsage
    # model that is not one of the roster's Claude aliases, or when it cannot be read; a missing envelope and a Codex tool event fail too. Only
    # a mention of the advisor in the result text is a warning.
    claude_fail = [e for e in claude if e["rule"] in TOOL_FAIL_RULES]
    crit["no_tool_use"] = codex == 0 and not claude_fail and not unchecked
    warnings = [f"{e['rule']} in {e['file']}: {e['detail']}" for e in claude if e not in claude_fail]
    if codex:
        why.append(f"{codex} Codex tool event(s)")
    for e in claude_fail:
        why.append(f"Claude tool use ({e['rule']}) in {e['file']}: {e['detail']}")
    if unchecked:
        why.append("Claude call(s) with no raw envelope to check: " + ", ".join(unchecked))

    h = heldout_result or {}
    crit["heldout_all_pass"] = bool(h) and int(h.get("total") or 0) > 0 and h.get("passed") == h.get("total")
    if not crit["heldout_all_pass"]:
        why.append(f"held-out cases not all passed ({h.get('passed')}/{h.get('total')})" if h else "held-out cases did not run")

    crit["original_verified"] = repo_state.get("original_verified") is True
    if not crit["original_verified"]:
        why.append("the original file was not verified by hash before the run")

    dirty = _porcelain_dirty(repo_state.get("git_porcelain") or [], manifest)
    crit["clean_tree_and_commit"] = not dirty and bool(repo_state.get("commit"))
    if dirty:
        why.append("git tree not clean: " + "; ".join(dirty[:5]))
    if not repo_state.get("commit"):
        why.append("no commit hash recorded")
    return {"solved": all(crit.values()), "criteria": crit, "reasons": why, "warnings": warnings}


# ---------------------------------------------------------------- solve

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(*args):
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8")
    return out.stdout


def _runlog(**ev):
    p = ROOT / "docs" / "sap" / "run_log.jsonl"
    ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **ev}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, sort_keys=True) + "\n")


def _template(manifest, bench_dir):
    """The planner's template job, made from the manifest (the loop's locked tests are the generic ones of sap_auto_acceptance.py)."""
    acc = "tests/acceptance/sap_auto_acceptance.py"
    try:
        import sap_auto_controls
        controls = sap_auto_controls.generic_controls(manifest)
        # 2026-11-17: the generated acceptance tests are test_new_<method> for the NON-held-out new methods; only those that fail on the base are baseline failures
        failing = {str(x).split("->")[-1].strip().lower() for x in manifest["gate"].get("base_fails", [])}
        base = [f"{acc}::test_new_{x}" for x in sap_auto_controls.acceptance_methods(manifest) if x in failing]
    except ImportError:
        controls, base = [], []
    return {"name": manifest["id"], "profile": "production", "visibility": "public",
            "spec": (bench_dir / "ticket.md").relative_to(ROOT).as_posix(), "files": [manifest["work_file"]], "tests": [acc],
            "acceptance_tests": [acc], "acceptance_baseline_fail": base, "negative_controls": controls, "reference": [],
            "writer_reference": False, "fixers": ["writer_a", "writer_b"], "reviewers": "by_lineage", "writer_edit": True,
            "budget": {"free_requests": 40, "review_usd": 0.05, "paid_usd": 0}, "deadline_min": 120,
            "sandbox_include": ["scripts", "tests", "abap_work", "config", "docs"]}


def _default_runner(job_rel, env):
    proc = subprocess.run([sys.executable, "scripts/sap_poc_run.py", job_rel], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout + proc.stderr


def _key_state(fn):
    try:
        return fn()
    except Exception:
        return None


def solve(manifest_path, *, series, runner=None, plan_fn=None, heldout_fn=None, preflight=True, preflight_fn=None, key_info_fn=None):
    """plan -> (plan review) -> per unit: verify the original, clear a stale _loop folder, run, evidence copy -> restore -> held-out -> verdict -> run log.
    runner(job_rel, env) -> (exit code, log text) and plan_fn / heldout_fn are injectable. Returns {"state", "solved", "verdicts", ...}.
    Spend guard (2026-11-17): unless preflight=False (tests only) sap_preflight.preflight() runs first and a failed role or a short key ends the run as
    `preflight-failed` BEFORE the planner call (a void run, PASS_RULE.md). The key's usage is read before and after: spend_usd is in the result and the
    run log. Between units a key limit_remaining under MIN_KEY_USD stops the run as `budget-guard`. key_info_fn() -> {"limit_remaining","usage","credits_left"}."""
    mpath = Path(manifest_path).resolve()
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    bid, bench_dir = manifest["id"], mpath.parent
    work, tag = ROOT / manifest["work_file"], f"{series}-{bid}"
    results = WORK / "results"
    results.mkdir(parents=True, exist_ok=True)
    if _sha(work) != manifest["original_sha256"]:
        return _record({"state": "abort-original-differs", "solved": False, "reason": f"{manifest['work_file']} differs from the manifest's original_sha256: restore it first"}, bid)
    import sap_preflight
    before = None
    if preflight:
        pf = (preflight_fn or sap_preflight.preflight)()
        if not pf.get("ok"):
            return _finish(tag, bid, {"state": "preflight-failed", "solved": False, "void": True, "failed_roles": pf.get("failed") or
                                      [r for r, v in (pf.get("roles") or {}).items() if not v.get("ok")],
                                      "key_problems": pf.get("key_problems") or [], "reason": "preflight failed before the planner call: a void run (PASS_RULE.md)"})
        before = dict(pf.get("key") or {}) if pf.get("key_checked", True) else None     # 2026-11-18 (defect 23): a roster with no OpenRouter role reads no key
    elif key_info_fn is not None:
        before = _key_state(key_info_fn)
    key_fn = key_info_fn or sap_preflight.default_key_info
    inner = _solve_run(mpath, manifest, series, tag, work, bench_dir, results, runner, plan_fn, heldout_fn, key_fn if before is not None else None)
    after = _key_state(key_fn) if before is not None else None
    if after is not None and key_info_fn is None:     # 2026-11-17: OpenRouter's key usage lags the calls (cal2b: logged 0.106 vs real 0.205); wait until it holds still for 3 reads
        stable, last = 0, after.get("usage")
        for _ in range(SETTLE_TRIES):
            time.sleep(SETTLE_S)
            now = _key_state(key_fn)
            if not now or not isinstance(now.get("usage"), (int, float)):
                continue
            stable = stable + 1 if now["usage"] == last else 0
            after, last = now, now["usage"]
            if stable >= 3:
                break
    if before and after and isinstance(before.get("usage"), (int, float)) and isinstance(after.get("usage"), (int, float)):
        inner["spend_usd"] = round(after["usage"] - before["usage"], 6)
        inner["credits_before"], inner["credits_after"] = before.get("credits_left"), after.get("credits_left")
    if os.environ.get("SAP_ALLOW_DUPLICATE_MODELS") == "1":      # 2026-11-18: the owner's testing exception is on: the panel may hold the code's own model, so nothing may count as solved
        inner["testing_exception"] = True
        inner["solved"] = False
        for v in inner.get("verdicts") or []:
            v["solved"] = False
            v.setdefault("reasons", []).append("testing exception SAP_ALLOW_DUPLICATE_MODELS=1 was on: the panel was not independent, so this run cannot count")
    return _finish(tag, bid, inner)


def _done(tag, bid, result):                                         # the run log line is written once, by solve(), after the spend is known
    return result


def _solve_run(mpath, manifest, series, tag, work, bench_dir, results, runner, plan_fn, heldout_fn, key_fn):
    bid = manifest["id"]
    original = work.read_bytes()
    original_verified = hashlib.sha256(original).hexdigest() == manifest["original_sha256"]     # 2026-11-18 (defect 21): the hash check at the start of the run
    plan_dir = bench_dir / "plans" / series
    plan_dir.mkdir(parents=True, exist_ok=True)
    tpl = plan_dir.with_name(plan_dir.name + ".template.job.json")        # outside the plan folder: a plan revision renames the folder
    tpl.write_text(json.dumps(_template(manifest, bench_dir), indent=2, sort_keys=True), encoding="utf-8")
    if plan_fn is None:
        import sap_plan
        os.environ["SATVIK_PROFILE"] = "production"
        import openrouter_call
        openrouter_call.ROSTER_PATH = ROOT / "config" / roster_name()
        plan_fn = sap_plan.plan
    plan = plan_fn(tpl, bench_dir / "ticket.md", plan_dir)
    if plan.get("state") == "planner-invalid" and not (plan_dir.with_name(plan_dir.name + ".invalid0")).exists():      # 2026-11-18: one retry of a plan the validator rejected (cal15: unit spec lines not copied exactly); the old folder stays as .invalid0
        old_dir = plan_dir.with_name(plan_dir.name + ".invalid0")
        plan_dir.rename(old_dir)
        retry_req = old_dir / "RETRY_REQUEST.md"
        retry_req.write_text((bench_dir / "ticket.md").read_text(encoding="utf-8") + chr(10) * 2 + "YOUR PREVIOUS PLAN WAS REJECTED BY THE CHECKER. Fix exactly this and answer again: " + str(plan.get("reason"))[:1500]
                             + chr(10) + "Every spec line of a unit must be copied EXACTLY (character for character) from a line of spec_md." + chr(10), encoding="utf-8")
        plan = plan_fn(tpl, retry_req, plan_dir)
    if plan.get("state") != "planned":
        return _done(tag, bid, {"state": "plan-" + str(plan.get("state")), "solved": False, "reason": plan.get("reason")})
    try:
        import plan_review                                    # agent D; absent: no review
        ticket_text = (bench_dir / "ticket.md").read_text(encoding="utf-8")

        def revise(findings):                  # the one planner revision (as sap_plan.main --review): the old plan stays as <plan>.rev0
            n = next(k for k in range(100) if not plan_dir.with_name(f"{plan_dir.name}.rev{k}").exists())
            if n >= int(os.environ.get("SAP_PLAN_REVISIONS", "3")):
                return False
            old = plan_dir.with_name(f"{plan_dir.name}.rev{n}")
            plan_dir.rename(old)
            nl = chr(10)
            (old / "REVISE_REQUEST.md").write_text(ticket_text + nl * 2 + "REVIEW FINDINGS to fix in the revised plan:" + nl * 2
                                                   + nl.join("- " + f for f in findings) + nl, encoding="utf-8")
            return plan_fn(tpl, old / "REVISE_REQUEST.md", plan_dir).get("state") == "planned"
        rv = plan_review.review_plan(plan_dir, ticket_text, revise=revise)
        if rv.get("status") != "passed":
            return _done(tag, bid, {"state": "plan-review-open", "solved": False, "reason": "; ".join(rv.get("findings") or [])[:400]})
    except ImportError:
        pass
    # 2026-11-18 (defect 4): SATVIK_HOME is PAR_SATVIK_HOME, else SATVIK_HOME, else satvik_home beside the repository root's parent (as `work` is)
    env = {**os.environ, "SATVIK_HOME": os.environ.get("PAR_SATVIK_HOME") or os.environ.get("SATVIK_HOME") or str(ROOT.parent / "satvik_home"),
           "PYTHONIOENCODING": "utf-8", "SAP_DIRECT_ROUTE": "nvidia_direct", "SAP_BENCH_MANIFEST": str(mpath), "SAP_BENCH_ID": bid,
           "SAP_ROSTER": roster_name()}      # 2026-11-18 (defect 2): the job gets the same roster as the planner in every case
    units = json.loads((plan_dir / "units.json").read_text(encoding="utf-8"))["units"]
    taken = [u["name"] for u in units if (EVIDENCE_ROOT / f"{series}-{u['name']}").exists()]
    if taken:                                 # 2026-11-18 (defect 1): an evidence folder left by an earlier run is never merged into or read
        return _done(tag, bid, {"state": "evidence-exists", "solved": False, "units": taken,
                                "reason": f"evidence folder(s) already exist for series {series}: {', '.join(taken)}: use a new series name"})
    # 2026-11-17: the ABAP sandbox passes no SAP_BENCH_* variable into its pytest (an environment whitelist), so the locked acceptance module finds its manifest
    # from this pointer file instead (tests/ and docs/ are copied into the sandbox work folder). One auto bench at a time.
    pointer = ROOT / "tests" / "controls_auto" / "ACTIVE_MANIFEST.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(Path(mpath).resolve().relative_to(ROOT).as_posix() + "\n", encoding="utf-8")
    run, verdicts, final, state = runner or _default_runner, [], work.with_name(work.name + ".final"), "no-unit"
    try:
        for i, u in enumerate(units):
            name = u["name"]
            if i and key_fn is not None:                              # spend guard: stop between units when the key is nearly empty
                import sap_preflight
                ki = _key_state(key_fn) or {}
                low = sap_preflight.key_problems(ki)
                if low:
                    verdicts.append({"unit": name, "state": "budget-guard", "solved": False, "reasons": low})
                    state = "budget-guard"
                    break
            stale = ROOT / "_loop" / name
            if stale.exists():
                dst = WORK / "residue_2026-11-16"
                dst.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stale), str(dst / f"_loop_{name}_before_{series}"))
            nm_file = ROOT / "tests" / "controls_auto" / "ACTIVE_NEW_METHODS.txt"      # the unit's announced helper methods, read by the sandboxed acceptance
            nm_file.write_text(",".join(u.get("new_methods") or []) + "\n", encoding="utf-8")
            code, text = run((plan_dir / u["job"]).relative_to(ROOT).as_posix(), env)
            nm_file.unlink(missing_ok=True)
            (results / f"{tag}_{name}.log").write_text(text + f"\nexit={code}\n", encoding="utf-8")
            ev = EVIDENCE_ROOT / f"{series}-{name}"
            state = "no-status"                  # 2026-11-18 (defect 1): only a _loop folder this run wrote counts (any stale one was moved away above)
            if (ROOT / "_loop" / name).is_dir():
                shutil.copytree(ROOT / "_loop" / name, ev)
                raw = plan_dir / "raw_response.json"
                if raw.is_file():
                    shutil.copy(raw, ev / "history" / "plan_raw.json") if (ev / "history").is_dir() else None
                try:
                    import evidence_pack
                    evidence_pack.build(ev)
                except Exception:                                   # the pack is a convenience; the verdict reads the raw files
                    pass
                state = (_load(ev / "status.json") or {}).get("state", "no-status")
            cand = results / f"{tag}_{name}_final.abap"
            shutil.copy(work, cand)
            if state != "passed":
                verdicts.append({"unit": name, "state": state, "solved": False, "reasons": [f"loop state {state}"]})
                break
            verdicts.append({"unit": name, "evidence": str(ev), "candidate": str(cand)})
    finally:
        work.write_bytes(original)                                   # restore the original, whatever happened
        pointer.unlink(missing_ok=True)
    state_ok = all("evidence" in v for v in verdicts) and verdicts
    aliases = _claude_aliases()
    out = []
    for v in verdicts:
        if "evidence" not in v:
            out.append(v)
            continue
        if heldout_fn is None:
            import sap_heldout
            heldout_fn = sap_heldout.run_manifest
        try:
            held = heldout_fn(str(mpath), v["candidate"])
        except Exception as exc:                                    # absent run_manifest or a runner error: held-out did not pass
            held = None
            v["heldout_error"] = f"{type(exc).__name__}: {exc}"
        repo = {"original_verified": original_verified, "git_porcelain": [l for l in _git("status", "--porcelain").splitlines() if l.strip()],
                "commit": _git("rev-parse", "HEAD").strip()}
        out.append({"unit": v["unit"], **verdict(v["evidence"], manifest, held, repo, aliases), "heldout": held})
    result = {"state": state, "solved": bool(state_ok) and all(v["solved"] for v in out), "verdicts": out}
    return _done(tag, bid, result)


def _record(result, bid):
    """Every solve result names its roster and whether the pre-send leak guard was active (2026-11-18: defects 2 and 12)."""
    result.setdefault("roster", roster_name())
    result.setdefault("leak_guard", leak_guard_state(bid))
    return result


def _finish(tag, bid, result):
    _record(result, bid)
    _runlog(event="solve", role="observer", job=bid, state=result.get("state"), solved=result.get("solved"), spend_usd=result.get("spend_usd"), msg=f"{tag}: {json.dumps(result, default=str)[:900]}")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan, run, held-out and COMPUTE the verdict for one automatic bench.")
    ap.add_argument("manifest")
    ap.add_argument("--series", required=True)
    a = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    r = solve(a.manifest, series=a.series)
    print(json.dumps(r, indent=2, default=str))
    return 0 if r.get("solved") else 1


if __name__ == "__main__":
    sys.exit(main())
