"""Tests for scripts/source/sap_mine.py: log parsing, the candidate filter, ordering and the real git path (a throw-away repo)."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import sap_mine as sm  # noqa: E402

P, T = "src/x/cl_thing.clas.abap", "src/x/cl_thing.clas.testclasses.abap"
BASE_TEST = "CLASS l DEFINITION FOR TESTING.\n  PRIVATE SECTION.\n    METHODS old FOR TESTING.\nENDCLASS.\n"
NEW_TEST = BASE_TEST.replace("METHODS old FOR TESTING.", "METHODS old FOR TESTING.\n    METHODS: a FOR TESTING,\n      b FOR TESTING.")


def test_classify():
    assert sm.classify([("M", P), ("M", T), ("M", "README.md")]) == (P, T)
    assert sm.classify([("M", P), ("A", T)]) == (P, T)
    assert sm.classify([("M", P)]) is None                                            # no tests
    assert sm.classify([("M", P), ("M", T), ("M", "src/x/cl_o.clas.abap")]) is None   # two production files
    assert sm.classify([("M", P), ("M", "src/x/cl_o.clas.testclasses.abap")]) is None  # not the sibling
    assert sm.classify([("A", P), ("M", T)]) is None                                  # production file is new
    assert sm.classify([("M", "src/x/cl_thing.clas.locals_imp.abap"), ("M", T)]) is None
    assert sm.classify([("M", "test/cl_thing.clas.abap"), ("M", "test/cl_thing.clas.testclasses.abap")]) is None


def test_fix_message_and_issue_ref():
    for ok in ("Fix date parsing", "bug in add", "wrong result", "incorrect offset", "error on empty", "issue #12", "closes #4", "Regression in x"):
        assert sm.looks_like_fix(ok), ok
    assert not sm.looks_like_fix("Add feature, refactor, rename")
    assert sm.issue_ref("Fix x\n\nCloses #42") == "#42"
    assert sm.issue_ref("see issue o/r#7") == "o/r#7"
    assert sm.issue_ref("Fix x (#1234)") == ""                                         # a PR suffix is not an issue ref


def test_parse_log():
    text = "\x01aaa\x1fbbb\x1f2026-01-02T00:00:00+00:00\x1fFix it\n\nbody\x1e\n\nM\tsrc/a.abap\nA\tb.txt\n\x01ccc\x1fddd eee\x1f2026-01-01T00:00:00+00:00\x1fx\x1e\n"
    c = sm.parse_log(text)
    assert c[0]["sha"] == "aaa" and c[0]["parents"] == ["bbb"] and c[0]["files"] == [("M", "src/a.abap"), ("A", "b.txt")]
    assert c[0]["message"].startswith("Fix it") and c[1]["parents"] == ["ddd", "eee"] and c[1]["files"] == []


def fake_git(commits, blobs):
    """commits: [(sha, parent, date, message, files)]; blobs {(sha, path): text}."""
    def run(cwd, *args, check=True):
        if args[0] == "log":
            return "".join(f"\x01{s}\x1f{p}\x1f{d}\x1f{m}\x1e\n\n" + "".join(f"{st}\t{pa}\n" for st, pa in f) for s, p, d, m, f in commits)
        if args[0] == "show":
            sha, _, path = args[1].partition(":")
            return blobs.get((sha, path), "")
        raise AssertionError(args)
    return run


def test_mine_repo_filters_and_funnel():
    new_prod = "CLASS c.\nENDCLASS.\n" * 3
    commits = [
        ("c1", "p1", "2026-05-01T00:00:00+00:00", "Fix add (#10)\n\ncloses #5", [("M", P), ("M", T)]),
        ("c2", "p2", "2026-04-01T00:00:00+00:00", "Fix one test only", [("M", P), ("M", T)]),
        ("c3", "p3", "2026-03-01T00:00:00+00:00", "Refactor", [("M", P), ("M", T)]),
        ("c4", "p4", "2026-02-01T00:00:00+00:00", "Fix kernel", [("M", P), ("M", T)]),
        ("c5", "p5 q5", "2026-01-01T00:00:00+00:00", "Fix merge", [("M", P), ("M", T)]),
    ]
    blobs = {("c1", T): NEW_TEST, ("p1", T): BASE_TEST, ("c1", P): new_prod, ("p1", P): "x",
             ("c2", T): BASE_TEST.replace("METHODS old FOR TESTING.", "METHODS old FOR TESTING.\n    METHODS one FOR TESTING."),("p2", T): BASE_TEST,
             ("c4", T): NEW_TEST, ("p4", T): BASE_TEST, ("c4", P): "METHOD x.\n  \"@KERNEL foo\nENDMETHOD.", ("p4", P): ""}
    st = {}
    out = sm.mine_repo("o/thing", "root", "2024-11-01", run=fake_git(commits, blobs), stats=st)
    assert [c["sha"] for c in out] == ["c1"]
    c = out[0]
    assert c["parent"] == "p1" and c["issue"] == "#5" and c["class"] == "cl_thing" and c["added_tests"] == 2
    assert c["message"] == "Fix add (#10)" and c["class_lines"] == new_prod.count("\n") + 1 and c["test_file"] == T
    assert st["commits"] == 5 and st["one_class_and_tests"] == 4 and st["fix_message"] == 3 and st["two_new_tests"] == 2 and st["kernel"] == 1


def test_outputs_newest_first_across_repos(tmp_path, monkeypatch):
    def fake_mine_repo(repo, root, since, run=None, stats=None):
        d = {"o/a": ["2026-02-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"], "o/b": ["2026-06-01T00:00:00+00:00"]}[repo]
        return [{"repo": repo, "sha": f"{repo[-1]}{i}", "parent": "p", "date": x, "message": "Fix | pipe", "issue": "", "class": "c",
                 "production_file": P, "test_file": T, "added_tests": 2, "class_lines": 9} for i, x in enumerate(d)]
    monkeypatch.setattr(sm, "mine_repo", fake_mine_repo)
    monkeypatch.setattr(sm, "ensure_clone", lambda repo, root, **kw: Path(root) / repo)
    cands, stats, since = sm.mine(["o/a", "o/b"], tmp_path, months=24, now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    assert [c["sha"] for c in cands] == ["b0", "a0", "a1"] and [c["rank"] for c in cands] == [1, 2, 3] and cands[0]["ref"] == "o/b@b0"
    assert since == "2024-11-16"
    sm.write_outputs(cands, stats, since, tmp_path)
    data = json.loads((tmp_path / "CANDIDATES_MINED.json").read_text())
    assert [c["ref"] for c in data["candidates"]] == ["o/b@b0", "o/a@a0", "o/a@a1"]
    md = (tmp_path / "CANDIDATES_MINED.md").read_text()
    assert "| 1 | o/b |" in md and "Fix / pipe" in md


def test_real_git_end_to_end(tmp_path):
    repo = tmp_path / "thing"
    (repo / "src" / "x").mkdir(parents=True)

    def g(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
    g("init", "-q")
    (repo / P).write_text("CLASS c.\nENDCLASS.\n")
    (repo / T).write_text(BASE_TEST)
    g("add", ".")
    g("commit", "-qm", "base")
    (repo / P).write_text("CLASS c.\n  \" fixed\nENDCLASS.\n")
    (repo / T).write_text(NEW_TEST)
    g("commit", "-qam", "Fix wrong result\n\nCloses #3")
    st = {}
    out = sm.mine_repo("o/thing", tmp_path, "2000-01-01", stats=st)
    assert len(out) == 1 and out[0]["issue"] == "#3" and out[0]["added_tests"] == 2 and out[0]["class_lines"] == 4
