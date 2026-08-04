import sqlite3

import pytest

from spider_agent_workbench.executor import execute_query

# Candidate tests for executor.py — uncomment/implement the ones you want.
#
# execute_query:
#   test_execute_query_returns_headers_and_rows    - simple SELECT returns correct headers list and row tuples
#   test_execute_query_truncates_at_max_rows        - max_rows smaller than result set sets truncated=True and caps rows,
#   test_execute_query_not_truncated_when_under_limit - result set smaller than max_rows sets truncated=False
#   test_execute_query_no_result_set_statement      - a statement with cursor.description=None (e.g. no-op) returns headers=None, rows=[]
#   test_execute_query_raises_on_missing_db_file    - nonexistent db_id/db_dir raises sqlite3.Error with a clear message


def test_execute_query_returns_headers_and_rows(db_dir, db_id):
    result = execute_query(db_id, "SELECT name FROM students ORDER BY name", db_dir)
    assert result.headers == ["name"]
    assert result.rows == [("Alice",), ("Bob",), ("Carol",)]


def test_execute_query_truncates_at_max_rows(db_dir, db_id):
    result = execute_query(db_id, "SELECT name FROM students ORDER BY name", db_dir, max_rows=2)
    assert result.truncated
    assert len(result.rows) == 2


def test_execute_query_not_truncated_when_under_limit(db_dir, db_id):
    result = execute_query(db_id, "SELECT name FROM students ORDER BY name", db_dir, max_rows=50)
    assert not result.truncated
    assert len(result.rows) == 3


def test_execute_query_no_result_set_statement(db_dir, db_id):
    result = execute_query(db_id, "DELETE FROM students WHERE id = 999", db_dir)
    assert result.headers is None
    assert result.rows == []


def test_execute_query_raises_on_missing_db_file(db_dir):
    with pytest.raises(sqlite3.Error):
        execute_query("missing_db", "SELECT 1", db_dir)


def test_execute_query_rejects_stacked_multi_statement_sql(db_dir, db_id):
    with pytest.raises(sqlite3.Error):
        execute_query(db_id, "SELECT * FROM students; DROP TABLE students", db_dir)