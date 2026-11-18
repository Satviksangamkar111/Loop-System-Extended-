"""Frozen acceptance tests for scripts/source/git_sap_sync.py (do not edit)."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import pytest
import git_sap_sync as g

A = "line1\nline2\nline3\n"
B = "line1\nline2 fixed\nline3\n"
H1, H2, H3 = 'a' * 64, 'b' * 64, 'c' * 64


def test_sha256_text():
    assert g.sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_drift_check():
    g.check_drift("aa", "aa")
    with pytest.raises(g.DriftError):
        g.check_drift("aa", "bb")


def test_diff_applies_cleanly(tmp_path):
    d = g.make_unified_diff(A, B, "src/zcl_x.clas.abap")
    assert d.startswith("--- a/src/zcl_x.clas.abap\n+++ b/src/zcl_x.clas.abap\n") and d.endswith("\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/zcl_x.clas.abap").write_text(A, newline="\n")
    (tmp_path / "p.patch").write_text(d, newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "apply", "--check", "p.patch"], cwd=tmp_path, check=True)


def test_diff_empty_when_equal():
    assert g.make_unified_diff(A, A, "x") == ""


def _m(**kw):
    base = dict(repo="o/r", commit="c" * 40, file_path="src/a.clas.abap", public_original_sha256=H1, sap_baseline_active_sha256=H1,
                projected_window_sha256=H3, candidate_sha256=H2, restored_baseline_sha256=H1, diff="d")
    base.update(kw)
    return g.GitSapSyncManifest(**base)


def test_manifest_json_sorted_and_roundtrip():
    j = _m().to_json()
    assert list(json.loads(j)) == sorted(json.loads(j))
    assert json.loads(j)["commit"] == "c" * 40


def test_manifest_validate():
    _m().validate()
    with pytest.raises(g.DriftError):
        _m(sap_baseline_active_sha256=H2).validate()
    with pytest.raises(g.DriftError):
        _m(restored_baseline_sha256=H2).validate()


def _apply_check(tmp_path, a, b):
    d = g.make_unified_diff(a, b, "f.abap")
    (tmp_path / "f.abap").write_bytes(a.encode())
    (tmp_path / "p.patch").write_bytes(d.encode())
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "apply", "--check", "p.patch"], cwd=tmp_path, check=True)
    return d


NL, CR, FF, BS = chr(10), chr(13), chr(12), chr(92)


def test_diff_splits_only_on_newline(tmp_path):
    _apply_check(tmp_path, "a" + FF + "b" + NL + "c" + NL, "a" + FF + "b" + NL + "d" + NL)


def test_diff_no_trailing_newline_marker(tmp_path):
    d = _apply_check(tmp_path, "x" + NL + "y", "x" + NL + "z")
    assert BS + " No newline at end of file" in d


def test_diff_crlf_content_lines(tmp_path):
    crlf = CR + NL
    _apply_check(tmp_path, "a" + crlf + "b" + crlf, "a" + crlf + "c" + crlf)


def test_validate_rejects_malformed_or_empty_hashes():
    with pytest.raises(g.DriftError):
        _m(public_original_sha256="", sap_baseline_active_sha256="", restored_baseline_sha256="").validate()
    with pytest.raises(g.DriftError):
        _m(candidate_sha256="nothex").validate()


def test_validate_rejects_changed_candidate_with_empty_diff():
    with pytest.raises(g.DriftError):
        _m(diff="").validate()
    _m(candidate_sha256=H1, diff="").validate()
