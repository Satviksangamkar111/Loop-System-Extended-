# sap_6505: local T packages must not be assigned to a transport request (abapGit issue 6505)

- KNOWN: The file is abap_work/abapgit_6505/zcl_abapgit_sap_package.clas.abap, an ABAP class taken from the public abapGit repository (commit 82633f8). It is plain ABAP text and is never executed.
- KNOWN: Problem: when abapGit pulls into a NEW package, method zif_abapgit_sap_package~are_changes_recorded_in_tr_req decides whether changes are recorded in a transport request. In the `WHEN 1.` branch ("For new packages, derive from package name") it treats every package whose name does not start with `$` as transport-recorded.
- KNOWN: Packages whose name starts with `T` are local packages as well, like `$` packages, and must not ask for a transport request.
- KNOWN: Required behaviour of that `WHEN 1.` result: false when the first character of mv_package is `$` or `T`; true for every other first character (for example `Z`, `Y` and `/`).
- KNOWN: Change only the condition inside `boolc( ... )` in the `WHEN 1.` branch of that one method. Keep every other line of the file byte for byte as it is: no new methods, no reformatting, no other branch.
- KNOWN: The result must still be valid ABAP: the statement keeps its form `rv_are_changes_rec_in_tr_req = boolc( ... ).` and the condition uses only mv_package(1), single-quoted literals, = <> EQ NE CA NA, NOT, AND, OR and parentheses.
- KNOWN: Reply with the complete file in the usual FILE format.
