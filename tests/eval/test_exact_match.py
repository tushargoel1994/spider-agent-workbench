"""Tests for eval/exact_match.py — score_exact_match(), a thin adapter around
the vendored official Spider evaluation scripts in eval/spider_official/
(process_sql.py, evaluation.py — see spider_official/notice.md; not modified
here or by the adapter).

These tests only prove the adapter wires the vendored code together
correctly (schema building, hardness, exact-match comparison, and graceful
handling of unparseable predicted SQL) — they don't re-test the vendored
code's internal clause-matching rules, which aren't ours to test.
"""

import json

import pytest

from spider_agent_workbench.eval.exact_match import score_exact_match


@pytest.fixture()
def tables_json_path(tmp_path):
    """A minimal tables.json entry for the `school` fixture db (see
    tests/conftest.py): courses(id, title), students(id, name, course_id),
    with a foreign key from students.course_id to courses.id."""
    path = tmp_path / "tables.json"
    path.write_text(
        json.dumps(
            [
                {
                    "db_id": "school",
                    "table_names_original": ["courses", "students"],
                    "column_names_original": [
                        [-1, "*"],
                        [0, "id"],
                        [0, "title"],
                        [1, "id"],
                        [1, "name"],
                        [1, "course_id"],
                    ],
                    "foreign_keys": [[5, 1]],
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


# score_exact_match — basic cases


def test_identical_sql_is_exact_match(db_dir, db_id, tables_json_path):
    result = score_exact_match(
        db_id,
        "SELECT count(*) FROM students",
        "SELECT count(*) FROM students",
        db_dir,
        tables_json_path,
    )

    assert result.score == 1


def test_missing_predicted_sql_is_not_exact_match(db_dir, db_id, tables_json_path):
    result = score_exact_match(db_id, None, "SELECT count(*) FROM students", db_dir, tables_json_path)

    assert result.score == 0


def test_empty_predicted_sql_is_not_exact_match(db_dir, db_id, tables_json_path):
    result = score_exact_match(db_id, "", "SELECT count(*) FROM students", db_dir, tables_json_path)

    assert result.score == 0


def test_garbage_predicted_sql_is_not_exact_match_and_does_not_crash(db_dir, db_id, tables_json_path):
    result = score_exact_match(
        db_id, "not valid sql at all", "SELECT count(*) FROM students", db_dir, tables_json_path
    )

    assert result.score == 0


def test_structurally_different_sql_is_not_exact_match_even_with_same_rows(db_dir, db_id, tables_json_path):
    # Both return the same rows (students in course 1), but gold expresses it
    # with an equality filter and predicted with IN -- Exact Match compares
    # SQL structure, not query results, so this must score 0 even though
    # eval/sql_result_scorer.py's Execution Accuracy would call it correct.
    gold = "SELECT name FROM students WHERE course_id = 1"
    predicted = "SELECT name FROM students WHERE course_id IN (1)"

    result = score_exact_match(db_id, predicted, gold, db_dir, tables_json_path)

    assert result.score == 0


# score_exact_match — hardness is always populated, even when predicted SQL
# fails to parse (hardness describes the gold question, not the agent's answer)


def test_hardness_is_reported_for_a_simple_query(db_dir, db_id, tables_json_path):
    result = score_exact_match(
        db_id, "SELECT count(*) FROM students", "SELECT count(*) FROM students", db_dir, tables_json_path
    )

    assert result.hardness == "easy"


def test_hardness_is_still_reported_when_predicted_sql_is_garbage(db_dir, db_id, tables_json_path):
    result = score_exact_match(db_id, "garbage", "SELECT count(*) FROM students", db_dir, tables_json_path)

    assert result.hardness == "easy"


# score_exact_match — a missing db raises rather than silently mis-scoring


def test_raises_for_unknown_db_id(db_dir, tables_json_path):
    with pytest.raises(FileNotFoundError):
        score_exact_match("ghost_db", "SELECT 1", "SELECT 1", db_dir, tables_json_path)
