"""Frozen acceptance tests for scripts/source/abap_expr.py (do not edit)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import pytest
import abap_expr as e

PKGS = {"$TMP": False, "TFOO": False, "ZFOO": True, "YBAR": True, "/NS/X": True}


@pytest.mark.parametrize("expr", [
    "mv_package(1) <> '$' AND mv_package(1) <> 'T'",
    "mv_package(1) NE '$' AND mv_package(1) NE 'T'",
    "NOT mv_package(1) CA '$T'",
    "mv_package(1) NA '$T'",
    "NOT ( mv_package(1) = '$' OR mv_package(1) = 'T' )",
    "NOT ( mv_package(1) EQ '$' OR mv_package(1) EQ 'T' )",
    "( mv_package(1) <> '$' ) AND ( mv_package(1) <> 'T' )",
])
def test_equivalent_forms(expr):
    assert {p: e.eval_condition(expr, p) for p in PKGS} == PKGS


def test_original_and_wrong_fixes():
    only_dollar = "mv_package(1) <> '$'"
    assert e.eval_condition(only_dollar, "TFOO") is True
    or_form = "mv_package(1) <> '$' OR mv_package(1) <> 'T'"        # always true: a classic wrong fix
    assert e.eval_condition(or_form, "$TMP") is True
    only_t = "mv_package(1) <> 'T'"
    assert e.eval_condition(only_t, "$TMP") is True


def test_keywords_are_case_insensitive_and_precedence():
    assert e.eval_condition("mv_package(1) = 'A' or mv_package(1) = 'B' and mv_package(1) = 'C'", "A") is True      # AND binds tighter than OR
    assert e.eval_condition("not mv_package(1) = 'A'", "B") is True


def test_unsupported_input_fails_closed():
    for bad in ["foo( 1 ) = 'a'", "mv_package(2) = 'a'", "mv_package(1) <> ", "mv_package(1) <> 'T' AND", "mv_package(1) CP 'T*'",
                "__import__('os')", "mv_package(1) <> 'T' )", ""]:
        with pytest.raises(e.ExprError):
            e.eval_condition(bad, "ZFOO")


SRC = """CLASS zcl_x IMPLEMENTATION.
  METHOD other.
    CASE sy-subrc.
      WHEN 1.
        rv_x = boolc( 1 = 1 ).
    ENDCASE.
  ENDMETHOD.
  METHOD zif_abapgit_sap_package~are_changes_recorded_in_tr_req.
    CASE sy-subrc.
      WHEN 0.
        rv_are_changes_rec_in_tr_req = li_package->wbo_korr_flag.
      WHEN 1.
        " For new packages, derive from package name
        rv_are_changes_rec_in_tr_req = boolc( mv_package(1) <> '$'
                                          AND mv_package(1) <> 'T' ).
      WHEN OTHERS.
        zcx_abapgit_exception=>raise_t100( ).
    ENDCASE.
  ENDMETHOD.
ENDCLASS.
"""


def test_branch_rule_extracts_condition_of_the_named_method_only():
    rule = e.branch_rule(SRC, "are_changes_recorded_in_tr_req", 1)
    assert e.eval_condition(rule, "TFOO") is False and e.eval_condition(rule, "ZFOO") is True


def test_branch_rule_errors():
    with pytest.raises(e.ExprError):
        e.branch_rule(SRC, "no_such_method", 1)
    with pytest.raises(e.ExprError):
        e.branch_rule(SRC, "are_changes_recorded_in_tr_req", 7)


def test_quote_escape_and_blank_padding():
    assert e.eval_condition("mv_package(1) = 'a'''", "a") in (True, False)          # valid literal a' (escaped quote), must not raise
    for bad in ("mv_package(1) CA '''''", "mv_package(1) = 'a''"):
        with pytest.raises(e.ExprError):
            e.eval_condition(bad, "T")
    assert e.eval_condition("mv_package(1) = ' '", "") is True                       # ABAP pads with blanks: an empty package is a blank
    assert e.eval_condition("mv_package(1) <> ' '", "") is False
