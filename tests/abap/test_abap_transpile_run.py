"""Frozen acceptance tests for scripts/source/abap_transpile_run.py (do not edit)."""
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import pytest
import abap_transpile_run as t

NODE = shutil.which("node")

CLEAN = """CLASS zcl_x IMPLEMENTATION.
  METHOD is_binary.
    REPLACE ALL OCCURRENCES OF cl_abap_char_utilities=>cr_lf IN lv WITH space.
    rv = boolc( lv_percentage > 10 ).
  ENDMETHOD.
ENDCLASS.
"""


def test_clean_abap_is_accepted():
    assert t.check_abap_text(CLEAN) == []


@pytest.mark.parametrize("risky", [
    "CALL FUNCTION 'HTTP_GET'.",
    "call function 'x'.",
    "OPEN DATASET lv_file FOR OUTPUT IN TEXT MODE.",
    "DELETE DATASET lv_file.",
    "READ DATASET lv_file INTO lv.",
    "DATA lo TYPE REF TO cl_http_client.",
    "cl_web_http_client_manager=>create_by_http_destination( ).",
    "SUBMIT zreport AND RETURN.",
    "CALL TRANSACTION 'SE38'.",
    "GENERATE SUBROUTINE POOL lt NAME lv.",
    "INSERT REPORT lv FROM lt.",
    "CALL METHOD (lv_class)=>(lv_method).",
    "CALL 'SYSTEM' ID 'COMMAND' FIELD lv.",
    "EXEC SQL.",
])
def test_risky_constructs_are_refused_with_a_reason(risky):
    problems = t.check_abap_text(CLEAN + risky + "\n")
    assert problems and all(isinstance(p, str) and p for p in problems)


def test_commented_out_risky_text_is_not_refused():
    assert t.check_abap_text(CLEAN + "* CALL FUNCTION 'X'." + chr(10) + "  \" OPEN DATASET x." + chr(10)) == []


