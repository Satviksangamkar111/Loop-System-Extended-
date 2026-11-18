# Install

Tested on Windows 11 with the versions below. Run the commands from the repository root, in bash (Git Bash on Windows). `npm ci` and `git fetch` steps were not run from an empty machine; the resulting layout was tested with an equivalent local runtime. Linux and macOS are untested.

## 1. Check prerequisites

| Tool | Tested | Needed for |
|---|---|---|
| Python | 3.14.5 | Everything |
| Node.js / npm | 22.22.3 / 10.9.8 | ABAP runs |
| git | 2.53 | Tests, verdicts, sources |
| Claude CLI | 2.1.322 | Claude roles only |
| Codex CLI | not exercised | `cli_exec` roles only |
| Docker | not installed | Not used by the ABAP path |

```bash
python --version && node --version && git --version
node --permission -e "console.log('ok')"
```

## 2. Install Python packages

```bash
git clone https://github.com/Satviksangamkar111/Loop-System-Extended-.git
cd Loop-System-Extended-
python -m venv .venv
source .venv/bin/activate          # Git Bash on Windows: source .venv/Scripts/activate
python -m pip install pytest==9.2.0 PyYAML==6.0.3 jsonschema==4.26.0 fastapi==0.139.0 starlette==1.3.1 httpx==0.28.1 uvicorn==0.49.0
```

## 3. Smoke test (no model call)

```bash
python scripts/sap_poc_run.py --roles
python scripts/sap_poc_run.py docs/sap/bench/D/job.json --dry-run
```

Expected: `duplicate models: none`, then `dry-run: job ok, sandbox selftest: ok`.

## 4. Install the ABAP tools and libraries

```bash
export ABAP_RUNTIME="$HOME/abap-runtime"
mkdir -p "$ABAP_RUNTIME"/{abap_tools,libs,projects,benchmark}
cp docs/sap/bench/A/abap_tools.package.json "$ABAP_RUNTIME/abap_tools/package.json"
cp docs/sap/bench/A/abap_tools.package-lock.json "$ABAP_RUNTIME/abap_tools/package-lock.json"
(cd "$ABAP_RUNTIME/abap_tools" && npm ci --ignore-scripts)

fetch() { mkdir -p "$2" && git -C "$2" init -q && git -C "$2" fetch -q --depth 1 "https://github.com/$1.git" "$3" && git -C "$2" checkout -q FETCH_HEAD; }
L="$ABAP_RUNTIME/libs"
fetch open-abap/open-abap-core    "$L/open-abap-core"       db548ccab0837ed53669ad01a97e42087ead5be8
fetch abaplint/deps               "$L/abaplint-deps"        13dfeb1764d59dc647cf82d188cb04e0566d764a
fetch open-abap/open-abap-gui     "$L/open-abap-gui"        011330ff4903deb4fc18a3f5ea4e0c98664023da
fetch open-abap/open-abap-seo     "$L/open-abap-seo"        960fdf30da08500e1a51aa12bd62e90971903823
fetch open-abap/express-icf-shim  "$L/express-icf-shim"     65f8d6266057a0a8fe15e54fdc0af319a29f5d72
fetch abapGit/abapGit-web-classic "$L/abapGit-web-classic"  81cb9d8f1f43ccdd99d1619bdece15f067ef2661
cp -r runtime_overlay/benchmark/proj "$ABAP_RUNTIME/benchmark/proj"
```

## 5. Add the real-repository projects (optional)

Needed for benches A, B, C, D, F, `abapgit_7118` and `abapgit_7922`.

```bash
P="$ABAP_RUNTIME/projects"
fetch abapGit/abapGit     "$P/A_project"          f87aa944e6e6b6a41ac78e878ecce7cdcefcb61d
fetch abapGit/abapGit     "$P/B_project"          84656774fd97a45050323b5f661d924b69678bfc
fetch abap2xlsx/abap2xlsx "$P/C_project_838"      16430d17ddf62344282fea3d8992591c15b1d4d9
fetch abapGit/abapGit     "$P/D_project"          511cdbef4ea3b821b04bb09400b20911a5c82361
fetch abapGit/abapGit     "$P/F_project"          b7bb00d7ee92ad648e033adc31c0c36e2aa45c6e
fetch abapGit/abapGit     "$P/abapgit_511cdbef4e" 511cdbef4ea3b821b04bb09400b20911a5c82361
fetch abapGit/abapGit     "$P/abapgit_b7bb00d7ee" b7bb00d7ee92ad648e033adc31c0c36e2aa45c6e
for b in A:A_project B:B_project C:C_project_838 D:D_project F:F_project; do
  mkdir -p "$P/${b#*:}/test"; cp "docs/sap/bench/${b%%:*}/abap_transpile.pinned2.json" "$P/${b#*:}/test/"
done
cp -r runtime_overlay/projects/. "$P/"
```

