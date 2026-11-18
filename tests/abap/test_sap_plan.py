"""scripts/source/sap_plan.py with a FAKE planner runner: no call is made, no roster is read (the planner role is replaced by a fake spec)."""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "source"))
import openrouter_call as oc  # noqa: E402
import sap_plan as sp  # noqa: E402

ABAP = "abap_work/abap2xlsx_C/zcl_excel_common.clas.abap"
ABAP_TEXT = (
    "CLASS zcl_excel_common DEFINITION." + "\n" + "  PUBLIC SECTION." + "\n" + "    CLASS-METHODS shift_formula." + "\n" + "  ENDCLASS." + "\n"
    + "CLASS zcl_excel_common IMPLEMENTATION." + "\n"
    + "  METHOD shift_formula." + "\n" + "    \" body" + "\n" + "  ENDMETHOD." + "\n"
    + "  METHOD condense_blanks." + "\n" + "  ENDMETHOD." + "\n"
    + "ENDCLASS." + "\n")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fake repo with the ABAP file and the real bench C template (copied), and a planner role that is a fake claude_code spec."""
    root = tmp_path / "repo"
    (root / Path(ABAP).parent).mkdir(parents=True)
    (root / ABAP).write_text(ABAP_TEXT, encoding="utf-8")
    template = json.loads((REPO / "docs" / "sap" / "bench" / "C" / "job.json").read_text(encoding="utf-8"))
    template_path = tmp_path / "job.json"
    template_path.write_text(json.dumps(template), encoding="utf-8")
    request = tmp_path / "request.md"
    request.write_text("# Shifting a formula\n\nSpaces and sheet names must not move.\n", encoding="utf-8")
    import p1b_routing as p1b
    monkeypatch.setattr(p1b, "budget_for", lambda profile=None: dict(template["budget"]))   # the owner's production budget (the test profile has 0)
    real_state = oc.roster_state
    monkeypatch.setattr(oc, "roster_state", lambda profile=None: {**real_state(profile), "ROLE_SPECS": {
        **real_state(profile)["ROLE_SPECS"], "planner": {"model": "fake-planner", "via": "claude_code", "effort": "medium"}}})
    return {"root": root, "template": template, "template_path": template_path, "request": request, "tmp": tmp_path}


class FakeRunner:
    """Answers with the given reply text, as the claude envelope; records every call."""
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, prompt, cwd, claude_cmd, timeout_s):
        self.calls.append(prompt)
        return 0, json.dumps({"type": "result", "is_error": False, "result": json.dumps(self.reply) if not isinstance(self.reply, str) else self.reply})


def good_reply(**over):
    units = [
        {"name": "shift_spaces", "file": ABAP, "methods": ["shift_formula"], "spec_lines": ["- KNOWN: Spaces inside a table reference stay."],
         "depends_on": []},
        {"name": "shift_sheets", "file": ABAP, "methods": ["shift_formula", "condense_blanks"],
         "spec_lines": ["- KNOWN: A sheet name that ends in digits is not a cell reference.", "- ASSUMED: Blanks are kept."],
         "depends_on": ["shift_spaces"]},
    ]
    reply = {"plan_md": "# Plan" + NL() + "Split the routine into two units.",
             "spec_md": "# Spec" + NL() + "- KNOWN: Spaces inside a table reference stay." + NL()
                        + "- KNOWN: A sheet name that ends in digits is not a cell reference." + NL() + "- ASSUMED: Blanks are kept." + NL(),
             "units": units}
    reply.update(over)
    return reply


def NL():
    return "\n"


def run(repo, runner, out=None):
    out = out or repo["root"] / "docs" / "sap" / "plans" / "bench-C"
    return sp.plan(repo["template_path"], repo["request"], out, root=repo["root"], runner=runner), out


def test_a_good_plan_is_accepted_and_written(repo):
    runner = FakeRunner(good_reply())
    result, out = run(repo, runner)
    assert result["state"] == "planned", result
    assert result["units"] == ["shift_spaces", "shift_sheets"]
    assert len(runner.calls) == 1
    for name in ("plan.md", "SPEC.md", "units.json", "shift_spaces.SPEC.md", "shift_spaces.job.json", "shift_sheets.job.json"):
        assert (out / name).is_file(), name
    units = json.loads((out / "units.json").read_text(encoding="utf-8"))
    assert [u["depends_on"] for u in units["units"]] == [[], ["shift_spaces"]]
    for u in units["units"]:
        assert hashlib.sha256((out / u["job"]).read_bytes()).hexdigest() == u["job_sha256"]
        assert hashlib.sha256((out / u["spec"].split("/")[-1]).read_bytes()).hexdigest() == u["spec_sha256"]
    job = json.loads((out / "shift_sheets.job.json").read_text(encoding="utf-8"))
    assert job["name"] == "shift_sheets"
    assert job["spec"] == "docs/sap/plans/bench-C/shift_sheets.SPEC.md"
    assert job["files"] == [ABAP]
    assert result["assumed"] == ["Blanks are kept."]


def test_each_unit_job_keeps_the_templates_acceptance_fields(repo):
    result, out = run(repo, FakeRunner(good_reply()))
    assert result["state"] == "planned", result
    keys = ["acceptance_tests", "negative_controls", "acceptance_baseline_fail", "budget", "sandbox_include", "tests", "reference", "fixers",
            "reviewers", "profile", "visibility", "deadline_min", "writer_reference"]
    for unit in ("shift_spaces", "shift_sheets"):
        job = json.loads((out / f"{unit}.job.json").read_text(encoding="utf-8"))
        for key in keys:
            assert job.get(key) == repo["template"].get(key), (unit, key)


def test_an_untagged_spec_line_is_refused_and_nothing_is_written(repo):
    reply = good_reply(spec_md="# Spec" + NL() + "The routine returns the value." + NL() + "- KNOWN: Spaces stay." + NL())
    result, out = run(repo, FakeRunner(reply))
    assert result["state"] == "planner-invalid"
    assert "not tagged" in result["reason"]
    assert not (out / "units.json").exists() and not (out / "shift_spaces.job.json").exists()


def test_an_unknown_method_is_refused(repo):
    units = good_reply()["units"]
    units[0]["methods"] = ["shift_formula", "no_such_method"]
    result, out = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planner-invalid"
    assert "no_such_method" in result["reason"]
    assert not (out / "units.json").exists()


def test_a_method_match_is_case_insensitive(repo):
    units = good_reply()["units"]
    units[0]["methods"] = ["SHIFT_FORMULA"]
    result, _ = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planned", result


def test_two_units_on_one_file_without_depends_on_are_refused(repo):
    units = good_reply()["units"]
    units[1]["depends_on"] = []
    result, out = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planner-invalid"
    assert "not ordered" in result["reason"]
    assert not (out / "units.json").exists()


def test_a_cyclic_depends_on_is_refused(repo):
    units = good_reply()["units"]
    units[0]["depends_on"] = ["shift_sheets"]
    result, _ = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planner-invalid"
    assert "cycle" in result["reason"]


def test_a_file_outside_the_template_is_refused(repo):
    units = good_reply()["units"]
    units[0]["file"] = "abap_work/other.clas.abap"
    result, _ = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planner-invalid"
    assert "not one of the template's files" in result["reason"]


def test_a_unit_name_that_is_not_filesystem_safe_is_refused(repo):
    units = good_reply()["units"]
    units[0]["name"] = "../escape"
    result, _ = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planner-invalid"


def test_a_restart_with_the_same_intent_makes_no_second_call(repo):
    runner = FakeRunner(good_reply())
    first, out = run(repo, runner)
    assert first["state"] == "planned"
    second, _ = run(repo, runner, out)
    assert second["state"] == "planned"
    assert second["units_sha256"] == first["units_sha256"]
    assert len(runner.calls) == 1


def test_a_restart_after_an_intent_with_no_answer_is_uncertain_and_makes_no_call(repo):
    out = repo["root"] / "docs" / "sap" / "plans" / "bench-C"
    first = FakeRunner(good_reply())
    run(repo, first, out)
    (out / "raw_response.json").unlink()
    (out / "units.json").unlink()
    second = FakeRunner(good_reply())
    result, _ = run(repo, second, out)
    assert result["state"] == "planner-uncertain"
    assert second.calls == []


def test_a_request_with_a_credential_shape_is_refused_before_any_call(repo):
    repo["request"].write_text("Use token ghp_" + "a" * 36 + " to fetch.\n", encoding="utf-8")
    runner = FakeRunner(good_reply())
    result, out = run(repo, runner)
    assert result["state"] == "planner-refused"
    assert runner.calls == [] and not out.exists()


def test_a_normal_run_leaves_the_job_files_read_only_and_the_plan_text_as_answered(repo):
    reply = good_reply()
    result, out = run(repo, FakeRunner(reply))
    assert result["state"] == "planned", result
    assert (out / "plan.md").read_bytes() == reply["plan_md"].encode("utf-8")
    for unit in ("shift_spaces", "shift_sheets"):
        assert (out / f"{unit}.job.json").stat().st_mode & stat.S_IWRITE == 0
    assert not [p for p in out.iterdir() if p.name.endswith(".tmp")]


def test_a_crash_after_the_first_job_file_restarts_to_planned_with_one_call(repo, monkeypatch):
    out = repo["root"] / "docs" / "sap" / "plans" / "bench-C"
    real_store = sp._store

    def crash_on_second_job(path, text, read_only):
        if path.name == "shift_sheets.job.json":
            raise OSError("simulated crash: the process died before this file")
        return real_store(path, text, read_only)

    runner = FakeRunner(good_reply())
    monkeypatch.setattr(sp, "_store", crash_on_second_job)
    with pytest.raises(OSError, match="simulated crash"):
        run(repo, runner, out)
    assert (out / "shift_spaces.job.json").is_file() and not (out / "units.json").exists()
    monkeypatch.setattr(sp, "_store", real_store)
    result, _ = run(repo, runner, out)                                  # restart: the saved answer, no second call
    assert result["state"] == "planned", result
    assert result["units"] == ["shift_spaces", "shift_sheets"]
    assert len(runner.calls) == 1
    assert (out / "units.json").is_file()
    assert (out / "shift_spaces.job.json").stat().st_mode & stat.S_IWRITE == 0


def test_a_job_file_with_different_bytes_is_refused_and_named(repo):
    out = repo["root"] / "docs" / "sap" / "plans" / "bench-C"
    runner = FakeRunner(good_reply())
    first, _ = run(repo, runner, out)
    assert first["state"] == "planned", first
    (out / "units.json").unlink()                                        # the plan looks unfinished: a restart re-writes its files
    tampered = out / "shift_sheets.job.json"
    os.chmod(tampered, stat.S_IREAD | stat.S_IWRITE)
    tampered.write_bytes(b'{"changed": true}\n')
    result, _ = run(repo, runner, out)
    assert result["state"] == "planner-invalid", result
    assert "shift_sheets.job.json" in result["reason"]
    assert tampered.read_bytes() == b'{"changed": true}\n'              # never silently overwritten
    assert not (out / "units.json").exists()
    assert len(runner.calls) == 1


def units_with(**changes):
    """good_reply's units, with the given keys changed on the first unit (a key set to the sentinel DROP is removed)."""
    units = good_reply()["units"]
    for key, value in changes.items():
        if value is DROP:
            units[0].pop(key, None)
        else:
            units[0][key] = value
    return units


