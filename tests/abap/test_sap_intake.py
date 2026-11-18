"""Tests for scripts/source/sap_intake.py with a fake GitHub and a fake sandbox (no network, no node)."""
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import sap_intake as si  # noqa: E402

REPO, PR, BASE, MERGE = "o/open-abap-core", 7, "b" * 40, "c" * 40
PROD = "src/x/cl_thing.clas.abap"
TEST = "src/x/cl_thing.clas.testclasses.abap"

BASE_PROD = """CLASS cl_thing DEFINITION PUBLIC.
  PUBLIC SECTION.
    CLASS-METHODS add IMPORTING a TYPE i RETURNING VALUE(r) TYPE i.
    CLASS-METHODS sub IMPORTING a TYPE i RETURNING VALUE(r) TYPE i.
ENDCLASS.
CLASS cl_thing IMPLEMENTATION.
  METHOD add.
    r = a.
  ENDMETHOD.
  METHOD sub.
    r = a.
  ENDMETHOD.
ENDCLASS.
"""
FIXED_PROD = BASE_PROD.replace("    r = a.\n  ENDMETHOD.\n  METHOD sub", "    r = a + 1001.\n    r = r + 1002.\n    r = r + 1002.\n  ENDMETHOD.\n  METHOD sub")
BASE_TEST = """CLASS ltcl DEFINITION FINAL FOR TESTING RISK LEVEL HARMLESS DURATION SHORT.
  PRIVATE SECTION.
    METHODS old FOR TESTING.
ENDCLASS.
CLASS ltcl IMPLEMENTATION.
  METHOD old.
  ENDMETHOD.
ENDCLASS.
"""
FIXED_TEST = BASE_TEST.replace("METHODS old FOR TESTING.", "METHODS old FOR TESTING.\n    METHODS: n1 FOR TESTING,\n      n2 FOR TESTING,\n      n3 FOR TESTING.")
PATCH = "@@ -7,3 +7,5 @@ CLASS cl_thing IMPLEMENTATION.\n   METHOD add.\n-    r = a.\n+    r = a + 1001.\n+    r = r + 1002.\n+    r = r + 1002.\n   ENDMETHOD.\n"


class Net:
    """Fake GitHub: url substring -> payload."""

    def __init__(self, **over):
        self.files = [
            {"filename": PROD, "status": "modified", "patch": PATCH},
            {"filename": TEST, "status": "modified", "patch": "@@"},
            {"filename": "README.md", "status": "modified"},
        ]
        self.pr = {"merged": True, "merge_commit_sha": MERGE, "body": "Fixes #5 and more"}
        self.issue = {"body": "adding does nothing"}
        self.raw = {(BASE, PROD): BASE_PROD, (MERGE, PROD): FIXED_PROD, (BASE, TEST): BASE_TEST, (MERGE, TEST): FIXED_TEST}
        self.__dict__.update(over)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith(f"/pulls/{PR}"):
            return json.dumps(self.pr)
        if "/pulls/" in url and "/files" in url:
            return json.dumps(self.files)
        if f"/commits/{MERGE}" in url:
            return json.dumps({"parents": [{"sha": BASE}]})
        if "/issues/" in url:
            return json.dumps(self.issue)
        if "raw.githubusercontent.com" in url:
            _, _, rest = url.partition(f"{REPO}/")
            sha, _, path = rest.partition("/")
            if (sha, path) in self.raw:
                return self.raw[(sha, path)]
        raise si.NotFound(url)


def sandbox_ok(job):
    t = "LTCL->"
    if job["label"] == "base":
        return {t + "old": "PASS", t + "n1": "FAIL: x", t + "n2": "PASS", t + "n3": "FAIL: y"}
    return {t + m: "PASS" for m in ("old", "n1", "n2", "n3")}


def run(tmp_path, net=None, sandbox=sandbox_ok):
    return si.intake(REPO, PR, tmp_path / "out", fetch=net or Net(), sandbox=sandbox, private_root=tmp_path / "priv")


