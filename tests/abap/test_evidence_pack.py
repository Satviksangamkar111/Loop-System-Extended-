"""Evidence pack (G2): one EVIDENCE.md and EVIDENCE_MANIFEST.json per finished loop run. Fake folders only, built in tmp_path: no model, no network.
Covered: the key facts appear, the manifest hashes match the files and never hash the two outputs, a key-shaped string in an event never reaches the
page, an old layout with missing files is reported as "not recorded" instead of crashing, and the CLI refuses a folder that does not exist."""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
import evidence_pack as ep  # noqa: E402

PLANTED = "sk-or-v1-PLANTEDKEY0123456789abcdef"
PLANTED_NV = "nvapi-PLANTEDNV0123456789abcdef"
PLANTED_BEARER = "Bearer PLANTEDTOKEN0123456789"


def write_events(folder, rows):
    (folder / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def full_folder(tmp_path, name="job-one"):
    """A finished run in the current layout: writer, sandbox red then green, one reviewer failing, a backup, and a planted key in an error."""
    folder = tmp_path / name
    (folder / "history").mkdir(parents=True)
    (folder / "original").mkdir()
    rows = [
        {"seq": 1, "ts": "2026-11-16T09:00:00.000Z", "job_id": name, "type": "attempt-start", "attempt_id": "a-01", "stage": "writer_a_write",
         "role": "writer_a", "mode": "write", "model": "fake-writer:free", "via": "openrouter", "effort": "off"},
        {"seq": 2, "ts": "2026-11-16T09:00:03.000Z", "job_id": name, "type": "attempt-end", "attempt_id": "a-01", "status": 200, "failed": False,
         "prompt_tokens": 100, "completion_tokens": 40, "reasoning_tokens": 0, "finish_reason": "stop", "seconds": 3.0, "requests": 1},
        {"seq": 3, "ts": "2026-11-16T09:01:00.000Z", "job_id": name, "type": "tests", "green": False,
         "failing": ["tests/acc.py::test_one", "tests/acc.py::test_two"]},
        {"seq": 4, "ts": "2026-11-16T09:02:00.000Z", "job_id": name, "type": "attempt-start", "attempt_id": "a-02", "stage": "writer_a_repair",
         "role": "writer_a", "mode": "repair", "model": "fake-writer:free", "via": "openrouter", "effort": "off"},
        {"seq": 5, "ts": "2026-11-16T09:02:10.000Z", "job_id": name, "type": "attempt-end", "attempt_id": "a-02", "status": 200, "failed": False,
         "prompt_tokens": 200, "completion_tokens": 90, "reasoning_tokens": None, "finish_reason": "stop", "seconds": 10.0, "requests": 1},
        {"seq": 6, "ts": "2026-11-16T09:03:00.000Z", "job_id": name, "type": "tests", "green": True, "failing": []},
        {"seq": 7, "ts": "2026-11-16T09:03:10.000Z", "job_id": name, "type": "attempt-start", "attempt_id": "a-03", "stage": "reviewer_a",
         "role": "reviewer_a", "mode": "review", "model": "fake-reviewer-a", "via": "claude_code", "effort": "medium"},
        {"seq": 8, "ts": "2026-11-16T09:03:20.000Z", "job_id": name, "type": "attempt-end", "attempt_id": "a-03", "status": None, "failed": True,
         "prompt_tokens": 2, "completion_tokens": 9, "reasoning_tokens": None, "finish_reason": None, "seconds": 10.0, "requests": 1,
         "error": f"reviewer reply has no verdict, key was {PLANTED} and {PLANTED_BEARER}"},
        {"seq": 9, "ts": "2026-11-16T09:03:30.000Z", "job_id": name, "type": "attempt-start", "attempt_id": "a-04", "stage": "reviewer_a",
         "role": "writer_b", "mode": "review", "model": "fake-backup:free", "via": "openrouter", "effort": "low"},
        {"seq": 10, "ts": "2026-11-16T09:04:00.000Z", "job_id": name, "type": "attempt-end", "attempt_id": "a-04", "status": 200, "failed": False,
         "prompt_tokens": 5000, "completion_tokens": 300, "reasoning_tokens": 120, "finish_reason": "stop", "seconds": 30.0, "requests": 1},
        {"seq": 11, "ts": "2026-11-16T09:04:01.000Z", "job_id": name, "type": "review", "reviewer": "fake-backup:free", "mode": "review",
         "verdict": "READY", "evidence_ok": None},
        {"seq": 12, "ts": "2026-11-16T09:04:05.000Z", "job_id": name, "type": "attempt-start", "attempt_id": "a-05", "stage": "reviewer_b",
         "role": "reviewer_b", "mode": "review", "model": "fake-reviewer-b", "via": "cli_exec", "effort": "low"},
        {"seq": 13, "ts": "2026-11-16T09:05:05.000Z", "job_id": name, "type": "attempt-end", "attempt_id": "a-05", "status": None, "failed": False,
         "prompt_tokens": None, "completion_tokens": None, "reasoning_tokens": None, "finish_reason": None, "seconds": 60.0, "requests": 1,
         "cost_usd": 0.012},
        {"seq": 14, "ts": "2026-11-16T09:05:06.000Z", "job_id": name, "type": "review", "reviewer": "fake-reviewer-b", "mode": "review",
         "verdict": "READY", "evidence_ok": None},
        {"seq": 15, "ts": "2026-11-16T09:05:07.000Z", "job_id": name, "type": "finish", "state": "passed", "reason": "READY from: fake-reviewer-b"},
    ]
    write_events(folder, rows)
    (folder / "status.json").write_text(json.dumps({
        "name": name, "schema_version": 1, "state": "passed", "tests_passed": True, "review_verdict": "READY",
        "reason": "READY from: fake-reviewer-b, fake-backup:free (backup for reviewer_a)", "failing_tests": [],
        "steps": [{"model": "fake-writer:free", "mode": "write", "note": "1 file(s) returned"}],
        "coder_calls": 2, "reviewer_calls": {"fake-reviewer-b": 1, "fake-backup:free": 1},
        "evidence": {"calibration": "passed", "tested_hash": "aa" * 32, "final_hash": "aa" * 32, "reviewed_hash": "aa" * 32,
                     "stage_snapshot": {"sha256": "bb" * 32, "revision": 1},
                     "budget": {"free_requests_used": 3, "free_requests": 40, "review_usd_spent": 0.012, "review_usd": 0.05,
                                "repair_calls": 1, "repair_enabled": True}},
        "updated": "2026-11-16T09:05:08Z"}), encoding="utf-8")
    (folder / "lineage.json").write_text(json.dumps({"abap_work/x.clas.abap": {"chain": ["fake-writer:free", "fake-repair:free"],
                                                                                "last": "fake-repair:free", "origin": "fake-writer:free"}}),
                                         encoding="utf-8")
    (folder / "acceptance_lock.json").write_text(json.dumps({"tests/acc.py": "cc" * 32, "conftest.py": None}), encoding="utf-8")
    (folder / "stage_snapshot.json").write_text("{}", encoding="utf-8")
    (folder / "history" / "call_01.json").write_text(json.dumps({"model": "fake-writer:free", "via": "openrouter", "mode": "write", "status": 200,
                                                                  "failed": False, "headers": {"X-Served-By": "fake-host-7"}}), encoding="utf-8")
    (folder / "history" / "review_02.txt").write_text("## Verdict: READY\n", encoding="utf-8")
    (folder / "original" / "x.clas.abap").write_text("CLASS x DEFINITION.\n", encoding="utf-8")
    return folder


def old_layout_folder(tmp_path):
    """The older layout: only a status.json with steps (no roles, no via, no events, no lock, no history)."""
    folder = tmp_path / "old-run"
    folder.mkdir()
    (folder / "status.json").write_text(json.dumps({
        "name": "old-run", "state": "escalate", "reason": "repair calls used up (2) and still red", "failing_tests": ["t::one"],
        "steps": [{"model": "fake-old:free", "mode": "write", "note": "1 file(s) returned"},
                  {"model": "sandbox", "mode": "tests", "note": "red: 5 failing"},
                  {"model": "fake-old-2", "mode": "failed", "call": "write", "message": "RemoteDisconnected", "note": "failed, no HTTP status"}],
        "coder_calls": 2, "reviewer_calls": {}, "evidence": {"budget": {"review_usd_spent": 0.0}}}), encoding="utf-8")
    return folder


def hashes_of(folder):
    out = {}
    for path in folder.rglob("*"):
        if path.is_file():
            rel = path.relative_to(folder).as_posix()
            if rel not in ep.OWN_OUTPUTS:
                out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_evidence_has_the_key_facts(tmp_path):
    folder = full_folder(tmp_path)
    md_path, _ = ep.build(folder)
    text = md_path.read_text(encoding="utf-8")
    for needle in ("# Evidence: job-one", "Final state: passed", "READY from: fake-reviewer-b", "Total duration: 5m 07s",
                   "09:00:00", "fake-writer:free", "writer_a_repair", "openrouter",
                   "Green runs: 1; red runs: 1", "tests/acc.py::test_one", "tests/acc.py::test_two",
                   "fake-reviewer-a", "fake-backup:free", "took the reviewer_a slot after fake-reviewer-a failed",
                   "verdict READY", "all equal: True", "Calibration: passed", "cc" * 32, "0.012",
                   "Free requests used: 3 of 40", "fake-host-7", "abap_work/x.clas.abap: fake-writer:free -> fake-repair:free",
                   "0.0 (free model)", "Offline ABAP is not SAP", "Tests are the oracle", "The sandbox does not block network yet"):
        assert needle in text, needle
    assert text.index("## Steps (in order)") < text.index("## Test runs") < text.index("## Reviewers") < text.index("## Limits")


def test_the_steps_keep_their_order_and_join_each_start_to_its_end(tmp_path):
    folder = full_folder(tmp_path)
    text = ep.build(folder)[0].read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| ") and line[2:3].isdigit()]
    # 1 writer, 2 red sandbox run, 3 repair, 4 green sandbox run, 5 failed reviewer, 6 backup reviewer, 7 second reviewer
    assert [r.split("|")[1].strip() for r in rows] == ["1", "2", "3", "4", "5", "6", "7"]
    assert "| 2 |" in text and "red: 2 failing" in text
    assert "| 3 | 09:02:00 | writer_a_repair" in rows[2]
    assert "failed: reviewer reply has no verdict" in rows[4]
    assert "ok, HTTP 200; verdict READY" in rows[5]


def test_the_manifest_hashes_match_and_the_outputs_are_not_hashed(tmp_path):
    folder = full_folder(tmp_path)
    before = hashes_of(folder)
    md_path, manifest_path = ep.build(folder)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["files"]) == set(before), "every other file is listed, by relative path"
    for rel, digest in manifest["files"].items():
        assert digest == before[rel], rel
    assert "EVIDENCE.md" not in manifest["files"] and "EVIDENCE_MANIFEST.json" not in manifest["files"]
    assert set(manifest["not_hashed"]) == {"EVIDENCE.md", "EVIDENCE_MANIFEST.json"}
    # running again gives the same manifest: the earlier outputs are not hashed into themselves
    ep.build(folder)
    again = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert again["files"] == manifest["files"]


