import sqlite3
from contextlib import closing
from pathlib import Path

from spider_agent_workbench import tools


def test_list_tables_returns_comma_separated_names(db_dir, db_id):
    result = tools.list_tables.invoke({"db_id": db_id, "db_dir": db_dir})
    assert "students" in result
    assert "courses" in result


def test_list_tables_empty_db_returns_error_string(tmp_path: Path):
    empty_db_id = "empty"
    db_folder = tmp_path / empty_db_id
    db_folder.mkdir()
    with closing(sqlite3.connect(db_folder / f"{empty_db_id}.sqlite")):
        pass

    result = tools.list_tables.invoke({"db_id": empty_db_id, "db_dir": tmp_path})
    assert "Error" in result


def test_describe_table_returns_create_sql(db_dir, db_id):
    result = tools.describe_table(db_id, "students", db_dir)
    assert "CREATE TABLE students" in result


def test_describe_table_unknown_table_lists_available(db_dir, db_id):
    result = tools.describe_table(db_id, "ghost", db_dir)
    assert "Error" in result
    assert "students" in result
    assert "courses" in result


def test_describe_table_missing_db_id_or_table_name(db_dir, db_id):
    assert tools.describe_table(db_id, "", db_dir) == "database name or table name not present"
    assert tools.describe_table("", "students", db_dir) == "database name or table name not present"


def test_sample_rows_returns_formatted_table(db_dir, db_id):
    result = tools.sample_rows(db_id, "students", 5, db_dir)
    assert "Alice" in result


def test_sample_rows_respects_num_rows_limit(db_dir, db_id):
    result = tools.sample_rows(db_id, "students", 1, db_dir)
    header_line, sep_line, *body_lines = result.splitlines()
    assert len(body_lines) == 1


def test_sample_rows_blocked_by_guardrail_on_bad_table(db_dir, db_id):
    result = tools.sample_rows(db_id, "ghost_table", 5, db_dir)
    assert "Rejected" in result


def test_run_query_returns_formatted_results(db_dir, db_id):
    result = tools.run_query(db_id, "SELECT name FROM students ORDER BY name", db_dir)
    assert "Alice" in result


def test_run_query_empty_query_returns_error(db_dir, db_id):
    result = tools.run_query(db_id, "", db_dir)
    assert result == "Error: Query empty, please fill query"


def test_run_query_blocked_by_guardrail(db_dir, db_id):
    result = tools.run_query(db_id, "DELETE FROM students", db_dir)
    assert "Rejected" in result


def test_run_query_no_rows_returns_message(db_dir, db_id):
    result = tools.run_query(db_id, "SELECT * FROM students WHERE id = 999", db_dir)
    assert result == "Query returned no rows."


def test_run_query_truncates_and_notes_it(db_dir, db_id):
    result = tools.run_query(db_id, "SELECT * FROM students", db_dir, max_rows=1)
    assert "(truncated to first 1 rows)" in result


def test_run_query_sql_error_returns_message(db_dir, db_id):
    result = tools.run_query(db_id, "SELECT * FROM", db_dir)
    assert result.startswith("SQL Error:")


def test_submit_final_sql_accepts_valid_query(db_dir, db_id):
    result = tools.submit_final_sql(db_id, "SELECT * FROM students", db_dir)
    assert result == "Final SQL recorded: SELECT * FROM students"