"""Tests for eval/sql_result_scorer.py — score_query, with a focus on the
`agent_notes` parameter that surfaces guardrail failures recorded on
AgentAnswer.notes (see agent.answer_question) into the ScoreResult detail.
"""

from spider_agent_workbench.eval.sql_result_scorer import score_query


# score_query — base behavior (agent_notes omitted / None)
#   a matching query scores 1 with status "match" and no detail
#   a missing predicted_sql scores 0 with status "no_sql"


def test_score_query_match_has_no_detail_when_no_agent_notes(db_dir, db_id):
    result = score_query(
        db_id, "SELECT COUNT(*) FROM students", "SELECT COUNT(*) FROM students", db_dir
    )

    assert result.score == 1
    assert result.status == "match"
    assert result.detail is None


def test_score_query_no_sql_detail_unchanged_when_no_agent_notes(db_dir, db_id):
    result = score_query(db_id, None, "SELECT COUNT(*) FROM students", db_dir)

    assert result.score == 0
    assert result.status == "no_sql"
    assert result.detail == "Agent did not submit a query."


# score_query — agent_notes merging
#   agent_notes is appended to whatever detail was already going to be produced
#   an empty/None agent_notes leaves detail untouched (falsy is a no-op)


def test_score_query_merges_agent_notes_into_no_sql_detail(db_dir, db_id):
    result = score_query(
        db_id,
        None,
        "SELECT COUNT(*) FROM students",
        db_dir,
        agent_notes="Rejected: 'INSERT' is not allowed. Only read-only SELECT queries are permitted.",
    )

    assert result.score == 0
    assert result.status == "no_sql"
    assert "Agent did not submit a query." in result.detail
    assert "Rejected: 'INSERT' is not allowed" in result.detail


def test_score_query_merges_agent_notes_into_mismatch_detail(db_dir, db_id):
    result = score_query(
        db_id,
        "SELECT * FROM students",
        "SELECT * FROM students WHERE course_id = 1",
        db_dir,
        agent_notes="Rejected: unknown table(s) ['ghost']",
    )

    assert result.score == 0
    assert result.status == "row_count_mismatch"
    assert "gold=2 rows, predicted=3 rows" in result.detail
    assert "Rejected: unknown table(s) ['ghost']" in result.detail


def test_score_query_merges_agent_notes_into_match_when_notes_present(db_dir, db_id):
    result = score_query(
        db_id,
        "SELECT COUNT(*) FROM students",
        "SELECT COUNT(*) FROM students",
        db_dir,
        agent_notes="Error: AgentError: recursion limit reached",
    )

    assert result.score == 1
    assert result.status == "match"
    assert result.detail is not None
    assert "Error: AgentError: recursion limit reached" in result.detail


def test_score_query_ignores_none_agent_notes(db_dir, db_id):
    result = score_query(
        db_id,
        "SELECT COUNT(*) FROM students",
        "SELECT COUNT(*) FROM students",
        db_dir,
        agent_notes=None,
    )

    assert result.detail is None


def test_score_query_ignores_empty_string_agent_notes(db_dir, db_id):
    result = score_query(
        db_id,
        "SELECT COUNT(*) FROM students",
        "SELECT COUNT(*) FROM students",
        db_dir,
        agent_notes="",
    )

    assert result.detail is None
