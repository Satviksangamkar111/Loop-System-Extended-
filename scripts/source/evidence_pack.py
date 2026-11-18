"""Evidence pack for one finished loop run (G2). Reads a job evidence folder as the loop leaves it and writes two files into that folder:
EVIDENCE.md (one page a reviewer can read without opening logs) and EVIDENCE_MANIFEST.json (sha256 of every other file in the folder).
Reads only that folder. No network, no model call, no folder created. A file the loop did not write (older layouts) is reported as "not recorded".
CLI: python scripts/source/evidence_pack.py <folder> [<folder> ...]
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import redact

OUT_MD = "EVIDENCE.md"
OUT_MANIFEST = "EVIDENCE_MANIFEST.json"
OWN_OUTPUTS = (OUT_MD, OUT_MANIFEST)
NOT_RECORDED = "not recorded"
EXPECTED_FILES = ("status.json", "events.jsonl", "lineage.json", "acceptance_lock.json", "stage_snapshot.json", "history")
FREE_SUFFIX = ":free"

# Printed as the Limits section of every pack. Keep the wording here; the report copies it.
LIMITS = (
    "Offline ABAP is not SAP: the ABAP is checked offline (a transpiler run and static checks), not on a SAP system.",
    "Tests are the oracle: a green run means the acceptance tests passed, not that the code is right where they do not look.",
    "The sandbox does not block network yet: a test run is not sealed from the network.",
)
# Credential shapes the shared redact module does not know yet. Applied after redact.scrub on the whole page.
EXTRA_SHAPES = (re.compile(r"nvapi-[A-Za-z0-9_\-]{6,}"),)


def scrub(text):
    out = redact.scrub(text)
    for pattern in EXTRA_SHAPES:
        out = pattern.sub(redact.REPLACEMENT, out)
    return out


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_events(folder):
    """(events sorted by seq, count of unreadable lines); (None, 0) when the file is absent."""
    try:
        lines = (folder / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, 0
    events, bad = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            bad += 1
    events.sort(key=lambda e: e.get("seq") if isinstance(e.get("seq"), (int, float)) else 0)
    return events, bad


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_key(obj, wanted):
    """The first value stored under a key named `wanted` (case-insensitive) anywhere inside a JSON object, or None."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() == wanted:
                return value
            found = find_key(value, wanted)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key(item, wanted)
            if found is not None:
                return found
    return None


def fmt_seconds(seconds):
    if seconds is None:
        return NOT_RECORDED
    total = float(seconds)
    if total < 60:
        return f"{total:.1f} s"
    whole = int(round(total))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m {secs:02d}s" if hours else f"{minutes}m {secs:02d}s"


