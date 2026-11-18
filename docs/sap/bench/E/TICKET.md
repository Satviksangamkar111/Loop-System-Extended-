# cl_abap_tstmp: add( ), subtractsecs( ) and subtract( ) keep the fract…

KNOWN: The 7 fraction digits of a `timestampl` input are dropped, and a fractional `secs` is ignored.
KNOWN: So a +60 s round trip comes back as 59 or 60:
KNOWN: GET TIME STAMP FIELD lv_from.                                " 20261012193756.7000000
KNOWN: lv_to = cl_abap_tstmp=>add( tstmp = lv_from secs = 60 ).     " system: 20261012193856.7000000
KNOWN: lv_diff = cl_abap_tstmp=>subtract( tstmp1 = lv_to tstmp2 = lv_from ). " system: 60
KNOWN: On the current main, `add( )` of `'20240229235959.5000000'` and 60 seconds answers `20240301000059.0012416`.
