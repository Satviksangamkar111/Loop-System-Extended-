"""Frozen acceptance tests for scripts/source/sap_ref.py (do not edit)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import pytest
import sap_ref as r

A = """# Clean ABAP
Intro text.
## Prefer boolc
Use boolc( ) to build abap_bool from a condition. Avoid IF abap_true.
## Naming
Use meaningful names for variables.
"""
B = """# Internal tables
## Hashed tables
Hashed tables give fast key access by WITH UNIQUE KEY. Use them for large lookups.
## Sorted tables
Sorted tables keep rows ordered by key.
"""


@pytest.fixture
def kb(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/x.md").write_text(A)
    (tmp_path / "b").mkdir()
    (tmp_path / "b/y.md").write_text(B)
    (tmp_path / "skip.txt").write_text("ignored boolc")
    return tmp_path


def test_split_sections_by_heading():
    secs = r.split_sections(A, "a/x.md")
    assert [s.heading for s in secs] == ["Clean ABAP", "Prefer boolc", "Naming"]
    assert all(s.source == "a/x.md" for s in secs)
    assert "boolc" in secs[1].body and "Naming" not in secs[1].body


def test_build_index_reads_only_markdown_with_relative_posix_sources(kb):
    secs = r.build_index(kb)
    assert {s.source for s in secs} == {"a/x.md", "b/y.md"}


def test_search_ranks_relevant_section_first(kb):
    secs = r.build_index(kb)
    assert r.search(secs, "boolc condition", 5000)[0].heading == "Prefer boolc"
    assert r.search(secs, "hashed unique key lookup", 5000)[0].heading == "Hashed tables"


def test_search_respects_size_limit_and_no_match(kb):
    secs = r.build_index(kb)
    picked = r.search(secs, "tables key", 120)
    assert picked and sum(len(s.body) for s in picked) <= 120
    assert r.search(secs, "zzzzqqq", 5000) == []
    with pytest.raises(ValueError):
        r.search(secs, "   ", 5000)


def test_render_has_notice_sources_and_headings(kb):
    text = r.render(r.search(r.build_index(kb), "boolc", 5000))
    assert text.startswith("# REFERENCE")
    assert "Reference only" in text and "a/x.md" in text and "Prefer boolc" in text


def test_main_writes_file(kb, tmp_path):
    out = tmp_path / "out" / "REF.md"
    assert r.main([str(kb), "hashed key", "--max-kb", "2", "--out", str(out)]) == 0
    assert "Hashed tables" in out.read_text()
    assert r.main([str(kb), "zzzzqqq", "--out", str(out)]) == 1


def test_empty_sections_are_never_returned_and_preamble_is_kept():
    text = "Preamble about boolc usage." + chr(10) + "# boolc" + chr(10) + "## Details" + chr(10) + "boolc builds booleans from conditions." + chr(10)
    secs = r.split_sections(text, "z.md")
    assert secs[0].heading == "" and "Preamble" in secs[0].body
    picked = r.search(secs, "boolc", 5000)
    assert picked and all(s.body.strip() for s in picked)


def test_headers_count_against_the_size_limit(kb):
    secs = r.build_index(kb)
    empty = len(r.render([]))
    for limit in (150, 300, 600):
        picked = r.search(secs, "tables key hashed sorted", limit)
        assert len(r.render(picked)) - empty <= limit
