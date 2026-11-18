"""Git <-> SAP baseline synchronization drift detection utilities."""

import difflib
import hashlib
import json
from dataclasses import asdict, dataclass

_HEX_DIGITS = frozenset("0123456789abcdef")

_SHA256_FIELDS = (
    "public_original_sha256",
    "sap_baseline_active_sha256",
    "projected_window_sha256",
    "candidate_sha256",
    "restored_baseline_sha256",
)

_NO_NEWLINE_MARKER = "\\ No newline at end of file\n"


class DriftError(Exception):
    """Raised when public original and SAP baseline active hashes diverge."""


def sha256_text(s: str) -> str:
    """Return the SHA-256 hex digest of *s* encoded as UTF-8."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def check_drift(public_original_sha256: str, sap_baseline_active_sha256: str) -> None:
    """Raise DriftError when the two baseline hashes differ."""
    if public_original_sha256 != sap_baseline_active_sha256:
        raise DriftError(
            "drift detected: public original "
            f"{public_original_sha256!r} != sap baseline active "
            f"{sap_baseline_active_sha256!r}"
        )


def _split_lines(text: str) -> list[str]:
    """Split *text* on the newline character only.

    Unlike ``str.splitlines``, carriage returns and form feeds are never
    treated as line boundaries.  The newline terminator is kept with each
    line except a possible final line that has no trailing newline.
    """
    if not text:
        return []
    parts = text.split("\n")
    lines: list[str] = []
    last_index = len(parts) - 1
    for index, part in enumerate(parts):
        if index == last_index:
            if part:
                lines.append(part)
        else:
            lines.append(part + "\n")
    return lines


def make_unified_diff(original: str, candidate: str, path: str) -> str:
    """Return a unified diff between *original* and *candidate* for *path*.

    Lines are split on the newline character only.  When a side does not end
    with a newline, git's ``\\ No newline at end of file`` marker is emitted
    after that line.  Returns an empty string when the texts are equal; the
    result always ends with a newline.
    """
    if original == candidate:
        return ""
    original_lines = _split_lines(original)
    candidate_lines = _split_lines(candidate)
    raw = difflib.unified_diff(
        original_lines,
        candidate_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    out: list[str] = []
    for line in raw:
        if line.endswith("\n"):
            out.append(line)
        else:
            out.append(line + "\n")
            out.append(_NO_NEWLINE_MARKER)
    return "".join(out)


@dataclass
class GitSapSyncManifest:
    repo: str
    commit: str
    file_path: str
    public_original_sha256: str
    sap_baseline_active_sha256: str
    projected_window_sha256: str
    candidate_sha256: str
    restored_baseline_sha256: str
    diff: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2)

    def validate(self) -> None:
        for field in _SHA256_FIELDS:
            value = getattr(self, field)
            if not (
                isinstance(value, str)
                and len(value) == 64
                and all(char in _HEX_DIGITS for char in value)
            ):
                raise DriftError(f"invalid {field}: {value!r}")
        check_drift(self.public_original_sha256, self.sap_baseline_active_sha256)
        if self.restored_baseline_sha256 != self.sap_baseline_active_sha256:
            raise DriftError(
                "restored baseline does not match sap baseline active"
            )
        if self.candidate_sha256 != self.public_original_sha256 and self.diff == "":
            raise DriftError(
                "candidate_sha256 differs from public_original_sha256 "
                "but diff is empty"
            )