def test_admission_writes_manifest_ticket_tests_and_private_fix(tmp_path):
    m = run(tmp_path)
    assert m["id"] == "open_abap_core_7" and m["label"] == "BLIND" and m["ticket_source"] == "issue"
    assert m["base_sha"] == BASE and m["merge_sha"] == MERGE and m["production_file"] == PROD
    assert m["allowed_methods"] == ["add"]
    tf = m["test_files"][0]
    assert tf["new_methods"] == ["n1", "n2", "n3"] and tf["heldout_methods"] == ["n2"]
    assert m["gate"]["base_fails"] == ["LTCL->n1", "LTCL->n3"] and m["gate"]["fix_passes"]
    assert m["gate"]["heldout_fails_on_base"] is False  # n2 passes on the base
    d = tmp_path / "out" / "open_abap_core_7"
    assert json.loads((d / "manifest.json").read_text()) == m
    assert (d / "ticket.md").read_text() == "adding does nothing"
    assert (d / tf["stored"]).read_text() == FIXED_TEST
    assert not (d / "REJECTED.md").exists()
    assert (tmp_path / "priv" / "open_abap_core_7" / "fixed.abap").read_text() == FIXED_PROD
    assert si._sha(BASE_PROD) == m["original_sha256"]
    assert (tmp_path / "abap_work" / "open_abap_core_7" / "cl_thing.clas.abap").read_text() == BASE_PROD
    # nothing of the fix leaks into the repo-side folder
    assert "r = a + 1001" not in "".join(p.read_text() for p in d.rglob("*") if p.is_file())


def test_pr_body_is_semi_guided_when_no_issue(tmp_path):
    m = run(tmp_path, Net(pr={"merged": True, "merge_commit_sha": MERGE, "body": "Make add work"}))
    assert m["label"] == "SEMI-GUIDED" and m["ticket_source"] == "pr_body"
    assert (tmp_path / "out" / m["id"] / "ticket.md").read_text() == "Make add work"


def test_fingerprints_and_run_guard(tmp_path):
    run(tmp_path)
    fp = si.fixed_line_fingerprints("open_abap_core_7", tmp_path / "priv")
    assert "r = a + 1001." in fp and "r = r + 1002." in fp
    assert si.fixed_line_fingerprints("nope", tmp_path / "priv") == frozenset()
    prompt = "x\n  r = a + 1001.\n  r = r + 1002.\n  r = r + 1002.\n"
    assert si.prompt_has_fix_run("open_abap_core_7", prompt, private_root=tmp_path / "priv")
    assert not si.prompt_has_fix_run("open_abap_core_7", "r = a + 1001.\nfoo bar baz qux\nr = r + 1002.\nr = r + 1002.", private_root=tmp_path / "priv")


def rejected(tmp_path, net=None, sandbox=sandbox_ok, match=""):
    with pytest.raises(si.Rejected, match=match):
        run(tmp_path, net, sandbox)
    d = tmp_path / "out" / "open_abap_core_7"
    assert (d / "REJECTED.md").exists() and not (d / "manifest.json").exists()
    assert not (tmp_path / "priv").exists()  # nothing stored privately for a refused bench


def test_rejects_two_production_files(tmp_path):
    net = Net()
    net.files.append({"filename": "src/x/cl_other.clas.abap", "status": "modified", "patch": "@@"})
    rejected(tmp_path, net, match="exactly one")


def test_rejects_locals_file_fix(tmp_path):
    net = Net()
    net.files[0] = {"filename": "src/x/cl_thing.clas.locals_imp.abap", "status": "modified", "patch": "@@"}
    rejected(tmp_path, net, match="main class")


def test_rejects_test_outside_src_beside_class(tmp_path):
    net = Net()
    net.files[1] = {"filename": "test/x/cl_thing.clas.testclasses.abap", "status": "modified"}
    rejected(tmp_path, net, match="not beside")


def test_rejects_fewer_than_two_new_methods(tmp_path):
    net = Net()
    net.raw[(MERGE, TEST)] = BASE_TEST.replace("METHODS old FOR TESTING.", "METHODS old FOR TESTING.\n    METHODS n1 FOR TESTING.")
    rejected(tmp_path, net, match="fewer than two")


