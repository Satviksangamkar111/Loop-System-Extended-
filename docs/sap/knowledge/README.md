# Offline ABAP / SAP knowledge package

For the loop's coders and reviewers, and for people. Everything here is plain text (markdown) and needs no internet to read.

## Contents
| Folder | What it is | Source / license |
|---|---|---|
| `clean-abap/` | SAP's Clean ABAP style guide and ABAP code-review guide (English) | SAP/styleguides, CC BY 3.0 |
| `cheat-sheets/` | ABAP syntax by topic with runnable examples (internal tables, ABAP SQL, OO, constructor expressions, unit tests, performance notes and more) | SAP-samples/abap-cheat-sheets, Apache-2.0 |
| `abapgit-docs/` | abapGit user and developer documentation (packages, transports, repository layout) | abapGit/docs.abapgit.org, CC BY 4.0 |
| `authored/` | Documents written for this project (SAP ecosystem primer, loop conventions). **Not from SAP; to be checked by a SAP expert.** | this project |
| `user_supplied/` | Your own exports you are licensed to hold (for example pages saved from SAP Help Portal). Not committed to git. | yours |
`SOURCES.md` has the exact commits and license text. SAP's own ABAP Keyword Documentation is copyrighted and is **not** included.

## How the loop uses it
1. `python scripts/source/sap_ref.py docs/sap/knowledge "<keywords for the ticket>" --max-kb 12 --out docs/sap/<job>/REFERENCE.md` picks the most relevant sections (BM25 search over headings and text).
2. The job file lists that file under `reference`. **Reviewers** always see it in the review package. **Writers** see it only when the job also sets `"writer_reference": true` (capped at 16,000 characters, shown as background, never as a requirement).
3. The SPEC and the locked tests always decide what is correct; reference text never overrides them.

## Limits
- Search is keyword-based; pick the keywords for the ticket yourself until a planner does it.
- Sections are large, and one section can fill the whole size cap.
- Coverage is style, syntax examples and abapGit: not every ABAP keyword, not SAP-specific dictionary or transaction details of your system.
