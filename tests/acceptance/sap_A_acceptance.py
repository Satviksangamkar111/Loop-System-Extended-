"""Locked acceptance tests for benchmark problem A (abapGit PR 7546): real ABAP unit tests run through the abaplint transpiler, confined (see abap_transpile_run)."""
import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "source"))
import abap_transpile_run as t  # noqa: E402

CFG = json.loads((ROOT / "docs/sap/bench/A/runner.json").read_text(encoding="utf-8"))
TARGET = ROOT / "abap_work/abapgit_A/zcl_abapgit_utils.clas.abap"
ORIGINAL = ROOT / "tests/controls/sap_A_original.abap"
REL_CLASS = "src/utils/zcl_abapgit_utils.clas.abap"
REL_TESTS = "src/utils/zcl_abapgit_utils.clas.testclasses.abap"
# The project's own unit tests plus the test its fix commit added (hidden from the writers, locked here as base64).
HIDDEN_TESTS_B64 = (
    "Q0xBU1MgbHRjbF9pc19iaW5hcnkgREVGSU5JVElPTiBGSU5BTCBGT1IgVEVTVElORwogIERVUkFUSU9OIFNIT1JUCiAgUklTSyBM"
    "RVZFTCBIQVJNTEVTUy4KICBQVUJMSUMgU0VDVElPTi4KICAgIENMQVNTLU1FVEhPRFM6CiAgICAgIGNsYXNzX2NvbnN0cnVjdG9y"
    "LgoKICBQUklWQVRFIFNFQ1RJT04uCiAgICBEQVRBIG12X2dpdmVuX2ZpbGUgVFlQRSB4c3RyaW5nLgogICAgREFUQSBtdl9hY3Rf"
    "aXNfYmluYXJ5IFRZUEUgYWJhcF9ib29sLgogICAgQ0xBU1MtREFUQToKICAgICAgZ3ZfbmwgICAgVFlQRSBjIExFTkdUSCAxLAog"
    "ICAgICBndl9jcl9sZiBUWVBFIGMgTEVOR1RIIDIuCgogICAgTUVUSE9EUzoKICAgICAgY2RzX21ldGFkYXRhX2lzX3RleHQgRk9S"
    "IFRFU1RJTkcgUkFJU0lORyBjeF9zdGF0aWNfY2hlY2ssCiAgICAgIGNkc193aXRoX3VtbGF1dF9pc190ZXh0IEZPUiBURVNUSU5H"
    "IFJBSVNJTkcgY3hfc3RhdGljX2NoZWNrLAogICAgICBpbWFnZV9pc19iaW5hcnkgRk9SIFRFU1RJTkcgUkFJU0lORyBjeF9zdGF0"
    "aWNfY2hlY2ssCiAgICAgIHRleHRfaXNfbm90X2JpbmFyeSBGT1IgVEVTVElORyBSQUlTSU5HIGN4X3N0YXRpY19jaGVjaywKICAg"
    "ICAgY3JsZl9tdWx0aWxpbmVfdGV4dF9pc19ub3RfYmluYXJ5IEZPUiBURVNUSU5HIFJBSVNJTkcgY3hfc3RhdGljX2NoZWNrLAog"
    "ICAgICBsZl9vbmx5X3RleHRfaXNfbm90X2JpbmFyeSBGT1IgVEVTVElORyBSQUlTSU5HIGN4X3N0YXRpY19jaGVjaywKICAgICAg"
    "bWFueV9jb250cm9sX2NoYXJzX2lzX2JpbmFyeSBGT1IgVEVTVElORyBSQUlTSU5HIGN4X3N0YXRpY19jaGVjaywKICAgICAgc29t"
    "ZV9jb250cm9sX2NoYXJzX2lzX2JpbmFyeSBGT1IgVEVTVElORyBSQUlTSU5HIGN4X3N0YXRpY19jaGVjaywKCiAgICAgIGdpdmVu"
    "X2ZpbGUKICAgICAgICBJTVBPUlRJTkcKICAgICAgICAgICAgICAgICAgaXZfZmlsZSBUWVBFIHN0cmluZwogICAgICAgIFJBSVNJ"
    "TkcgICB6Y3hfYWJhcGdpdF9leGNlcHRpb24sCiAgICAgIGdpdmVuX2ltYWdlLAogICAgICBnaXZlbl9jZHNfbWV0YWRhdGEKICAg"
    "ICAgICBSQUlTSU5HIHpjeF9hYmFwZ2l0X2V4Y2VwdGlvbiwKICAgICAgZ2l2ZW5fY2RzX3ZpZXdfd2l0aF91bWxhdXQKICAgICAg"
    "ICBSQUlTSU5HIHpjeF9hYmFwZ2l0X2V4Y2VwdGlvbiwKICAgICAgZ2l2ZW5fdGV4dAogICAgICAgIFJBSVNJTkcgemN4X2FiYXBn"
    "aXRfZXhjZXB0aW9uLAoKICAgICAgd2hlbl9pc19iaW5hcnlfZGV0ZXJtaW5lZAogICAgICAgIFJBSVNJTkcgemN4X2FiYXBnaXRf"
    "ZXhjZXB0aW9uLAoKICAgICAgdGhlbl9pc19ub3RfYmluYXJ5LAogICAgICB0aGVuX2lzX2JpbmFyeS4KCkVORENMQVNTLgoKCkNM"
    "QVNTIGx0Y2xfaXNfYmluYXJ5IElNUExFTUVOVEFUSU9OLgoKICBNRVRIT0QgY2xhc3NfY29uc3RydWN0b3IuCgogICAgZ3Zfbmwg"
    "ICAgPSBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5uZXdsaW5lLgogICAgZ3ZfY3JfbGYgPSBjbF9hYmFwX2NoYXJfdXRpbGl0aWVz"
    "PT5jcl9sZi4KCiAgRU5ETUVUSE9ELgoKICBNRVRIT0QgY2RzX21ldGFkYXRhX2lzX3RleHQuCgogICAgZ2l2ZW5fY2RzX21ldGFk"
    "YXRhKCApLgogICAgd2hlbl9pc19iaW5hcnlfZGV0ZXJtaW5lZCggKS4KICAgIHRoZW5faXNfbm90X2JpbmFyeSggKS4KCiAgRU5E"
    "TUVUSE9ELgoKCiAgTUVUSE9EIGNkc193aXRoX3VtbGF1dF9pc190ZXh0LgoKICAgIGdpdmVuX2Nkc192aWV3X3dpdGhfdW1sYXV0"
    "KCApLgogICAgd2hlbl9pc19iaW5hcnlfZGV0ZXJtaW5lZCggKS4KICAgIHRoZW5faXNfbm90X2JpbmFyeSggKS4KCiAgRU5ETUVU"
    "SE9ELgoKCiAgTUVUSE9EIGltYWdlX2lzX2JpbmFyeS4KCiAgICBnaXZlbl9pbWFnZSggKS4KICAgIHdoZW5faXNfYmluYXJ5X2Rl"
    "dGVybWluZWQoICkuCiAgICB0aGVuX2lzX2JpbmFyeSggKS4KCiAgRU5ETUVUSE9ELgoKICBNRVRIT0QgdGV4dF9pc19ub3RfYmlu"
    "YXJ5LgoKICAgIGdpdmVuX3RleHQoICkuCiAgICB3aGVuX2lzX2JpbmFyeV9kZXRlcm1pbmVkKCApLgogICAgdGhlbl9pc19ub3Rf"
    "YmluYXJ5KCApLgoKICBFTkRNRVRIT0QuCgogIE1FVEhPRCBnaXZlbl90ZXh0LgoKICAgIG12X2dpdmVuX2ZpbGUgPSB6Y2xfYWJh"
    "cGdpdF9jb252ZXJ0PT5zdHJpbmdfdG9feHN0cmluZ191dGY4KCAnVGVzdCcgJiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+Y3Jf"
    "bGYgKS4KCiAgRU5ETUVUSE9ELgoKICBNRVRIT0QgY3JsZl9tdWx0aWxpbmVfdGV4dF9pc19ub3RfYmluYXJ5LgoKICAgIGdpdmVu"
    "X2ZpbGUoICdvbmUnICYmIGd2X2NyX2xmICYmICd0d28nICYmIGd2X2NyX2xmICYmICd0aHJlZScgJiYgZ3ZfY3JfbGYgJiYgJ2Zv"
    "dXInICYmIGd2X2NyX2xmICYmICdmaXZlJyAmJiBndl9jcl9sZiApLgogICAgd2hlbl9pc19iaW5hcnlfZGV0ZXJtaW5lZCggKS4K"
    "ICAgIHRoZW5faXNfbm90X2JpbmFyeSggKS4KCiAgRU5ETUVUSE9ELgoKICBNRVRIT0QgbGZfb25seV90ZXh0X2lzX25vdF9iaW5h"
    "cnkuCgogICAgZ2l2ZW5fZmlsZSggJ29uZScgJiYgZ3ZfbmwgJiYgJ3R3bycgJiYgZ3ZfbmwgJiYgJ3RocmVlJyAmJiBndl9ubCAp"
    "LgogICAgd2hlbl9pc19iaW5hcnlfZGV0ZXJtaW5lZCggKS4KICAgIHRoZW5faXNfbm90X2JpbmFyeSggKS4KCiAgRU5ETUVUSE9E"
    "LgoKICBNRVRIT0QgbWFueV9jb250cm9sX2NoYXJzX2lzX2JpbmFyeS4KCiAgICBnaXZlbl9maWxlKCBjbF9hYmFwX2NoYXJfdXRp"
    "bGl0aWVzPT5mb3JtX2ZlZWQgJiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+Zm9ybV9mZWVkICYmIGNsX2FiYXBfY2hhcl91dGls"
    "aXRpZXM9PmZvcm1fZmVlZCAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT5mb3JtX2ZlZWQgJiYgY2xfYWJhcF9jaGFyX3V0aWxp"
    "dGllcz0+Zm9ybV9mZWVkICkuCiAgICB3aGVuX2lzX2JpbmFyeV9kZXRlcm1pbmVkKCApLgogICAgdGhlbl9pc19iaW5hcnkoICku"
    "CgogIEVORE1FVEhPRC4KCiAgTUVUSE9EIHNvbWVfY29udHJvbF9jaGFyc19pc19iaW5hcnkuCgogICAgZ2l2ZW5fZmlsZSggJ2Fi"
    "Y2RlZmcnICYmIGNsX2FiYXBfY2hhcl91dGlsaXRpZXM9PnZlcnRpY2FsX3RhYiAmJiBjbF9hYmFwX2NoYXJfdXRpbGl0aWVzPT52"
    "ZXJ0aWNhbF90YWIgJiYgY2xfYWJhcF9jaGFyX3V0aWxpdGllcz0+dmVydGljYWxfdGFiICkuCiAgICB3aGVuX2lzX2JpbmFyeV9k"
    "ZXRlcm1pbmVkKCApLgogICAgdGhlbl9pc19iaW5hcnkoICkuCgogIEVORE1FVEhPRC4KCiAgTUVUSE9EIGdpdmVuX2ZpbGUuCgog"
    "ICAgbXZfZ2l2ZW5fZmlsZSA9IHpjbF9hYmFwZ2l0X2NvbnZlcnQ9PnN0cmluZ190b194c3RyaW5nX3V0ZjgoIGl2X2ZpbGUgKS4K"
    "CiAgRU5ETUVUSE9ELgoKCiAgTUVUSE9EIGdpdmVuX2ltYWdlLgoKICAgIG12X2dpdmVuX2ZpbGUgPQogICAgICB6Y2xfYWJhcGdp"
    "dF9jb252ZXJ0PT5iYXNlNjRfdG9feHN0cmluZygKICAgICAgYGlWQk9SdzBLR2dvQUFBQU5TVWhFVWdBQUFMRUFBQUExQ0FZQUFB"
    "QU9DQW9MQUFBQUFYTlNSMElBcnM0YzZRQUFBQVJuUVUxQkFBQ3hqd3Y4WWAKICAgICAgJiYgYFFVQUFBQUpjRWhaY3dBQURzTUFB"
    "QTdEQWNkdnFHUUFBQWVjU1VSQlZIaGU3WnZMaWx4VkZJYjFCZlFGZE94QWNhQWdKSWdYOEI0SE9ra1BIQmAKICAgICAgJiYgYGt4"
    "T2pGaUZCUmFFSXpvd0lFWUJWR1FCTVVMZUlzakZlTkkwWUdUNkV6c0IrakVUdUlibFAwVjdtYlZxbi92czA2ZGM2cnFkUGJnZys0"
    "K2ExL2AKICAgICAgJiYgYE8zdCsrVnZWVjI5dmJrMHBsekZTSks2T25TbHdaUFZYaXl1aXBFbGRHVDVXNE1ub0drM2puODQ4bmw0"
    "NC9QZG41OEQzNXZGTHBpMEVrdnZqeWAKICAgICAgJiYgYDg1Ti9iNzk1RDM1WGNaVktIL1F1c1JlNGlsd1ptbDRsemdtY3FDSlho"
    "cUJYaVhjMmowdDVMVlhrU3QvMEl2R0ZuMzdZKzdtS1hGazJuU1ZPV2AKICAgICAgJiYgYDRoL1B2dG83MjlWNU1veTZTUnhFampo"
    "UmI1NDlMR1o1NTRxOHY3ajE1L1BUczUrLzgwVTlYd0lGcGJZQzV5d0lpZEtNL09xUmY3ajNPK1R0OWAKICAgICAgJiYgYDU0UWZM"
    "amQxL0xOQlVOYlhiYkRWZnZzWEhvcHNuVzMzL0oyRDVaU09LY3dJbnp2LzB5bCtiU0kvZklXRmlseUdlK09EWFQ4Qlk2UmFYWmJ6"
    "Q2AKICAgICAgJiYgYFFQM2ozeE9UWUV3OU9qbXdjbkdtRHUyKzlkdm8zMm9KWlZxVUhaTFhwRXUrLzg2cU03NVBXRWpjSkRETGRt"
    "bTR0L094aDJlOFNJNldYdG9tSGAKICAgICAgJiYgYDc3eCs4dW5wazNONXNXcXArR1cwWVN1Skl3S0QzRks4L29xTXRheENaR2FR"
    "VDA2OVBkbDQ2TWFWZE1DcTRKMzkrN1pCNWFuaVNqTXh6MUxjNGAKICAgICAgJiYgYDRjUHlKZ0lZWW1qQWsrNS8rRE10VnRpblc4"
    "dDFMWml2MHBjV24wQW9STHFPYWg4clpUQXhGRGFFNS9ZZkhJdmRuQ0pXd244UDJ3ZlNJdk1ZN2AKICAgICAgJiYgYGgrVTh2aGZw"
    "UTR0K3dmdXVPNjZleXMwcWdCcnVLQS9UVmxSQTdGbEpueUcxVGlSUVFHS3pHL3I3dklWNHJFVnB4RTA0d0pQbzJLYVlNZkdJTmAK"
    "ICAgICAgJiYgYEpITm5INXZBU3c5eGVlV3VyOSt1M2RFL0phZnZNbDZlblA1ZE8xWWttaVpsaDB2MG50TGs2SWphbG8xN3BaL0pV"
    "OFczdzlWSXhpZHcrT05JK2AKICAgICAgJiYgYFhuNFZFOFZ2TzJBUWlia21VMkpGVVJKRDIrczNkVWowSU1sTHoyNU1UODYrY1JK"
    "Y0ZTRmxUcjZjeFB3OWQ0Si9iZk5vVVdiU2NtMmwwaWE0U2AKICAgICAgJiYgYHlYT3A2VnNGWjhPU2dpcDNqZTlwODhQMUI3M3hX"
    "T0haYXlIL1N2cFV4NzJtV3E3aEsyTDNRTkh5TDJISnl2eGhXKy9rbEpGeVVuTTc3NHNZbWAKICAgICAgJiYgYDJNWmVma20zUHhG"
    "aVNpNDFRaktCQlM1YU02b2pRb0VraW84bXQ3K21kNXRlbHpFbE4veWxUUExBeHFteCtvdU1nczNFVDBybDBOb2hLZEpXYWAKICAg"
    "ICAgJiYgYHB2M3pmQVNsV2hKekVhbWE5L09pOU16RVdKYjJGbVVRMUFBMTIxeTNYeUdkcTVpdk5KazM0eHM0TkxKWmtkWlVIREJp"
    "YkIzbm02aC9GRG96Y2AKICAgICAgJiYgYCs5a3lGNFZ5MUY0YlZpdnhMaXo5aTRxY2szam0rbTEzb0pRT2pwR3RoTzlvR3RNdThX"
    "ci94YkptODRCY0o1TS9BNFVHelEwWWhHM0tLMjBEZ2AKICAgICAgJiYgYFBvcG1mMGVtYmhuamp3d0Z3ZTJYcmtZdTBxb09pR1ZM"
    "YThycXEydGlNejYxRVBGMFI0OHMwVFBERVdKWVZHUnN4SUhpUWdNZENDZGtXWmVOWGAKICAgICAgJiYgYHA5ZzZuT285RjhISG5i"
    "QVFHNWJRTHBiVjZwVHNCenYyeFR6MUllcFRnMUNGVWNwUHFyNTZvZHVxRGFVUFdIaXV0U2wwYUpZUkdSdTBnY0ZUaGAKICAgICAg"
    "JiYgYEtwTUdpSFFCcTZjekY1bEJTUlNWV2NlRGpiS3pLcHlRT2c0NDBUZGk2Uk50UXhRMHVNYlFSbWJpWkxjTnpUOGs0UmQ4Q1E2"
    "VEJvaDBBNnBTZGAKICAgICAgJiYgYGk4MUJ2TS9EQ3RFMkRuZ3ZINXYyeFdvRktZbWp5bFhZOTE1N2lTRXE4cHlJd1VOaUY0SFpQ"
    "L0hGRkJxTmt6bW4rRVNrd2RwSXJEcVlyWWVLSmAKICAgICAgJiYgYFYvaUlYMUxETlROaDVKVGxhWGlRRW1jM2tHOUgvZzhFcm45"
    "dnlmbEQ5RTJWSEZMa3hnaUlwLy84OXhjdXRJMUdpd3FNSHMrcFBXTlVtSUlpZWAKICAgICAgJiYgYGwwRzhNTUdMbWlzeWc1VlZr"
    "cURrb1NNOGo5TThoZHNURnpreGFVME9rZ1p0TkUyMURGTFZWaWFCS1pPK2FaTk16RWhXdTBMZ0kzM1ptcVc0QWAKICAgICAgJiYg"
    "YGhKTGF4cFh0VDRBQ3E5dFZLVGxXV2lnTWxzWTMxTnptZ0RvbWVxSFRSTm96bUYyVWhpYUVrTXNMeWZCcmJ3elZhanR4VmpaOWRm"
    "RXhYaWRXVmAKICAgICAgJiYgYGxvMVZBNGZuOXFZakttYzBEdFRBc0cyaDl2SmNEL29iR0U5VXVtZ2JSdk9Mc3JERTBEUWpsMlpm"
    "NkNJd0tKbFVCL3VZTGgxQWgvczRzT1g2WmAKICAgICAgJiYgYDhobDg0QytKVVpXSHdjMkpyZWxZRFVyaWF6YVp0OUlESkU5c3FL"
    "cndNQ0wrOGF3bjFLQjZselZZSEpXMysxY1A2dm5EanhKQWlXNS96QWtsMGAKICAgICAgJiYgYDlVWWc2STlvTUF5bFRiS25YWVZM"
    "TXhrRjZWRDMxTHJBWlRaRVhJMFZsaWFDdHlId0pEYm5ua20yS1FPL0RSWVQ0dkpVdUMrTnlOQXZoRG5ZcGAKICAgICAgJiYgYEJQ"
    "T3BFT2JsOC9BQ0VVcjNTVFFmdnJKNnIvS2JDaSsxT2dycVJKK1h5QmFmY2V5dUoxVmtndCtmMmNVQTdVeTdRWHI1ZGMvUWlNVVJG"
    "N2t0Z2AKICAgICAgJiYgYGFQc2xHNCtkcVVxeWxPQ3daR2RGVUN0RUczaXZydlhLWGZsQms4Z1JyTVNSZnZCQ1J0cElyV0NLM2lT"
    "R0pwSDdGRGpSMUJsMHB0b3FnTzBJdGAKICAgICAgJiYgYGI5dTZod0VWa3V3V2xZdHBDUHZYRWNpYnNwTFNkejB6anh2V3BwNVR0"
    "N3F4aUpDVXgwOXRxMmhxWTBTcW4wOXZVb01PWkdIRUJqb0RFYTU3d2AKICAgICAgJiYgYHlrVE1zcCsxb2EwV09YT241V3owanJC"
    "YWNzeXZRenNJWEc5N0p4d0xQcEdGeTJ6RVRUVEV6ZTRPdEYvc1EzQ1d3aGx2S29sN3JkU0ZBdllvamAKICAgICAgJiYgYDErYWNC"
    "V1VKdEs5UTdBTzFHdkQrUDVPaGRZa0RrOUVWM2hCNUs0R1hUUm82K3lFbXNZdnRrRmUrNmFKbURTRHhsYTJ2Ni9RbjE2VjBsenFv"
    "a2AKICAgICAgJiYgYEhoUERTVnpwaFNweE0xWGlOWWE5cy9vZnZmVFBwcXRZOHRlUkt2R2FvbWJnSENyOWxVU1ZlRTJwRXNlcEVx"
    "OHA3SHNST1lKS2Z5VlJKYTZNbmAKICAgICAgJiYgYGlweFpmUlVpU3VqcDBwY0dUMVY0c3JvcVJKWFJrK1Z1REp5dGlmL0FhOFps"
    "bVZwZk5WUUFBQUFBRWxGVGtTdVFtQ0NgICkuCgogIEVORE1FVEhPRC4KCgogIE1FVEhPRCBnaXZlbl9jZHNfbWV0YWRhdGEuCgog"
    "ICAgZ2l2ZW5fZmlsZSggYHtgCiAgICAgICYmIGd2X25sICYmIGAiQkFTRUlORk8iOmAKICAgICAgJiYgZ3ZfbmwgJiYgYHtgCiAg"
    "ICAgICYmIGd2X25sICYmIGAiRlJPTSI6YAogICAgICAmJiBndl9ubCAmJiBgW2AKICAgICAgJiYgZ3ZfbmwgJiYgYCJUMTAwImAK"
    "ICAgICAgJiYgZ3ZfbmwgJiYgYF0sYAogICAgICAmJiBndl9ubCAmJiBgIkFTU09DSUFURUQiOmAKICAgICAgJiYgZ3ZfbmwgJiYg"
    "YFtdLGAKICAgICAgJiYgZ3ZfbmwgJiYgYCJCQVNFIjpgCiAgICAgICYmIGd2X25sICYmIGBbXSxgCiAgICAgICYmIGd2X25sICYm"
    "IGAiQU5OT19SRUYiOmAKICAgICAgJiYgZ3ZfbmwgJiYgYFtdLGAKICAgICAgJiYgZ3ZfbmwgJiYgYCJWRVJTSU9OIjowYAogICAg"
    "ICAmJiBndl9ubCAmJiBgfWAKICAgICAgJiYgZ3ZfbmwgJiYgYH1gICkuCgogIEVORE1FVEhPRC4KCgogIE1FVEhPRCBnaXZlbl9j"
    "ZHNfdmlld193aXRoX3VtbGF1dC4KCiAgICBDT05TVEFOVFMgbGNfdW1sYXV0X3VlIFRZUEUgeHN0cmluZyBWQUxVRSBgQzNCQ2Au"
    "CgogICAgZ2l2ZW5fZmlsZSggYEBFbmRVc2VyVGV4dC5sYWJlbDogYAogICAgICAmJgogICAgICB6Y2xfYWJhcGdpdF9jb252ZXJ0"
    "PT54c3RyaW5nX3RvX3N0cmluZ191dGY4KCBsY191bWxhdXRfdWUgKQogICAgICAmJiBgYmVybmFobWVrYW5kaWRhdCdgCiAgICAg"
    "ICYmIGd2X2NyX2xmICYmIGBAQWJhcENhdGFsb2cuc3FsVmlld05hbWU6ICdaVEVTVERETFNCVUcyJ2AKICAgICAgJiYgZ3ZfY3Jf"
    "bGYgJiYgYEBBYmFwQ2F0YWxvZy5jb21waWxlci5jb21wYXJlRmlsdGVyOiB0cnVlYAogICAgICAmJiBndl9jcl9sZiAmJiBgQEFi"
    "YXBDYXRhbG9nLnByZXNlcnZlS2V5OiB0cnVlYAogICAgICAmJiBndl9jcl9sZiAmJiBgQEFjY2Vzc0NvbnRyb2wuYXV0aG9yaXph"
    "dGlvbkNoZWNrOiAjQ0hFQ0tgCiAgICAgICYmIGd2X2NyX2xmICYmIGBkZWZpbmUgdmlldyB6dGVzdF9kZGxzX2J1ZzJgCiAgICAg"
    "ICYmIGd2X2NyX2xmICYmIGAgIGFzIHNlbGVjdCBmcm9tIHQxMDBgCiAgICAgICYmIGd2X2NyX2xmICYmIGB7YAogICAgICAmJiBn"
    "dl9jcl9sZiAmJiBgICBrZXkgc3Byc2wgYXMgU3Byc2wsYAogICAgICAmJiBndl9jcl9sZiAmJiBgICBrZXkgYXJiZ2IgYXMgQXJi"
    "Z2IsYAogICAgICAmJiBndl9jcl9sZiAmJiBgICBrZXkgbXNnbnIgYXMgTXNnbnIsYAogICAgICAmJiBndl9jcl9sZiAmJiBgICAg"
    "ICAgdGV4dCAgYXMgVGV4dGAKICAgICAgJiYgZ3ZfY3JfbGYgJiYgYH1gICkuCgogIEVORE1FVEhPRC4KCiAgTUVUSE9EIHdoZW5f"
    "aXNfYmluYXJ5X2RldGVybWluZWQuCgogICAgbXZfYWN0X2lzX2JpbmFyeSA9IHpjbF9hYmFwZ2l0X3V0aWxzPT5pc19iaW5hcnko"
    "IG12X2dpdmVuX2ZpbGUgKS4KCiAgRU5ETUVUSE9ELgoKCiAgTUVUSE9EIHRoZW5faXNfbm90X2JpbmFyeS4KCiAgICBjbF9hYmFw"
    "X3VuaXRfYXNzZXJ0PT5hc3NlcnRfZXF1YWxzKAogICAgICBhY3QgPSBtdl9hY3RfaXNfYmluYXJ5CiAgICAgIGV4cCA9IGFiYXBf"
    "ZmFsc2UgKS4KCiAgRU5ETUVUSE9ELgoKCiAgTUVUSE9EIHRoZW5faXNfYmluYXJ5LgoKICAgIGNsX2FiYXBfdW5pdF9hc3NlcnQ9"
    "PmFzc2VydF9lcXVhbHMoCiAgICAgIGFjdCA9IG12X2FjdF9pc19iaW5hcnkKICAgICAgZXhwID0gYWJhcF90cnVlICkuCgogIEVO"
    "RE1FVEhPRC4KCkVORENMQVNTLgo="
)

