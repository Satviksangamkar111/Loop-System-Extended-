"""Locked acceptance tests for job sap-6505 (abapGit issue 6505). Static: they read ABAP text, nothing is executed."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import abap_expr as e  # noqa: E402

TARGET = ROOT / "abap_work" / "abapgit_6505" / "zcl_abapgit_sap_package.clas.abap"
ORIGINAL = ROOT / "tests" / "controls" / "sap_6505_original.abap"
METHOD = "are_changes_recorded_in_tr_req"
STATEMENT = re.compile(r"rv_are_changes_rec_in_tr_req\s*=\s*boolc\((?:[^.]|\.(?!\s))*?\)\s*\.", re.S | re.I)


def source(path):
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def rule():
    return e.branch_rule(source(TARGET), METHOD, 1)


def test_dollar_and_t_packages_are_not_recorded():
    for package in ("$TMP", "$ZFOO", "TFOO", "T1"):
        assert e.eval_condition(rule(), package) is False, package


def test_customer_packages_are_still_recorded():
    for package in ("ZFOO", "YBAR", "/NS/X", "A1"):
        assert e.eval_condition(rule(), package) is True, package


def test_nothing_else_in_the_file_changed():
    def blanked(text):
        found = STATEMENT.findall(text)
        assert len(found) == 1, "exactly one boolc statement of rv_are_changes_rec_in_tr_req is expected"
        return [line.rstrip() for line in STATEMENT.sub("<RULE>", text).split("\n")]
    assert blanked(source(TARGET)) == blanked(source(ORIGINAL))
