"""Frozen acceptance tests for scripts/source/abap_object_adapters.py (do not edit)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import pytest
import abap_object_adapters as m

SRC = """CLASS zcl_x DEFINITION PUBLIC.
  PUBLIC SECTION.
    METHODS create_style_sheet.
    METHODS create_xl_sheet.
  PROTECTED SECTION.
    DATA styles_mapping TYPE STANDARD TABLE OF ty_map WITH DEFAULT KEY.
  PRIVATE SECTION.
    DATA hashed_t TYPE HASHED TABLE OF ty_map WITH UNIQUE KEY guid.
    DATA counter TYPE i.
ENDCLASS.
CLASS zcl_x IMPLEMENTATION.
  METHOD create_style_sheet.
    APPEND ls TO styles_mapping.
    INSERT ls INTO TABLE hashed_t.
  ENDMETHOD.
  METHOD create_xl_sheet.
* READ TABLE styles_mapping INTO ls WITH KEY guid = lv.  (comment, ignored)
    READ TABLE styles_mapping INTO ls WITH KEY guid = lv.
    LOOP AT styles_mapping INTO ls WHERE guid = lv.
    ENDLOOP.
    DATA(x) = styles_mapping[ guid = lv ].
    CLEAR styles_mapping.
    counter = counter + 1.
  ENDMETHOD.
ENDCLASS.
"""


def test_registry_has_11_families_and_only_clas_patchable():
    assert set(m.ADAPTER_REGISTRY) == {"CLAS", "INTF", "PROG", "FUGR", "TABL", "DTEL", "DOMA", "DDLS", "DCLS", "BDEF", "SRVD"}
    assert m.ADAPTER_REGISTRY["CLAS"].uri_template == "/sap/bc/adt/oo/classes/{name}"
    assert m.ADAPTER_REGISTRY["CLAS"].lock_granularity == "CLASS_ROOT_AND_INCLUDES"
    assert [t for t, a in m.ADAPTER_REGISTRY.items() if a.patch_enabled] == ["CLAS"]


@pytest.mark.parametrize("t", ["INTF", "PROG", "FUGR", "TABL", "DDLS", "BDEF"])
def test_non_clas_fails_closed(t):
    with pytest.raises(m.UnsupportedAbapCapabilityError):
        m.get_adapter(t).require("patch")


def test_clas_patch_ok_and_unknown_type_fails_closed():
    m.get_adapter("clas").require("patch")
    with pytest.raises(m.UnsupportedAbapCapabilityError):
        m.get_adapter("XXXX")


def test_lifecycle_protected_standard():
    r = m.analyze_attribute_lifecycle(SRC, "STYLES_MAPPING")
    assert r["section"] == "PROTECTED" and r["subclass_accessible"] is True
    assert r["table_kind"] == "STANDARD"
    assert r["inserts"] == [("create_style_sheet", 13)]
    assert r["reads"] == [("create_xl_sheet", 18), ("create_xl_sheet", 19), ("create_xl_sheet", 21)]
    assert r["mutations"] == [("create_xl_sheet", 22)]
    assert r["consumers"] == ["create_style_sheet", "create_xl_sheet"]


def test_lifecycle_private_hashed_and_scalar():
    h = m.analyze_attribute_lifecycle(SRC, "hashed_t")
    assert h["section"] == "PRIVATE" and h["subclass_accessible"] is False and h["table_kind"] == "HASHED"
    assert h["inserts"] == [("create_style_sheet", 14)]
    c = m.analyze_attribute_lifecycle(SRC, "counter")
    assert c["table_kind"] == "SCALAR" and c["consumers"] == ["create_xl_sheet"]


def test_lifecycle_unknown_symbol_raises():
    with pytest.raises(KeyError):
        m.analyze_attribute_lifecycle(SRC, "nope")


SRC2 = """CLASS zcl_y DEFINITION DEFERRED.
CLASS zcl_y DEFINITION PUBLIC.
  PROTECTED SECTION.
    DATA:
      chained TYPE HASHED TABLE OF ty WITH UNIQUE KEY guid,
      other TYPE i.
    DATA table_cnt TYPE i.
    DATA multi
      TYPE SORTED TABLE OF ty WITH UNIQUE KEY guid.
ENDCLASS.
CLASS zcl_y IMPLEMENTATION.
  METHOD a.
    CALL METHOD lo->b.
    my_chained[ guid = 1 ].
    CLEAR chained-guid.
    chained[ guid = 1 ].
    table_cnt = 1.
  ENDMETHOD.
  METHOD b.
    DELETE TABLE chained FROM ls.
  ENDMETHOD.
ENDCLASS.
"""


def test_lifecycle_chained_and_multiline_declarations():
    assert m.analyze_attribute_lifecycle(SRC2, "chained")["table_kind"] == "HASHED"
    assert m.analyze_attribute_lifecycle(SRC2, "other")["table_kind"] == "SCALAR"
    assert m.analyze_attribute_lifecycle(SRC2, "multi")["table_kind"] == "SORTED"
    assert m.analyze_attribute_lifecycle(SRC2, "table_cnt")["table_kind"] == "SCALAR"


def test_lifecycle_no_false_sites_and_call_method_not_a_method():
    r = m.analyze_attribute_lifecycle(SRC2, "chained")
    assert r["reads"] == [("a", 16)]                 # chained[ ... ]; my_chained[ and chained-guid are not sites of chained
    assert r["mutations"] == [("b", 20)]
    assert r["consumers"] == ["a", "b"]


def test_require_patch_is_case_insensitive():
    with pytest.raises(m.UnsupportedAbapCapabilityError):
        m.get_adapter("INTF").require(" PATCH ")