DROP = object()


def test_a_new_method_is_accepted_and_listed_in_units_json_but_not_in_the_job(repo):
    units = units_with(new_methods=["shift_helper"], methods=["shift_formula"])
    result, out = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planned", result
    listed = json.loads((out / "units.json").read_text(encoding="utf-8"))["units"][0]
    assert listed["new_methods"] == ["shift_helper"]
    assert "New methods (to add): shift_helper" in (out / "shift_spaces.SPEC.md").read_text(encoding="utf-8")
    job = json.loads((out / "shift_spaces.job.json").read_text(encoding="utf-8"))
    assert "new_methods" not in job


def test_a_unit_may_have_only_new_methods(repo):
    units = units_with(methods=DROP, new_methods=["shift_helper"])
    result, _ = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planned", result


def test_a_new_method_that_already_exists_is_refused_and_named(repo):
    units = units_with(new_methods=["condense_blanks"])
    result, out = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planner-invalid"
    assert "condense_blanks" in result["reason"] and "already exists" in result["reason"]
    assert not (out / "units.json").exists()


def test_a_bad_new_method_identifier_is_refused(repo):
    for i, bad in enumerate(("shift-helper", "1shift", "x" * 31, "shift helper")):
        units = units_with(new_methods=[bad])
        result, out = run(repo, FakeRunner(good_reply(units=units)), out=repo["root"] / "docs" / "sap" / "plans" / f"bad{i}")
        assert result["state"] == "planner-invalid", bad
        assert bad in result["reason"], bad


def test_a_thirty_character_new_method_identifier_is_accepted(repo):
    name = "h" * 30
    result, _ = run(repo, FakeRunner(good_reply(units=units_with(new_methods=[name]))))
    assert result["state"] == "planned", result


def test_duplicate_new_methods_are_refused(repo):
    result, _ = run(repo, FakeRunner(good_reply(units=units_with(new_methods=["h1", "h1"]))))
    assert result["state"] == "planner-invalid"
    assert "repeats" in result["reason"]


def test_a_unit_with_neither_methods_nor_new_methods_is_refused(repo):
    units = units_with(methods=DROP)
    result, out = run(repo, FakeRunner(good_reply(units=units)))
    assert result["state"] == "planner-invalid"
    assert "names no method" in result["reason"]
    assert not (out / "units.json").exists()


def test_a_plan_without_new_methods_still_passes_and_lists_none(repo):
    result, out = run(repo, FakeRunner(good_reply()))
    assert result["state"] == "planned", result
    listed = json.loads((out / "units.json").read_text(encoding="utf-8"))["units"]
    assert [u["new_methods"] for u in listed] == [[], []]
