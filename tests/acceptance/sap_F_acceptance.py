"""Locked acceptance tests for benchmark problem F (abapGit PR 7118): the PR's own unit tests (testclasses file at the merge commit), run through the abaplint transpiler, confined (see abap_transpile_run)."""
import base64
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import abap_transpile_run as t  # noqa: E402

CFG = json.loads((ROOT / "docs/sap/bench/F/runner.json").read_text(encoding="utf-8"))
TARGET = ROOT / "abap_work/abapgit_F/zcl_abapgit_html.clas.abap"
ORIGINAL = ROOT / "tests/controls/sap_F_original.abap"
REL_CLASS = "src/ui/core/zcl_abapgit_html.clas.abap"
REL_TESTS = "src/ui/core/zcl_abapgit_html.clas.testclasses.abap"
# The upstream unit tests of PR 7118 (testclasses file at the merge commit), hidden from the writers, locked here as base64.
UPSTREAM_TESTS_B64 = (
    "Q0xBU1MgbGNsX2dvb2RfcmVuZGVyYWJsZSBERUZJTklUSU9OIEZJTkFMLgogIFBVQkxJQyBTRUNUSU9OLgogICAgSU5URVJGQUNFUyB6aWZf"
    "YWJhcGdpdF9ndWlfcmVuZGVyYWJsZS4KRU5EQ0xBU1MuCkNMQVNTIGxjbF9nb29kX3JlbmRlcmFibGUgSU1QTEVNRU5UQVRJT04uCiAgTUVU"
    "SE9EIHppZl9hYmFwZ2l0X2d1aV9yZW5kZXJhYmxlfnJlbmRlci4KICAgIHJpX2h0bWwgPSB6Y2xfYWJhcGdpdF9odG1sPT5jcmVhdGUoICdI"
    "ZWxsbycgKS4KICBFTkRNRVRIT0QuCkVORENMQVNTLgoKQ0xBU1MgbGNsX2JhZF9yZW5kZXJhYmxlIERFRklOSVRJT04gRklOQUwuCiAgUFVC"
    "TElDIFNFQ1RJT04uCiAgICBJTlRFUkZBQ0VTIHppZl9hYmFwZ2l0X2d1aV9yZW5kZXJhYmxlLgpFTkRDTEFTUy4KQ0xBU1MgbGNsX2JhZF9y"
    "ZW5kZXJhYmxlIElNUExFTUVOVEFUSU9OLgogIE1FVEhPRCB6aWZfYWJhcGdpdF9ndWlfcmVuZGVyYWJsZX5yZW5kZXIuCiAgICB6Y3hfYWJh"
    "cGdpdF9leGNlcHRpb249PnJhaXNlKCAnRmFpbCEnICkuCiAgRU5ETUVUSE9ELgpFTkRDTEFTUy4KCkNMQVNTIGx0Y2xfaHRtbCBERUZJTklU"
    "SU9OIEZPUiBURVNUSU5HIERVUkFUSU9OIFNIT1JUIFJJU0sgTEVWRUwgSEFSTUxFU1MuCgogIFBSSVZBVEUgU0VDVElPTi4KICAgIERBVEEg"
    "bW9faHRtbCBUWVBFIFJFRiBUTyB6aWZfYWJhcGdpdF9odG1sLgoKICAgIE1FVEhPRFM6CiAgICAgIHdyYXAgICAgRk9SIFRFU1RJTkcgUkFJ"
    "U0lORyB6Y3hfYWJhcGdpdF9leGNlcHRpb24sCiAgICAgIGFkZF9yZW5kZXJhYmxlIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRf"
    "ZXhjZXB0aW9uLAogICAgICB0ZCAgICAgIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLAogICAgICB0aCAgICAg"
    "IEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLAogICAgICB3cmFwX2lpIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4"
    "X2FiYXBnaXRfZXhjZXB0aW9uLAogICAgICBpbmRlbnQxIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLAogICAg"
    "ICBpbmRlbnQyIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLAogICAgICBpbmRlbnQzIEZPUiBURVNUSU5HIFJB"
    "SVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLAogICAgICBpbmRlbnQ0IEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0"
    "aW9uLAogICAgICBpbmRlbnQ1IEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLAogICAgICBpbmRlbnQ2IEZPUiBU"
    "RVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLAogICAgICBpbmRlbnQ3IEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBn"
    "aXRfZXhjZXB0aW9uLAogICAgICBzdHlsZTEgIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2FiYXBnaXRfZXhjZXB0aW9uLgoKICAgIE1FVEhP"
    "RFM6CiAgICAgIHNldHVwLgoKRU5EQ0xBU1MuCgoKQ0xBU1MgbHRjbF9odG1sIElNUExFTUVOVEFUSU9OLgoKICBNRVRIT0Qgc2V0dXAuCiAg"
    "ICBDUkVBVEUgT0JKRUNUIG1vX2h0bWwgVFlQRSB6Y2xfYWJhcGdpdF9odG1sLgogIEVORE1FVEhPRC4KCiAgTUVUSE9EIGluZGVudDEuCgog"
    "ICAgREFUQSBsdl9leHAgVFlQRSBzdHJpbmcuCgogICAgbW9faHRtbC0+YWRkKCAnPHRkPicgKS4KICAgIG1vX2h0bWwtPmFkZCggJ2hlbGxv"
    "IHdvcmxkJyApLgogICAgbW9faHRtbC0+YWRkKCAnPC90ZD4nICkuCgogICAgbHZfZXhwID0gJzx0ZD4nICYmIGNsX2FiYXBfY2hhcl91dGls"
    "aXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAgICAgICcgIGhlbGxvIHdvcmxkJyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5l"
    "ICYmCiAgICAgICAgICAgICAnPC90ZD4nLgoKICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9IG1v"
    "X2h0bWwtPnJlbmRlciggKQogICAgICBleHAgPSBsdl9leHAgKS4KCiAgRU5ETUVUSE9ELgoKICBNRVRIT0QgaW5kZW50Mi4KCiAgICBEQVRB"
    "IGx2X2V4cCBUWVBFIHN0cmluZy4KCiAgICBtb19odG1sLT5hZGQoICc8dGQ+JyApLgogICAgbW9faHRtbC0+YWRkKCAnPGlucHV0IG5hbWU9"
    "ImNvbW1lbnQiIHR5cGU9InRleHQiPicgKS4KICAgIG1vX2h0bWwtPmFkZCggJzwvdGQ+JyApLgoKICAgIGx2X2V4cCA9ICc8dGQ+JyAmJiBj"
    "bF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgICAgICAnICA8aW5wdXQgbmFtZT0iY29tbWVudCIgdHlwZT0idGV4"
    "dCI+JyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgICAgICAnPC90ZD4nLgoKICAgIGNsX2FiYXBfdW5p"
    "dF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9IG1vX2h0bWwtPnJlbmRlciggKQogICAgICBleHAgPSBsdl9leHAgKS4KCiAg"
    "RU5ETUVUSE9ELgoKICBNRVRIT0QgaW5kZW50My4KCiAgICBEQVRBIGx2X2V4cCBUWVBFIHN0cmluZy4KCiAgICBtb19odG1sLT5hZGQoICc8"
    "dGQ+JyApLgogICAgbW9faHRtbC0+YWRkKCAnPHRleHRhcmVhIG5hbWU9ImJvZHkiIHJvd3M9IjEwIiBjb2xzPSI3MiI+PC90ZXh0YXJlYT4n"
    "ICkuCiAgICBtb19odG1sLT5hZGQoICc8L3RkPicgKS4KCiAgICBsdl9leHAgPSAnPHRkPicgJiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+"
    "bmV3bGluZSAmJgogICAgICAgICAgICAgJyAgPHRleHRhcmVhIG5hbWU9ImJvZHkiIHJvd3M9IjEwIiBjb2xzPSI3MiI+PC90ZXh0YXJlYT4n"
    "ICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAgICAgICc8L3RkPicuCgogICAgY2xfYWJhcF91bml0X2Fz"
    "c2VydD0+YXNzZXJ0X2VxdWFscygKICAgICAgYWN0ID0gbW9faHRtbC0+cmVuZGVyKCApCiAgICAgIGV4cCA9IGx2X2V4cCApLgoKICBFTkRN"
    "RVRIT0QuCgogIE1FVEhPRCBpbmRlbnQ0LgoKICAgIERBVEEgbHZfZXhwIFRZUEUgc3RyaW5nLgoKICAgIG1vX2h0bWwtPmFkZCggJzx0ZD4n"
    "ICkuCiAgICBtb19odG1sLT5hZGQoICdmb288YnI+YmFyJyApLgogICAgbW9faHRtbC0+YWRkKCAnPC90ZD4nICkuCgogICAgbHZfZXhwID0g"
    "Jzx0ZD4nICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAgICAgICcgIGZvbzxicj5iYXInICYmIGNsX2Fi"
    "YXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAgICAgICc8L3RkPicuCgogICAgY2xfYWJhcF91bml0X2Fzc2VydD0+YXNz"
    "ZXJ0X2VxdWFscygKICAgICAgYWN0ID0gbW9faHRtbC0+cmVuZGVyKCApCiAgICAgIGV4cCA9IGx2X2V4cCApLgoKICBFTkRNRVRIT0QuCgog"
    "IE1FVEhPRCBpbmRlbnQ1LgoqIGRvbid0IGR1bXAgaWYgc29tZXRoaW5nIG1lc3NlcyB1cCBvciB0aGUgbmVzdGluZyBnZXRzIHRvbyB3aWRl"
    "CiAgICBETyAzMDAgVElNRVMuCiAgICAgIG1vX2h0bWwtPmFkZCggJzx0ZD4nICkuCiAgICBFTkRETy4KCiAgICBtb19odG1sLT5yZW5kZXIo"
    "ICkuCgogIEVORE1FVEhPRC4KCiAgTUVUSE9EIGluZGVudDYuCgogICAgIiBDb250ZW50IG9mIHRleHRhcmVhIG11c3Qgbm90IGJlIGluZGVu"
    "dGVkCiAgICBEQVRBIGx2X2V4cCBUWVBFIHN0cmluZy4KCiAgICBtb19odG1sLT5hZGQoICc8dGQ+JyApLgogICAgbW9faHRtbC0+YWRkKCAn"
    "PHRleHRhcmVhIG5hbWU9ImJvZHkiIHJvd3M9IjEwIiBjb2xzPSI3MiI+JyApLgogICAgbW9faHRtbC0+YWRkKCAnU29tZSBkZWZhdWx0JyAp"
    "LgogICAgbW9faHRtbC0+YWRkKCAnY29udGVudCcgKS4KICAgIG1vX2h0bWwtPmFkZCggJzwvdGV4dGFyZWE+JyApLgogICAgbW9faHRtbC0+"
    "YWRkKCAnPC90ZD4nICkuCgogICAgbHZfZXhwID0gJzx0ZD4nICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAg"
    "ICAgICAgICc8dGV4dGFyZWEgbmFtZT0iYm9keSIgcm93cz0iMTAiIGNvbHM9IjcyIj4nICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5l"
    "d2xpbmUgJiYKICAgICAgICAgICAgICdTb21lIGRlZmF1bHQnICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAg"
    "ICAgICAgICdjb250ZW50JyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgICAgICAnPC90ZXh0YXJlYT4n"
    "ICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAgICAgICc8L3RkPicuCgogICAgY2xfYWJhcF91bml0X2Fz"
    "c2VydD0+YXNzZXJ0X2VxdWFscygKICAgICAgYWN0ID0gbW9faHRtbC0+cmVuZGVyKCApCiAgICAgIGV4cCA9IGx2X2V4cCApLgoKICBFTkRN"
    "RVRIT0QuCgogIE1FVEhPRCBpbmRlbnQ3LgoKICAgICIgQ29udGVudCBvZiBwcmUgdGFnIG11c3Qgbm90IGJlIGluZGVudGVkCiAgICBEQVRB"
    "IGx2X2V4cCBUWVBFIHN0cmluZy4KCiAgICBtb19odG1sLT5hZGQoICc8dGQ+JyApLgogICAgbW9faHRtbC0+YWRkKCAnPHByZT4nICkuCiAg"
    "ICBtb19odG1sLT5hZGQoICdEbyBub3QgY2hhbmdlJyApLgogICAgbW9faHRtbC0+YWRkKCAnICB0aGUgaW5kZW50JyApLgogICAgbW9faHRt"
    "bC0+YWRkKCAnICAgIGhlcmUnICkuCiAgICBtb19odG1sLT5hZGQoICc8L3ByZT4nICkuCiAgICBtb19odG1sLT5hZGQoICc8L3RkPicgKS4K"
    "CiAgICBsdl9leHAgPSAnPHRkPicgJiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+bmV3bGluZSAmJgogICAgICAgICAgICAgJzxwcmU+JyAm"
    "JiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgICAgICAnRG8gbm90IGNoYW5nZScgJiYgY2xfYWJhcF9jaGFy"
    "X3V0aWxpdGllcz0+bmV3bGluZSAmJgogICAgICAgICAgICAgJyAgdGhlIGluZGVudCcgJiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+bmV3"
    "bGluZSAmJgogICAgICAgICAgICAgJyAgICBoZXJlJyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgICAg"
    "ICAnPC9wcmU+JyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgICAgICAnPC90ZD4nLgoKICAgIGNsX2Fi"
    "YXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9IG1vX2h0bWwtPnJlbmRlciggKQogICAgICBleHAgPSBsdl9leHAg"
    "KS4KCiAgRU5ETUVUSE9ELgoKCiAgTUVUSE9EIHN0eWxlMS4KCiAgICBEQVRBIGx2X2V4cCBUWVBFIHN0cmluZy4KCiAgICBtb19odG1sLT5h"
    "ZGQoICc8c3R5bGUgdHlwZT0idGV4dC9jc3MiPicgKS4KICAgIG1vX2h0bWwtPmFkZCggJy5jbGFzczEgeyBjb2xvcjogcmVkIH0nICkuCiAg"
    "ICBtb19odG1sLT5hZGQoICcuY2xhc3MyIHsnICkuCiAgICBtb19odG1sLT5hZGQoICdjb2xvcjogcmVkJyApLgogICAgbW9faHRtbC0+YWRk"
    "KCAnfScgKS4KICAgIG1vX2h0bWwtPmFkZCggJzwvc3R5bGU+JyApLgoKICAgIGx2X2V4cCA9ICc8c3R5bGUgdHlwZT0idGV4dC9jc3MiPicg"
    "JiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+bmV3bGluZSAmJgogICAgICAgICAgICAgJyAgLmNsYXNzMSB7IGNvbG9yOiByZWQgfScgJiYg"
    "Y2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+bmV3bGluZSAmJgogICAgICAgICAgICAgJyAgLmNsYXNzMiB7JyAmJiBjbF9hYmFwX2NoYXJfdXRp"
    "bGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgICAgICAnICAgIGNvbG9yOiByZWQnICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xp"
    "bmUgJiYKICAgICAgICAgICAgICcgIH0nICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAgICAgICc8L3N0"
    "eWxlPicuCgogICAgY2xfYWJhcF91bml0X2Fzc2VydD0+YXNzZXJ0X2VxdWFscygKICAgICAgYWN0ID0gbW9faHRtbC0+cmVuZGVyKCApCiAg"
    "ICAgIGV4cCA9IGx2X2V4cCApLgoKICBFTkRNRVRIT0QuCgogIE1FVEhPRCB0ZC4KCiAgICBtb19odG1sLT50ZCggJ0hlbGxvJyApLgogICAg"
    "bW9faHRtbC0+dGQoCiAgICAgIGl2X2Zvcm1hdF9zaW5nbGVfbGluZSA9IGFiYXBfZmFsc2UKICAgICAgaXZfY29udGVudCA9ICdIZWxsbycg"
    "KS4KICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9IG1vX2h0bWwtPnJlbmRlciggKQogICAgICBl"
    "eHAgPQogICAgICAgICc8dGQ+SGVsbG88L3RkPicgJiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+bmV3bGluZSAmJgogICAgICAgICc8dGQ+"
    "JyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYmCiAgICAgICAgJyAgSGVsbG8nICYmIGNsX2FiYXBfY2hhcl91dGlsaXRp"
    "ZXM9Pm5ld2xpbmUgJiYKICAgICAgICAnPC90ZD4nICkuCgogIEVORE1FVEhPRC4KCiAgTUVUSE9EIHRoLgoKICAgIG1vX2h0bWwtPnRoKCAn"
    "SGVsbG8nICkuCiAgICBtb19odG1sLT50aCgKICAgICAgaXZfZm9ybWF0X3NpbmdsZV9saW5lID0gYWJhcF9mYWxzZQogICAgICBpdl9jb250"
    "ZW50ID0gJ0hlbGxvJyApLgogICAgY2xfYWJhcF91bml0X2Fzc2VydD0+YXNzZXJ0X2VxdWFscygKICAgICAgYWN0ID0gbW9faHRtbC0+cmVu"
    "ZGVyKCApCiAgICAgIGV4cCA9CiAgICAgICAgJzx0aD5IZWxsbzwvdGg+JyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lICYm"
    "CiAgICAgICAgJzx0aD4nICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAnICBIZWxsbycgJiYgY2xfYWJh"
    "cF9jaGFyX3V0aWxpdGllcz0+bmV3bGluZSAmJgogICAgICAgICc8L3RoPicgKS4KCiAgRU5ETUVUSE9ELgoKICBNRVRIT0Qgd3JhcF9paS4K"
    "CiAgICBtb19odG1sLT53cmFwKAogICAgICBpdl90YWcgICAgID0gJ3RkJwogICAgICBpaV9jb250ZW50ID0gemNsX2FiYXBnaXRfaHRtbD0+"
    "Y3JlYXRlKCApLT5hZGQoICdIZWxsbycgKSApLgoKICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9"
    "IG1vX2h0bWwtPnJlbmRlciggKQogICAgICBleHAgPQogICAgICAgICc8dGQ+JyAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5l"
    "ICYmCiAgICAgICAgJyAgSGVsbG8nICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9Pm5ld2xpbmUgJiYKICAgICAgICAnPC90ZD4nICkuCgog"
    "IEVORE1FVEhPRC4KCiAgTUVUSE9EIHdyYXAuCgogICAgbW9faHRtbC0+d3JhcCggJ3RkJyApLgogICAgbW9faHRtbC0+d3JhcCgKICAgICAg"
    "aXZfdGFnICAgICA9ICd0ZCcKICAgICAgaXZfY29udGVudCA9ICdIZWxsbycgKS4KICAgIG1vX2h0bWwtPndyYXAoCiAgICAgIGl2X3RhZyAg"
    "ICAgPSAndGQnCiAgICAgIGl2X2NsYXNzICAgPSAnY2xhc3MnCiAgICAgIGl2X2hpbnQgICAgPSAnaGludCcKICAgICAgaXZfaWQgICAgICA9"
    "ICdpZCcKICAgICAgaXZfY29udGVudCA9ICdIZWxsbycgKS4KICAgIG1vX2h0bWwtPndyYXAoCiAgICAgIGl2X3RhZyAgICAgPSAndGQnCiAg"
    "ICAgIGl2X2NvbnRlbnQgPSAnSGVsbG8nCiAgICAgIGl2X2Zvcm1hdF9zaW5nbGVfbGluZSA9IGFiYXBfdHJ1ZSApLgogICAgbW9faHRtbC0+"
    "d3JhcCgKICAgICAgaXZfdGFnICAgICA9ICd0ZCcKICAgICAgaXZfY29udGVudCA9ICdIZWxsbycKICAgICAgaXNfZGF0YV9hdHRyID0gemNs"
    "X2FiYXBnaXRfaHRtbD0+cGFyc2VfZGF0YV9hdHRyKCAnaWQ9MTIzJyApCiAgICAgIGl2X2Zvcm1hdF9zaW5nbGVfbGluZSA9IGFiYXBfdHJ1"
    "ZSApLgoKICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9IG1vX2h0bWwtPnJlbmRlciggKQogICAg"
    "ICBleHAgPQogICAgICAgIHw8dGQ+PC90ZD5cbnwgJiYKICAgICAgICB8PHRkPlxufCAmJgogICAgICAgIHwgIEhlbGxvXG58ICYmCiAgICAg"
    "ICAgfDwvdGQ+XG58ICYmCiAgICAgICAgfDx0ZCBpZD0iaWQiIGNsYXNzPSJjbGFzcyIgdGl0bGU9ImhpbnQiPlxufCAmJgogICAgICAgIHwg"
    "IEhlbGxvXG58ICYmCiAgICAgICAgfDwvdGQ+XG58ICYmCiAgICAgICAgfDx0ZD5IZWxsbzwvdGQ+XG58ICYmCiAgICAgICAgfDx0ZCBkYXRh"
    "LWlkPSIxMjMiPkhlbGxvPC90ZD58ICkuCgogIEVORE1FVEhPRC4KCiAgTUVUSE9EIGFkZF9yZW5kZXJhYmxlLgoKICAgIERBVEEgbG9fZ29v"
    "ZCBUWVBFIFJFRiBUTyBsY2xfZ29vZF9yZW5kZXJhYmxlLgogICAgREFUQSBsb19iYWQgVFlQRSBSRUYgVE8gbGNsX2JhZF9yZW5kZXJhYmxl"
    "LgoKICAgIENSRUFURSBPQkpFQ1QgbG9fZ29vZC4KICAgIENSRUFURSBPQkpFQ1QgbG9fYmFkLgoKICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9"
    "PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9IHpjbF9hYmFwZ2l0X2h0bWw9PmNyZWF0ZSggbG9fZ29vZCApLT5yZW5kZXIoICkKICAgICAg"
    "ZXhwID0gJ0hlbGxvJyApLgoKICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9jaGFyX2NwKAogICAgICBhY3QgPSB6Y2xfYWJhcGdp"
    "dF9odG1sPT5jcmVhdGUoIGxvX2JhZCApLT5yZW5kZXIoICkKICAgICAgZXhwID0gJzxzcGFuKkZhaWwhKicgKS4KCiAgRU5ETUVUSE9ELgoK"
    "RU5EQ0xBU1MuCg=="
)
# Methods whose bodies the upstream fix does not change (byte-identical in the original and the upstream fix). Their bodies must stay identical. Every other method body (icon, indent_line, study_line, zif_abapgit_html~wrap and any method a writer adds) may change. The class DEFINITION is not compared (see README, limits).
UNCHANGED_METHODS = ('checkbox', 'class_constructor', 'set_debug_mode', 'create', 'parse_data_attr', 'zif_abapgit_html~a', 'zif_abapgit_html~add', 'zif_abapgit_html~add_a', 'zif_abapgit_html~add_checkbox', 'zif_abapgit_html~add_icon', 'zif_abapgit_html~div', 'zif_abapgit_html~icon', 'zif_abapgit_html~is_empty', 'zif_abapgit_html~render', 'zif_abapgit_html~set_title', 'zif_abapgit_html~td', 'zif_abapgit_html~th')
_METHOD_RE = re.compile(r"^  METHOD ([\w~]+)\.\n(.*?)^  ENDMETHOD\.\n", re.M | re.S)


