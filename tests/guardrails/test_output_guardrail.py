"""
Test file for output guardrails
"""

import pytest

from spider_agent_workbench.constants import MAX_TABLE_JOINS
from spider_agent_workbench.guardrails.output_guardrails import check_output_valid_sql

# check_output_valid_sql validates the agent's final SQL three ways:
#   - structurally, via sqlglot (catches syntax garbage)
#   - via sql_guardrails.validate_sql (catches SQL that is well-formed and would
#     execute fine, but violates safety/schema rules, e.g. a write statement or an
#     unknown table) — this must run BEFORE execute_query, since letting an unsafe
#     statement reach sqlite defeats the point of a guardrail
#   - by actually running it through execute_query (catches SQL that parses fine
#     and passes guardrails but fails at runtime, e.g. a syntactically valid
#     reference to a column that doesn't exist)


def test_check_valid_output(db_dir, db_id):
    assert check_output_valid_sql(db_id, db_dir, "SELECT * FROM students").ok


@pytest.mark.parametrize(
    "agent_output",
    [
        "",
        "SELECT FROM WHERE (((",
        "SELECT * FROM ghost_table",
    ],
)
def test_reject_empty_invalid_output_sql(db_dir, db_id, agent_output):
    assert not check_output_valid_sql(db_id, db_dir, agent_output).ok


def test_reject_output_that_fails_sql_guardrails(db_dir, db_id):
    result = check_output_valid_sql(db_id, db_dir, "DELETE FROM students")
    assert not result.ok
    assert "DELETE" in result.reason


def test_reject_output_that_would_otherwise_execute_successfully(db_dir, db_id):
    """A query that violates a guardrail (too many joins) but is otherwise
    valid, executable SQL — proves validate_sql is what catches this, since
    parsing and execute_query alone would both let it through."""
    aliases = [f"students t{i}" for i in range(MAX_TABLE_JOINS + 2)]
    sql = "SELECT * FROM " + " JOIN ".join(aliases)
    result = check_output_valid_sql(db_id, db_dir, sql)
    assert not result.ok
    assert "JOIN" in result.reason