def test_rejects_kernel(tmp_path):
    net = Net()
    net.raw[(MERGE, PROD)] = FIXED_PROD + "\nWRITE '@KERNEL x'.\n"
    rejected(tmp_path, net, match="KERNEL")


def test_rejects_tests_calling_method_added_by_fix(tmp_path):
    net = Net()
    net.raw[(MERGE, PROD)] = FIXED_PROD.replace("ENDCLASS.\nCLASS", "CLASS-METHODS brand_new.\nENDCLASS.\nCLASS", 1)
    net.raw[(MERGE, TEST)] = FIXED_TEST + "\nDATA cut TYPE REF TO cl_thing.\ncut->brand_new( ).\n"
    rejected(tmp_path, net, match="do not exist before")


def test_rejects_when_no_new_test_fails_before(tmp_path):
    rejected(tmp_path, sandbox=lambda j: {"LTCL->old": "PASS", "LTCL->n1": "PASS", "LTCL->n2": "PASS", "LTCL->n3": "PASS"}, match="fails on the pre-fix")


def test_rejects_when_fix_has_failing_test(tmp_path):
    def sb(job):
        r = sandbox_ok(job)
        if job["label"] == "fix":
            r["LTCL->n2"] = "FAIL: z"
        return r
    rejected(tmp_path, sandbox=sb, match="do not pass on the upstream fix")


def test_rejects_when_base_does_not_transpile(tmp_path):
    def sb(job):
        raise si.SandboxError("syntax error")
    rejected(tmp_path, sandbox=sb, match="pre-fix code does not transpile")


def test_rejects_unmerged_pr(tmp_path):
    rejected(tmp_path, Net(pr={"merged": False, "body": "x"}), match="not merged")


def test_rate_limit_is_a_clear_error(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "rate", {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "123"}, None)
    monkeypatch.setattr(si.urllib.request, "urlopen", boom)
    with pytest.raises(si.NetworkError, match="rate limit"):
        si.default_fetch("https://api.github.com/x")


def test_requests_carry_no_credentials_or_local_data(monkeypatch):
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"ok"

    def fake(req, timeout=0):
        seen.update(req.header_items())
        return R()
    monkeypatch.setattr(si.urllib.request, "urlopen", fake)
    assert si.default_fetch("https://api.github.com/x") == "ok"
    assert set(seen) <= {"User-agent", "Accept"} and seen["User-agent"] == si.UA


def test_cli_exit_codes(monkeypatch, tmp_path):
    def rej(*a, **k):
        raise si.Rejected("because")
    monkeypatch.setattr(si, "intake", rej)
    assert si.main(["o/r", "1", "--out", str(tmp_path)]) == 3

    def net(*a, **k):
        raise si.NetworkError("down")
    monkeypatch.setattr(si, "intake", net)
    assert si.main(["o/r", "1", "--out", str(tmp_path)]) == 2
    monkeypatch.setattr(si, "intake", lambda *a, **k: {"id": "i", "label": "BLIND", "test_files": [{"new_methods": [], "heldout_methods": []}]})
    assert si.main(["o/r", "1", "--out", str(tmp_path)]) == 0


def test_ensure_project_extracts_zip_safely(tmp_path):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("r-abc/abap_transpile.json", "{}")
        z.writestr("r-abc/src/a.abap", "x")
        z.writestr("r-abc/../evil.txt", "no")
    cfg = si.ensure_project("o/r", "abc" * 13, tmp_path, download=lambda u: buf.getvalue())
    proj = Path(cfg["project_dir"])
    assert (proj / "src" / "a.abap").exists() and cfg["config"] == "abap_transpile.auto.json"
    assert not (tmp_path / "evil.txt").exists() and not (proj.parent / "evil.txt").exists()


