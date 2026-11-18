"""SAP planner (2026-11-16): one planner call turns a ticket and the job's ABAP files into a spec and a split of the work into units. The
acceptance tests and negative controls are NOT written by the planner: every unit job keeps the template's own (copied unchanged).

The call, the secret filtering, the O_EXCL INTENT.json lock (a restart never calls twice) and the states are plan_job's (reused, not copied).
A reply is validated before anything is written: every spec line is tagged KNOWN or ASSUMED, each unit's file is one of the template's files,
each method exists in that file as `METHOD <name>.`, units on one file are ordered by depends_on, depends_on has no cycle, unit names are unique
and filesystem-safe, and each unit job passes the production checks. Output (docs/sap/plans/<name>/): plan.md, SPEC.md, <unit>.SPEC.md,
<unit>.job.json and units.json (the sha256 of every job file). units.json is written last: its presence means the plan is complete.

CLI: python scripts/source/sap_plan.py <job.json> <request.md> --out docs/sap/plans/<name>
"""
import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import jsonschema

import claude_code as cc
import exec_role as er
import fix_loop as fl
import openrouter_call as oc
import p1b_routing as p1b
import plan_job as pj

REPO = Path(__file__).resolve().parents[2]
NL = chr(10)
UNIT_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
UNIT_KEYS = {"name", "file", "methods", "new_methods", "spec_lines", "depends_on"}
NEW_METHOD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,29}$")
INSTRUCTIONS = (
    "You are the planner for one SAP production job. Reply with ONE JSON object and nothing else, with these keys:" + NL
    + "- plan_md: the plan in Markdown." + NL
    + "- spec_md: the specification. Every line that states a requirement starts with `KNOWN:` (taken from the request or the files) or "
      "`ASSUMED:` (your own assumption). Headings may stay untagged." + NL
    + "- units: a list that splits the change into work units. Each unit is an object {name, file, methods, new_methods, spec_lines, depends_on}: "
      "name uses only letters, digits, `_` and `-`; file is one of the FILES below; methods lists the existing METHOD routines of that file "
      "the unit changes (spelled as they are after the word METHOD); new_methods lists methods the unit expects to add (usually empty; "
      "each name is a plain ABAP identifier of at most 30 letters, digits or `_`, not yet a METHOD of that file); a unit names at least one "
      "method in methods or new_methods; spec_lines are the requirement lines of this unit (each tagged KNOWN or ASSUMED and "
      "also a line of spec_md); depends_on lists the names of the units that must finish first. Two units on the same file must be ordered "
      "by depends_on, and there is no cycle." + NL
    + "Keep every concrete example of the request (each input together with its expected result, and each stated rule) word for word inside the "
      "spec lines it belongs to: the writers see only the spec lines of their unit, and a vague summary makes them guess. Give no implementation "
      "design of your own as a requirement; write such a step only as an ASSUMED line, and only when the request does not settle it." + NL
    + "Do not write tests, acceptance files or negative controls: the controller fixes them.")


def file_sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _outcome(state, reason, **extra):
    out = {"state": state, "reason": reason, "units": [], "units_sha256": None, "assumed": []}
    out.update(extra)
    return out


def _template_problems(template):
    """The template must be a production job the schema accepts and the production rules pass (checked before any call)."""
    try:
        jsonschema.validate(instance=template, schema=fl.JOB_SCHEMA)
    except jsonschema.ValidationError as exc:
        return ["template job schema: " + exc.message]
    try:
        p1b.check_production_job(template)
    except p1b.JobRefused as exc:
        return [str(exc)]
    return []


