# Progress indicator crashes with a division by zero when the total is 0

- KNOWN: The file is src/ui/progress/zcl_abapgit_progress.clas.abap (abapGit, class ZCL_ABAPGIT_PROGRESS). It shows a progress bar in the status bar and works out the percentage to show from the current step and the total number of steps.
- KNOWN: Symptom: when the total number of steps is 0 (for example an empty list of objects), working out the percentage ends in a short dump (CX_SY_ZERODIVIDE) instead of showing something.
- KNOWN: Example: a progress indicator with a total of 0 and a current step of 1 dumps; so does any current step above 0. (A current step of 0 with a total of 0 does not dump today and is not part of this report.)
- KNOWN: Expected: with a total of 0 and a current step above 0 the percentage is 0 and nothing is raised.
- KNOWN: Every other case must keep the result it has today: for example 50 of 100 gives 50, 1 of 3 gives 33, 2 of 3 gives 67. The existing rule that a result of 100 is reported as 99 and a result of 0 is reported as 1 stays as it is for a total larger than 0.
- KNOWN: Change only what is needed in that file. Keep every other line exactly as it is: no new methods, no reformatting.
