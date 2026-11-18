"""ponytail: runs on the host without confinement; safe only because models write .abap text that is never executed (selftest enforces it); use DockerSandbox when Docker is available."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath

from sandbox_runner import CONTROLLER_INI, RunResult

_SKIP_NAMES = ("__pycache__", ".git", ".pytest_cache")
_OUTPUT_LIMIT = 200000

_RESERVED_STEMS = {"CON", "PRN", "AUX", "NUL"} | {
    f"COM{i}" for i in range(1, 10)
} | {f"LPT{i}" for i in range(1, 10)}


def _normalize(path: str) -> str:
    return os.path.normpath(path).replace("\\", "/")


def _is_absolute_path(path: str) -> bool:
    return os.path.isabs(path) or path.startswith(("/", "\\"))


def _is_linkish(path: os.PathLike[str] | str) -> bool:
    if os.path.islink(path):
        return True
    if hasattr(os.path, "isjunction") and os.path.isjunction(path):
        return True
    return False


def _is_outside_root(path: Path, root_resolved: Path) -> bool:
    try:
        real = Path(os.path.realpath(path))
    except OSError:
        return True
    return not real.is_relative_to(root_resolved)


class AbapStaticSandbox:
    def __init__(self, editable, include, python=None):
        self.editable = list(editable)
        self.include = list(include)
        self.python = python if python is not None else sys.executable

    def selftest(self) -> list[str]:
        problems: list[str] = []
        if not self.editable:
            problems.append("editable list is empty")
            return problems
        for path in self.editable:
            p = str(path)
            if not p.lower().endswith(".abap"):
                problems.append(f"editable file {path} is not .abap")
                continue
            if _is_absolute_path(p):
                problems.append(f"editable file {path} is absolute")
                continue
            if ":" in p:
                problems.append(f"editable file {path} contains a drive colon")
                continue
            if ".." in PurePath(p).parts:
                problems.append(f"editable file {path} contains '..'")
                continue
            stem = PurePath(p).stem.upper()
            if stem in _RESERVED_STEMS:
                problems.append(f"editable file {path} has a reserved name {stem}")
        return problems

    def _copy_one(
        self,
        src: Path,
        dst: Path,
        root_resolved: Path,
        work_resolved: Path,
    ) -> RunResult | None:
        dst_resolved = dst.resolve(strict=False)
        if not dst_resolved.is_relative_to(work_resolved):
            return RunResult(125, f"include {src} escapes the work area", None, False)

        try:
            if _is_linkish(src):
                return None

            if src.is_dir():
                if _is_outside_root(src, root_resolved):
                    return None
                dst.mkdir(parents=True, exist_ok=True)
                for entry in os.scandir(src):
                    name = entry.name
                    if name in _SKIP_NAMES or name.endswith(".pyc"):
                        continue
                    entry_path = Path(entry.path)
                    if _is_linkish(entry_path):
                        continue
                    result = self._copy_one(
                        entry_path, dst / name, root_resolved, work_resolved
                    )
                    if result is not None:
                        return result
                return None

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return None
        except OSError:
            return None

    def run(self, root, tests, overlay=None, readonly=(), timeout_s=600) -> RunResult:
        problems = self.selftest()
        if problems:
            return RunResult(125, "\n".join(problems), None, False)

        root = Path(root)
        overlay = dict(overlay or {})

        for name in self.include:
            p = str(name)
            stripped = p.strip()
            if stripped == "" or stripped == ".":
                return RunResult(125, f"include {name!r} is not a usable name", None, False)
            if ":" in p:
                return RunResult(125, f"include {name!r} contains a drive colon", None, False)
            if _is_absolute_path(p):
                return RunResult(125, f"include {name} is absolute", None, False)
            if ".." in PurePath(p).parts:
                return RunResult(125, f"include {name} contains '..'", None, False)

        editable_normalized = {_normalize(p) for p in self.editable}
        for key in overlay:
            nk = _normalize(str(key))
            if not nk.lower().endswith(".abap"):
                return RunResult(125, f"overlay key {key} is not .abap", None, False)
            if nk not in editable_normalized:
                return RunResult(125, f"overlay key {key} is not an editable path", None, False)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp = Path(tmp)
            work = tmp / "work"
            work.mkdir()
            root_resolved = root.resolve(strict=False)
            work_resolved = work.resolve(strict=False)

            for name in self.include:
                p = str(name)
                if p.strip() in ("", ".") or ":" in p:
                    continue
                if name in _SKIP_NAMES or str(name).endswith(".pyc"):
                    continue
                src = root / name
                if not src.exists():
                    continue
                result = self._copy_one(src, work / name, root_resolved, work_resolved)
                if result is not None:
                    return result

            for rel, host_file in overlay.items():
                dst = work / rel
                dst_resolved = dst.resolve(strict=False)
                if not dst_resolved.is_relative_to(work_resolved):
                    return RunResult(
                        125, f"overlay destination {dst} escapes work", None, False
                    )
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(host_file, dst)
                except OSError as exc:
                    return RunResult(
                        125,
                        f"overlay {rel} cannot be copied: {exc}",
                        None,
                        False,
                    )

            p0 = tmp / "p0"
            p0.mkdir(parents=True, exist_ok=True)
            ini = p0 / "pytest.ini"
            ini_text = CONTROLLER_INI
            if ini_text and not ini_text.endswith("\n"):
                ini_text += "\n"
            ini_text += f"pythonpath = {work}\n"
            ini.write_text(ini_text, encoding="utf-8")

            junit_path = tmp / "junit.xml"
            cmd = [
                self.python,
                "-E",
                "-P",
                "-m",
                "pytest",
                "-c",
                str(ini),
                "--rootdir",
                str(work),
                "-p",
                "no:cacheprovider",
                "--runxfail",
                "-q",
                "--tb=short",
                "-rfE",
                "--junitxml",
                str(junit_path),
            ] + list(tests)

            env = {
                key: os.environ[key]
                for key in (
                    "PATH",
                    "SYSTEMROOT",
                    "TEMP",
                    "TMP",
                    "APPDATA",
                    "USERPROFILE",
                    "LOCALAPPDATA",
                )
                if key in os.environ
            }

            try:
                completed = subprocess.run(
                    cmd,
                    cwd=work,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    timeout=timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                msg = f"SANDBOX: pytest timed out after {timeout_s} s"
                extra = exc.output or exc.stderr or ""
                if isinstance(extra, bytes):
                    extra = extra.decode("utf-8", errors="replace")
                if extra:
                    msg += "\n" + extra
                return RunResult(124, msg, None, True)

            combined = (completed.stdout or "") + (completed.stderr or "")
            if len(combined) > _OUTPUT_LIMIT:
                combined = combined[-_OUTPUT_LIMIT:]

            junit_text = None
            if junit_path.exists():
                junit_text = junit_path.read_text(encoding="utf-8", errors="replace")
            return RunResult(completed.returncode, combined, junit_text, False)
