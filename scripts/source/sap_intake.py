"""Automatic bench intake: turn a public GitHub PR into a bench folder, or refuse it.

Usage: python scripts/source/sap_intake.py owner/repo PR [--out docs/sap/bench_auto]
           [--private DIR] [--projects DIR] [--work DIR] [--libs DIR] [--tools DIR]
Base folder (bench_private, bench/libs, abap_tools, work): env SAP_LOOP_BASE, else the parent of this repository.
Exit 0 admitted, 3 rejected (REJECTED.md written), 2 usage or network error.
Interface: docs/sap/AUTO_BENCH_CONTRACT.md section 1 and 2-A; gate: docs/sap/PASS_RULE.md (2026-11-17).

Network: public, unauthenticated GitHub only (api.github.com, raw.githubusercontent.com,
codeload.github.com). Nothing about the user or the local machine is ever sent.
The upstream fix and its changed lines are kept OUTSIDE the repo (bench_private/<id>/).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

BASE = Path(os.environ.get("SAP_LOOP_BASE") or ROOT.parent)     # holds bench_private/, bench/, abap_tools/, work/
DEFAULT_OUT = ROOT / "docs" / "sap" / "bench_auto"
DEFAULT_PRIVATE = BASE / "bench_private"
LIBS_DIR = BASE / "bench" / "libs"
TOOLS_DIR = BASE / "abap_tools"
LINT_DEPS_DIR = LIBS_DIR / "abaplint-deps"
TIMEOUT_S = 900
UA = "abap-bench-intake"  # generic on purpose: nothing about the user goes to GitHub


class Rejected(Exception):
    """The admission gate refused this PR; REJECTED.md has been written."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NetworkError(RuntimeError):
    """GitHub could not be reached, or the public rate limit was hit."""


class NotFound(NetworkError):
    """HTTP 404 for a URL (a file that does not exist at that commit)."""


class SandboxError(RuntimeError):
    """The sandbox could not transpile or run the job (message says why)."""


# ---------------------------------------------------------------- network