def test_pin_config_maps_libs_local_and_refuses_missing(tmp_path):
    for n in ("open-abap-core", "open-abap-gui", "open-abap-seo"):
        (tmp_path / n).mkdir()
    cfg = {"libs": [{"url": "https://github.com/open-abap/open-abap-core"}, {"url": "https://github.com/open-abap/open-abap-gui"},
                    {"url": "https://github.com/abapGit/abapGit-web-classic"}],
           "input_filter": ["a"], "options": {"ignoreSyntaxCheck": False, "setup": {"filename": "../test/setup.mjs", "preFunction": "setup"}, "populateTables": {}}}
    out = si.pin_config(cfg, tmp_path)
    assert [l["folder"] for l in out["libs"]] == ["../libs/open-abap-core", "../libs/open-abap-gui", "../libs/open-abap-seo"]
    assert out["options"]["ignoreSyntaxCheck"] is True and out["options"]["extraSetup"] == "../test/setup.mjs"
    assert "setup" not in out["options"] and "populateTables" not in out["options"] and out["input_filter"] == ["a"]
    assert si.pin_config(cfg, tmp_path) == out and cfg["libs"][0].get("url")  # deterministic, input untouched
    with pytest.raises(si.SandboxError, match="not in"):
        si.pin_config({"libs": [{"url": "https://github.com/x/missing-lib"}]}, tmp_path)


def test_first_base_failing_method_is_acceptance_even_when_second(tmp_path):
    def sb(job):  # only the second new method fails on the base (the abapGit 7118 shape)
        r = {"LTCL->" + m: "PASS" for m in ("old", "n1", "n2", "n3")}
        if job["label"] == "base":
            r["LTCL->n2"] = "FAIL: x"
        return r
    m = run(tmp_path, sandbox=sb)
    assert m["test_files"][0]["heldout_methods"] == ["n1"] and m["gate"]["heldout_fails_on_base"] is False


def test_rejects_when_no_heldout_left(tmp_path):
    net = Net()
    net.raw[(MERGE, TEST)] = BASE_TEST.replace("METHODS old FOR TESTING.", "METHODS old FOR TESTING.\n    METHODS n1 FOR TESTING.")
    rejected(tmp_path, net, match="fewer than two")


# ---------------------------------------------------------------- commit mode

class CommitNet(Net):
    """Fake GitHub for commit mode without a local clone: commits API + issues + raw."""

    def __init__(self, message="Fix add. Closes #5", **over):
        super().__init__(**over)
        self.message = message

    def __call__(self, url):
        if url.endswith(f"/commits/{MERGE}"):
            self.calls.append(url)
            return json.dumps({"sha": MERGE, "parents": [{"sha": BASE}], "commit": {"message": self.message}, "files": self.files})
        if "/pulls/" in url:
            raise AssertionError("commit mode must not ask the PR API: " + url)
        return super().__call__(url)


def run_commit(tmp_path, net=None, sandbox=sandbox_ok):
    return si.intake_commit(REPO, MERGE, tmp_path / "out", fetch=net or CommitNet(), sandbox=sandbox,
                            private_root=tmp_path / "priv", mine_root=tmp_path / "nomine")


def test_commit_mode_admits_with_issue_body_as_blind_ticket(tmp_path):
    m = run_commit(tmp_path)
    assert m["id"] == "open_abap_core_cccccccc" and m["pr"] == 0 and m["commit"] == MERGE
    assert m["base_sha"] == BASE and m["label"] == "BLIND" and m["ticket_source"] == "issue"
    assert (tmp_path / "out" / m["id"] / "ticket.md").read_text() == "adding does nothing"
    tf = m["test_files"][0]
    assert tf["new_methods"] == ["n1", "n2", "n3"] and tf["heldout_methods"] == ["n2"]
    assert (tmp_path / "priv" / m["id"] / "fixed.abap").read_text() == FIXED_PROD