def cell(value, limit=160):
    if value is None or value == "":
        return NOT_RECORDED
    text = " ".join(str(value).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def attempt_outcome(event):
    if event.get("failed"):
        text = "failed" + (f": {event['error']}" if event.get("error") else "")
    elif event.get("status") is None:
        text = "ok (no HTTP status)"
    else:
        text = f"ok, HTTP {event['status']}"
    finish = event.get("finish_reason")
    if finish and finish != "stop":
        text += f" (finish: {finish})"
    return text


def tokens_text(event):
    values = [event.get("prompt_tokens"), event.get("completion_tokens"), event.get("reasoning_tokens")]
    if all(v is None for v in values):
        return NOT_RECORDED
    return " / ".join(NOT_RECORDED if v is None else str(v) for v in values)


def blank_step(**fields):
    step = {"when": None, "stage": None, "role": None, "mode": None, "model": None, "via": None, "effort": None,
            "outcome": None, "verdict": None, "seconds": None, "tokens": None, "cost": None}
    step.update(fields)
    return step


def build_steps(events, status):
    """Every step in order: attempts (start joined to end), test runs and review verdicts. Falls back to status.json steps."""
    if not events:
        steps = []
        for item in status.get("steps") or []:
            if isinstance(item, dict):
                outcome = " ".join(str(x) for x in (item.get("note"), item.get("message")) if x) or None
                steps.append(blank_step(mode=item.get("mode"), model=item.get("model"), stage=item.get("call"), outcome=outcome))
        return steps
    steps, open_steps, last_by_model = [], {}, {}
    for event in events:
        kind = event.get("type")
        if kind == "attempt-start":
            step = blank_step(when=event.get("ts"), stage=event.get("stage"), role=event.get("role"), mode=event.get("mode"),
                              model=event.get("model"), via=event.get("via"), effort=event.get("effort"))
            steps.append(step)
            open_steps[event.get("attempt_id")] = step
            last_by_model[event.get("model")] = step
        elif kind == "attempt-end":
            step = open_steps.pop(event.get("attempt_id"), None)
            if step is None:
                step = blank_step(when=event.get("ts"))
                steps.append(step)
            step["outcome"] = attempt_outcome(event)
            step["seconds"] = event.get("seconds")
            step["tokens"] = tokens_text(event)
            if event.get("cost_usd") is not None:
                step["cost"] = event.get("cost_usd")
        elif kind == "tests":
            failing = event.get("failing") or []
            outcome = "green" if event.get("green") is True else f"red: {len(failing)} failing"
            steps.append(blank_step(when=event.get("ts"), stage="tests", mode="tests", model="sandbox", outcome=outcome))
        elif kind == "review":
            step = last_by_model.get(event.get("reviewer"))
            if step is not None:
                step["verdict"] = event.get("verdict")
            else:
                steps.append(blank_step(when=event.get("ts"), mode=event.get("mode") or "review", model=event.get("reviewer"),
                                        verdict=event.get("verdict")))
    for step in open_steps.values():
        step["outcome"] = "no end recorded"
    return steps


def step_row(index, step):
    outcome = cell(step["outcome"], 220)
    if step["verdict"]:
        outcome = f"{outcome}; verdict {cell(step['verdict'], 40)}"
    when = step["when"] if isinstance(step["when"], str) else ""
    clock = when[11:19] if len(when) >= 19 else NOT_RECORDED
    seconds = fmt_seconds(step["seconds"]) if step["seconds"] is not None else NOT_RECORDED
    return f"| {index} | {clock} | {cell(step['stage'], 40)} | {cell(step['role'], 40)} | {cell(step['mode'], 20)} | " \
           f"{cell(step['model'], 80)} | {cell(step['via'], 30)} | {outcome} | {seconds} | {cell(step['tokens'], 60)} |"


def collect_calls(folder):
    """One record per file in history/: model, via, HTTP status and any x-served-by header the record holds."""
    calls = []
    history = folder / "history"
    if not history.is_dir():
        return calls
    for path in sorted(history.glob("*.json")):
        data = load_json(path)
        if not isinstance(data, dict):
            calls.append({"file": path.name, "unreadable": True})
            continue
        calls.append({"file": path.name, "unreadable": False, "model": data.get("model"), "via": data.get("via"),
                      "call": data.get("call") or data.get("mode"), "status": data.get("status"),
                      "served_by": data.get("served_by") or find_key(data, "x-served-by")})   # 2026-11-16: the call record's own served_by field (it was never read)
    return calls


def review_rows(steps):
    return [s for s in steps if s["mode"] == "review" and s["model"]]


def backup_lines(steps):
    """A reviewer step run by a writer role is a backup that took a reviewer's slot; name the failed reviewer it replaced."""
    lines = []
    for step in steps:
        if step["mode"] != "review" or str(step["role"] or "").startswith("reviewer"):
            continue
        failed = [s["model"] for s in steps if s["mode"] == "review" and s["stage"] == step["stage"]
                  and str(s["outcome"] or "").startswith("failed")]
        slot = step["stage"] or NOT_RECORDED
        lines.append(f"- Backup: {cell(step['model'])} (role {cell(step['role'])}) took the {slot} slot"
                     + (f" after {', '.join(cell(m) for m in failed)} failed" if failed else "") + ".")
    return lines or ["- Backup: none recorded."]


def collect(folder):
    status = load_json(folder / "status.json")
    status = status if isinstance(status, dict) else {}
    events, bad_lines = load_events(folder)
    events = events or []
    lock = load_json(folder / "acceptance_lock.json")
    lineage = load_json(folder / "lineage.json")
    evidence = status.get("evidence") if isinstance(status.get("evidence"), dict) else {}
    steps = build_steps(events, status)
    stamps = [(parse_ts(e.get("ts")), e.get("ts")) for e in events]
    stamps = sorted((s for s in stamps if s[0] is not None), key=lambda s: s[0])
    finish = next((e for e in reversed(events) if e.get("type") == "finish"), None)
    start_raw = stamps[0][1] if stamps else None
    end_raw = stamps[-1][1] if stamps else status.get("updated")
    duration = None
    if stamps:
        duration = (stamps[-1][0] - stamps[0][0]).total_seconds()
    runs = [e for e in events if e.get("type") == "tests"]
    if runs:
        green = sum(1 for r in runs if r.get("green") is True)
        last_red = next((r for r in reversed(runs) if r.get("green") is not True), None)
        failing = (last_red.get("failing") or []) if last_red else []
        if last_red is not None and not failing:
            failing = status.get("failing_tests") or []
        tests = {"green": green, "red": len(runs) - green, "failing": failing, "has_red": last_red is not None, "recorded": True}
    else:
        notes = [s for s in (status.get("steps") or []) if isinstance(s, dict) and s.get("mode") == "tests"]
        green = sum(1 for s in notes if str(s.get("note", "")).startswith("green"))
        red = sum(1 for s in notes if str(s.get("note", "")).startswith("red"))
        tests = {"green": green, "red": red, "failing": status.get("failing_tests") or [], "has_red": red > 0, "recorded": bool(notes)}
    budget = evidence.get("budget") if isinstance(evidence.get("budget"), dict) else {}
    priced = [s["cost"] for s in steps if s["cost"] is not None]
    hashes = {k: evidence.get(k) for k in ("tested_hash", "final_hash", "reviewed_hash")}
    known = [v for v in hashes.values() if v]
    return {
        "job": status.get("name") or next((e.get("job_id") for e in events if e.get("job_id")), None) or folder.name,
        "state": status.get("state") or (finish or {}).get("state"),
        "reason": status.get("reason") or (finish or {}).get("reason"),
        "tests_passed": status.get("tests_passed"),
        "verdict": status.get("review_verdict"),
        "coder_calls": status.get("coder_calls"),
        "reviewer_calls": status.get("reviewer_calls"),
        "escalate": (folder / "ESCALATE.md").is_file(),
        "start": start_raw, "end": end_raw, "duration": duration,
        "has_events": bool(events), "bad_lines": bad_lines,
        "steps": steps, "tests": tests,
        "backups": backup_lines(steps),
        "calls": collect_calls(folder),
        "lineage": lineage if isinstance(lineage, dict) else None,
        "lock": lock if isinstance(lock, dict) else None,
        "calibration": evidence.get("calibration"),
        "snapshot": evidence.get("stage_snapshot"),
        "hashes": hashes, "hashes_match": (len(known) == 3 and len(set(known)) == 1) if len(known) == 3 else None,
        "budget": budget, "priced": priced,
        "missing": [name for name in EXPECTED_FILES if not (folder / name).exists()],
        "status_present": bool(status),
    }


def render(d):
    out = []
    add = out.append
    add(f"# Evidence: {cell(d['job'], 120)}")
    add("")
    add(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')} from the files in this folder. Nothing was re-run; "
        "each line below is what the loop recorded.")
    add("")
    add("## Outcome")
    add(f"- Final state: {cell(d['state'])}")
    add(f"- Reason: {cell(d['reason'], 400)}")
    add(f"- Tests passed: {cell(d['tests_passed'])}")
    add(f"- Review verdict: {cell(d['verdict'])}")
    add(f"- Writer/repair calls: {cell(d['coder_calls'])}; reviewer calls: {cell(d['reviewer_calls'], 200)}")
    if d["escalate"]:
        add("- ESCALATE.md is in this folder: the loop asked for a human.")
    add("")
    add("## Timing")
    add(f"- Start: {cell(d['start'])}")
    add(f"- End: {cell(d['end'])}")
    add(f"- Total duration: {fmt_seconds(d['duration'])}")
    add("")
    add("## Steps (in order)")
    if d["steps"]:
        add("| # | Time (UTC) | Stage | Role | Mode | Model | Via | Outcome | Seconds | Tokens in / out / reasoning |")
        add("|---|---|---|---|---|---|---|---|---|---|")
        for index, step in enumerate(d["steps"], 1):
            add(step_row(index, step))
    else:
        add(f"- {NOT_RECORDED}")
    add("")
    add("## Test runs")
    t = d["tests"]
    if t["recorded"]:
        add(f"- Green runs: {t['green']}; red runs: {t['red']}")
        if t["has_red"]:
            add("- Failing tests in the last red run:")
            for name in t["failing"] or [NOT_RECORDED]:
                add(f"  - {cell(name, 240)}")
        else:
            add("- No red run recorded.")
    else:
        add(f"- {NOT_RECORDED}")
    add("")
    add("## Reviewers")
    reviews = review_rows(d["steps"])
    if reviews:
        for step in reviews:
            add(f"- {cell(step['model'])}: verdict {cell(step['verdict'] or NOT_RECORDED)}")
    else:
        add(f"- {NOT_RECORDED}")
    for backup in d["backups"]:
        add(backup)
    add("")
    add("## How calls were served")
    if d["calls"]:
        add("| Record | Model | Via | Call | HTTP | Served by (x-served-by) |")
        add("|---|---|---|---|---|---|")
        for call in d["calls"]:
            if call["unreadable"]:
                add(f"| {cell(call['file'], 60)} | {NOT_RECORDED} | {NOT_RECORDED} | {NOT_RECORDED} | {NOT_RECORDED} | {NOT_RECORDED} |")
                continue
            add(f"| {cell(call['file'], 60)} | {cell(call['model'], 80)} | {cell(call['via'], 30)} | {cell(call['call'], 20)} | "
                f"{cell(call['status'], 10)} | {cell(call['served_by'], 60)} |")
    else:
        add(f"- No call records in history/ ({NOT_RECORDED}).")
    if d["lineage"]:
        add("")
        add("Which model produced each file (lineage):")
        for path, info in sorted(d["lineage"].items()):
            if isinstance(info, dict) and isinstance(info.get("chain"), list):
                add(f"- {cell(path, 120)}: {' -> '.join(cell(m, 80) for m in info['chain'])}")
    add("")
    add("## Acceptance lock")
    add(f"- Calibration: {cell(d['calibration'])}")
    snap = d["snapshot"] if isinstance(d["snapshot"], dict) else {}
    add(f"- Stage snapshot sha256: {cell(snap.get('sha256'), 80)} (revision {cell(snap.get('revision'))})")
    h = d["hashes"]
    add(f"- Hashes: tested {cell(h.get('tested_hash'), 80)}; final {cell(h.get('final_hash'), 80)}; "
        f"reviewed {cell(h.get('reviewed_hash'), 80)}; all equal: {cell(d['hashes_match'])}")
    if d["lock"] is not None:
        hashed = {k: v for k, v in d["lock"].items() if v}
        add(f"- Locked files: {len(d['lock'])} ({len(hashed)} with a hash)")
        for path in sorted(d["lock"]):
            add(f"  - {cell(path, 120)}: {cell(d['lock'][path], 80) if d['lock'][path] else 'no hash recorded'}")
    else:
        add(f"- Lock file: {NOT_RECORDED}")
    add("")
    add("## Cost (USD, as recorded)")
    b = d["budget"]
    add(f"- Review spend recorded: {cell(b.get('review_usd_spent'))} USD of cap {cell(b.get('review_usd'))}")
    add(f"- Free requests used: {cell(b.get('free_requests_used'))} of {cell(b.get('free_requests'))}; "
        f"repair calls: {cell(b.get('repair_calls'))}")
    if d["priced"]:
        add(f"- Per-call cost summed from the events: {sum(d['priced']):.4f} USD")
    else:
        add("- Per-call cost: not recorded in the events; free-model calls are 0.0 USD.")
    for step in d["steps"]:
        if step["model"] and step["mode"] != "tests":
            cost = step["cost"]
            if cost is None:
                cost = "0.0 (free model)" if str(step["model"]).endswith(FREE_SUFFIX) else NOT_RECORDED
            add(f"  - {cell(step['model'], 80)} ({cell(step['mode'], 20)}): {cell(cost, 40)}")
    add("")
    add("## Limits")
    for item in LIMITS:
        add(f"- {item}")
    add("")
    add("## Not recorded")
    if d["missing"]:
        add(f"- Files the loop did not leave here: {', '.join(d['missing'])}.")
    if d["bad_lines"]:
        add(f"- Unreadable event lines skipped: {d['bad_lines']}.")
    if not d["missing"] and not d["bad_lines"]:
        add("- Nothing missing.")
    return "\n".join(out) + "\n"


def write_atomic(path, text):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def manifest_for(folder):
    files = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(folder).as_posix()
        if rel in OWN_OUTPUTS:
            continue
        files[rel] = sha256_file(path)
    return {"schema_version": 1, "folder": folder.name, "algorithm": "sha256", "files": files, "not_hashed": list(OWN_OUTPUTS)}


def build(folder):
    """Writes EVIDENCE.md, then the manifest (which excludes both outputs). Returns the two paths."""
    text = scrub(render(collect(folder)))
    md_path = folder / OUT_MD
    write_atomic(md_path, text)
    manifest_path = folder / OUT_MANIFEST
    write_atomic(manifest_path, json.dumps(manifest_for(folder), indent=2, ensure_ascii=False) + "\n")
    return md_path, manifest_path


def main(argv):
    if not argv:
        print("usage: python scripts/source/evidence_pack.py <folder> [<folder> ...]", file=sys.stderr)
        return 2
    status = 0
    for arg in argv:
        folder = Path(arg)
        if not folder.is_dir():
            print(f"not a folder: {arg}", file=sys.stderr)
            status = 1
            continue
        try:
            md_path, manifest_path = build(folder)
        except OSError as exc:
            print(f"could not write in {arg}: {exc}", file=sys.stderr)
            status = 1
            continue
        print(md_path)
        print(manifest_path)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
