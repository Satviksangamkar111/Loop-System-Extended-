# Proof set: five new public problems (fixed 2026-11-17, BEFORE any of them is run)

Order is fixed by the scouting lists in work/ (medium_candidates.md, older_candidates.md, hard_candidates.md), taken top to bottom. The proof set is the FIRST FIVE candidates that pass the automatic admission gate (docs/sap/AUTO_BENCH_CONTRACT.md, section 3). A candidate that fails the gate is rejected with its REJECTED.md and the next one is taken; no candidate is swapped, skipped or re-ordered after the first run of the proof set has started, and a candidate is never dropped because a run on it failed.

Already used, so excluded: abapGit 7922 (bench D), abapGit 7118 (bench F), abap2xlsx 838 (bench C), bench E (rejected), bench A and B (calibration).

Order of candidates:
1. open-abap/open-abap-core #1311 (cl_abap_tstmp: add, subtract, subtractsecs)
2. open-abap/open-abap-core #1306 (cl_http_client; test lives under test/)
3. open-abap/open-abap-core #1285 (cl_abap_dyn_prg; test uses a SAP table: expected to be rejected)
4. open-abap/open-abap-core #1292 (two production classes: expected to be rejected by the one-file gate)
5. abapGit/abapGit #7062
6. abapGit/abapGit #7120
7. abapGit/abapGit #7414
8. open-abap/open-abap-core #1162
9. open-abap/open-abap-core #1137
10. abapGit/abapGit #7923
11. open-abap/open-abap-core #1191
12. abapGit/abapGit #7812
13. open-abap/open-abap-core #1179
14. open-abap/open-abap-core #1166

Reading rule: these are public pull requests, so a model may have seen them; no result here proves the loop works on private SAP code. The label of each problem (BLIND = the ticket text is the maintainers' own issue body; SEMI-GUIDED = only a PR body existed) is recorded in its manifest and stated with its result.