def _refuse_new_risky_text():
    """The original class has no risky text, but the check is kept as in B and D: only the lines the writer ADDED (compared to the original, as a multiset) are checked. A writer-added CALL FUNCTION, @KERNEL, etc. is still refused."""
    orig = ORIGINAL.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10)).split(chr(10))
    added = []
    for line in TARGET.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10)).split(chr(10)):
        if line in orig:
            orig.remove(line)
        else:
            added.append(line)
    problems = t.check_abap_text(chr(10).join(added))
    if problems:
        raise t.AbapTextRefused("; ".join(problems))

_CACHE = {}


def results():
    """One transpile and run per pytest process; all tests below read this dict. A failed run is cached too (a broken edit would otherwise re-transpile once per test)."""
    if "r" not in _CACHE and "err" not in _CACHE:
        with tempfile.TemporaryDirectory() as tmp:
            hidden = Path(tmp) / "upstream.clas.testclasses.abap"
            hidden.write_bytes(base64.b64decode(UPSTREAM_TESTS_B64))
            try:
                _refuse_new_risky_text()
                _CACHE["r"] = t.run_abap_tests(CFG, {REL_CLASS: TARGET, REL_TESTS: hidden}, timeout_s=240, trusted=(REL_TESTS, REL_CLASS))
            except (t.AbapTextRefused, t.RunnerError) as exc:     # a failing check is an assertion failure with the reason in the message (the loop requires controls to fail by assertion)
                _CACHE["err"] = f"the ABAP could not be run: {type(exc).__name__}: {exc}"
    if "err" in _CACHE:
        raise AssertionError(_CACHE["err"])
    return _CACHE["r"]


