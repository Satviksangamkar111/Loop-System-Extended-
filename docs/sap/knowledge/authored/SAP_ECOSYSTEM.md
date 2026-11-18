# SAP ecosystem primer for the loop's coders, reviewers and people

> Authored for this project by an AI assistant from general SAP knowledge. It is NOT SAP documentation. A SAP expert should check it before anyone relies on it.
> When this page and a job's SPEC or locked tests disagree, the SPEC and the tests win.

## Systems, clients, packages, transports
- A SAP landscape usually has development (DEV), quality (QAS) and production (PRD) systems. Changes move DEV to QAS to PRD in **transport requests**. Production is never edited directly.
- A **client** is a logical data segment inside one system (client 200 is a number, not a role). Table data is usually per client (field MANDT). **Repository objects (classes, programs, dictionary objects) are cross-client**: a Z class created in one client exists in every client of that system. A local package is therefore not an isolation boundary.
- Packages: `$TMP` and names starting with `$` are local (not transported). Customer objects use the `Z` or `Y` prefix, or a registered namespace like `/NS/`. A package in a transport layer asks for a transport request on every change.
- A system's role and each client's settings (transaction SCC4) decide whether changes are allowed there. Only the system owner or Basis team can confirm them.

## Tools
SE80 (object navigator), SE24 (class builder), SE38 (ABAP editor), SE11 (dictionary), SU53 (last authorization failure), SCC4 (client settings). **ABAP Development Tools (ADT)** is Eclipse; it talks to the system over HTTPS under `/sap/bc/adt`.
**ABAP Unit** runs test classes. **ATC** (ABAP Test Cockpit) runs static checks and reports findings with priority 1 to 3. **abapGit** stores ABAP objects as files in Git.

## Object life cycle
Edit and save (an inactive version), syntax check, **activate** (active version). An object is locked for one user while edited. Restoring the old source does not undo database commits, update tasks, external RFC calls or transports.

## Release
S/4HANA 2022 is ABAP Platform 2022 (SAP_BASIS 757): modern syntax (inline declarations, constructor expressions, string templates, `@` host variables in ABAP SQL) is available. Open-source projects often support older releases: read the project's `abaplint.json` for the language version it targets before using new syntax.

## ABAP basics a reviewer should check
- A statement ends with a period. Keywords are case-insensitive. A comment is a `*` in column 1 or a `"` outside a literal. Literals: `'text'` (trailing blanks are not significant), `` `text` ``, `|template {var}|`.
- `sy-subrc` is 0 on success: check it after `READ TABLE`, `SELECT SINGLE`, `CALL FUNCTION` and similar.
- Internal tables are STANDARD, SORTED or HASHED. `READ TABLE ... WITH KEY` on a standard table scans linearly; `WITH TABLE KEY` or a hashed or sorted table uses the key. Avoid `SELECT` or `READ TABLE` scans inside big loops.
- `boolc( cond )` and `xsdbool( cond )` turn a condition into an ABAP boolean.
- Security: customer code that reads protected data needs `AUTHORITY-CHECK`; never build SQL or dynamic calls from raw input.
- Unit tests: `CLASS ltcl_x DEFINITION FOR TESTING RISK LEVEL HARMLESS DURATION SHORT.` with methods `FOR TESTING`, asserting with `cl_abap_unit_assert=>assert_equals( act = ... exp = ... )`.

## abapGit file layout
`src/<package>/zcl_x.clas.abap` (class), `zcl_x.clas.testclasses.abap` (local test classes), `zcl_x.clas.xml` (metadata), `.abapgit.xml` (repository settings).