def test_commit_mode_falls_back_to_message_when_rate_limited_or_missing(tmp_path):
    class Limited(CommitNet):
        def __call__(self, url):
            if "/issues/" in url:
                raise si.NetworkError("GitHub public rate limit reached")
            return super().__call__(url)
    m = run_commit(tmp_path, Limited())
    assert m["label"] == "SEMI-GUIDED" and m["ticket_source"] == "pr_body"
    assert (tmp_path / "out" / m["id"] / "ticket.md").read_text() == "Fix add. Closes #5"
    n = CommitNet(message="Fix add", issue={})
    m = run_commit(tmp_path / "b", n)
    assert m["label"] == "SEMI-GUIDED" and not any("/issues/" in u for u in n.calls)  # no issue ref, no issue GET


def test_commit_mode_issue_word_reference_and_pull_request_is_not_a_ticket(tmp_path):
    m = run_commit(tmp_path, CommitNet(message="add is wrong, see issue #12"))
    assert m["label"] == "BLIND"
    m = run_commit(tmp_path / "b", CommitNet(message="Fix add (#9)\n\nfixes #5", issue={"pull_request": {}, "body": "x"}))
    assert m["label"] == "SEMI-GUIDED"


def test_commit_mode_rejection_names_the_commit_and_applies_the_gate(tmp_path):
    net = CommitNet()
    net.files.append({"filename": "src/x/cl_other.clas.abap", "status": "modified", "patch": "@@"})
    with pytest.raises(si.Rejected, match="2 production"):
        run_commit(tmp_path, net)
    d = tmp_path / "out" / "open_abap_core_cccccccc"
    assert "commit cccccccc" in (d / "REJECTED.md").read_text() and not (d / "manifest.json").exists()


def test_commit_mode_unknown_commit_is_a_network_error(tmp_path):
    class Gone(CommitNet):
        def __call__(self, url):
            raise si.NotFound(url)
    with pytest.raises(si.NetworkError, match="not found"):
        run_commit(tmp_path, Gone())
    with pytest.raises(ValueError):
        si.intake_commit(REPO, "zz", tmp_path / "out")


def test_commit_mode_reads_a_local_clone_and_asks_github_only_for_the_issue(tmp_path, monkeypatch):
    import subprocess

    def g(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=clone, check=True, capture_output=True)
    clone = tmp_path / "mine" / "open-abap-core"
    (clone / "src" / "x").mkdir(parents=True)
    g("init", "-q")
    (clone / PROD).write_bytes(BASE_PROD.encode())
    (clone / TEST).write_bytes(BASE_TEST.encode())
    g("add", ".")
    g("commit", "-qm", "base")
    (clone / PROD).write_bytes(FIXED_PROD.encode())
    (clone / TEST).write_bytes(FIXED_TEST.encode())
    g("commit", "-qam", "Fix add\n\nCloses #5")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    urls = []

    def spy(url):
        urls.append(url)
        if "/issues/" in url:
            return json.dumps({"body": "adding does nothing"})
        raise AssertionError("only the issue may go to GitHub: " + url)
    monkeypatch.setattr(si, "default_fetch", spy)       # no fetch injected -> local mode; the issue GET uses default_fetch
    m = si.intake_commit(REPO, sha[:10], tmp_path / "out", sandbox=sandbox_ok, private_root=tmp_path / "priv", mine_root=tmp_path / "mine")
    assert m["commit"] == sha and m["label"] == "BLIND" and m["allowed_methods"] == ["add"]
    assert len(urls) == 1 and "/issues/5" in urls[0]
    assert (tmp_path / "priv" / m["id"] / "fixed.abap").read_text() == FIXED_PROD


