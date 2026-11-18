"""SAP extension: a job's reference files reach the WRITER only when the job sets writer_reference (owner decision 2026-11-10)."""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "source"))
import p1b_production as pp
import fix_loop


def stub(tmp_path, job):
    (tmp_path / "f.abap").write_text("FILE TEXT", encoding="utf-8")
    (tmp_path / "ref.md").write_text("REFTEXT " * 5000, encoding="utf-8")        # 40,000 characters
    s = SimpleNamespace(spec="SPEC TEXT", files=["f.abap"], root=tmp_path, job=job, fix_findings=None, last_junit=None)
    s._repair_files = lambda: ["f.abap"]
    s._reference_text = lambda: pp.Production._reference_text(s)
    return s


def request(tmp_path, job):
    return pp.Production._writer_user(stub(tmp_path, job))


def test_off_by_default_so_existing_jobs_are_unchanged(tmp_path):
    assert "REFTEXT" not in request(tmp_path, {"reference": ["ref.md"]})


def test_opt_in_shows_capped_reference_after_the_files_and_not_in_the_spec(tmp_path):
    text = request(tmp_path, {"reference": ["ref.md"], "writer_reference": True})
    assert pp.REFERENCE_HEAD in text and text.index("FILE TEXT") < text.index(pp.REFERENCE_HEAD)
    assert text.count("REFTEXT") <= pp.REFERENCE_CHARS // len("REFTEXT ") + 1
    assert text.index("SPEC TEXT") < text.index("EXPECTED FILES")


def test_missing_reference_file_is_skipped(tmp_path):
    assert pp.REFERENCE_HEAD not in request(tmp_path, {"reference": ["nope.md"], "writer_reference": True})


def test_job_schema_accepts_the_flag():
    assert fix_loop.JOB_SCHEMA["properties"]["writer_reference"]["type"] == "boolean"


def test_total_request_part_never_exceeds_the_cap_even_with_many_files(tmp_path):
    for i in range(40):
        (tmp_path / f"r{i}.md").write_text("x" * 900, encoding="utf-8")
    s = stub(tmp_path, {"reference": [f"r{i}.md" for i in range(40)], "writer_reference": True})
    assert len(pp.Production._reference_text(s)) <= pp.REFERENCE_CHARS