def test_node_command_has_only_read_permissions():
    cmd = t.build_node_command("node", ["index.mjs", "--skip-critical"], ["C:/a b/work", "C:/tools/node_modules"])
    assert cmd[0] == "node" and "--permission" in cmd
    reads = [c for c in cmd if c.startswith("--allow-fs-read=")]
    assert reads == ["--allow-fs-read=C:/a b/work", "--allow-fs-read=C:/tools/node_modules"]
    joined = " ".join(cmd)
    for forbidden in ("allow-fs-write", "allow-child-process", "allow-worker", "allow-addons", "allow-wasi"):
        assert forbidden not in joined
    assert cmd[-2:] == ["index.mjs", "--skip-critical"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_real_node_is_confined_by_the_built_command(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    js = ("const fs=require('fs');const out=[];"
          "try{fs.writeFileSync('x.txt','1');out.push('WRITE-OK')}catch(e){out.push('WRITE-BLOCKED')}"
          "try{require('child_process').execSync('cmd /c echo hi');out.push('CHILD-OK')}catch(e){out.push('CHILD-BLOCKED')}"
          "try{fs.readFileSync(process.env.SystemRoot+'/win.ini');out.push('READ-OUT-OK')}catch(e){out.push('READ-OUT-BLOCKED')}"
          "try{fs.readdirSync('.');out.push('READ-IN-OK')}catch(e){out.push('READ-IN-BLOCKED')}"
          "console.log(out.join(' '))")
    cmd = t.build_node_command(NODE, ["-e", js], [str(work)])
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=60)
    assert res.stdout.split() == ["WRITE-BLOCKED", "CHILD-BLOCKED", "READ-OUT-BLOCKED", "READ-IN-OK"], res.stdout + res.stderr


def test_parse_results():
    out = "noise\nPASS ltcl_a->m1\nFAIL ltcl_a->m2 :: boom\nSUMMARY done\nPASS ltcl_b->m3\n"
    assert t.parse_results(out) == {"ltcl_a->m1": "PASS", "ltcl_a->m2": "FAIL: boom", "ltcl_b->m3": "PASS"}
    assert t.parse_results("") == {}


SKELETON = """async function run() {
  const skipCritical = process.argv[2] === "--skip-critical";
  for (const st of getData()) {
    const imported = await import(st.filename);
        await test.FRIENDS_ACCESS_INSTANCE[m.name]();
  }
}

run().then(() => {
  process.exit(0);
"""


def test_patch_runner_adds_object_filter_per_test_report_and_summary():
    out = t.patch_runner(SKELETON)
    assert "ONLY_OBJECT" in out and "PASS " in out and "FAIL " in out and "SUMMARY done" in out
    assert "for (const st of getData())" not in out


def test_patch_runner_fails_closed_when_the_generated_runner_changed():
    with pytest.raises(t.RunnerError):
        t.patch_runner("totally different generated file")


def test_more_bypasses_are_refused():
    tricks = [
        "TRANSFER: lv TO f.",
        "lv = `a" + chr(34) + "`. CALL FUNCTION 'X'.",
        "DEFINE m." + chr(10) + "  CALL &1 &2." + chr(10) + "END-OF-DEFINITION.",
        "CREATE OBJECT lo TYPE (lv).",
        "CALL METHOD lo->(lv).",
        "CALL FUNCTION 'X' DESTINATION 'D'.",
        "SYSTEM-CALL ctype.",
        "LEAVE TO TRANSACTION 'SE38'.",
    ]
    for trick in tricks:
        assert t.check_abap_text(CLEAN + trick + chr(10)), trick


def test_edited_paths_are_limited_to_abap_files_under_src(tmp_path):
    evil = tmp_path / "evil.js"
    evil.write_text("x")
    cfg = {"project_dir": str(tmp_path), "libs_dir": str(tmp_path), "tools_dir": str(tmp_path), "config": "c.json", "only_object": "ZCL_X"}
    for bad in ("node_modules/x.js", "abaplint.json", "output/index.mjs", "src/../abaplint.json", "src/x.js", "/src/x.abap", "src/x.abap:s"):
        with pytest.raises(t.RunnerError):
            t.run_abap_tests(cfg, {bad: evil})


def test_nonce_marks_report_lines_and_forged_lines_are_ignored():
    out = t.patch_runner(SKELETON, "abc123")
    assert "PASS@abc123" in out and "FAIL@abc123" in out
    stdout = "PASS ltcl_a->forged" + chr(10) + "PASS@n1 ltcl_a->real" + chr(10) + "FAIL@n1 ltcl_a->bad :: no" + chr(10) + "PASS@other ltcl_a->forged2" + chr(10)
    assert t.parse_results(stdout, "n1") == {"ltcl_a->real": "PASS", "ltcl_a->bad": "FAIL: no"}
    assert t.parse_results("PASS ltcl_a->m1" + chr(10)) == {"ltcl_a->m1": "PASS"}


def test_round3_bypasses_are_refused():
    bs, dq = chr(92), chr(34)
    tricks = [
        "lv = |a " + bs + "| " + dq + " | CALL FUNCTION 'X'.",
        "CALL: FUNCTION 'X'.",
        "OPEN: DATASET f FOR OUTPUT.",
        "CREATE: OBJECT lo TYPE (lv).",
        "CALL'SYSTEM' ID 'COMMAND' FIELD lv.",
        "lo->(lv_m)( ).",
    ]
    for trick in tricks:
        assert t.check_abap_text(CLEAN + trick + chr(10)), trick


def test_backslash_edited_key_is_refused(tmp_path):
    evil = tmp_path / "e.abap"
    evil.write_text("x")
    cfg = {"project_dir": str(tmp_path), "libs_dir": str(tmp_path), "tools_dir": str(tmp_path), "config": "c.json", "only_object": "ZCL_X"}
    with pytest.raises(t.RunnerError):
        t.run_abap_tests(cfg, {"src/.." + chr(92) + "x.abap": evil})


def test_a_pass_never_replaces_an_earlier_fail():
    out = "FAIL@n ltcl_a->m :: boom" + chr(10) + "PASS@n ltcl_a->m" + chr(10)
    assert t.parse_results(out, "n") == {"ltcl_a->m": "FAIL: boom"}
    out2 = "PASS@n ltcl_a->m" + chr(10) + "FAIL@n ltcl_a->m :: late" + chr(10)
    assert t.parse_results(out2, "n") == {"ltcl_a->m": "FAIL: late"}


def test_summary_marker_is_bound_to_the_nonce():
    assert "SUMMARY@abc123 done" in t.patch_runner(SKELETON, "abc123")
    assert "SUMMARY done" in t.patch_runner(SKELETON)


def test_transpile_command_is_confined_to_one_output_folder():
    cmd = t.build_transpile_command("node", "C:/tools/node_modules/@abaplint/transpiler-cli/build/bundle.js", "test/c.json",
                                    ["C:/w/p", "C:/w/libs", "C:/tools/node_modules"], "C:/w/p/output")
    assert cmd[0] == "node" and "--permission" in cmd
    assert [c for c in cmd if c.startswith("--allow-fs-write=")] == ["--allow-fs-write=C:/w/p/output"]
    assert [c for c in cmd if c.startswith("--allow-fs-read=")] == ["--allow-fs-read=C:/w/p", "--allow-fs-read=C:/w/libs", "--allow-fs-read=C:/tools/node_modules"]
    assert "allow-child-process" not in " ".join(cmd)
    assert cmd[-2:] == ["C:/tools/node_modules/@abaplint/transpiler-cli/build/bundle.js", "test/c.json"]


DATA_DIR = Path(__file__).resolve().parent / "data"


@pytest.mark.parametrize("trick", [
    "WRITE '@KERNEL console.log(1);'.",
    "write '@kernel console.log(1);'.",
    "WRITE: '@KERNEL console.log(1);'.",
    "WRITE `@KERNEL console.log(1);`.",
    "WRITE |@KERNEL console.log(1);|.",
    "WRITE '@ KERNEL console.log(1);'.",
    "WRITE '@" + chr(10) + "KERNEL console.log(1);'.",
    "lv = '@KERNEL x'.",
    "WRITE '@console.log(1)'.",
])
def test_kernel_write_is_refused(trick):
    assert t.check_abap_text(CLEAN + trick + chr(10)), trick


def test_a_legitimate_at_sign_is_not_refused():
    assert t.check_abap_text(CLEAN + "lv_mail = 'user@example.com'." + chr(10) + "SELECT * FROM t INTO @DATA(ls) WHERE a = @lv_a." + chr(10)) == []


def test_the_audit_poc_is_refused_before_anything_runs(tmp_path):
    poc = DATA_DIR / "kernel_poc.clas.abap"
    assert t.check_abap_text(poc.read_text(encoding="utf-8")), "the unfixed class plus one KERNEL write must be refused"
    cfg = {"project_dir": str(tmp_path), "libs_dir": str(tmp_path), "tools_dir": str(tmp_path), "config": "c.json", "only_object": "ZCL_X"}
    with pytest.raises(t.AbapTextRefused):
        t.run_abap_tests(cfg, {"src/utils/zcl_abapgit_utils.clas.abap": poc})


def test_abaplint_config_enables_the_kernel_rule_and_localizes_dependencies():
    cfg = {"global": {"files": "/src/**/*.*"}, "dependencies": [{"files": "/**/*.*", "folder": "/deps"}, {"url": "https://github.com/abaplint/deps", "files": "/src/**/*.*", "folder": "/lint_deps"}],
           "syntax": {"version": "v702"}, "rules": {"check_syntax": True}}
    snapshot = repr(cfg)
    out = t.abaplint_config(cfg)
    assert repr(cfg) == snapshot, "the input must not be changed"
    assert out["rules"]["forbidden_kernel_write"]["allow"] == ["^$"] and out["rules"]["forbidden_kernel_write"]["severity"] == "Error"
    assert out["rules"]["check_syntax"] is True and out["syntax"] == cfg["syntax"] and out["global"] == cfg["global"]
    assert all("url" not in d for d in out["dependencies"]) and [d["folder"] for d in out["dependencies"]] == ["/deps", "/lint_deps"]


def test_parse_abaplint_issues_keeps_only_the_edited_files():
    import json
    issues = [
        {"description": "bad statement", "key": "parser_error", "file": "//?/C:/w/p/src/utils/zcl_x.clas.abap", "start": {"row": 7, "col": 1}, "end": {"row": 7, "col": 9}, "severity": "Error"},
        {"description": "elsewhere", "key": "check_syntax", "file": "C:/w/p/test/src/other.clas.abap", "start": {"row": 1, "col": 1}, "end": {"row": 1, "col": 2}, "severity": "Error"},
        {"description": "kernel", "key": "forbidden_kernel_write", "file": "C:" + chr(92) + "w" + chr(92) + "p" + chr(92) + "SRC" + chr(92) + "Utils" + chr(92) + "ZCL_X.clas.abap", "start": {"row": 3, "col": 1}, "end": {"row": 3, "col": 2}, "severity": "Error"},
    ]
    out = t.parse_abaplint_issues(json.dumps(issues), ["src/utils/zcl_x.clas.abap"])
    assert len(out) == 2 and all("zcl_x" in o.lower() for o in out) and any("parser_error" in o and "7" in o for o in out) and any("forbidden_kernel_write" in o for o in out)
    assert t.parse_abaplint_issues("[]", ["src/utils/zcl_x.clas.abap"]) == []
    with pytest.raises(t.RunnerError):
        t.parse_abaplint_issues("not json", ["src/utils/zcl_x.clas.abap"])


def test_run_abaplint_refuses_bad_input_before_running(tmp_path):
    cfg = {"project_dir": str(tmp_path), "libs_dir": str(tmp_path), "tools_dir": str(tmp_path), "lint_deps_dir": str(tmp_path), "config": "c.json", "only_object": "ZCL_X"}
    poc = DATA_DIR / "kernel_poc.clas.abap"
    with pytest.raises(t.AbapTextRefused):
        t.run_abaplint(cfg, {"src/utils/zcl_x.clas.abap": poc})
    clean = tmp_path / "c.abap"
    clean.write_text(CLEAN)
    with pytest.raises(t.RunnerError):
        t.run_abaplint(cfg, {"node_modules/x.abap": clean})


def test_parse_abaplint_issues_ignores_log_lines_around_the_json():
    import json
    issue = {"description": "bad", "key": "parser_error", "file": "C:/w/p/src/utils/zcl_x.clas.abap", "start": {"row": 9, "col": 1}, "end": {"row": 9, "col": 2}, "severity": "Error"}
    mixed = "noise before" + chr(10) + json.dumps([issue]) + chr(10) + "abaplint 2.120.100" + chr(10) + "Using config: abaplint.sap.json" + chr(10)
    assert len(t.parse_abaplint_issues(mixed, ["src/utils/zcl_x.clas.abap"])) == 1
    assert t.parse_abaplint_issues("[]" + chr(10) + "Using config: x" + chr(10), ["src/utils/zcl_x.clas.abap"]) == []
    with pytest.raises(t.RunnerError):
        t.parse_abaplint_issues("abaplint 2.120.100" + chr(10) + "no json here" + chr(10), ["src/utils/zcl_x.clas.abap"])