def test_cli_commit_form(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(si, "intake_commit", lambda repo, sha, out, **kw: seen.update(repo=repo, sha=sha) or
                        {"id": "x", "label": "BLIND", "test_files": [{"new_methods": ["a", "b"], "heldout_methods": ["b"]}]})
    assert si.main([f"{REPO}@abc1234", "--out", str(tmp_path)]) == 0 and seen == {"repo": REPO, "sha": "abc1234"}
    monkeypatch.setattr(si, "intake_commit", lambda *a, **k: (_ for _ in ()).throw(si.Rejected("no")))
    assert si.main([f"{REPO}@abc1234", "--out", str(tmp_path)]) == 3


def test_pin_config_input_filter_is_a_whitelist_so_the_class_under_test_is_added(tmp_path):
    cfg = {"input_filter": ["zcl_abapgit_a", "zif_"], "options": {}}
    out = si.pin_config(cfg, tmp_path, include=("src/objects/tabl/zcl_abapgit_object_tabl_compar.clas.abap",))
    assert out["input_filter"][-1] == r"zcl_abapgit_object_tabl_compar\."
    again = si.pin_config(cfg, tmp_path, include=("src/zcl_abapgit_a1.clas.abap",))  # already let through: untouched
    assert again["input_filter"] == ["zcl_abapgit_a", "zif_"]
    assert si.pin_config({"options": {}}, tmp_path, include=("src/x.clas.abap",)).get("input_filter") is None


def test_pin_config_db_gives_back_the_repo_sqlite_setup_only_when_asked(tmp_path):
    cfg = {"options": {"extraSetup": "../test/setup.mjs"}}
    assert si.pin_config(cfg, tmp_path)["options"]["extraSetup"] == "../test/setup.mjs"
    on = si.pin_config(cfg, tmp_path, db=True)["options"]
    assert on["setup"] == {"filename": "../test/setup.mjs", "preFunction": "setup"} and "extraSetup" not in on


def test_pin_config_clones_a_missing_public_library_through_the_injected_clone(tmp_path):
    seen = []
    def clone(url, dest):
        seen.append(url); dest.mkdir()
    out = si.pin_config({"libs": [{"url": "https://github.com/o/newlib"}]}, tmp_path, clone=clone)
    assert seen == ["https://github.com/o/newlib"] and out["libs"][0]["folder"] == "../libs/newlib"
    with pytest.raises(si.SandboxError):
        si._git_clone("https://example.com/o/x", tmp_path / "x")  # only public github.com repos


def test_jsonc_strips_comments_and_trailing_commas_but_not_strings():
    d = si._jsonc('{\n // c\n "a": "x // not a comment", /* b */ "b": [1, 2,],\n}')
    assert d == {"a": "x // not a comment", "b": [1, 2]}


def test_ensure_project_without_a_transpile_config_derives_one_from_abaplint(tmp_path):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("r-abc/abaplint.jsonc", '{ // x\n "global": {"files": ["/src/00/**/*.*", "/src/01/**/*.*", "/src/*.*"]}, }')
        z.writestr("r-abc/src/00/a.clas.abap", "x")
        z.writestr("r-abc/src/01/b.clas.abap", "x")
    libs = tmp_path / "libs"
    (libs / "open-abap-core").mkdir(parents=True)
    old = si.LIBS_DIR
    si.LIBS_DIR = libs
    try:
        cfg = si.ensure_project("o/r", "abc" * 13, tmp_path / "p", download=lambda u: buf.getvalue())
    finally:
        si.LIBS_DIR = old
    pinned = json.loads((Path(cfg["project_dir"]) / cfg["config"]).read_text(encoding="utf-8"))
    assert cfg["config"] == "abap_transpile.auto.json" and pinned["input_folder"] == ["src"]  # src/*.* swallows the sub-folders
    assert pinned["libs"] == [{"folder": "../libs/open-abap-core"}] and pinned["options"]["ignoreSyntaxCheck"] is True


def test_ensure_project_variant_config_sits_at_the_root_with_a_content_hash(tmp_path):
    import io, zipfile
    buf = io.BytesIO()
    cfg_in = {"input_folder": ["test", "src"], "input_filter": ["zcl_a"], "options": {"extraSetup": "../test/setup.mjs"}}
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("r-abc/test/abap_transpile.json", json.dumps(cfg_in))
    inc = ("src/zcl_b.clas.abap",)
    c_off = si.ensure_project("o/r", "abc" * 13, tmp_path, download=lambda u: buf.getvalue(), include=inc)
    c_db = si.ensure_project("o/r", "abc" * 13, tmp_path, download=lambda u: buf.getvalue(), include=inc, db=True)
    for c in (c_off, c_db):
        assert "/" not in c["config"] and c["config"].startswith("abap_transpile.auto.x")  # not in an input folder
    assert c_off["config"] != c_db["config"]
    assert si.ensure_project("o/r", "abc" * 13, tmp_path, download=lambda u: buf.getvalue())["config"] == "test/abap_transpile.auto.json"


def test_default_sandbox_retries_once_with_the_database_setup_and_reports_the_first_error(monkeypatch, tmp_path):
    import abap_transpile_run as t
    calls = []
    monkeypatch.setattr(si, "ensure_project", lambda repo, sha, root, include=(), db=False: {"config": "db.json" if db else "plain.json"})
    def run(cfg, edited, timeout_s=0, trusted=()):
        calls.append(cfg["config"])
        if cfg["config"] == "plain.json":
            raise t.RunnerError("first failure")
        return {"LTCL->a": "PASS"}
    monkeypatch.setattr(t, "run_abap_tests", run)
    sb = si.make_default_sandbox(tmp_path)
    job = {"repo": "o/r", "base_sha": "a", "production_file": "src/x.clas.abap", "production_text": "x", "test_files": {}, "only_object": "X"}
    assert sb(job) == {"LTCL->a": "PASS"} and sb.state["db"] is True and calls == ["plain.json", "db.json"]
    calls.clear()
    assert sb(job) == {"LTCL->a": "PASS"} and calls == ["db.json"]  # stays on
    monkeypatch.setattr(t, "run_abap_tests", lambda cfg, *a, **k: (_ for _ in ()).throw(t.RunnerError("first failure" if cfg["config"] == "plain.json" else "second")))
    sb2 = si.make_default_sandbox(tmp_path)
    with pytest.raises(si.SandboxError, match="first failure"):
        sb2(job)
    monkeypatch.setattr(si, "ensure_project", lambda repo, sha, root, include=(), db=False: {"config": "same.json"})
    sb3 = si.make_default_sandbox(tmp_path)
    monkeypatch.setattr(t, "run_abap_tests", lambda cfg, *a, **k: (_ for _ in ()).throw(t.RunnerError("boom")))
    with pytest.raises(si.SandboxError, match="boom"):  # no database variant exists: no retry
        sb3(job)


def test_normalise_config_bridges_old_repo_keys(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "deps").mkdir()
    (tmp_path / "src" / "zcl_x.clas.testclasses.abap").write_text(
        "CLASS ltcl_a DEFINITION FOR TESTING.\n  PRIVATE SECTION.\n    METHODS: one FOR TESTING,\n      two FOR TESTING.\nENDCLASS.\n"
        "CLASS ltcl_b DEFINITION FOR TESTING.\n  PRIVATE SECTION.\n    METHODS three FOR TESTING.\nENDCLASS.\n", encoding="utf-8")
    raw = {"input_folder": "downport", "lib": "https://github.com/open-abap/open-abap",
           "options": {"skip": [{"object": "ZCL_X", "class": "ltcl_a"}, {"object": "ZCL_X", "class": "ltcl_b", "method": "three"}]}}
    out = si.normalise_config(tmp_path, raw)
    assert out["libs"] == [{"url": "https://github.com/open-abap/open-abap"}] and "lib" not in out
    assert out["input_folder"] == ["src", "deps"] and out["exclude_filter"] == [r"\.prog\."]
    assert [(e["class"], e["method"]) for e in out["options"]["skip"]] == [("ltcl_a", "one"), ("ltcl_a", "two"), ("ltcl_b", "three")]
    assert raw["input_folder"] == "downport"  # input untouched
    same = {"input_folder": ["src"], "options": {}}
    assert si.normalise_config(tmp_path, same) == same


def test_pin_config_adds_gui_and_seo_libs_next_to_core(tmp_path):
    for n in ("open-abap-core", "open-abap-gui", "open-abap-seo"):
        (tmp_path / n).mkdir()
    out = si.pin_config({"libs": [{"url": "https://github.com/open-abap/open-abap-core"}]}, tmp_path)
    assert [l["folder"] for l in out["libs"]] == ["../libs/open-abap-core", "../libs/open-abap-gui", "../libs/open-abap-seo"]
