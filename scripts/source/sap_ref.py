"""Offline ABAP/SAP knowledge selector (stdlib only)."""

import argparse
import math
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

HEADING_RE = re.compile(r"^#{1,6}[ \t]*(.*)$")
WORD_RE = re.compile(r"[a-z0-9_]+")
FENCE_MARKER = "```"

K1 = 1.5
B = 0.75


@dataclass(frozen=True)
class Section:
    source: str
    heading: str
    body: str


def split_sections(text, source):
    sections = []
    in_fence = False
    current_heading = None
    current_lines = []
    pre_lines = []
    for line in text.splitlines():
        if line.startswith(FENCE_MARKER):
            in_fence = not in_fence
            continue
        if in_fence:
            if current_heading is not None:
                current_lines.append(line)
            continue
        match = HEADING_RE.match(line)
        if match:
            if current_heading is not None:
                sections.append(
                    Section(
                        source,
                        current_heading,
                        "\n".join(current_lines).rstrip(),
                    )
                )
            else:
                preamble = "\n".join(pre_lines).rstrip()
                if preamble.strip():
                    sections.append(Section(source, "", preamble))
            current_heading = match.group(1).strip()
            current_lines = []
            pre_lines = None
        elif pre_lines is not None:
            pre_lines.append(line)
        else:
            current_lines.append(line)
    if current_heading is not None:
        sections.append(
            Section(source, current_heading, "\n".join(current_lines).rstrip())
        )
    return sections


def build_index(root):
    root = Path(root)
    sections = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        source = path.relative_to(root).as_posix()
        sections.extend(split_sections(text, source))
    return sections


def _tokens(text):
    return WORD_RE.findall(text.lower())


def search(sections, query, max_chars):
    words = list(dict.fromkeys(_tokens(query)))
    if not words:
        raise ValueError("query must contain at least one word")

    # Sections with blank bodies are never returned; skip them before scoring.
    candidates = [sec for sec in sections if sec.body.strip()]
    if not candidates:
        return []

    n_sec = len(candidates)
    doc_tokens = [_tokens(sec.heading + " " + sec.body) for sec in candidates]
    heading_sets = [set(_tokens(sec.heading)) for sec in candidates]
    lengths = [len(tokens) for tokens in doc_tokens]
    avgdl = sum(lengths) / n_sec if n_sec else 0.0

    doc_freq = {}
    for tokens in doc_tokens:
        for term in set(tokens):
            doc_freq[term] = doc_freq.get(term, 0) + 1

    def idf(term):
        n = doc_freq.get(term, 0)
        return math.log((n_sec - n + 0.5) / (n + 0.5) + 1.0)

    scored = []
    for sec, tokens, hset, length in zip(
        candidates, doc_tokens, heading_sets, lengths
    ):
        term_freq = {}
        for term in tokens:
            term_freq[term] = term_freq.get(term, 0) + 1
        score = 0.0
        for term in words:
            f = term_freq.get(term, 0)
            if f:
                denominator = f + K1 * (
                    1 - B + B * (length / avgdl if avgdl else 0.0)
                )
                score += idf(term) * f * (K1 + 1) / denominator
            if term in hset:
                score += 3.0 * idf(term)
        if score > 0.0:
            scored.append((score, sec))

    if not scored:
        return []

    scored.sort(
        key=lambda item: (
            -item[0],
            len(item[1].body),
            item[1].source,
            item[1].heading,
        )
    )

    def cost(sec):
        return len(sec.body) + len(sec.source) + len(sec.heading) + 8

    best = scored[0][1]
    result = []
    best_cost = cost(best)
    if best_cost <= max_chars:
        result.append(best)
        total = best_cost
    else:
        max_body = max_chars - len(best.source) - len(best.heading) - 8
        if max_body >= 0:
            result.append(replace(best, body=best.body[:max_body]))
            total = max_chars
        else:
            # Headers alone do not fit; keep at least one body character.
            result.append(replace(best, body=best.body[:1]))
            total = cost(result[0])

    for _, sec in scored[1:]:
        c = cost(sec)
        if total + c <= max_chars:
            result.append(sec)
            total += c
        else:
            break
    return result


def render(sections):
    lines = [
        "# REFERENCE (offline ABAP knowledge, selected for this job)",
        "Reference only: the SPEC and the locked tests decide what is correct.",
    ]
    for sec in sections:
        lines.append("")
        lines.append(f"## {sec.source} > {sec.heading}")
        lines.append("")
        lines.append(sec.body)
    return "\n".join(lines) + "\n"


def main(argv):
    parser = argparse.ArgumentParser(description="Select relevant SAP knowledge sections.")
    parser.add_argument("kb_dir")
    parser.add_argument("query")
    parser.add_argument("--max-kb", type=int, default=40)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    sections = build_index(args.kb_dir)
    picked = search(sections, args.query, args.max_kb * 1024)
    if not picked:
        return 1
    text = render(picked)
    if args.out is None:
        sys.stdout.buffer.write(text.encode("utf-8"))
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