def _open(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotFound(f"404 for {url}") from exc
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if exc.code in (403, 429) and (remaining == "0" or exc.code == 429):
            reset = exc.headers.get("X-RateLimit-Reset", "?")
            raise NetworkError(
                f"GitHub public rate limit reached (unauthenticated, 60 requests per hour); "
                f"resets at unix time {reset}. Wait and run again."
            ) from exc
        raise NetworkError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkError(f"cannot reach {url}: {exc}") from exc


def default_fetch(url: str) -> str:
    """GET a public URL as text. Raises NotFound / NetworkError."""
    return _open(url).decode("utf-8", errors="replace")


# ---------------------------------------------------------------- parsing

def make_id(repo: str, pr: int) -> str:
    name = repo.split("/")[-1].lower()
    return re.sub(r"[^a-z0-9]+", "_", f"{name}_{pr}").strip("_")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lines(text: str) -> list[str]:
    return text.split("\n")


def method_ranges(text: str) -> list[tuple[str, int, int]]:
    """(lower-case name, first line, last line) of every METHOD ... ENDMETHOD block, 1-based."""
    out, cur = [], None
    for i, line in enumerate(_lines(text), 1):
        if cur is None:
            m = re.match(r"\s*METHOD\s+([\w~]+)\s*\.", line, re.I)
            if m:
                cur = (m.group(1).lower(), i)
        elif re.match(r"\s*ENDMETHOD\s*\.", line, re.I):
            out.append((cur[0], cur[1], i))
            cur = None
    return out


def parse_patch(patch: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """(added [(new line no, text)], removed [(old line no, text)]) from a unified diff."""
    added, removed, o, n = [], [], 0, 0
    for line in patch.split("\n"):
        line = line.rstrip("\r")
        if line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
            if m:
                o, n = int(m.group(1)), int(m.group(2))
        elif line.startswith("\\"):
            continue
        elif line.startswith("+"):
            added.append((n, line[1:]))
            n += 1
        elif line.startswith("-"):
            removed.append((o, line[1:]))
            o += 1
        else:
            o += 1
            n += 1
    return added, removed


def touched_methods(patch: str, base_text: str, fixed_text: str) -> list[str]:
    """Methods whose body the diff changed (added lines mapped on the fixed file, removed on the base)."""
    added, removed = parse_patch(patch)
    found: list[str] = []
    for pairs, text in ((added, fixed_text), (removed, base_text)):
        ranges = method_ranges(text)
        for no, _ in pairs:
            for name, a, b in ranges:
                if a <= no <= b and name not in found:
                    found.append(name)
    return found


def test_methods(text: str) -> list[str]:
    """FOR TESTING method names in file order (lower case, unique)."""
    out: list[str] = []
    for m in re.finditer(r"(?:\bMETHODS\s*:?|,)\s*(\w+)\s+FOR\s+TESTING", text, re.I):
        name = m.group(1).lower()
        if name not in out:
            out.append(name)
    return out


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[\w~]+", text)}


def calls_missing_methods(test_text: str, cls: str, base_text: str, fixed_text: str) -> list[str]:
    """Methods the tests call on the class under test that the fix introduces (absent pre-fix)."""
    cls_re = re.escape(cls)
    refs = {m.group(1).lower() for m in re.finditer(rf"\b{cls_re}\s*=>\s*(\w+)", test_text, re.I)}
    for v in re.finditer(rf"\b(\w+)\s+TYPE\s+REF\s+TO\s+{cls_re}\b", test_text, re.I):
        refs |= {m.group(1).lower() for m in re.finditer(rf"\b{re.escape(v.group(1))}\s*->\s*(\w+)", test_text, re.I)}
    base_w, fixed_w = _words(base_text), _words(fixed_text)
    return sorted(r for r in refs if r in fixed_w and r not in base_w)


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def _trivial(norm: str) -> bool:
    return len(norm) < 12 or norm.startswith(("*", '"'))


def fixed_line_fingerprints(bench_id: str, private_root=None, *, strict: bool = False) -> frozenset:
    """Normalised, non-trivial lines the upstream fix added (for the pre-send guard).
    A missing private file gives an empty set, unless strict: then FileNotFoundError, so a caller can tell 'no file' from 'no lines'."""
    path = Path(private_root or DEFAULT_PRIVATE) / bench_id / "fixed_lines.txt"
    if not path.exists():
        if strict:
            raise FileNotFoundError(f"no upstream-fix lines at {path}")
        return frozenset()
    norms = (_norm(l) for l in path.read_text(encoding="utf-8").splitlines())
    return frozenset(n for n in norms if n and not _trivial(n))


def prompt_has_fix_run(bench_id: str, prompt: str, run: int = 3, private_root=None) -> bool:
    """True when the prompt holds `run` or more consecutive upstream-fix lines (trivial lines are transparent)."""
    fp = fixed_line_fingerprints(bench_id, private_root)
    count = 0
    for line in prompt.splitlines():
        n = _norm(line)
        if not n or _trivial(n):
            continue
        count = count + 1 if n in fp else 0
        if count >= run:
            return True
    return False


# ---------------------------------------------------------------- sandbox

def _read_pkg_version(pkg: str) -> str:
    try:
        data = json.loads((TOOLS_DIR / "node_modules" / pkg / "package.json").read_text(encoding="utf-8"))
        return str(data.get("version", "?"))
    except (OSError, ValueError):
        return "?"


def tool_versions() -> dict:
    return {p: _read_pkg_version(p) for p in ("@abaplint/transpiler-cli", "@abaplint/runtime", "@abaplint/cli")}


def ensure_project(repo: str, base_sha: str, projects_root: Path, *, download=None, include=(), db=False) -> dict:
    """Project folder = the repo at base_sha (codeload zip), plus the runner cfg for abap_transpile_run.

    The transpile config is the repo's own (abap_transpile.json, else test/abap_transpile.json), else derived from abaplint.json(c).
    include = repo paths of the class under test (made sure the repo's input_filter lets them through); db = give the repo's
    own SQLite test setup back to the transpiler (in-memory database; off unless a run needed it).
    """
    proj = Path(projects_root) / f"{repo.split('/')[-1].lower()}_{base_sha[:10]}"
    marker = proj / ".intake_ready"
    if not marker.exists():
        if proj.exists():
            shutil.rmtree(proj, ignore_errors=True)
        data = (download or (lambda u: _open(u, "application/zip")))(f"https://codeload.github.com/{repo}/zip/{base_sha}")
        proj.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "src.zip"
            zpath.write_bytes(data)
            with zipfile.ZipFile(zpath) as z:
                for info in z.infolist():
                    parts = info.filename.split("/")[1:]  # drop the <repo>-<sha>/ top folder
                    if not parts or not parts[-1] or ".." in parts or ":" in info.filename or info.filename.startswith("/"):
                        continue
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:  # symlink: skip
                        continue
                    dest = proj.joinpath(*parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(info))
        marker.write_text(base_sha, encoding="utf-8")
    rel, raw = None, None
    for cand in ("abap_transpile.json", "test/abap_transpile.json"):
        if (proj / cand).exists():
            rel, raw = cand, json.loads((proj / cand).read_text(encoding="utf-8"))
            break
    if raw is None:  # no transpile config at this commit: derive one from the repo's abaplint config and src layout
        raw = fallback_config(proj)
        rel = "abap_transpile.json"
    raw = normalise_config(proj, raw)
    plain = pin_config(raw, LIBS_DIR, clone=_git_clone)
    pinned = pin_config(raw, LIBS_DIR, include=include, db=db, clone=_git_clone)
    auto_rel = rel.replace("abap_transpile.json", "abap_transpile.auto.json")
    if pinned != plain:  # per-class/db variant at the project root (never in an input folder: the transpiler would read it as source)
        auto_rel = "abap_transpile.auto.x" + hashlib.sha1(json.dumps(pinned, sort_keys=True).encode()).hexdigest()[:8] + ".json"
    (proj / auto_rel).write_text(json.dumps(pinned, indent=1), encoding="utf-8")
    return {
        "project_dir": str(proj), "libs_dir": str(LIBS_DIR), "tools_dir": str(TOOLS_DIR),
        "config": auto_rel, "lint_deps_dir": str(LINT_DEPS_DIR),
    }


def normalise_config(proj: Path, raw: dict) -> dict:
    """Bridge a repo's own transpile config to the installed transpiler (older repos use older keys and build steps).

    - `lib` (one url, 2021 key) becomes `libs`.
    - an input_folder that the repo only creates in a build step (abaplint-fix `downport` copy of src) falls back to src (+ deps), programs excluded.
    - a `skip` entry without `method` (newer transpilers skip the whole class; this one crashes on it) is expanded to the class's FOR TESTING methods.
    """
    cfg = json.loads(json.dumps(raw))
    if isinstance(cfg.get("lib"), str):
        cfg.setdefault("libs", [{"url": cfg["lib"]}])
        cfg.pop("lib")
    folders = cfg.get("input_folder") or ["src"]
    folders = [folders] if isinstance(folders, str) else list(folders)
    missing = [f for f in folders if not re.search(r"[*{]", f) and not (proj / f).is_dir()]
    if missing:
        cfg["input_folder"] = [f for f in folders if f not in missing] or ["src"] + (["deps"] if (proj / "deps").is_dir() else [])
        cfg["exclude_filter"] = list(cfg.get("exclude_filter") or []) + [r"\.prog\."]
    skip = (cfg.get("options") or {}).get("skip")
    if skip and any("method" not in e for e in skip):
        expanded = []
        for e in skip:
            if "method" in e:
                expanded.append(e)
                continue
            for tf in proj.glob(f"**/{str(e.get('object', '')).lower()}.clas.testclasses.abap"):
                text = tf.read_text(encoding="utf-8", errors="replace")
                blk = re.search(rf"CLASS\s+{re.escape(str(e.get('class', '')))}\s+DEFINITION(.*?)ENDCLASS\.", text, re.I | re.S)
                expanded += [{**e, "method": m} for m in test_methods(blk.group(1))] if blk else []
        cfg["options"]["skip"] = expanded
    return cfg


def _jsonc(text: str):
    """json.loads for abaplint.jsonc: strips // and /* */ comments (outside strings) and trailing commas."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True; out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            i = text.find("*/", i + 2)
            i = n if i < 0 else i + 2
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def fallback_config(proj: Path) -> dict:
    """Transpile config for a repo that has none: sources = the folders of abaplint's global.files (else src), open-abap-core as runtime library."""
    files = []
    for name in ("abaplint.json", "abaplint.jsonc"):
        if (proj / name).exists():
            try:
                g = _jsonc((proj / name).read_text(encoding="utf-8")).get("global", {}).get("files", "")
            except ValueError:
                g = ""
            files = [g] if isinstance(g, str) else list(g)
            break
    folders = []
    for f in files:
        d = f.lstrip("/").split("*")[0].rstrip("/")
        if d and (proj / d).is_dir() and d not in folders:
            folders.append(d)
    folders = [d for d in folders if not any(o != d and d.startswith(o + "/") for o in folders)] or ["src"]
    return {
        "input_folder": folders, "output_folder": "output",
        "exclude_filter": [r"\.prog\.", r"\.fugr\."],  # programs and function groups need SAP-only tables; classes are what the tests exercise
        "libs": [{"url": "https://github.com/open-abap/open-abap-core"}],
        "write_unit_tests": True, "write_source_map": True,
        "options": {"ignoreSyntaxCheck": False, "addFilenames": True, "addCommonJS": True, "unknownTypes": "runtimeError"},
    }


def _git_clone(url: str, dest: Path) -> None:
    """Fetch a public library repo into bench/libs (host side, at intake; never inside the sandbox)."""
    import subprocess
    if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+?(\.git)?", url):
        raise SandboxError(f"library url is not a public github.com repo: {url}")
    r = subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise SandboxError(f"cannot clone library {url}: {r.stderr.strip()[-200:]}")
    shutil.rmtree(Path(dest) / ".git", ignore_errors=True)


# Libraries the hand-built benches (D, F, B, C) left out of the pinned config; abapGit-web-classic is dropped in D's.
DROP_LIBS = {"abapgit-web-classic"}


def pin_config(config: dict, libs_dir: Path, *, include=(), db: bool = False, clone=None) -> dict:
    """Deterministic transform repo config -> pinned config (what bench D/F/B/C hand-built).

    Libraries become local folders ../libs/<name> (a missing local library is a SandboxError, never a fetch);
    ignoreSyntaxCheck on, keywords added, `setup` becomes `extraSetup` (same file), populateTables dropped.
    input_filter, skip list and everything else stay as the repo has them.
    """
    cfg = json.loads(json.dumps(config))
    libs, seen = [], set()
    for lib in cfg.get("libs") or []:
        src = lib.get("url") or lib.get("folder") or ""
        name = src.rstrip("/").split("/")[-1]
        if name.lower() in DROP_LIBS or name in seen:
            continue
        seen.add(name)
        if not (Path(libs_dir) / name).is_dir() and clone is not None and lib.get("url"):
            clone(lib["url"], Path(libs_dir) / name)
        if not (Path(libs_dir) / name).is_dir():
            raise SandboxError(f"required library '{name}' is not in {libs_dir}; add it there (nothing is fetched inside the sandbox)")
        entry = {k: v for k, v in lib.items() if k != "url"}
        entry["folder"] = f"../libs/{name}"
        libs.append(entry)
    for extra in ("open-abap-gui", "open-abap-seo"):  # B, F and D carry both; the current open-abap-core no longer has the SEO types or CL_SALV_* old repos use
        if ({"open-abap-core", "open-abap"} & seen) and extra not in seen and (Path(libs_dir) / extra).is_dir():
            libs.append({"folder": f"../libs/{extra}"})
    if libs:
        cfg["libs"] = libs
    opts = cfg.setdefault("options", {})
    opts["ignoreSyntaxCheck"] = True
    opts.setdefault("keywords", ["return", "in", "class", "arguments"])
    setup = opts.pop("setup", None)
    if isinstance(setup, dict) and "extraSetup" not in opts:
        opts["extraSetup"] = setup.get("filename")
    opts.pop("populateTables", None)
    if db and opts.get("extraSetup"):  # the repo's setup file opens its SQLite database; this transpiler only knows `setup`, not `extraSetup`
        opts["setup"] = {"filename": opts.pop("extraSetup"), "preFunction": "setup"}
    flt = cfg.get("input_filter")
    for rel in include:  # input_filter is a WHITELIST (a file must match one entry): let the class under test and its tests in
        if flt and not any(_matches(p, rel) for p in flt):
            flt.append(re.escape(Path(rel).name.split(".")[0]) + r"\.")
    return cfg


def _matches(pattern: str, path: str) -> bool:
    try:
        return re.search(pattern, path, re.I) is not None
    except re.error:
        return False


def make_default_sandbox(projects_root: Path):
    """The default sandbox callable: the existing confined transpile runner on a project checkout.

    job = {repo, base_sha, production_file, production_text, test_files {rel: text}, only_object, label}
    returns {"LTCL_X->method": "PASS" | "FAIL: ..."}; raises SandboxError when it cannot run.
    """
    import abap_transpile_run as t

    state = {"db": False}  # set once a run needed the repo's SQLite setup; later runs of this intake keep it

    def run(job: dict, db: bool) -> dict:
        cfg = dict(ensure_project(job["repo"], job["base_sha"], projects_root, include=(job["production_file"],), db=db))
        cfg["only_object"] = job["only_object"]
        files = {job["production_file"]: job["production_text"], **job["test_files"]}
        with tempfile.TemporaryDirectory() as tmp:
            edited = {}
            for i, (rel, text) in enumerate(files.items()):
                p = Path(tmp) / f"f{i}.abap"
                p.write_text(text, encoding="utf-8", newline="")
                edited[rel] = p
            return t.run_abap_tests(cfg, edited, timeout_s=TIMEOUT_S, trusted=tuple(files))

    def sandbox(job: dict) -> dict:
        try:
            try:
                return run(job, state["db"])
            except t.RunnerError as first:
                # The runner keeps only the tail of the error, so "database not initialized" cannot be recognised by text:
                # retry once with the repo's own SQLite setup when that makes a different config; report the FIRST error if it still fails.
                inc = (job["production_file"],)
                same = (ensure_project(job["repo"], job["base_sha"], projects_root, include=inc, db=True)["config"]
                        == ensure_project(job["repo"], job["base_sha"], projects_root, include=inc, db=False)["config"])
                if state["db"] or same:
                    raise
                try:
                    res = run(job, True)
                except t.RunnerError:
                    raise first from None
                state["db"] = True
                return res
        except (t.AbapTextRefused, t.RunnerError, NetworkError) as exc:
            raise SandboxError(f"{type(exc).__name__}: {exc}") from exc

    sandbox.state = state
    return sandbox


# ---------------------------------------------------------------- intake

def _reject(bench_dir: Path, repo: str, pr: int, reason: str, what: str = ""):
    bench_dir.mkdir(parents=True, exist_ok=True)
    (bench_dir / "manifest.json").unlink(missing_ok=True)
    (bench_dir / "REJECTED.md").write_text(
        f"# Rejected: {repo} {what or f'PR {pr}'}\n\n{reason}\n\nThe admission gate (docs/sap/PASS_RULE.md, 2026-11-17) "
        f"refuses; it is never relaxed.\n\nChecked: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )
    raise Rejected(reason)


def _json(fetch, url):
    try:
        return json.loads(fetch(url))
    except ValueError as exc:
        raise NetworkError(f"not JSON: {url}") from exc


def _pr_files(fetch, repo, pr):
    files, page = [], 1
    while True:
        chunk = _json(fetch, f"https://api.github.com/repos/{repo}/pulls/{pr}/files?per_page=100&page={page}")
        files += chunk
        if len(chunk) < 100:
            return files
        page += 1


def _raw(fetch, repo, sha, path):
    try:
        return fetch(f"https://raw.githubusercontent.com/{repo}/{sha}/{path}")
    except NotFound:
        return None


_LINK = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?\s+(?:https?://github\.com/([\w.-]+/[\w.-]+)/issues/|([\w.-]+/[\w.-]+)?#)(\d+)", re.I)


def intake(repo, pr, out_root, *, fetch=None, sandbox=None, private_root=None, work_root=None, projects_root=None,
           _id=None, _what="", _commit=None, _link=_LINK) -> dict:
    """Build the bench folder for a merged public PR, or raise Rejected (REJECTED.md written).

    The underscore arguments are used by intake_commit (commit mode) only; PR mode never sets them.
    """
    fetch = fetch or default_fetch
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError(f"repo must look like owner/name: {repo!r}")
    pr = int(pr)
    bench_id = _id or make_id(repo, pr)
    out_root = Path(out_root)
    bench_dir = out_root / bench_id
    private_dir = Path(private_root or DEFAULT_PRIVATE) / bench_id
    if work_root is None:
        work_root = ROOT / "abap_work" if ROOT in out_root.resolve().parents else out_root.parent / "abap_work"
    reject = lambda why: _reject(bench_dir, repo, pr, why, _what)  # noqa: E731

    pr_data = _json(fetch, f"https://api.github.com/repos/{repo}/pulls/{pr}")
    merge_sha = pr_data.get("merge_commit_sha")
    if not pr_data.get("merged") or not merge_sha:
        reject("the PR is not merged, so there is no upstream fix to hold out")
    commit = _json(fetch, f"https://api.github.com/repos/{repo}/commits/{merge_sha}")
    parents = commit.get("parents") or []
    if not parents:
        reject("the merge commit has no parent")
    base_sha = parents[0]["sha"]

    # ---- files: exactly one production class file, its test file beside it
    prod, tests, bad = [], [], []
    for f in _pr_files(fetch, repo, pr):
        name = f["filename"]
        if not name.endswith(".abap"):
            continue
        base = name.rsplit("/", 1)[-1]
        if base.endswith(".testclasses.abap"):
            tests.append(f)
        elif name.startswith("test/") or "/test/" in name:
            bad.append(f"test support file outside src: {name}")
        else:
            prod.append(f)
    if len(prod) != 1:
        reject(f"the PR changes {len(prod)} production .abap files ({', '.join(p['filename'] for p in prod) or 'none'}); exactly one is required")
    pf = prod[0]
    prod_path = pf["filename"]
    m = re.fullmatch(r"(.*/)?([\w#]+)\.clas\.abap", prod_path)
    if not m:
        reject(f"the fix is not in a main class file (.clas.abap): {prod_path}")
    cls_dir, cls = m.group(1) or "", m.group(2)
    if pf.get("status") != "modified" or not pf.get("patch"):
        reject(f"the production file is {pf.get('status')} / has no readable diff: {prod_path}")
    if bad:
        reject("; ".join(bad))
    if not tests:
        reject("the PR changes no unit-test file")
    for tf in tests:
        if tf["filename"] != f"{cls_dir}{cls}.clas.testclasses.abap":
            reject(f"test file is not beside the class in src: {tf['filename']}")
    if len(tests) > 1:
        reject("more than one test file changed")
    tf = tests[0]
    test_path = tf["filename"]

    base_prod = _raw(fetch, repo, base_sha, prod_path)
    fixed_prod = _raw(fetch, repo, merge_sha, prod_path)
    fixed_test = _raw(fetch, repo, merge_sha, test_path)
    base_test = _raw(fetch, repo, base_sha, test_path) or ""
    if base_prod is None or fixed_prod is None or fixed_test is None:
        reject("a production or test file could not be read at the base or merge commit")

    new_methods = [x for x in test_methods(fixed_test) if x not in test_methods(base_test)]
    if len(new_methods) < 2:
        reject(f"fewer than two new test methods ({len(new_methods)}), or no held-out left")

    allowed = touched_methods(pf["patch"], base_prod, fixed_prod)
    if not allowed:
        reject("the diff changes no method body of the production class")

    # ---- static gate
    for label, text in (("base", base_prod), ("fix", fixed_prod), ("tests", fixed_test)):
        if re.search(r"@\s*KERNEL", text, re.I):
            reject(f"{label} file contains @KERNEL")
    import abap_transpile_run as t
    # 2026-11-17: the loop's refusal list applies to the lines a model ADDS, never to code that already exists (real classes use CALL METHOD, SUBMIT, DEFINE).
    # The old gate refused 25 of 33 real candidates for pre-existing constructs. Only the lines the upstream fix adds are checked here (a quick screen; the
    # generated acceptance's own check of added lines, run by the oracle check, is the authority).
    base_lines = set(base_prod.splitlines())
    added_text = chr(10).join(l for l in fixed_prod.splitlines() if l not in base_lines)
    problems = t.check_abap_text(added_text)
    if problems:
        reject("the lines the upstream fix adds would be refused by the loop's own text check: " + "; ".join(problems))
    missing = calls_missing_methods(fixed_test, cls, base_prod, fixed_prod)
    if missing:
        reject("the tests call method(s) that do not exist before the fix: " + ", ".join(missing))

    # ---- sandbox gate
    projects_root = Path(projects_root or Path(private_root or DEFAULT_PRIVATE).parent / "bench" / "auto").resolve()     # absolute: the sandbox work folder is elsewhere
    default_sb = sandbox is None
    if default_sb:
        sandbox = make_default_sandbox(projects_root)
    job = {"repo": repo, "base_sha": base_sha, "production_file": prod_path, "production_text": base_prod,
           "test_files": {test_path: fixed_test}, "only_object": cls.upper(), "label": "base"}
    try:
        base_res = sandbox(job)
    except SandboxError as exc:
        reject(f"the pre-fix code does not transpile or run: {exc}")
    base_fails = sorted(k for k, v in base_res.items() if v != "PASS")
    failing_new = [n for n in new_methods if any(k.lower().endswith("->" + n) for k in base_fails)]
    if not failing_new:
        reject("no new test method fails on the pre-fix code")
    # held-out rule: the first base-failing new method (file order) is always acceptance; of the rest, every second one
    # (the first remaining, the third, ...) is held out. With the first new method failing this equals new_methods[1::2].
    rest = [n for n in new_methods if n != failing_new[0]]
    heldout = rest[0::2]
    if not heldout:
        reject("fewer than two new test methods, or no held-out left")
    try:
        fix_res = sandbox({**job, "production_text": fixed_prod, "label": "fix"})
    except SandboxError as exc:
        reject(f"the upstream fix does not transpile or run: {exc}")
    not_passing = sorted(k for k, v in fix_res.items() if v != "PASS")
    if not_passing:
        reject("tests that do not pass on the upstream fix: " + ", ".join(not_passing))
    ran = {k.lower().rsplit("->", 1)[-1] for k in fix_res}
    if [n for n in new_methods if n not in ran]:
        reject("new test methods that did not run on the upstream fix: " + ", ".join(n for n in new_methods if n not in ran))

    # ---- admitted: ticket, files, manifest
    ticket, label, source = None, "SEMI-GUIDED", "pr_body"
    body = pr_data.get("body") or ""
    link = _link.search(body)
    if link:
        irepo = link.group(1) or link.group(2) or repo
        try:
            issue = _json(fetch, f"https://api.github.com/repos/{irepo}/issues/{link.group(3)}")
        except NotFound:
            issue = {}
        if "pull_request" not in issue and (issue.get("body") or "").strip():
            ticket, label, source = issue["body"], "BLIND", "issue"
    if ticket is None:
        ticket = body
    if not ticket.strip():
        reject("neither a linked issue nor the PR body gives a ticket text")

    bench_dir.mkdir(parents=True, exist_ok=True)
    (bench_dir / "REJECTED.md").unlink(missing_ok=True)
    (bench_dir / "ticket.md").write_text(ticket, encoding="utf-8", newline="")
    stored = f"tests_upstream/{test_path.rsplit('/', 1)[-1]}"
    (bench_dir / stored).parent.mkdir(parents=True, exist_ok=True)
    (bench_dir / stored).write_text(fixed_test, encoding="utf-8", newline="")
    work_rel = f"abap_work/{bench_id}/{prod_path.rsplit('/', 1)[-1]}"
    work_file = Path(work_root) / bench_id / prod_path.rsplit("/", 1)[-1]
    work_file.parent.mkdir(parents=True, exist_ok=True)
    work_file.write_text(base_prod, encoding="utf-8", newline="")

    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / "fixed.abap").write_text(fixed_prod, encoding="utf-8", newline="")
    added, _ = parse_patch(pf["patch"])
    fixed_lines = [l.strip() for _, l in added if l.strip()]
    (private_dir / "fixed_lines.txt").write_text("\n".join(fixed_lines) + "\n", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # runner = a cfg that abap_transpile_run.run_abap_tests accepts (plus "project"); ensure_project is cached after the gate
    if default_sb:
        cfg = ensure_project(repo, base_sha, projects_root, include=(prod_path,), db=sandbox.state["db"])
    else:
        cfg = {"project_dir": str(projects_root / f"{repo.split('/')[-1].lower()}_{base_sha[:10]}"), "libs_dir": str(LIBS_DIR),
               "tools_dir": str(TOOLS_DIR), "config": "abap_transpile.json", "lint_deps_dir": str(LINT_DEPS_DIR)}
    manifest = {
        "schema": 1, "id": bench_id, "repo": repo, "pr": pr, **({"commit": merge_sha} if _commit else {}),
        "base_sha": base_sha, "merge_sha": merge_sha,
        "label": label, "ticket_source": source,
        "production_file": prod_path, "work_file": work_rel, "original_sha256": _sha(base_prod),
        "test_files": [{"path": test_path, "stored": stored, "sha256": _sha(fixed_test),
                        "new_methods": new_methods, "heldout_methods": heldout}],
        "allowed_methods": allowed,
        "runner": {"project": cfg.get("project_dir", ""), **cfg, "only_object": cls.upper(), "repo": repo, "base_sha": base_sha},
        "gate": {"base_transpiles": True, "base_fails": base_fails, "fix_passes": True,
                 "heldout_fails_on_base": all(h in failing_new for h in heldout), "checked_utc": now,
                 "tool_versions": tool_versions()},
        "created_utc": now,
    }
    (bench_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


# ---------------------------------------------------------------- commit mode

MINE_ROOT = BASE / "work" / "mine"
# Issue references of a commit message (fix #N, closes #N, issue #N, bug #N); same groups as _LINK.
_COMMIT_LINK = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|issue|bug)\s*:?\s+(?:https?://github\.com/([\w.-]+/[\w.-]+)/issues/|([\w.-]+/[\w.-]+)?#)(\d+)", re.I)


def make_commit_id(repo: str, sha: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", f"{repo.split('/')[-1].lower()}_{sha[:8].lower()}").strip("_")


def _local_git(clone: Path, *args) -> bytes | None:
    import subprocess
    p = subprocess.run(["git", *args], cwd=clone, capture_output=True, timeout=300)
    return p.stdout if p.returncode == 0 else None


def _commit_fetch(repo, sha, *, fetch, clone):
    """Answer the PR-mode URLs for ONE commit (pr number 0): from a local clone when there is one, else the commits API.

    Only issue lookups reach `fetch` in local mode, and a rate limit or network error there becomes an empty issue
    (the ticket then falls back to the commit message, labelled SEMI-GUIDED).
    """
    cache = {}

    def info():
        if "i" not in cache:
            if clone is not None:
                full = (_local_git(clone, "rev-parse", "--verify", f"{sha}^{{commit}}") or b"").decode().strip()
                if not full:
                    raise NotFound(f"commit {sha} not in the local clone")
                parent = (_local_git(clone, "rev-parse", "--verify", f"{full}^") or b"").decode().strip()
                msg = (_local_git(clone, "show", "-s", "--format=%B", full) or b"").decode("utf-8", "replace").strip()
                ns = (_local_git(clone, "diff", "--name-status", "--no-renames", f"{full}^", full) if parent else b"") or b""
                files = []
                for line in ns.decode("utf-8", "replace").splitlines():
                    st, _, path = line.partition("\t")
                    patch = ""
                    if path.endswith(".abap") and st[:1] == "M":
                        raw = (_local_git(clone, "diff", "--no-renames", f"{full}^", full, "--", path) or b"").decode("utf-8", "replace")
                        patch = raw[raw.find("@@"):] if "@@" in raw else ""
                    files.append({"filename": path, "status": {"M": "modified", "A": "added", "D": "removed"}.get(st[:1], st), "patch": patch})
                cache["i"] = {"sha": full, "parents": [{"sha": parent}] if parent else [], "message": msg, "files": files}
            else:
                c = _json(fetch, f"https://api.github.com/repos/{repo}/commits/{sha}")
                cache["i"] = {"sha": c["sha"], "parents": c.get("parents") or [], "message": (c.get("commit") or {}).get("message", ""),
                              "files": c.get("files") or []}
        return cache["i"]

    def answer(url: str) -> str:
        i = info()
        if re.search(r"/pulls/0$", url):
            return json.dumps({"merged": True, "merge_commit_sha": i["sha"], "body": i["message"]})
        if re.search(r"/commits/[0-9a-f]+$", url):
            return json.dumps({"parents": i["parents"]})
        if "/pulls/0/files" in url:
            return json.dumps(i["files"] if url.endswith("&page=1") else [])
        if url.startswith("https://raw.githubusercontent.com/"):
            m = re.fullmatch(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/([0-9a-f]+)/(.+)", url)
            if clone is not None and m:
                data = _local_git(clone, "show", f"{m.group(1)}:{m.group(2)}")
                if data is None:
                    raise NotFound(f"404 for {url}")
                return data.decode("utf-8", errors="replace")
            return fetch(url)
        if "/issues/" in url:
            try:
                return fetch(url)
            except NetworkError as exc:
                if isinstance(exc, NotFound):
                    raise
                return "{}"
        raise NetworkError(f"unexpected URL in commit mode: {url}")
    return answer


def intake_commit(repo, sha, out_root, *, fetch=None, sandbox=None, private_root=None, work_root=None, projects_root=None,
                  mine_root=None) -> dict:
    """Build a bench from ONE commit that fixes a bug and adds tests (no PR): base = first parent, tests = files at the commit.

    Same gate, held-out rule and private storage as PR mode. The ticket is the body of the issue the commit message
    references (one public GitHub GET; BLIND), else the commit message (SEMI-GUIDED). Bench id `<repo-name>_<sha[:8]>`,
    manifest `pr` 0 plus a `commit` field. Uses a local clone in <mine_root>/<name> when it exists and no `fetch` is injected.
    """
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError(f"repo must look like owner/name: {repo!r}")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
        raise ValueError(f"sha must be 7 to 40 hex characters: {sha!r}")
    sha = sha.lower()
    clone = Path(mine_root or MINE_ROOT) / repo.split("/")[-1]
    clone = clone if (fetch is None and ((clone / ".git").exists() or (clone / "HEAD").exists())) else None
    api = fetch or default_fetch
    answer = _commit_fetch(repo, sha, fetch=api, clone=clone)
    try:
        return intake(repo, 0, out_root, fetch=answer, sandbox=sandbox, private_root=private_root, work_root=work_root,
                      projects_root=projects_root, _id=make_commit_id(repo, sha), _what=f"commit {sha[:8]}", _commit=True,
                      _link=_COMMIT_LINK)
    except NotFound as exc:
        raise NetworkError(f"commit {sha} not found for {repo}: {exc}") from exc


def main(argv=None) -> int:
    global LIBS_DIR, TOOLS_DIR, LINT_DEPS_DIR
    ap = argparse.ArgumentParser(description="Build an automatic bench from a merged public PR (owner/repo PR) or a commit (owner/repo@sha).")
    ap.add_argument("repo")
    ap.add_argument("pr", type=int, nargs="?")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--private", default=str(DEFAULT_PRIVATE))
    ap.add_argument("--work", default=None, help="where the work file copy goes (default: abap_work beside the repo)")
    ap.add_argument("--projects", default=None, help="where the base-commit project checkouts go (default: <private>/../bench/auto)")
    ap.add_argument("--libs", default=str(LIBS_DIR), help="bench libraries folder (abaplint-deps lives in it)")
    ap.add_argument("--tools", default=str(TOOLS_DIR), help="ABAP tools folder (its node_modules)")
    a = ap.parse_args(argv)
    LIBS_DIR, TOOLS_DIR = Path(a.libs), Path(a.tools)
    LINT_DEPS_DIR = LIBS_DIR / "abaplint-deps"
    try:
        if "@" in a.repo:
            repo, _, sha = a.repo.partition("@")
            m = intake_commit(repo, sha, a.out, private_root=a.private, work_root=a.work, projects_root=a.projects)
        elif a.pr is None:
            ap.error("a PR number is required (or use owner/repo@sha)")
        else:
            m = intake(a.repo, a.pr, a.out, private_root=a.private, work_root=a.work, projects_root=a.projects)
    except Rejected as exc:
        print(f"REJECTED: {exc.reason}")
        return 3
    except (NetworkError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"ADMITTED {m['id']} ({m['label']}); new tests {m['test_files'][0]['new_methods']}; held out {m['test_files'][0]['heldout_methods']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