_CACHE = {}


def results():
    """One transpile and run per pytest process; all tests below read this dict."""
    if "r" not in _CACHE:
        with tempfile.TemporaryDirectory() as tmp:
            hidden = Path(tmp) / "hidden.clas.testclasses.abap"
            hidden.write_bytes(base64.b64decode(HIDDEN_TESTS_B64))
            try:
                _CACHE["r"] = t.run_abap_tests(CFG, {REL_CLASS: TARGET, REL_TESTS: hidden}, timeout_s=240, trusted=(REL_TESTS,))
            except (t.AbapTextRefused, t.RunnerError) as exc:     # a failing check is an assertion failure with the reason in the message (the loop requires controls to fail by assertion)
                raise AssertionError(f"the ABAP could not be run: {type(exc).__name__}: {exc}") from None
    return _CACHE["r"]


def _passes(name):
    assert results().get("ltcl_is_binary->" + name) == "PASS", results()


def test_cds_metadata_is_text():
    _passes("cds_metadata_is_text")


def test_cds_with_umlaut_is_text():
    _passes("cds_with_umlaut_is_text")


def test_image_is_binary():
    _passes("image_is_binary")


def test_text_with_windows_line_endings_is_not_binary():
    _passes("text_is_not_binary")


def test_multiline_windows_text_is_not_binary():
    _passes("crlf_multiline_text_is_not_binary")


def test_lf_only_text_is_not_binary():
    _passes("lf_only_text_is_not_binary")


def test_many_control_characters_is_binary():
    _passes("many_control_chars_is_binary")


def test_some_control_characters_is_binary():
    _passes("some_control_chars_is_binary")


def _outside_is_binary(path):
    text = path.read_bytes().decode("utf-8").replace(chr(13) + chr(10), chr(10))
    start = text.index("METHOD is_binary.")
    end = text.index("ENDMETHOD.", start)
    return [line.rstrip() for line in (text[:start] + text[end:]).split(chr(10))]


def test_nothing_outside_is_binary_changed():
    assert _outside_is_binary(TARGET) == _outside_is_binary(ORIGINAL)


def test_no_abaplint_issues_in_the_edited_file():
    """abaplint with the project's own config (ABAP release of the project) plus the kernel-write rule: syntax errors and raw JavaScript are caught here."""
    try:
        issues = t.run_abaplint(CFG, {REL_CLASS: TARGET}, timeout_s=240)
    except (t.AbapTextRefused, t.RunnerError) as exc:
        raise AssertionError(f"abaplint could not be run: {type(exc).__name__}: {exc}") from None
    assert issues == [], issues