def _passes(name):
    assert results().get("ltcl_html->" + name) == "PASS", results()


def test_wrap():
    _passes("wrap")


def test_add_renderable():
    _passes("add_renderable")


def test_td():
    _passes("td")


def test_th():
    _passes("th")


def test_wrap_ii():
    _passes("wrap_ii")


def test_indent1():
    _passes("indent1")


def test_indent2():
    _passes("indent2")


def test_indent3():
    _passes("indent3")


def test_indent4():
    _passes("indent4")


def test_indent5():
    _passes("indent5")


def test_indent6():
    _passes("indent6")


def test_indent7():
    _passes("indent7")


def test_style1():
    _passes("style1")


def _split_methods(path):
    """Return (skeleton lines, {method name: body}) for the implementation part of the class (after the DEFINITION's ENDCLASS.). Lower-cased: ABAP is case-insensitive (the upstream fix only changes the case of the class name in the IMPLEMENTATION line)."""
    text = path.read_bytes().decode("utf-8").replace(chr(13) + chr(10), chr(10))
    impl = text[text.index("ENDCLASS.") :]
    bodies = {m.group(1).lower(): m.group(2) for m in _METHOD_RE.finditer(impl)}
    skeleton = [line.rstrip().lower() for line in _METHOD_RE.sub("", impl).split(chr(10))]
    return skeleton, bodies


def test_nothing_outside_changed_methods_changed():
    """Everything outside the method bodies (including the methods' own order) is as in the original, and the methods the upstream fix does not change are byte-identical. Other methods and any new method may change."""
    new_skel, new_bodies = _split_methods(TARGET)
    old_skel, old_bodies = _split_methods(ORIGINAL)
    blank = lambda lines: [line for line in lines if line.strip()]  # the upstream fix moves set_debug_mode, so blank lines between methods may differ
    assert blank(new_skel) == blank(old_skel), "code outside the method bodies changed"
    for name in UNCHANGED_METHODS:
        assert new_bodies.get(name.lower()) == old_bodies.get(name.lower()), f"method {name} changed"


def test_no_abaplint_issues_in_the_edited_file():
    """abaplint with the project's own config (ABAP release of the project) plus the kernel-write rule: syntax errors and raw JavaScript are caught here."""
    try:
        issues = (_refuse_new_risky_text(), t.run_abaplint(CFG, {REL_CLASS: TARGET}, timeout_s=240, trusted=(REL_CLASS,)))[1]
    except (t.AbapTextRefused, t.RunnerError) as exc:
        raise AssertionError(f"abaplint could not be run: {type(exc).__name__}: {exc}") from None
    assert issues == [], issues
