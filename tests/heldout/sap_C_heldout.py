"""Held-out cases for benchmark C (abap2xlsx PR 838, SHIFT_FORMULA).
Derived from docs/sap/bench/C/SPEC.md only (never from the upstream tests or implementation).
The ABAP unit tests are base64 here, so the plaintext stays out of docs/ (the loop may read docs/).
Run after a job by scripts/source/sap_heldout.py; never in the loop's view.
"""
BENCH = "C"
RUNNER = "docs/sap/bench/C/runner.json"
LOCAL_CLASS = "lcl_heldout_shift"
REL_CLASS = "src/zcl_excel_common.clas.abap"
REL_TESTS = "src/zcl_excel_common.clas.testclasses.abap"
# (method name, one-line probe). The probe describes the case, not its test text.
CASES = [
    ('c01_digit_sheet_name', 'sheet name ending in digits, moved by columns and rows'),
    ('c02_quoted_sheet_with_spaces', 'quoted sheet name with digits and spaces, moved left'),
    ('c03_quoted_sheet_like_cell', 'quoted sheet name shaped like a cell, the range after it moves'),
    ('c04_name_letters_underscore_digit', 'defined name with letters, an underscore and a digit is left alone'),
    ('c05_spaces_in_function_args', 'spaces around function arguments kept, rows moved down'),
    ('c06_nested_functions_mixed', 'nested functions, absolute column, rows up and columns right'),
    ('c07_digit_sheet_rows_up', 'sheet name ending in digits, rows moved up'),
    ('c08_zero_shift_unchanged', 'zero shift returns the formula unchanged'),
    ('c09_cell_text_inside_quotes', 'cell-like text inside double quotes is left alone'),
    ('c10_digit_sheet_absolute_col_range', 'range with an absolute column on a sheet name ending in digits'),
    ('c11_move_off_sheet_gives_ref_error', 'reference moved off the sheet gives the reference error'),
]
HELDOUT_TESTS_B64 = (
    "Q0xBU1MgbGNsX2hlbGRvdXRfc2hpZnQgREVGSU5JVElPTiBGSU5BTCBGT1IgVEVTVElORwogIERVUkFUSU9OIFNIT1JUCiAgUklT"
    "SyBMRVZFTCBIQVJNTEVTUy4KCiAgUFJJVkFURSBTRUNUSU9OLgogICAgTUVUSE9EUzoKICAgICAgaF9jaGVjawogICAgICAgIElN"
    "UE9SVElORwogICAgICAgICAgaXZfZm9ybXVsYSAgVFlQRSBzdHJpbmcKICAgICAgICAgIGl2X2NvbHMgICAgIFRZUEUgaQogICAg"
    "ICAgICAgaXZfcm93cyAgICAgVFlQRSBpCiAgICAgICAgICBpdl9leHBlY3RlZCBUWVBFIHN0cmluZwogICAgICAgIFJBSVNJTkcK"
    "ICAgICAgICAgIHpjeF9leGNlbCwKCiAgICAgIGMwMV9kaWdpdF9zaGVldF9uYW1lIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2V4"
    "Y2VsLAogICAgICBjMDJfcXVvdGVkX3NoZWV0X3dpdGhfc3BhY2VzIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2V4Y2VsLAogICAg"
    "ICBjMDNfcXVvdGVkX3NoZWV0X2xpa2VfY2VsbCBGT1IgVEVTVElORyBSQUlTSU5HIHpjeF9leGNlbCwKICAgICAgYzA0X25hbWVf"
    "bGV0dGVyc191bmRlcnNjb3JlX2RpZ2l0IEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2V4Y2VsLAogICAgICBjMDVfc3BhY2VzX2lu"
    "X2Z1bmN0aW9uX2FyZ3MgRk9SIFRFU1RJTkcgUkFJU0lORyB6Y3hfZXhjZWwsCiAgICAgIGMwNl9uZXN0ZWRfZnVuY3Rpb25zX21p"
    "eGVkIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4X2V4Y2VsLAogICAgICBjMDdfZGlnaXRfc2hlZXRfcm93c191cCBGT1IgVEVTVElO"
    "RyBSQUlTSU5HIHpjeF9leGNlbCwKICAgICAgYzA4X3plcm9fc2hpZnRfdW5jaGFuZ2VkIEZPUiBURVNUSU5HIFJBSVNJTkcgemN4"
    "X2V4Y2VsLAogICAgICBjMDlfY2VsbF90ZXh0X2luc2lkZV9xdW90ZXMgRk9SIFRFU1RJTkcgUkFJU0lORyB6Y3hfZXhjZWwsCiAg"
    "ICAgIGMxMF9kaWdpdF9zaGVldF9hYnNvbHV0ZV9jb2xfcmFuZ2UgRk9SIFRFU1RJTkcgUkFJU0lORyB6Y3hfZXhjZWwsCiAgICAg"
    "IGMxMV9tb3ZlX29mZl9zaGVldF9naXZlc19yZWZfZXJyb3IgRk9SIFRFU1RJTkcgUkFJU0lORyB6Y3hfZXhjZWwuCgpFTkRDTEFT"
    "Uy4KCgpDTEFTUyBsY2xfaGVsZG91dF9zaGlmdCBJTVBMRU1FTlRBVElPTi4KCiAgTUVUSE9EIGhfY2hlY2suCgogICAgREFUQSBs"
    "dl9hY3R1YWwgVFlQRSBzdHJpbmcuCgogICAgbHZfYWN0dWFsID0gemNsX2V4Y2VsX2NvbW1vbj0+c2hpZnRfZm9ybXVsYSgKICAg"
    "ICAgaXZfcmVmZXJlbmNlX2Zvcm11bGEgPSBpdl9mb3JtdWxhCiAgICAgIGl2X3NoaWZ0X2NvbHMgICAgICAgID0gaXZfY29scwog"
    "ICAgICBpdl9zaGlmdF9yb3dzICAgICAgICA9IGl2X3Jvd3MgKS4KCiAgICBjbF9hYmFwX3VuaXRfYXNzZXJ0PT5hc3NlcnRfZXF1"
    "YWxzKAogICAgICBleHAgPSBpdl9leHBlY3RlZAogICAgICBhY3QgPSBsdl9hY3R1YWwgKS4KCiAgRU5ETUVUSE9ELgoKCiAgTUVU"
    "SE9EIGMwMV9kaWdpdF9zaGVldF9uYW1lLgoKICAgIGhfY2hlY2soIGl2X2Zvcm11bGEgPSBgUmVwb3J0OSFCMmAgaXZfY29scyA9"
    "IDIgaXZfcm93cyA9IDMgaXZfZXhwZWN0ZWQgPSBgUmVwb3J0OSFENWAgKS4KCiAgRU5ETUVUSE9ELgoKCiAgTUVUSE9EIGMwMl9x"
    "dW90ZWRfc2hlZXRfd2l0aF9zcGFjZXMuCgogICAgaF9jaGVjayggaXZfZm9ybXVsYSA9IGAnUGxhbiAyIEInIUUxMGAgaXZfY29s"
    "cyA9IC0xIGl2X3Jvd3MgPSAwIGl2X2V4cGVjdGVkID0gYCdQbGFuIDIgQichRDEwYCApLgoKICBFTkRNRVRIT0QuCgoKICBNRVRI"
    "T0QgYzAzX3F1b3RlZF9zaGVldF9saWtlX2NlbGwuCgogICAgaF9jaGVjayggaXZfZm9ybXVsYSA9IGAnQzUnIUExOkIyYCBpdl9j"
    "b2xzID0gMSBpdl9yb3dzID0gMSBpdl9leHBlY3RlZCA9IGAnQzUnIUIyOkMzYCApLgoKICBFTkRNRVRIT0QuCgoKICBNRVRIT0Qg"
    "YzA0X25hbWVfbGV0dGVyc191bmRlcnNjb3JlX2RpZ2l0LgoKICAgIGhfY2hlY2soIGl2X2Zvcm11bGEgPSBgTmV0X1YyKkIzYCBp"
    "dl9jb2xzID0gMSBpdl9yb3dzID0gMSBpdl9leHBlY3RlZCA9IGBOZXRfVjIqQzRgICkuCgogIEVORE1FVEhPRC4KCgogIE1FVEhP"
    "RCBjMDVfc3BhY2VzX2luX2Z1bmN0aW9uX2FyZ3MuCgogICAgaF9jaGVjayggaXZfZm9ybXVsYSA9IGBTVU0oIEExICwgQjEgKWAg"
    "aXZfY29scyA9IDAgaXZfcm93cyA9IDIgaXZfZXhwZWN0ZWQgPSBgU1VNKCBBMyAsIEIzIClgICkuCgogIEVORE1FVEhPRC4KCgog"
    "IE1FVEhPRCBjMDZfbmVzdGVkX2Z1bmN0aW9uc19taXhlZC4KCiAgICBoX2NoZWNrKCBpdl9mb3JtdWxhID0gYElGKElTTlVNQkVS"
    "KEEyKSxNQVgoQjM6QzQpKyAkRDUsIngiKWAKICAgICAgICAgICAgIGl2X2NvbHMgPSAyCiAgICAgICAgICAgICBpdl9yb3dzID0g"
    "LTEKICAgICAgICAgICAgIGl2X2V4cGVjdGVkID0gYElGKElTTlVNQkVSKEMxKSxNQVgoRDI6RTMpKyAkRDQsIngiKWAgKS4KCiAg"
    "RU5ETUVUSE9ELgoKCiAgTUVUSE9EIGMwN19kaWdpdF9zaGVldF9yb3dzX3VwLgoKICAgIGhfY2hlY2soIGl2X2Zvcm11bGEgPSBg"
    "U2hlZXQxIUExMCoyYCBpdl9jb2xzID0gMCBpdl9yb3dzID0gLTMgaXZfZXhwZWN0ZWQgPSBgU2hlZXQxIUE3KjJgICkuCgogIEVO"
    "RE1FVEhPRC4KCgogIE1FVEhPRCBjMDhfemVyb19zaGlmdF91bmNoYW5nZWQuCgogICAgaF9jaGVjayggaXZfZm9ybXVsYSA9IGAn"
    "TXkgc2hlZXQgMichQTEgJiAiIEIyICJgIGl2X2NvbHMgPSAwIGl2X3Jvd3MgPSAwIGl2X2V4cGVjdGVkID0gYCdNeSBzaGVldCAy"
    "JyFBMSAmICIgQjIgImAgKS4KCiAgRU5ETUVUSE9ELgoKCiAgTUVUSE9EIGMwOV9jZWxsX3RleHRfaW5zaWRlX3F1b3Rlcy4KCiAg"
    "ICBoX2NoZWNrKCBpdl9mb3JtdWxhID0gYCJzZWUgQzMgIiZBMWAgaXZfY29scyA9IDEgaXZfcm93cyA9IDEgaXZfZXhwZWN0ZWQg"
    "PSBgInNlZSBDMyAiJkIyYCApLgoKICBFTkRNRVRIT0QuCgoKICBNRVRIT0QgYzEwX2RpZ2l0X3NoZWV0X2Fic29sdXRlX2NvbF9y"
    "YW5nZS4KCiAgICBoX2NoZWNrKCBpdl9mb3JtdWxhID0gYERhdGEyISRCNDpDNWAgaXZfY29scyA9IDEgaXZfcm93cyA9IDEgaXZf"
    "ZXhwZWN0ZWQgPSBgRGF0YTIhJEI1OkQ2YCApLgoKICBFTkRNRVRIT0QuCgoKICBNRVRIT0QgYzExX21vdmVfb2ZmX3NoZWV0X2dp"
    "dmVzX3JlZl9lcnJvci4KCiAgICBoX2NoZWNrKCBpdl9mb3JtdWxhID0gYEIxK0MyYCBpdl9jb2xzID0gLTIgaXZfcm93cyA9IDAg"
    "aXZfZXhwZWN0ZWQgPSBgI1JFRiErQTJgICkuCgogIEVORE1FVEhPRC4KCkVORENMQVNTLgo="
)
