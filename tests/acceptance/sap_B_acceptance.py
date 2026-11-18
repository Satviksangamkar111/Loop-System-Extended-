"""Locked acceptance tests for benchmark problem B (abapGit PR 7036): real ABAP unit tests run through the abaplint transpiler, confined (see abap_transpile_run)."""
import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import abap_transpile_run as t  # noqa: E402

CFG = json.loads((ROOT / "docs/sap/bench/B/runner.json").read_text(encoding="utf-8"))
TARGET = ROOT / "abap_work/abapgit_B/zcl_abapgit_progress.clas.abap"
ORIGINAL = ROOT / "tests/controls/sap_B_original.abap"
REL_CLASS = "src/ui/progress/zcl_abapgit_progress.clas.abap"
REL_TESTS = "src/ui/progress/zcl_abapgit_progress.clas.testclasses.abap"
# Our own unit tests (the upstream PR added none), hidden from the writers, locked here as base64.
HIDDEN_TESTS_B64 = (
    "Q0xBU1MgemNsX2FiYXBnaXRfcHJvZ3Jlc3MgREVGSU5JVElPTiBMT0NBTCBGUklFTkRTIGx0Y2xfY2FsY19wY3QuDQoNCkNMQVNTIGx0"
    "Y2xfY2FsY19wY3QgREVGSU5JVElPTiBGSU5BTCBGT1IgVEVTVElORw0KICBEVVJBVElPTiBTSE9SVA0KICBSSVNLIExFVkVMIEhBUk1M"
    "RVNTLg0KDQogIFBSSVZBVEUgU0VDVElPTi4NCiAgICBEQVRBIG12X2FjdCBUWVBFIGkuDQoNCiAgICBNRVRIT0RTOg0KICAgICAgemVy"
    "b190b3RhbF9jdXJyZW50X29uZSBGT1IgVEVTVElORyBSQUlTSU5HIGN4X3N0YXRpY19jaGVjaywNCiAgICAgIHplcm9fdG90YWxfY3Vy"
    "cmVudF96ZXJvX25vX2R1bXAgRk9SIFRFU1RJTkcgUkFJU0lORyBjeF9zdGF0aWNfY2hlY2ssDQogICAgICB6ZXJvX3RvdGFsX2N1cnJl"
    "bnRfbGFyZ2UgRk9SIFRFU1RJTkcgUkFJU0lORyBjeF9zdGF0aWNfY2hlY2ssDQogICAgICBoYWxmX2lzXzUwIEZPUiBURVNUSU5HIFJB"
    "SVNJTkcgY3hfc3RhdGljX2NoZWNrLA0KICAgICAgb25lX29mX3RocmVlX2lzXzMzIEZPUiBURVNUSU5HIFJBSVNJTkcgY3hfc3RhdGlj"
    "X2NoZWNrLA0KICAgICAgdHdvX29mX3RocmVlX2lzXzY3IEZPUiBURVNUSU5HIFJBSVNJTkcgY3hfc3RhdGljX2NoZWNrLA0KICAgICAg"
    "ZnVsbF9pc185OSBGT1IgVEVTVElORyBSQUlTSU5HIGN4X3N0YXRpY19jaGVjaywNCiAgICAgIHplcm9fY3VycmVudF9pc18xIEZPUiBU"
    "RVNUSU5HIFJBSVNJTkcgY3hfc3RhdGljX2NoZWNrLA0KICAgICAgYWJvdmVfdG90YWxfdW5jaGFuZ2VkIEZPUiBURVNUSU5HIFJBSVNJ"
    "TkcgY3hfc3RhdGljX2NoZWNrLA0KICAgICAgbmV3X3RvdGFsX2FmdGVyX3plcm8gRk9SIFRFU1RJTkcgUkFJU0lORyBjeF9zdGF0aWNf"
    "Y2hlY2ssDQogICAgICBjYWxjDQogICAgICAgIElNUE9SVElORw0KICAgICAgICAgIGl2X3RvdGFsICAgVFlQRSBpDQogICAgICAgICAg"
    "aXZfY3VycmVudCBUWVBFIGkuDQoNCkVORENMQVNTLg0KDQoNCkNMQVNTIGx0Y2xfY2FsY19wY3QgSU1QTEVNRU5UQVRJT04uDQoNCiAg"
    "TUVUSE9EIGNhbGMuDQoNCiAgICBEQVRBIGxpX3Byb2dyZXNzIFRZUEUgUkVGIFRPIHppZl9hYmFwZ2l0X3Byb2dyZXNzLg0KICAgIERB"
    "VEEgbG9fcHJvZ3Jlc3MgVFlQRSBSRUYgVE8gemNsX2FiYXBnaXRfcHJvZ3Jlc3MuDQoNCiAgICBsaV9wcm9ncmVzcyA9IHpjbF9hYmFw"
    "Z2l0X3Byb2dyZXNzPT5nZXRfaW5zdGFuY2UoIGl2X3RvdGFsICkuDQogICAgbG9fcHJvZ3Jlc3MgPz0gbGlfcHJvZ3Jlc3MuDQogICAg"
    "bXZfYWN0ID0gbG9fcHJvZ3Jlc3MtPmNhbGNfcGN0KCBpdl9jdXJyZW50ID0gaXZfY3VycmVudCApLg0KDQogIEVORE1FVEhPRC4NCg0K"
    "ICBNRVRIT0QgemVyb190b3RhbF9jdXJyZW50X29uZS4NCg0KICAgIGNhbGMoIGl2X3RvdGFsID0gMCBpdl9jdXJyZW50ID0gMSApLg0K"
    "ICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoIGFjdCA9IG12X2FjdCBleHAgPSAwICkuDQoNCiAgRU5ETUVUSE9E"
    "Lg0KDQogIE1FVEhPRCB6ZXJvX3RvdGFsX2N1cnJlbnRfemVyb19ub19kdW1wLg0KDQogICAgIiAwIG9mIDAgZG9lcyBub3QgcmFpc2Ug"
    "dG9kYXkgKHRoZSBkaXZpc2lvbiAwIC8gMCBpcyBkZWZpbmVkIGFzIDAsIHNvIHRoZSAwLT4xIHJ1bGUgYXBwbGllcyk7IG9ubHkgIm5v"
    "IGR1bXAsIHNhbmUgdmFsdWUiIGlzIGFzc2VydGVkDQogICAgY2FsYyggaXZfdG90YWwgPSAwIGl2X2N1cnJlbnQgPSAwICkuDQogICAg"
    "SUYgbXZfYWN0IDw+IDAgQU5EIG12X2FjdCA8PiAxLg0KICAgICAgY2xfYWJhcF91bml0X2Fzc2VydD0+ZmFpbCggKS4NCiAgICBFTkRJ"
    "Ri4NCg0KICBFTkRNRVRIT0QuDQoNCiAgTUVUSE9EIHplcm9fdG90YWxfY3VycmVudF9sYXJnZS4NCg0KICAgIGNhbGMoIGl2X3RvdGFs"
    "ID0gMCBpdl9jdXJyZW50ID0gNSApLg0KICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoIGFjdCA9IG12X2FjdCBl"
    "eHAgPSAwICkuDQoNCiAgRU5ETUVUSE9ELg0KDQogIE1FVEhPRCBoYWxmX2lzXzUwLg0KDQogICAgY2FsYyggaXZfdG90YWwgPSAxMDAg"
    "aXZfY3VycmVudCA9IDUwICkuDQogICAgY2xfYWJhcF91bml0X2Fzc2VydD0+YXNzZXJ0X2VxdWFscyggYWN0ID0gbXZfYWN0IGV4cCA9"
    "IDUwICkuDQoNCiAgRU5ETUVUSE9ELg0KDQogIE1FVEhPRCBvbmVfb2ZfdGhyZWVfaXNfMzMuDQoNCiAgICBjYWxjKCBpdl90b3RhbCA9"
    "IDMgaXZfY3VycmVudCA9IDEgKS4NCiAgICBjbF9hYmFwX3VuaXRfYXNzZXJ0PT5hc3NlcnRfZXF1YWxzKCBhY3QgPSBtdl9hY3QgZXhw"
    "ID0gMzMgKS4NCg0KICBFTkRNRVRIT0QuDQoNCiAgTUVUSE9EIHR3b19vZl90aHJlZV9pc182Ny4NCg0KICAgIGNhbGMoIGl2X3RvdGFs"
    "ID0gMyBpdl9jdXJyZW50ID0gMiApLg0KICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoIGFjdCA9IG12X2FjdCBl"
    "eHAgPSA2NyApLg0KDQogIEVORE1FVEhPRC4NCg0KICBNRVRIT0QgZnVsbF9pc185OS4NCg0KICAgIGNhbGMoIGl2X3RvdGFsID0gMTAw"
    "IGl2X2N1cnJlbnQgPSAxMDAgKS4NCiAgICBjbF9hYmFwX3VuaXRfYXNzZXJ0PT5hc3NlcnRfZXF1YWxzKCBhY3QgPSBtdl9hY3QgZXhw"
    "ID0gOTkgKS4NCiAgICBjYWxjKCBpdl90b3RhbCA9IDMgaXZfY3VycmVudCA9IDMgKS4NCiAgICBjbF9hYmFwX3VuaXRfYXNzZXJ0PT5h"
    "c3NlcnRfZXF1YWxzKCBhY3QgPSBtdl9hY3QgZXhwID0gOTkgKS4NCg0KICBFTkRNRVRIT0QuDQoNCiAgTUVUSE9EIHplcm9fY3VycmVu"
    "dF9pc18xLg0KDQogICAgY2FsYyggaXZfdG90YWwgPSAxMDAgaXZfY3VycmVudCA9IDAgKS4NCiAgICBjbF9hYmFwX3VuaXRfYXNzZXJ0"
    "PT5hc3NlcnRfZXF1YWxzKCBhY3QgPSBtdl9hY3QgZXhwID0gMSApLg0KICAgIGNhbGMoIGl2X3RvdGFsID0gMTAwMCBpdl9jdXJyZW50"
    "ID0gMSApLg0KICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9PmFzc2VydF9lcXVhbHMoIGFjdCA9IG12X2FjdCBleHAgPSAxICkuDQoNCiAg"
    "RU5ETUVUSE9ELg0KDQogIE1FVEhPRCBhYm92ZV90b3RhbF91bmNoYW5nZWQuDQoNCiAgICBjYWxjKCBpdl90b3RhbCA9IDEwMCBpdl9j"
    "dXJyZW50ID0gMTUwICkuDQogICAgY2xfYWJhcF91bml0X2Fzc2VydD0+YXNzZXJ0X2VxdWFscyggYWN0ID0gbXZfYWN0IGV4cCA9IDE1"
    "MCApLg0KDQogIEVORE1FVEhPRC4NCg0KICBNRVRIT0QgbmV3X3RvdGFsX2FmdGVyX3plcm8uDQoNCiAgICBjYWxjKCBpdl90b3RhbCA9"
    "IDAgaXZfY3VycmVudCA9IDEgKS4NCiAgICBjbF9hYmFwX3VuaXRfYXNzZXJ0PT5hc3NlcnRfZXF1YWxzKCBhY3QgPSBtdl9hY3QgZXhw"
    "ID0gMCApLg0KICAgIGNhbGMoIGl2X3RvdGFsID0gMTAgaXZfY3VycmVudCA9IDUgKS4NCiAgICBjbF9hYmFwX3VuaXRfYXNzZXJ0PT5h"
    "c3NlcnRfZXF1YWxzKCBhY3QgPSBtdl9hY3QgZXhwID0gNTAgKS4NCg0KICBFTkRNRVRIT0QuDQoNCkVORENMQVNTLg0K"
)


