"""Tests for scripts/hard_question_eval/select_hard_questions.py::select_pool.

select_pool() is the one piece of genuinely new algorithmic logic in
scripts/hard_question_eval/ (the quota-aware greedy fill balancing hard vs.
extra floors) -- everything else in that folder is thin glue over
already-tested collaborators (loaders, eval.exact_match, eval.runner,
eval.metrics, eval.sql_features).

compute_hardness_pools() (the real train-split scan + score_exact_match
calls) is monkeypatched out in every test here so these run fast, offline,
and without needing the Spider dataset/sqlite files on disk -- only
select_pool()'s own selection logic is under test.

scripts/ isn't an installed package, so the module is loaded directly from
its file path rather than imported normally.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from spider_agent_workbench.loaders import SpiderExample

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "hard_question_eval" / "select_hard_questions.py"
)
_spec = importlib.util.spec_from_file_location("select_hard_questions", _MODULE_PATH)
select_hard_questions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(select_hard_questions)

select_pool = select_hard_questions.select_pool


def _examples(db_id: str, label: str, count: int) -> list[SpiderExample]:
    return [
        SpiderExample(db_id=db_id, question=f"{db_id}-{label}-{i}", gold_sql=f"SELECT {i}")
        for i in range(count)
    ]


def _patch_pools(monkeypatch, hard_by_db: dict, extra_by_db: dict) -> None:
    monkeypatch.setattr(
        select_hard_questions, "compute_hardness_pools", lambda: (hard_by_db, extra_by_db)
    )


# select_pool
#   total questions == num_dbs * questions_per_db, every db gets exactly
#   questions_per_db, and the returned hardness_breakdown matches what's
#   actually in the selected examples


def test_select_pool_returns_full_grid_with_ample_supply(monkeypatch):
    hard_by_db = {f"db{i}": _examples(f"db{i}", "hard", 5) for i in range(4)}
    extra_by_db = {f"db{i}": _examples(f"db{i}", "extra", 5) for i in range(4)}
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    selected, breakdown = select_pool(
        num_dbs=4, questions_per_db=5, seed=42, min_hard_fraction=0.4, min_extra_fraction=0.4
    )

    assert len(selected) == 4
    assert all(len(picks) == 5 for picks in selected.values())
    total = sum(len(picks) for picks in selected.values())
    assert total == 20

    hard_count = sum(1 for picks in selected.values() for _, hardness in picks if hardness == "hard")
    extra_count = sum(1 for picks in selected.values() for _, hardness in picks if hardness == "extra")
    assert breakdown == {"hard": hard_count, "extra": extra_count}


def test_select_pool_meets_hard_and_extra_floors(monkeypatch):
    hard_by_db = {f"db{i}": _examples(f"db{i}", "hard", 5) for i in range(4)}
    extra_by_db = {f"db{i}": _examples(f"db{i}", "extra", 5) for i in range(4)}
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    _, breakdown = select_pool(
        num_dbs=4, questions_per_db=5, seed=42, min_hard_fraction=0.4, min_extra_fraction=0.4
    )

    # total=20, floors are ceil(20*0.4)=8 each
    assert breakdown["hard"] >= 8
    assert breakdown["extra"] >= 8


def test_select_pool_handles_dbs_that_are_pure_one_hardness(monkeypatch):
    """Two dbs are all-hard, two are all-extra -- exercises the branches
    where a db's preferred bucket is empty and the fill has to fall through
    to whichever bucket that db actually has."""
    hard_by_db = {
        "hard_db_a": _examples("hard_db_a", "hard", 5),
        "hard_db_b": _examples("hard_db_b", "hard", 5),
    }
    extra_by_db = {
        "extra_db_a": _examples("extra_db_a", "extra", 5),
        "extra_db_b": _examples("extra_db_b", "extra", 5),
    }
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    selected, breakdown = select_pool(
        num_dbs=4, questions_per_db=5, seed=42, min_hard_fraction=0.4, min_extra_fraction=0.4
    )

    assert set(selected.keys()) == {"hard_db_a", "hard_db_b", "extra_db_a", "extra_db_b"}
    assert breakdown == {"hard": 10, "extra": 10}


def test_select_pool_never_duplicates_an_example(monkeypatch):
    hard_by_db = {f"db{i}": _examples(f"db{i}", "hard", 6) for i in range(5)}
    extra_by_db = {f"db{i}": _examples(f"db{i}", "extra", 6) for i in range(5)}
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    selected, _ = select_pool(
        num_dbs=5, questions_per_db=5, seed=7, min_hard_fraction=0.4, min_extra_fraction=0.4
    )

    all_questions = [example.question for picks in selected.values() for example, _ in picks]
    assert len(all_questions) == len(set(all_questions))


def test_select_pool_is_deterministic_for_the_same_seed(monkeypatch):
    hard_by_db = {f"db{i}": _examples(f"db{i}", "hard", 5) for i in range(6)}
    extra_by_db = {f"db{i}": _examples(f"db{i}", "extra", 5) for i in range(6)}
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    first, first_breakdown = select_pool(
        num_dbs=4, questions_per_db=5, seed=123, min_hard_fraction=0.4, min_extra_fraction=0.4
    )
    second, second_breakdown = select_pool(
        num_dbs=4, questions_per_db=5, seed=123, min_hard_fraction=0.4, min_extra_fraction=0.4
    )

    assert first == second
    assert first_breakdown == second_breakdown


def test_select_pool_different_seeds_can_pick_different_dbs(monkeypatch):
    hard_by_db = {f"db{i}": _examples(f"db{i}", "hard", 5) for i in range(10)}
    extra_by_db = {f"db{i}": _examples(f"db{i}", "extra", 5) for i in range(10)}
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    first, _ = select_pool(num_dbs=4, questions_per_db=5, seed=1, min_hard_fraction=0.4, min_extra_fraction=0.4)
    second, _ = select_pool(num_dbs=4, questions_per_db=5, seed=2, min_hard_fraction=0.4, min_extra_fraction=0.4)

    assert set(first.keys()) != set(second.keys())


# select_pool -- error paths


def test_select_pool_raises_when_not_enough_eligible_dbs(monkeypatch):
    hard_by_db = {f"db{i}": _examples(f"db{i}", "hard", 5) for i in range(2)}
    extra_by_db: dict = {}
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    with pytest.raises(ValueError, match="Only 2 db_ids"):
        select_pool(num_dbs=3, questions_per_db=5, seed=42)


def test_select_pool_raises_when_hardness_floor_unreachable(monkeypatch):
    # 2 eligible dbs (combined >= 5 each), but only 2 extra questions exist
    # in total -- nowhere near the 8-question extra floor at min_extra_fraction=0.8.
    hard_by_db = {
        "db0": _examples("db0", "hard", 5),
        "db1": _examples("db1", "hard", 5),
    }
    extra_by_db = {
        "db0": _examples("db0", "extra", 1),
        "db1": _examples("db1", "extra", 1),
    }
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    with pytest.raises(ValueError, match="doesn't meet the hardness floor"):
        select_pool(num_dbs=2, questions_per_db=5, seed=42, min_hard_fraction=0.2, min_extra_fraction=0.8)


def test_select_pool_db_with_exactly_questions_per_db_combined_is_eligible(monkeypatch):
    """A db with exactly questions_per_db combined hard+extra questions
    should still be selectable -- the eligibility check is >=, not >."""
    hard_by_db = {"db0": _examples("db0", "hard", 3)}
    extra_by_db = {"db0": _examples("db0", "extra", 2)}
    _patch_pools(monkeypatch, hard_by_db, extra_by_db)

    selected, breakdown = select_pool(
        num_dbs=1, questions_per_db=5, seed=42, min_hard_fraction=0.4, min_extra_fraction=0.4
    )

    assert len(selected["db0"]) == 5
    assert breakdown["hard"] + breakdown["extra"] == 5
