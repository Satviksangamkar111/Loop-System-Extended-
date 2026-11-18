# Text files with Windows line endings are reported as binary

- KNOWN: The file is src/utils/zcl_abapgit_utils.clas.abap (abapGit, class ZCL_ABAPGIT_UTILS). It decides whether the content of a file is text or binary.
- KNOWN: Symptom: some small text files that use Windows line endings (a carriage return followed by a line feed, CR+LF) are wrongly treated as binary.
- KNOWN: Example: a file whose whole content is the word `Test` followed by one CR+LF is reported as binary.
- KNOWN: Expected: such a file is text, not binary. A file that really is binary (for example an image) and text containing umlauts or CDS metadata must keep the result they have today.
- KNOWN: Change only what is needed in that file. Keep every other line exactly as it is: no new methods, no reformatting.
