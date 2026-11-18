"""Pure decision logic for SAP ADT evaluation (standard library only, no network)."""

import re
import xml.etree.ElementTree as ET
from collections import Counter

_FAILURE_LOCAL_NAMES = {"failedAssertion", "exception", "aborted", "warning"}


def _local_name(tag: str) -> str:
    """Return the element local name, stripping any {namespace} prefix."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _normalize_message(message: str) -> str:
    """Lowercase, replace digit runs with '#', collapse and strip whitespace."""
    text = re.sub(r"\d+", "#", str(message).lower())
    return re.sub(r"\s+", " ", text).strip()


def evaluate_aunit(http_status: int, xml_text: str) -> tuple[bool, list[str]]:
    """Evaluate an AUnit run result; return (passed, reasons)."""
    reasons: list[str] = []

    if http_status != 200:
        reasons.append(f"HTTP status {http_status} is not 200")

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        reasons.append("XML did not parse")
        return (False, reasons)

    program_elements = [
        el for el in root.iter() if _local_name(el.tag) == "program"
    ]
    if not program_elements:
        reasons.append("missing program element")

    test_method_in_program = any(
        any(_local_name(desc.tag) == "testMethod" for desc in program.iter())
        for program in program_elements
    )
    if not test_method_in_program:
        reasons.append("missing testMethod element")

    for el in root.iter():
        local = _local_name(el.tag)
        if local == "alert":
            kind = el.get("kind")
            if kind:
                reasons.append(f"alert element present (kind={kind})")
            else:
                reasons.append("alert element present")
        if local in _FAILURE_LOCAL_NAMES:
            reasons.append(f"failure element {local} present")

    return (len(reasons) == 0, reasons)


def _finding_key(finding: dict) -> tuple:
    return (
        finding["obj_uri"],
        finding["check_id"],
        finding["message_code"],
        _normalize_message(finding["message"]),
    )


def evaluate_atc_delta(baseline: list[dict], candidate: list[dict]) -> tuple[bool, list[str]]:
    """Compare ATC findings; return (passed, reasons). Line is ignored."""
    baseline_counts = Counter(_finding_key(f) for f in baseline)
    candidate_counts = Counter(_finding_key(f) for f in candidate)

    baseline_priority: dict = {}
    candidate_priority: dict = {}

    for f in baseline:
        key = _finding_key(f)
        priority = int(f.get("priority", 1))
        if key not in baseline_priority or priority < baseline_priority[key]:
            baseline_priority[key] = priority

    for f in candidate:
        key = _finding_key(f)
        priority = int(f.get("priority", 1))
        if key not in candidate_priority or priority < candidate_priority[key]:
            candidate_priority[key] = priority

    reasons: list[str] = []
    for key, cand_count in candidate_counts.items():
        base_count = baseline_counts.get(key, 0)
        if cand_count > base_count:
            reasons.append(f"finding count increased for {key!r}")
        if base_count > 0 and candidate_priority[key] < baseline_priority[key]:
            reasons.append(f"severity regression for {key!r}")

    return (len(reasons) == 0, reasons)


def classify_remote_state(
    orig_active: str,
    orig_inactive: str | None,
    remote_active: str,
    remote_inactive: str | None,
    candidate: str,
    locked: bool,
) -> str:
    """Classify the remote ABAP version state; first match wins."""
    if remote_active == candidate:
        if remote_inactive in (None, orig_inactive, candidate):
            return "REMOTE_ACTIVE_CANDIDATE_UNRESTORED"
        return "REMOTE_CONFLICT_HUMAN_MODIFIED"
    if remote_active == orig_active and remote_inactive == candidate:
        return "REMOTE_DIRTY_INACTIVE_CANDIDATE"
    if remote_active == orig_active and remote_inactive == orig_inactive:
        if locked:
            return "REMOTE_LOCKED_BY_CURRENT_OR_STALE_SESSION"
        return "REMOTE_CLEAN_ORIGINAL"
    return "REMOTE_CONFLICT_HUMAN_MODIFIED"