def test_a_key_shaped_string_in_an_event_never_reaches_the_page(tmp_path):
    folder = full_folder(tmp_path)
    md_path, manifest_path = ep.build(folder)
    text = md_path.read_text(encoding="utf-8")
    assert PLANTED not in text and PLANTED_BEARER not in text
    assert "PLANTEDKEY" not in text and "PLANTEDTOKEN" not in text
    assert "reviewer reply has no verdict" in text  # the rest of the error text is kept
    # the planted key is in the raw events file (hashed as is); only the page is scrubbed
    assert PLANTED in (folder / "events.jsonl").read_text(encoding="utf-8")


def test_nvapi_keys_are_scrubbed_too(tmp_path):
    folder = full_folder(tmp_path)
    write_events(folder, [{"seq": 1, "ts": "2026-11-16T09:00:00.000Z", "type": "finish", "state": "passed",
                           "reason": f"ok with {PLANTED_NV}"}])
    text = ep.build(folder)[0].read_text(encoding="utf-8")
    assert PLANTED_NV not in text and "PLANTEDNV" not in text


def test_an_old_layout_with_missing_files_is_reported_not_crashed(tmp_path):
    folder = old_layout_folder(tmp_path)
    md_path, manifest_path = ep.build(folder)
    text = md_path.read_text(encoding="utf-8")
    assert "Final state: escalate" in text
    assert "repair calls used up (2) and still red" in text
    assert "red: 5 failing" in text  # from status.json steps when events are absent
    assert "fake-old-2" in text and "RemoteDisconnected" in text
    assert "Total duration: not recorded" in text
    assert "Lock file: not recorded" in text
    assert "events.jsonl" in text and "acceptance_lock.json" in text and "history" in text  # named as not left here
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["files"] == hashes_of(folder)


