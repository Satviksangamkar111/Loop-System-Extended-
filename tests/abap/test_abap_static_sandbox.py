"""Frozen acceptance tests for scripts/source/abap_static_sandbox.py (do not edit)."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import abap_static_sandbox as s

TEST = """from pathlib import Path

def test_marker_is_ok():
    assert Path("abap_work/x.clas.abap").read_text() == "OK"
"""
SLOW = """import time

def test_slow():
    time.sleep(30)
"""


def make_root(tmp_path, body="OK", test=TEST):
    (tmp_path / "abap_work").mkdir()
    (tmp_path / "abap_work/x.clas.abap").write_text(body)
    (tmp_path / "tests/acceptance").mkdir(parents=True)
    (tmp_path / "tests/acceptance/t_acc.py").write_text(test)
    return tmp_path


def box(**kw):
    return s.AbapStaticSandbox(editable=["abap_work/x.clas.abap"], include=["abap_work", "tests"], **kw)


def test_selftest_ok_and_rejects_non_abap_editable():
    assert box().selftest() == []
    bad = s.AbapStaticSandbox(editable=["abap_work/x.clas.abap", "scripts/evil.py"], include=["abap_work"])
    assert bad.selftest() and "evil.py" in " ".join(bad.selftest())


def test_run_green_and_junit(tmp_path):
    root = make_root(tmp_path)
    r = box().run(root, ["tests/acceptance/t_acc.py"])
    assert r.returncode == 0 and r.timed_out is False and r.junit
    cases = ET.fromstring(r.junit).iter("testcase")
    assert [c.get("name") for c in cases] == ["test_marker_is_ok"]


def test_overlay_changes_the_result_and_never_touches_root(tmp_path):
    root = make_root(tmp_path)
    wrong = tmp_path / "wrong.abap"
    wrong.write_text("WRONG")
    r = box().run(root, ["tests/acceptance/t_acc.py"], overlay={"abap_work/x.clas.abap": wrong})
    assert r.returncode != 0 and "failure" in r.junit
    assert (root / "abap_work/x.clas.abap").read_text() == "OK"


def test_run_refuses_when_editable_is_not_abap(tmp_path):
    root = make_root(tmp_path)
    r = s.AbapStaticSandbox(editable=["abap_work/x.py"], include=["abap_work", "tests"]).run(root, ["tests/acceptance/t_acc.py"])
    assert r.returncode != 0 and r.junit is None


def test_timeout(tmp_path):
    root = make_root(tmp_path, test=SLOW)
    r = box().run(root, ["tests/acceptance/t_acc.py"], timeout_s=2)
    assert r.timed_out is True and r.returncode != 0


def test_selftest_hardening():
    for bad in ([], ["../x.abap"], ["/abs/x.abap"], ["a/x.py:s.abap"], ["abap_work/CON.abap"], ["C:/x.abap"]):
        assert s.AbapStaticSandbox(editable=bad, include=["abap_work"]).selftest(), bad


def test_overlay_only_for_editable_abap_inside_work(tmp_path):
    root = make_root(tmp_path)
    evil = tmp_path / "evil"
    evil.write_text("x")
    for key in ("tests/acceptance/t_acc.py", "../escape.abap", "abap_work/other.abap"):
        r = box().run(root, ["tests/acceptance/t_acc.py"], overlay={key: evil})
        assert r.returncode != 0 and r.junit is None, key
    assert not (tmp_path.parent / "escape.abap").exists()


def test_include_cannot_leave_root(tmp_path):
    root = make_root(tmp_path)
    r = s.AbapStaticSandbox(editable=["abap_work/x.clas.abap"], include=["abap_work", "tests", ".."]).run(root, ["tests/acceptance/t_acc.py"])
    assert r.returncode != 0 and r.junit is None


def test_non_ascii_output_does_not_crash(tmp_path):
    body = "def test_u():\n    print(chr(8364) * 3)\n    assert False\n"
    r = box().run(make_root(tmp_path, test=body), ["tests/acceptance/t_acc.py"])
    assert r.returncode != 0 and r.junit


def test_include_dot_empty_and_drive_names_are_refused(tmp_path):
    root = make_root(tmp_path)
    for bad in (".", "", "C:foo"):
        r = s.AbapStaticSandbox(editable=["abap_work/x.clas.abap"], include=["abap_work", "tests", bad]).run(root, ["tests/acceptance/t_acc.py"])
        assert r.returncode != 0 and r.junit is None, repr(bad)


import subprocess
import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions")
def test_windows_junction_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.abap").write_text("SECRET")
    root = tmp_path / "root"
    root.mkdir()
    make_root(root)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "abap_work" / "jct"), str(outside)], check=True, capture_output=True)
    body = "from pathlib import Path" + chr(10) + "def test_no_junction_target():" + chr(10) + "    assert not Path(" + chr(34) + "abap_work/jct/secret.abap" + chr(34) + ").exists()" + chr(10)
    (root / "tests/acceptance/t_acc.py").write_text(body)
    r = box().run(root, ["tests/acceptance/t_acc.py"])
    assert r.returncode == 0, r.output
