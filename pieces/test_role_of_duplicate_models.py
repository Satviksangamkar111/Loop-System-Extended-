"""With two roles on one model (the all-Haiku testing roster) a call's mode picks its role: a write is a writer's, a review a reviewer's (cal13/cal14)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "source"))
import p1b_production as pp


class _Stub:
    _ROLE_ORDER = pp.Production._ROLE_ORDER

    def __init__(self, models):
        self._view = {r: {"model": m} for r, m in models.items()}

    def ladder_roles(self):
        return self._view


def role(models, model, mode):
    return pp.Production._role_of(_Stub(models), model, mode)


def test_same_model_everywhere_a_write_is_a_writer_and_a_review_a_reviewer():
    same = {"writer_a": "haiku", "writer_b": "haiku", "reviewer_a": "haiku", "reviewer_b": "haiku"}
    assert role(same, "haiku", "write") == "writer_a" and role(same, "haiku", "repair") == "writer_a"
    assert role(same, "haiku", "review") == "reviewer_b" and role(same, "haiku", "review-reask") == "reviewer_b"


def test_distinct_models_are_unchanged():
    distinct = {"writer_a": "w1", "writer_b": "w2", "reviewer_a": "r1", "reviewer_b": "r2"}
    assert [role(distinct, m, "write") for m in ("w1", "w2", "r1", "r2")] == ["writer_a", "writer_b", "reviewer_a", "reviewer_b"]
