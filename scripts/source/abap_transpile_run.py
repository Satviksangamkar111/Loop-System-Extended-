"""Run ABAP unit tests of a project through the abaplint transpiler, confined.

ponytail: Node's permission model blocks file writes, child processes and reads
outside the work folder, but NOT network access; the static check and the
key-less environment are the other layers.
"""

import copy
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import loop_home

# Defence in depth only: blocks outbound networking inside the node process.
# Not a security boundary; the OS firewall / container rule is. See docs/sap/SANDBOX_NETWORK.md.
NET_GUARD_PRELOAD = str(Path(__file__).resolve().parent / "net_guard_preload.js")
SLOT_ENV = "SAP_TRANSPILE_SLOTS"
SLOT_DEFAULT = 2


class AbapTextRefused(ValueError):
    """Raised when model-written ABAP text contains a refused construct."""


class RunnerError(RuntimeError):
    """Raised when the transpile or test-run pipeline fails."""


_OUTPUT_CAP = 2_000_000

_CONSTRUCTS = [
    (r"\bCALL\s+FUNCTION\b", "CALL FUNCTION"),
    (r"\bOPEN\s+DATASET\b", "OPEN DATASET"),
    (r"\bDELETE\s+DATASET\b", "DELETE DATASET"),
    (r"\bREAD\s+DATASET\b", "READ DATASET"),
    (r"\bTRANSFER\s", "TRANSFER"),
    (r"\bSUBMIT\b", "SUBMIT"),
    (r"\bCALL\s+TRANSACTION\b", "CALL TRANSACTION"),
    (r"\bGENERATE\s+SUBROUTINE\b", "GENERATE SUBROUTINE"),
    (r"\bINSERT\s+REPORT\b", "INSERT REPORT"),
    (r"\bEXEC\s+SQL\b", "EXEC SQL"),
    (r"\bCALL\s*'[^']+'", "CALL 'SYSTEM'"),
    (r"\bCALL\s+METHOD\s*\(", "CALL METHOD"),
    (r"->\(", "->("),
    (r"\bDEFINE\b", "DEFINE"),
    (r"CREATE\s+OBJECT\b.*?\bTYPE\s*\(", "CREATE OBJECT ... TYPE ("),
    (r"\bCALL\s+METHOD\b.*?->\s*\(", "CALL METHOD ...->("),
    (r"=>\s*\(", "=>("),
    (r"\bDESTINATION\b", "DESTINATION"),
    (r"\bSYSTEM-CALL\b", "SYSTEM-CALL"),
    (r"\bLEAVE\s+TO\s+TRANSACTION\b", "LEAVE TO TRANSACTION"),
]

_HTTP_PREFIXES = ("CL_HTTP", "IF_HTTP", "CL_WEB_HTTP", "CL_GUI_FRONTEND")

_PASS_RE = re.compile(r"^PASS\s+(\S+)\s*$")
_FAIL_RE = re.compile(r"^FAIL\s+(\S+)\s*::\s*(.*?)\s*$")

_ANCHOR_LOOP = "  for (const st of getData()) {"
_ANCHOR_CALL = "        await test.FRIENDS_ACCESS_INSTANCE[m.name]();"
_ANCHOR_RUN = "run().then(() => {"

_SKIP_NAMES = {".git", "node_modules", "output", ".github"}