Bench E has no pinned project here, so its ABAP tests cannot run after this step.

## 6. Point the benches at the runtime

```bash
python scripts/relocate_runtime.py "$ABAP_RUNTIME"
```

This rewrites local paths in `runner.json` and `manifest.json`. Do not commit those changes.

## 7. First offline run (no model call)

```bash
export SATVIK_HOME="$HOME/satvik-loop-home"
python scripts/rehearse_bench.py hb_0
```

Expected last line: `state: calibration-passed`.

## 8. Run the test groups

```bash
unset SATVIK_HOME OPENROUTER_FREE_KEY OPENROUTER_PAID_KEY SAP_ROSTER SAP_ALLOW_DUPLICATE_MODELS
export SATVIK_NO_OPUS=1
```

```bash
python -m pytest -q -p no:cacheprovider                 # everything, about 13 minutes
python -m pytest -q -p no:cacheprovider tests/abap      # SAP pipeline only
```

Expected: 0 failed. About 30 tests skip when Docker is missing or on Windows.

## 9. Configure model access (for real runs)

| Route | Setup |
|---|---|
| Claude CLI | Install it and sign in with `claude`. `ANTHROPIC_*` variables are removed from each call |
| OpenRouter | `OPENROUTER_FREE_KEY`, or `secrets/openrouter_free_key.txt` |
| OpenRouter paid reviewer | `OPENROUTER_PAID_KEY`, or `secrets/openrouter_paid_key.txt` |
| NVIDIA arbiter route | Key files `nvidia_api_key*.txt` in `NVIDIA_KEYS_DIR` (default: `../secrets/nvidia`) |
| Codex | Sign in to `codex`; command is in `config/exec_role.json` |

```bash
export OPENROUTER_FREE_KEY="<your key>"
export SATVIK_HOME="$HOME/satvik-loop-home"
export PAR_SATVIK_HOME="$SATVIK_HOME"
python scripts/source/sap_preflight.py     # makes one short call per distinct model
```

Set a credit limit on the OpenRouter key. The per-job dollar limit does not cover OpenRouter writers.

## 10. Run a bench

```bash
python scripts/source/sap_solve.py docs/sap/bench_auto/hb_0/manifest.json --series run1
```

Claude only:

```bash
export PAR_SATVIK_HOME="$HOME/satvik-loop-home"
export SAP_ROSTER=roster_sap_claude.json SAP_ALLOW_DUPLICATE_MODELS=1
python scripts/run_claude_only.py run1 docs/sap/bench_auto/hb_0/manifest.json
```

## Folder layout

All outside folders (private references, ABAP libraries, tools, work, loop evidence) sit under one base folder: `SAP_LOOP_BASE`, default the parent of this repository. Set `PAR_SATVIK_HOME` for the loop home. Bench `runner.json` and `manifest.json` paths: step 6.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `acceptance-invalid` with `FileNotFoundError` | Repeat steps 4 to 6 |
| Loop home is inside a git worktree | Set `SATVIK_HOME` outside the repository |
| Four claim tests fail | Unset `SATVIK_HOME` for tests |
| ABAP tests are skipped | Runtime paths are missing; repeat step 6 |
| `bad option: --permission` | Use Node 22.22.x |
| `preflight-failed` | Check the key and CLI sign-in; use `run_claude_only.py` for Claude-only rosters |
| Wrong models in a job | Check `SAP_ROSTER`; the plan and the job use the same roster file |
| `abort-original-differs` | `git checkout -- abap_work/<bench>` |
| `claim-conflict` | Use one checkout and one loop home per worker |
| `opus` role refused | `OPUS_ENABLED` in `scripts/source/opus_repair.py` is off by default |