def _refuse_new_risky_text():
    """The original class already contains CALL FUNCTION (progress bar), which the static check refuses. So only the lines the writer ADDED (compared to the original, as a multiset) are checked; a writer-added CALL FUNCTION, @KERNEL, etc. is still refused. The class is then passed as trusted."""
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
            hidden = Path(tmp) / "hidden.clas.testclasses.abap"
            hidden.write_bytes(base64.b64decode(HIDDEN_TESTS_B64))
            try:
                _refuse_new_risky_text()
                _CACHE["r"] = t.run_abap_tests(CFG, {REL_CLASS: TARGET, REL_TESTS: hidden}, timeout_s=240, trusted=(REL_TESTS, REL_CLASS))
            except (t.AbapTextRefused, t.RunnerError) as exc:     # a failing check is an assertion failure with the reason in the message (the loop requires controls to fail by assertion)
                _CACHE["err"] = f"the ABAP could not be run: {type(exc).__name__}: {exc}"
    if "err" in _CACHE:
        raise AssertionError(_CACHE["err"])
    return _CACHE["r"]


def _passes(name):
    assert results().get("ltcl_calc_pct->" + name) == "PASS", results()


def test_zero_total_current_one_is_zero():
    _passes("zero_total_current_one")


def test_zero_total_current_zero_does_not_dump():
    _passes("zero_total_current_zero_no_dump")