def _strip_comments(line: str) -> str:
    """Return the line with ABAP comment text removed.

    A line whose first character is "*" is a full comment line. Everything
    from a `"` that is outside a single-quoted literal to end of line is a
    comment. Backtick-quoted and |...| template literals are tracked so a
    `"` inside them does not start a comment; inside |...| a backslash
    escapes the next character.
    """
    if line[:1] == "*":
        return ""
    out: list[str] = []
    i = 0
    n = len(line)
    literal = False
    backtick = False
    pipe = False
    while i < n:
        ch = line[i]
        if literal:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and line[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                literal = False
            i += 1
        elif backtick:
            out.append(ch)
            if ch == "`":
                backtick = False
            i += 1
        elif pipe:
            out.append(ch)
            if ch == "\\":
                i += 1
                if i < n:
                    out.append(line[i])
                    i += 1
                continue
            if ch == "|":
                pipe = False
            i += 1
        elif ch == "'":
            literal = True
            out.append(ch)
            i += 1
        elif ch == "`":
            backtick = True
            out.append(ch)
            i += 1
        elif ch == "|":
            pipe = True
            out.append(ch)
            i += 1
        elif ch == '"':
            break
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def check_abap_text(text: str) -> list[str]:
    """Refuse dangerous ABAP constructs; return one problem string per match."""
    cleaned = "\n".join(_strip_comments(line) for line in text.splitlines())
    # Normalize chain syntax so CALL: FUNCTION and OPEN: DATASET are caught.
    cleaned = cleaned.replace(":", " ")
    problems: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        problem = f"refused construct: {label}"
        if problem not in seen:
            seen.add(problem)
            problems.append(problem)

    flags = re.IGNORECASE | re.DOTALL
    for pattern, construct in _CONSTRUCTS:
        if construct is not None and re.search(pattern, cleaned, flags):
            add(construct)

    # JavaScript injection: the transpiler turns WRITE '@KERNEL ...' into raw JS, which can fake the tests and reach the network (Opus audit C1)
    if re.search(r"@\s*KERNEL", text, re.IGNORECASE):
        add("@KERNEL (raw JavaScript)")
    if re.search(r"\bWRITE\b[\s:]*['`|]\s*@", cleaned, re.IGNORECASE):
        add("WRITE of a literal starting with @")

    # Obfuscated HTTP-ish identifiers: strip quotes, && and spaces first so
    # split-up identifiers such as cl_'http'_client still surface.
    compact = re.sub(r"[\s'\"&]+", "", cleaned)
    tokens = [tok.lower() for tok in re.findall(r"\w+", compact)]
    low_cleaned = cleaned.lower()
    low_compact = compact.lower()
    for prefix in _HTTP_PREFIXES:
        pl = prefix.lower()
        if (
            any(tok.startswith(pl) for tok in tokens)
            or pl in low_compact
            or pl in low_cleaned
        ):
            add(prefix)

    return problems


def build_node_command(
    node: str, script_args: list[str], read_paths: list[str], preload: str | None = None
) -> list[str]:
    """Build a confined Node permission-model command. With `preload`, the guard file is read-granted and loaded first."""
    preload_args = [f"--allow-fs-read={preload}", "--require", preload] if preload else []
    return [node, "--permission"] + [f"--allow-fs-read={p}" for p in read_paths] + preload_args + list(script_args)


def build_transpile_command(
    node: str, entry: str, config: str, read_paths: list[str], write_path: str, preload: str | None = None
) -> list[str]:
    """Build a confined Node permission-model command for the transpiler CLI."""
    preload_args = [f"--allow-fs-read={preload}", "--require", preload] if preload else []
    return (
        [node, "--permission"]
        + [f"--allow-fs-read={p}" for p in read_paths]
        + preload_args
        + [f"--allow-fs-write={write_path}", entry, config]
    )


def slot_count() -> int:
    """Concurrent transpile runs allowed across all processes (env SAP_TRANSPILE_SLOTS, default 2)."""
    raw = os.environ.get(SLOT_ENV, "").strip()
    if not raw:
        return SLOT_DEFAULT
    try:
        n = int(raw)
    except ValueError as exc:
        raise RunnerError(f"{SLOT_ENV} must be a whole number, got {raw!r}") from exc
    if n < 1:
        raise RunnerError(f"{SLOT_ENV} must be at least 1, got {n}")
    return n


@contextmanager
def transpile_slot(home_dir=None, poll_s: float = 0.5):
    """Hold one of N cross-process slots (lock files under the loop home) for the heavy transpile+run step.

    Each slot is an OS byte-range lock (loop_home._os_lock), so it is released by the kernel when the holder
    dies. Called before the run's own timer starts, so time spent waiting never counts against timeout_s.
    ponytail: polls every 0.5 s and has no fairness; a queue file if waits ever get long.
    """
    n = slot_count()
    root = Path(home_dir) if home_dir is not None else _slot_home()
    root.mkdir(parents=True, exist_ok=True)
    while True:
        for i in range(n):
            stack = ExitStack()
            try:
                stack.enter_context(loop_home._os_lock(root / f"transpile_slot{i}.lock", timeout_s=0.05))
            except loop_home.LockTimeout:
                stack.close()
                continue
            with stack:
                yield i
            return
        time.sleep(poll_s)


def _slot_home() -> Path:
    """The loop home, or a machine-wide fallback folder when SATVIK_HOME is unset (same on every process of this machine)."""
    try:
        return loop_home.home(fallback=Path(tempfile.gettempdir()) / "satvik-loop-home")
    except loop_home.LoopHomeError as exc:
        raise RunnerError(f"transpile slot lock: {exc}") from exc


def parse_results(stdout: str, nonce: str | None = None) -> dict[str, str]:
    """Parse PASS/FAIL result lines into {name: status}.

    A PASS never replaces an earlier FAIL for the same name; a later FAIL
    still replaces an earlier PASS. With a nonce only lines tagged with
    PASS@<nonce> / FAIL@<nonce> are accepted.
    """
    if nonce is None:
        pass_re = _PASS_RE
        fail_re = _FAIL_RE
    else:
        pt = re.escape(nonce)
        pass_re = re.compile(rf"^PASS@{pt}\s+(\S+)\s*$")
        fail_re = re.compile(rf"^FAIL@{pt}\s+(\S+)\s*::\s*(.*?)\s*$")
    results: dict[str, str] = {}
    for line in stdout.splitlines():
        m = pass_re.match(line)
        if m:
            name = m.group(1)
            if name not in results or not results[name].startswith("FAIL:"):
                results[name] = "PASS"
            continue
        m = fail_re.match(line)
        if m:
            results[m.group(1)] = "FAIL: " + m.group(2)
    return results


def patch_runner(text: str, nonce: str | None = None) -> str:
    """Patch the generated abaplint runner; each anchor must occur exactly once."""
    if nonce is None:
        pass_token = "PASS "
        fail_token = "FAIL "
        summary = "SUMMARY done"
    else:
        pass_token = "PASS@" + nonce + " "
        fail_token = "FAIL@" + nonce + " "
        summary = "SUMMARY@" + nonce + " done"

    replacements = [
        (
            _ANCHOR_LOOP,
            "  const ONLY = process.env.ONLY_OBJECT;\n"
            "  const ONLY_M = process.env.ONLY_METHODS ? process.env.ONLY_METHODS.split(',') : null;\n"
            "  for (const st of getData().filter(d => !ONLY || d.objectName === ONLY).map(d => ({...d, methods: d.methods.filter(m => !ONLY_M || ONLY_M.includes(m.name))}))) {",
        ),
        (
            _ANCHOR_CALL,
            "        try {\n"
            "          await test.FRIENDS_ACCESS_INSTANCE[m.name]();\n"
            f"          console.log('{pass_token}' + st.localClass + '->' + m.name);\n"
            "        } catch (e) {\n"
            "          const val = x => { try { return x && typeof x.get === 'function' ? String(x.get()) : String(x); } catch (_) { return '?'; } };\n"
            "          const raw = e.message ? String(e.message) : (e.msg !== undefined ? 'msg=' + val(e.msg) + ' expected=' + val(e.expected) + ' actual=' + val(e.actual) : String(e));\n"
            "          const msg = raw.replace(/\\s+/g, ' ').slice(0, 300);\n"
            f"          console.log('{fail_token}' + st.localClass + '->' + m.name + ' :: ' + msg);\n"
            "        }",
        ),
        (
            _ANCHOR_RUN,
            _ANCHOR_RUN + "\n  console.log('" + summary + "');",
        ),
    ]
    for anchor, replacement in replacements:
        if text.count(anchor) != 1:
            raise RunnerError(f"missing anchor: {anchor}")
        text = text.replace(anchor, replacement, 1)
    return text


def _validate_edited_key(rel: str) -> None:
    if not isinstance(rel, str) or rel == "":
        raise RunnerError(f"edited file key is not valid: {rel!r}")
    if "\\" in rel:
        raise RunnerError(f"edited file key is not allowed: {rel}")
    if ":" in rel:
        raise RunnerError(f"edited file key is not allowed: {rel}")
    if rel[:1] in ("/", "\\"):
        raise RunnerError(f"edited file key is not allowed: {rel}")
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != "src":
        raise RunnerError(f"edited file key must start with src/: {rel}")
    if ".." in parts:
        raise RunnerError(f"edited file key contains a parent-step: {rel}")
    if not rel.endswith(".abap"):
        raise RunnerError(f"edited file key must end with .abap: {rel}")


def _is_skip_link(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
    except OSError:
        return False
    is_junction = getattr(os, "isjunction", None)
    if is_junction is not None:
        try:
            if is_junction(path):
                return True
        except OSError:
            return False
    return False


def _copy_tree_confined(src: Path, dst: Path) -> None:
    def ignore(dirpath: str, names: list[str]) -> set[str]:
        skipped: set[str] = set()
        for name in names:
            full = os.path.join(dirpath, name)
            if name in _SKIP_NAMES or _is_skip_link(full):
                skipped.add(name)
        return skipped

    shutil.copytree(src, dst, ignore=ignore, symlinks=True)


def _decode_bytes(data: bytes | None) -> str:
    if data is None:
        return ""
    return data.decode("utf-8", errors="replace")


def _mask_nonce(text: str, nonce: str | None) -> str:
    if not text or not nonce:
        return text
    return text.replace(nonce, "<nonce>")


def _cap_output(text: str) -> str:
    if len(text) > _OUTPUT_CAP:
        return text[-_OUTPUT_CAP:]
    return text


def _kill_process_tree(proc: subprocess.Popen, win: bool) -> None:
    if win:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def _base_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _popen_captured(
    cmd: list[str], cwd: Path, env: dict[str, str], timeout: float, win: bool, nonce: str | None = None
) -> tuple[int, str]:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out_b, err_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc, win)
        try:
            out_b, err_b = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out_b, err_b = proc.communicate()
        text = _cap_output(_decode_bytes(out_b) + _decode_bytes(err_b))
        raise RunnerError(_mask_nonce(text[-600:], nonce) or "subprocess timed out")
    text = _cap_output(_decode_bytes(out_b) + _decode_bytes(err_b))
    return proc.returncode, text


def run_abap_tests(cfg: dict, edited: dict, timeout_s: int = 900, trusted=()) -> dict[str, str]:
    """Transpile edited ABAP and run its unit tests through confined Node.

    Refusals run first (no slot needed). The heavy part waits for a transpile slot before its
    per-process timers start, so queueing behind other loops does not eat timeout_s.
    """
    for rel in edited:
        _validate_edited_key(rel)

    contents: dict[str, str] = {}
    for rel, host_path in edited.items():
        text = Path(host_path).read_text(encoding="utf-8")
        problems = [] if rel in trusted else check_abap_text(text)  # trusted: controller-provided locked files, never model-written
        if problems:
            raise AbapTextRefused("; ".join(problems))
        contents[rel] = text

    with transpile_slot():
        return _transpile_and_run(cfg, contents, timeout_s)


def _transpile_and_run(cfg: dict, contents: dict, timeout_s: int) -> dict[str, str]:
    node = cfg.get("node") or shutil.which("node")
    project_dir = Path(cfg["project_dir"])
    libs_dir = Path(cfg["libs_dir"])
    tools_dir = Path(cfg["tools_dir"])
    config = cfg["config"]
    only_object = cfg["only_object"]
    win = sys.platform == "win32"
    nonce = secrets.token_hex(8)

    if cfg.get("transpile_cmd"):
        transpile_cmd = list(cfg["transpile_cmd"])
    else:
        bin_name = "abap_transpile.cmd" if win else "abap_transpile"
        transpile_cmd = [str(tools_dir / "node_modules" / ".bin" / bin_name), config]

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        w = Path(tmp)
        p = w / "p"
        _copy_tree_confined(project_dir, p)
        shutil.copytree(libs_dir, w / "libs")
        shutil.copytree(tools_dir / "node_modules", p / "node_modules", symlinks=True)

        (p / "output").mkdir(parents=True, exist_ok=True)

        p_resolved = p.resolve()
        for rel, text in contents.items():
            dest = (p / rel).resolve()
            if not dest.is_relative_to(p_resolved):
                raise RunnerError(f"edited file escapes project folder: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8", newline=chr(10))

        if not cfg.get("transpile_cmd"):
            entry = tools_dir / "node_modules" / "@abaplint" / "transpiler-cli" / "build" / "bundle.js"
            transpile_cmd = build_transpile_command(
                node,
                str(entry),
                config,
                [str(p), str(w / "libs"), str(tools_dir / "node_modules")],
                str(p / "output"),
                preload=NET_GUARD_PRELOAD,
            )

        transpile_env = _base_env()
        for key in ("APPDATA", "USERPROFILE", "LOCALAPPDATA"):
            value = os.environ.get(key)
            if value:
                transpile_env[key] = value

        code, output = _popen_captured(transpile_cmd, p, transpile_env, float(timeout_s), win, nonce)
        if code != 0:
            raise RunnerError(_mask_nonce(output[-600:], nonce) or "transpile failed")

        index_mjs = p / "output" / "index.mjs"
        patched = patch_runner(index_mjs.read_text(encoding="utf-8"), nonce)
        (p / "output" / "index.local.mjs").write_text(patched, encoding="utf-8")

        env = _base_env()
        env["ONLY_OBJECT"] = only_object
        if cfg.get("only_methods"):  # optional: run just these test methods (problem C: other tests of the class fail on this runtime)
            env["ONLY_METHODS"] = ",".join(cfg["only_methods"])
        cmd = build_node_command(
            node,
            ["output/index.local.mjs", "--skip-critical"],
            [str(p), str(tools_dir / "node_modules")],
            preload=NET_GUARD_PRELOAD,
        )
        proc = subprocess.Popen(
            cmd,
            cwd=p,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, _stderr = proc.communicate(timeout=float(timeout_s))
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc, win)
            try:
                stdout, _stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, _stderr = proc.communicate()
            message = _cap_output(_mask_nonce(stdout or "", nonce))
            raise RunnerError(message[-600:] or "node test run timed out")

        if proc.returncode != 0 or f"SUMMARY@{nonce} done" not in stdout.splitlines():
            message = _cap_output(_mask_nonce(stdout or "", nonce))
            raise RunnerError(message[-600:] or "node run failed")

        results = parse_results(stdout, nonce)
        if not results:
            raise RunnerError("no test result lines")
        return results


def abaplint_config(config: dict) -> dict:
    """Return a deep copy of config with the forbidden_kernel_write rule forced
    to Error and every dependency URL removed (abaplint must run offline)."""
    out = copy.deepcopy(config)
    rules = out.setdefault("rules", {})
    rules["forbidden_kernel_write"] = {"severity": "Error", "allow": ["^$"], "exclude": []}
    dependencies = out.get("dependencies")
    if isinstance(dependencies, list):
        for dep in dependencies:
            if isinstance(dep, dict):
                dep.pop("url", None)
    return out


def parse_abaplint_issues(text: str, rel_paths: list[str]) -> list[str]:
    """Parse abaplint -f json output; return one formatted line per issue
    whose file belongs to one of rel_paths."""
    try:
        # abaplint writes its log lines to the same stream: take the first line that is the JSON list
        data = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("["):
                try:
                    data = json.loads(line)
                    break
                except ValueError:
                    continue
        if data is None:
            data = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - any JSON problem is a RunnerError
        raise RunnerError(f"abaplint output is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RunnerError("abaplint output is not a JSON list of issues")

    def file_matches(file_raw: str, rel: str) -> bool:
        file_norm = file_raw.replace("\\", "/")
        if file_norm.startswith("//?/"):
            file_norm = file_norm[4:]
        return file_norm.lower().endswith(rel.replace("\\", "/").lower())

    issues: list[str] = []
    for issue in data:
        if not isinstance(issue, dict):
            continue
        file_raw = issue.get("file")
        if not isinstance(file_raw, str):
            continue
        for rel in rel_paths:
            if file_matches(file_raw, rel):
                start = issue.get("start")
                row = start.get("row") if isinstance(start, dict) else ""
                issues.append(
                    f"{issue.get('key', '')}: {issue.get('description', '')} ({rel}:{row})"
                )
                break
    return issues


def run_abaplint(cfg: dict, edited: dict, timeout_s: int = 240, trusted=()) -> list[str]:
    """Lint edited ABAP with abaplint at the project's own release, confined.

    Every edited key is validated and every edited host file is statically
    checked (trusted files exempt) before anything runs. abaplint is then
    executed offline in a copied project tree; a non-zero exit is expected
    when issues are found and is not an error by itself.
    """
    for rel in edited:
        _validate_edited_key(rel)

    node = cfg.get("node") or shutil.which("node")
    project_dir = Path(cfg["project_dir"])
    tools_dir = Path(cfg["tools_dir"])
    lint_deps_dir = Path(cfg["lint_deps_dir"])
    win = sys.platform == "win32"
    nonce = secrets.token_hex(8)

    contents: dict[str, str] = {}
    for rel, host_path in edited.items():
        text = Path(host_path).read_text(encoding="utf-8")
        problems = [] if rel in trusted else check_abap_text(text)
        if problems:
            raise AbapTextRefused("; ".join(problems))
        contents[rel] = text

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        w = Path(tmp)
        p = w / "p"
        _copy_tree_confined(project_dir, p)
        shutil.copytree(lint_deps_dir / "src", p / "lint_deps" / "src")
        shutil.copytree(tools_dir / "node_modules", p / "node_modules", symlinks=True)

        p_resolved = p.resolve()
        for rel, text in contents.items():
            dest = (p / rel).resolve()
            if not dest.is_relative_to(p_resolved):
                raise RunnerError(f"edited file escapes project folder: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8", newline=chr(10))

        raw_cfg = (p / "abaplint.json").read_text(encoding="utf-8")
        try:
            config_in = json.loads(raw_cfg)
        except json.JSONDecodeError:    # 2026-11-17: a repo's abaplint.json may hold regex backslashes that strict JSON rejects (abapGit's does); read them literally
            config_in = json.loads(re.sub(r'\\(["\\/bfnrtu])|\\', lambda m: m.group(0) if m.group(1) else chr(92) * 2, raw_cfg))     # valid pairs (incl. \\) are consumed first
        (p / "abaplint.sap.json").write_text(
            json.dumps(abaplint_config(config_in)), encoding="utf-8"
        )

        cli_js = tools_dir / "node_modules" / "@abaplint" / "cli" / "build" / "cli.js"
        cmd = build_node_command(
            node,
            [str(cli_js), "abaplint.sap.json", "-f", "json"],
            [str(p), str(tools_dir / "node_modules")],
            preload=NET_GUARD_PRELOAD,
        )
        _returncode, output = _popen_captured(
            cmd, p, _base_env(), float(timeout_s), win, nonce
        )

        try:
            return parse_abaplint_issues(output, list(edited))
        except RunnerError as exc:
            tail = _mask_nonce(output[-600:], nonce) or "<empty>"
            raise RunnerError(
                f"{exc}; abaplint output (last 600 chars): {tail}"
            ) from exc