def plan(template_path, request_path, out_dir, root=REPO, runner=None, claude_cmd=None, timeout_s=pj.PLAN_TIMEOUT_S, client=None):
    """Plans one SAP job into units. Returns {state, reason, units, units_sha256, assumed}; states as plan_job's. The only planner call is made
    after INTENT.json is written; a restart with the same intent never calls again (its saved answer is read, or the outcome is uncertain)."""
    root, out = Path(root), Path(out_dir)
    try:
        template_bytes = Path(template_path).read_bytes()
        template = json.loads(template_bytes.decode("utf-8"))
        request = Path(request_path).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return _outcome("planner-invalid", f"the template or the request is unreadable: {exc}")
    if not isinstance(template, dict):
        return _outcome("planner-invalid", "the template job must be a JSON object")
    problems = _template_problems(template)
    if problems:
        return _outcome("planner-invalid", "; ".join(problems))
    try:
        spec = oc.roster_state()["ROLE_SPECS"]["planner"]
    except oc.RosterRefused as exc:
        return _outcome("planner-refused", str(exc))
    model, via, effort = spec["model"], oc.via_of(spec), spec.get("effort")
    if model in oc.SENTINELS:
        return _outcome("planner-refused", f"the {oc.active_profile()} profile has no planner (planner={model})")
    files = list(template["files"])
    problem = pj.input_problem(root, files, request)                  # no secret file, key or credential is sent (before any intent)
    if problem:
        return _outcome("planner-refused", problem)
    try:
        out_rel = out.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return _outcome("planner-refused", f"the output folder must be inside the repo: {out}")
    tsha = hashlib.sha256(template_bytes).hexdigest()
    fingerprint = pj.request_fingerprint(out.name, request + NL + "template_sha256 " + tsha, files, via, model, effort)
    ctx = {"root": root, "out": out, "out_rel": out_rel, "template": template, "template_sha256": tsha, "request": request}
    intent_path, raw_path = out / "INTENT.json", out / "raw_response.json"
    if intent_path.is_file():
        return _existing_intent(intent_path, raw_path, fingerprint, ctx)
    if len(files) > pj.MAX_FILES:
        return _outcome("planner-refused", f"at most {pj.MAX_FILES} files may be sent to the planner; got {len(files)}")
    if runner is None and via == "claude_code" and cc.real_call_refused(list(claude_cmd or ["claude"])):
        return _outcome("planner-refused", "a real planner command is refused under the test guard: no call was made")
    if runner is None and via == "cli_exec" and er.real_call_refused():
        return _outcome("planner-refused", "a real coding-agent planner command is refused under the test guard: no call was made")
    if runner is None and via == "claude_code":
        def runner(prompt, cwd, claude_cmd, timeout_s):
            return pj.claude_runner(prompt, cwd, claude_cmd, timeout_s, model=model, effort=effort)
    elif runner is None and via == "cli_exec":
        runner = pj.cli_runner(spec)
    elif runner is None:
        runner = pj.openrouter_runner(client or oc.OpenRouter(oc.load_keys(), root / "_loop" / "openrouter"))
    prompt = _prompt(root, request, files)
    out.mkdir(parents=True, exist_ok=True)
    try:                                       # the lock: only the call that creates INTENT.json may call the planner
        pj._create_intent(intent_path, {"job": out.name, "via": via, "model": model, "effort": effort, "files": files,
                                        "request_sha256": hashlib.sha256(request.encode("utf-8")).hexdigest(),
                                        "template_sha256": tsha, "fingerprint": fingerprint, "timeout_s": timeout_s,
                                        "written": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    except FileExistsError:
        return _existing_intent(intent_path, raw_path, fingerprint, ctx)
    try:
        with tempfile.TemporaryDirectory(prefix="sap_plan_cwd_") as empty:
            with pj._planner_attempt(out / "planner", model, via, effort) as attempt:   # events.jsonl lands in the plan folder
                _code, raw = runner(prompt, cwd=empty, claude_cmd=claude_cmd, timeout_s=timeout_s)
                raw = pj._scrub_reply(raw)                             # scrubbed and scanned before it is kept or read
                attempt["raw"] = raw
    except subprocess.TimeoutExpired:
        return _outcome("planner-uncertain", f"the call did not finish in {timeout_s} s: the outcome is unknown, and it is never retried")
    raw_path.write_text(raw, encoding="utf-8")
    return _from_answer(raw, ctx)


def _existing_intent(intent_path, raw_path, fingerprint, ctx):
    """The plan name already holds an intent: the same request is served from its saved answer (no call); another request is refused; an
    intent with no saved answer is uncertain and never retried."""
    try:
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _outcome("planner-uncertain", "the intent is unreadable or still being written: the outcome is unknown, and it is never retried")
    if not isinstance(intent, dict) or intent.get("fingerprint") != fingerprint:
        return _outcome("request-conflict", "this plan name already holds a plan for a different request, template or planner: the earlier plan "
                                            "is not served")
    if raw_path.is_file():
        return _from_answer(raw_path.read_text(encoding="utf-8"), ctx)       # reused: no call
    return _outcome("planner-uncertain", "the intent was written but no answer was saved: the outcome is unknown, and it is never retried")


def _prompt(root, request, files):
    parts = [INSTRUCTIONS, "REQUEST:", request, "", "FILES (chosen by the controller):"]
    for rel in files:
        problem = pj._file_problem(root, rel)                                # the same secret rule as input_problem
        if problem:
            raise ValueError(problem)
        parts.append(f"### {rel}" + NL + (root / rel).read_text(encoding="utf-8", errors="replace"))
    return NL.join(parts)


def _from_answer(raw, ctx):
    """The saved reply read the way plan_job reads its own: refused, failed or invalid replies stop here; a valid answer is written."""
    try:
        envelope = json.loads(raw)
    except ValueError:
        return _outcome("planner-invalid", "the output is not JSON")
    if not isinstance(envelope, dict):
        return _outcome("planner-invalid", "the output is not a JSON object")
    if envelope.get("redaction_hits"):
        kinds = ", ".join(str(k) for k in envelope["redaction_hits"])
        return _outcome("planner-refused", f"the planner's reply held credential-shaped text ({kinds}): it is refused and not used")
    reported = [key for key in ("mcp_servers", "mcpServers", "mcp", "plugins") if envelope.get(key)]
    if reported:
        return _outcome("planner-refused", f"the session reports MCP servers or plugins ({', '.join(reported)}); the planner runs with none")
    if envelope.get("is_error"):
        detail = envelope.get("result") or envelope.get("stderr") or envelope.get("exit_code")
        return _outcome("planner-failed", f"the call reported an error: {str(detail)[:300]}")
    text = envelope.get("result")
    if not isinstance(text, str):
        return _outcome("planner-invalid", "the answer has no result text")
    try:
        answer = json.loads(pj._strip_fences(text))
    except ValueError:
        return _outcome("planner-invalid", "the answer text is not JSON")
    if not isinstance(answer, dict):
        return _outcome("planner-invalid", "the answer is not a JSON object")
    problems = _problems(answer, ctx)
    if problems:
        return _outcome("planner-invalid", "; ".join(problems))
    return _write(answer, ctx)


def _method_pattern(name):
    return re.compile(r"^\s*METHOD\s+" + re.escape(name) + r"\s*\.", re.M | re.I)


def _order_problems(units):
    """depends_on must name known units, have no self or cyclic edge, and order every two units that share a file (directly or through
    other units)."""
    problems, names = [], {u["name"] for u in units}
    deps = {u["name"]: u["depends_on"] for u in units}
    for u in units:
        for d in u["depends_on"]:
            if d not in names:
                problems.append(f"unit {u['name']} depends on unknown unit {d!r}")
            elif d == u["name"]:
                problems.append(f"unit {u['name']} depends on itself")
    reach = {}
    for u in units:                                                    # every unit reachable through depends_on (known names only)
        seen, todo = set(), [d for d in deps[u["name"]] if d in names]
        while todo:
            d = todo.pop()
            if d not in seen:
                seen.add(d)
                todo.extend(x for x in deps.get(d, []) if x in names)
        reach[u["name"]] = seen
    for name in names:
        if name in reach[name]:
            problems.append(f"depends_on has a cycle through unit {name}")
    for i, a in enumerate(units):
        for b in units[i + 1:]:
            if a["file"] == b["file"] and b["name"] not in reach[a["name"]] and a["name"] not in reach[b["name"]]:
                problems.append(f"units {a['name']} and {b['name']} share {a['file']} and are not ordered by depends_on")
    return problems


def _problems(answer, ctx):
    missing = [key for key in ("plan_md", "spec_md", "units") if key not in answer]
    if missing:
        return [f"missing {', '.join(missing)}"]
    if not isinstance(answer["plan_md"], str) or not isinstance(answer["spec_md"], str):
        return ["plan_md and spec_md must be text"]
    if not isinstance(answer["units"], list) or not answer["units"]:
        return ["units must be a non-empty list"]
    spec_md = answer["spec_md"]
    problems = pj.spec_problems(spec_md)
    spec_lines = {line.strip() for line in spec_md.splitlines()}
    template, root = ctx["template"], ctx["root"]
    units, names = [], set()
    for i, u in enumerate(answer["units"]):
        if not isinstance(u, dict):
            problems.append(f"unit {i} must be an object")
            continue
        extra = sorted(set(u) - UNIT_KEYS)
        if extra:
            problems.append(f"unit {i} has unknown keys {extra}")
        name = u.get("name")
        if not isinstance(name, str) or not UNIT_NAME.match(name):
            problems.append(f"unit {i} name must be 1-64 letters, digits, _ or -: {name!r}")
            continue
        if name in names:
            problems.append(f"unit name {name!r} is used twice")
        names.add(name)
        rel = u.get("file")
        if rel not in template["files"]:
            problems.append(f"unit {name} file {rel!r} is not one of the template's files")
            continue
        methods, lines = u.get("methods", []), u.get("spec_lines")
        new_methods = u.get("new_methods", [])
        depends = u.get("depends_on", [])
        if not isinstance(methods, list) or not all(isinstance(m, str) for m in methods):
            problems.append(f"unit {name} methods must be a list of names")
            continue
        if not isinstance(new_methods, list) or not all(isinstance(m, str) for m in new_methods):
            problems.append(f"unit {name} new_methods must be a list of names")
            continue
        if not methods and not new_methods:
            problems.append(f"unit {name} names no method: methods or new_methods must name at least one")
            continue
        if len(set(new_methods)) != len(new_methods) or len(set(methods)) != len(methods):
            problems.append(f"unit {name} repeats a name in methods or new_methods")
            continue
        if not isinstance(lines, list) or not lines or not all(isinstance(x, str) for x in lines):
            problems.append(f"unit {name} spec_lines must be a non-empty list of text")
            continue
        if not isinstance(depends, list) or not all(isinstance(x, str) for x in depends):
            problems.append(f"unit {name} depends_on must be a list of unit names")
            continue
        for line in lines:
            if pj.spec_problems(line):
                problems.append(f"unit {name} spec line {line[:80]!r} is not tagged KNOWN or ASSUMED")
            elif line.strip() not in spec_lines:
                problems.append(f"unit {name} spec line {line[:80]!r} is not a line of spec_md")
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        for m in methods:
            if not _method_pattern(m).search(text):
                problems.append(f"unit {name}: method {m!r} is not a METHOD of {rel}")
        for m in new_methods:
            if not NEW_METHOD.match(m):
                problems.append(f"unit {name}: new method {m!r} is not an ABAP identifier (a letter first, then letters, digits or _, at most 30)")
            elif _method_pattern(m).search(text):
                problems.append(f"unit {name}: new method {m!r} already exists as a METHOD of {rel}: name it in methods instead")
        units.append({"name": name, "file": rel, "methods": methods, "new_methods": new_methods, "spec_lines": lines, "depends_on": depends})
    if problems:
        return problems
    problems += _order_problems(units)
    if problems:
        return problems
    for u in units:
        try:
            job = _unit_job(template, u, ctx)
            jsonschema.validate(instance=job, schema=fl.JOB_SCHEMA)
            p1b.check_production_job(job)
            if not template.get("writer_edit"):          # writer_edit jobs have no line limit (fix_loop checks characters instead)
                p1b.check_job_size({u["file"]: len((root / u["file"]).read_text(encoding="utf-8", errors="replace").splitlines())})
        except (jsonschema.ValidationError, p1b.JobRefused, p1b.JobTooLarge) as exc:
            problems.append(f"unit {u['name']} job: {getattr(exc, 'message', None) or exc}")
        for control in template.get("negative_controls") or []:
            targets = set((control.get("replace") or {}).keys())
            if targets - {u["file"]}:
                problems.append(f"unit {u['name']}: negative control {control.get('name')!r} targets {sorted(targets - {u['file']})}, "
                                "not the unit's file")
    return problems


def _unit_job(template, unit, ctx):
    """The unit's job: the template with the unit's name, spec and file. The acceptance tests, controls, budget and the rest are copied."""
    job = copy.deepcopy(template)
    job["name"] = unit["name"]
    job["spec"] = f"{ctx['out_rel']}/{unit['name']}.SPEC.md"
    job["files"] = [unit["file"]]
    return job


def _store(path, text, read_only):
    """Writes the text's utf-8 bytes to a temporary file in the same folder, then os.replace it over the target. A read-only target is made
    writable first (Windows refuses to replace it otherwise) and read-only again after; the bytes are the hashes' bytes."""
    if path.exists():
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    if read_only:
        os.chmod(path, stat.S_IREAD)                                      # a planned job is fixed from here on


def _write(answer, ctx):
    out = ctx["out"]
    if (out / "units.json").is_file():                                  # a restart: the artifacts of this answer are already written
        return _summary(out)
    units_json = []
    texts = {"plan.md": answer["plan_md"], "SPEC.md": answer["spec_md"]}
    for u in answer["units"]:
        unit = {"name": u["name"], "file": u["file"], "methods": u.get("methods", []), "new_methods": u.get("new_methods", []),
                "spec_lines": u["spec_lines"], "depends_on": u.get("depends_on", [])}
        head = f"# {unit['name']} ({unit['file']})" + NL
        if unit["new_methods"]:                                           # the job file keeps its fixed keys: new methods live in the spec only
            head += "New methods (to add): " + ", ".join(unit["new_methods"]) + NL
        spec_text = head + NL + NL.join(unit["spec_lines"]) + NL
        job_text = json.dumps(_unit_job(ctx["template"], unit, ctx), indent=2, sort_keys=True) + NL
        texts[f"{unit['name']}.SPEC.md"] = spec_text
        texts[f"{unit['name']}.job.json"] = job_text
        units_json.append({**unit, "job": f"{unit['name']}.job.json", "job_sha256": file_sha256_text(job_text),
                           "spec": f"{ctx['out_rel']}/{unit['name']}.SPEC.md", "spec_sha256": file_sha256_text(spec_text)})
    body = json.dumps({"name": out.name, "template_sha256": ctx["template_sha256"],
                       "request_sha256": hashlib.sha256(ctx["request"].encode("utf-8")).hexdigest(), "units": units_json},
                      indent=2, sort_keys=True) + NL
    texts["units.json"] = body
    for rel, text in texts.items():                                       # before any write: a file that holds other bytes is never overwritten
        target = out / rel
        if target.is_file() and target.read_bytes() != text.encode("utf-8"):
            return _outcome("planner-invalid", f"{rel} already exists with different bytes than this plan writes (a changed file): "
                                               "refused, nothing was overwritten")
    out.mkdir(parents=True, exist_ok=True)
    for rel, text in texts.items():
        if rel == "units.json":
            continue                                                      # written last: its presence means the plan is complete
        _store(out / rel, text, read_only=rel.endswith(".job.json"))
    _store(out / "units.json", body, read_only=False)
    return _summary(out)


def _summary(out):
    units = json.loads((out / "units.json").read_text(encoding="utf-8"))["units"]
    spec = (out / "SPEC.md").read_bytes().decode("utf-8")
    assumed = [line.split(":", 1)[1].strip() for line in spec.splitlines() if re.match(r"^\s*(?:[-*]\s+)?ASSUMED:", line)]
    return {"state": "planned", "reason": None, "units": [u["name"] for u in units],
            "units_sha256": hashlib.sha256((out / "units.json").read_bytes()).hexdigest(), "assumed": assumed}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Plan one SAP job into units (one planner call).")
    parser.add_argument("template", help="the template job.json")
    parser.add_argument("request", help="the request (ticket) markdown file")
    parser.add_argument("--out", required=True, help="the plan folder, e.g. docs/sap/plans/<name>")
    parser.add_argument("--review", action="store_true", help="after planning, a second model reviews the plan (plan_review.py); one planner revision")
    args = parser.parse_args(argv)
    os.environ["SATVIK_PROFILE"] = "production"     # as scripts/sap_poc_run.py main(): the SAP roster lives in the production slot of its own file
    oc.ROSTER_PATH = Path(__file__).resolve().parents[2] / "config" / os.environ.get("SAP_ROSTER", "roster_sap.json")
    result = plan(args.template, args.request, args.out)
    print(json.dumps(result, indent=2))
    if args.review and result["state"] == "planned":
        import plan_review
        ticket, out = Path(args.request).read_text(encoding="utf-8"), Path(args.out)

        def revise(findings):                       # the one planner revision: the old plan is kept as <out>.rev0, the planner is asked again
            old = out.with_name(out.name + ".rev0")
            if old.exists():
                return False
            out.rename(old)
            note = ticket + NL + NL + "REVIEW FINDINGS to fix in the revised plan:" + NL + NL.join("- " + f for f in findings) + NL
            (old / "REVISE_REQUEST.md").write_text(note, encoding="utf-8")
            return plan(args.template, old / "REVISE_REQUEST.md", out)["state"] == "planned"
        review = plan_review.review_plan(out, ticket, revise=revise)
        print(json.dumps(review, indent=2))
        if review["status"] != "passed":
            print("plan-review-open")
            return 4
    return 0 if result["state"] == "planned" else 1


if __name__ == "__main__":
    sys.exit(main())
