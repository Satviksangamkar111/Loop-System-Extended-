# How the Satvik Loop works on ABAP jobs (conventions for coders and reviewers)

## For a writer
- The request holds the SPEC, the files you may edit, and (if the job allows) background reference pages. Edit ONLY the files listed as expected files.
- Reply with `FILE: <path>` followed by the complete file in a fenced block, for each file, and nothing else. Never write a reviewer verdict line.
- Change the least possible. Keep every other line of the file exactly as it is: no reformatting, no new methods, no renamed variables, same line endings.
- Spec lines marked `KNOWN:` are requirements; `ASSUMED:` lines need approval. Reference pages are background only.
- You cannot see the locked acceptance tests. Do not try to weaken or replace them; a changed test fails the job.

## For a reviewer
- Check the code against every SPEC line and every CHECK in the package. Report a finding only as `file:line | requirement | one sentence`; a finding without a line and the requirement it breaks is not counted.
- End with `## Verdict: READY` or `## Verdict: FIX FIRST`.
- Reference pages explain style and syntax; they never add requirements.

## What the loop guarantees and what it does not
- The tested, reviewed and delivered file have the same hash. Locked acceptance tests and wrong-fix controls are checked before any model is called.
- On ABAP jobs without SAP, the check is offline (a static or transpiled check). It does **not** prove the code compiles on a SAP system. That needs a SAP sandbox, which has not been approved.
- No job may write to a SAP system until the sandbox gate (system identity, client role, ownership and written permission) has passed.