def test_zero_total_current_large_is_zero():
    _passes("zero_total_current_large")


def test_half_is_50():
    _passes("half_is_50")


def test_one_of_three_is_33():
    _passes("one_of_three_is_33")


def test_two_of_three_is_67():
    _passes("two_of_three_is_67")


def test_full_is_99():
    _passes("full_is_99")


def test_zero_current_is_1():
    _passes("zero_current_is_1")


def test_above_total_unchanged():
    _passes("above_total_unchanged")


def test_new_total_after_zero():
    _passes("new_total_after_zero")


def _outside_calc_pct(path):
    text = path.read_bytes().decode("utf-8").replace(chr(13) + chr(10), chr(10))
    start = text.index("METHOD calc_pct.")
    end = text.index("ENDMETHOD.", start)
    return [line.rstrip() for line in (text[:start] + text[end:]).split(chr(10))]


def test_nothing_outside_calc_pct_changed():
    assert _outside_calc_pct(TARGET) == _outside_calc_pct(ORIGINAL)


def test_no_abaplint_issues_in_the_edited_file():
    """abaplint with the project's own config (ABAP release of the project) plus the kernel-write rule: syntax errors and raw JavaScript are caught here."""
    try:
        issues = (_refuse_new_risky_text(), t.run_abaplint(CFG, {REL_CLASS: TARGET}, timeout_s=240, trusted=(REL_CLASS,)))[1]
    except (t.AbapTextRefused, t.RunnerError) as exc:
        raise AssertionError(f"abaplint could not be run: {type(exc).__name__}: {exc}") from None
    assert issues == [], issues
