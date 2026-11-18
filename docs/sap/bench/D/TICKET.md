# Patch: no form feed in the staged file

- KNOWN: The file is src/git/zcl_abapgit_git_add_patch.clas.abap (abapGit, class ZCL_ABAPGIT_GIT_ADD_PATCH).
- KNOWN: When only one side of a file ends in a newline, `zcl_abapgit_diff_std` marks the last line of the other side with a form feed. The patch is built from the diff texts, so an unpicked change of that last line put the form feed into the commit: staging only an added line "c" in a file that is "a\nb" in Git and "a\nb\nc\n" locally gave "a\nb<FF>\nc\n".