def test_an_empty_folder_gets_a_page_and_a_manifest(tmp_path):
    folder = tmp_path / "empty-run"
    folder.mkdir()
    md_path, manifest_path = ep.build(folder)
    text = md_path.read_text(encoding="utf-8")
    assert "# Evidence: empty-run" in text and "not recorded" in text
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["files"] == {}


def test_a_damaged_event_line_is_counted_and_skipped(tmp_path):
    folder = full_folder(tmp_path)
    with open(folder / "events.jsonl", "a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    text = ep.build(folder)[0].read_text(encoding="utf-8")
    assert "Unreadable event lines skipped: 1" in text
    assert "Final state: passed" in text


def test_the_cli_refuses_a_missing_folder_and_writes_nothing_for_it(tmp_path, capsys):
    missing = tmp_path / "does-not-exist"
    assert ep.main([str(missing)]) == 1
    assert not missing.exists()
    assert ep.main([]) == 2


def test_the_cli_writes_both_files_for_each_folder(tmp_path, capsys):
    a, b = full_folder(tmp_path, "run-a"), old_layout_folder(tmp_path)
    assert ep.main([str(a), str(b)]) == 0
    for folder in (a, b):
        assert (folder / "EVIDENCE.md").is_file() and (folder / "EVIDENCE_MANIFEST.json").is_file()
    out = capsys.readouterr().out
    assert "EVIDENCE.md" in out and "EVIDENCE_MANIFEST.json" in out


def test_the_module_names_no_model_family():
    text = (REPO / "scripts" / "source" / "evidence_pack.py").read_text(encoding="utf-8").lower()
    for word in ("gpt", "claude", "anthropic", "haiku", "opus", "sonnet", "nemotron", "dots", "gemini", "llama", "mistral", "codex"):
        assert word not in text, word
