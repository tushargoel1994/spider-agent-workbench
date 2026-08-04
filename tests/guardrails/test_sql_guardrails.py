import pytest

from spider_agent_workbench.guardrails.sql_guardrails import (
    FORBIDDEN_KEYWORDS,
    MAX_QUERY_CHARS,
    MAX_SUBQUERY_DEPTH,
    MAX_TABLE_JOINS,
    check_num_joins,
    check_query_length,
    check_read_only,
    check_schema_tables,
    check_subquery_depth,
    validate_sql,
)


def _joins_query(num_joins: int) -> str:
    tables = [f"t{i}" for i in range(num_joins + 1)]
    return "SELECT * FROM " + " JOIN ".join(tables)


def _nested_from_subquery(depth: int) -> str:
    """Depth-0 is a flat select; each level wraps the previous as a derived table in FROM."""
    sql = "SELECT * FROM students"
    for _ in range(depth):
        sql = f"SELECT * FROM ({sql})"
    return sql


def _nested_where_subquery(depth: int) -> str:
    """Depth-0 is a flat select; each level adds one more WHERE ... IN (SELECT ...) layer."""
    if depth == 0:
        return "SELECT * FROM students"
    inner = "SELECT id FROM courses"
    for _ in range(depth - 1):
        inner = f"SELECT id FROM courses WHERE id IN ({inner})"
    return f"SELECT * FROM students WHERE course_id IN ({inner})"


def _nested_select_list_subquery(depth: int) -> str:
    """Depth-0 is a flat select; each level adds one more scalar subquery in the SELECT list."""
    if depth == 0:
        return "SELECT * FROM students"
    inner = "SELECT COUNT(*) FROM courses"
    for _ in range(depth - 1):
        inner = f"SELECT ({inner}) FROM courses"
    return f"SELECT ({inner}) FROM students"

def test_check_read_only_allows_cte_select():
    sql = "WITH x AS (SELECT * FROM students) SELECT * FROM x"
    assert check_read_only(sql).ok


def test_check_read_only_ignores_keyword_inside_identifier():
    sql = "SELECT updated_at FROM students"
    assert check_read_only(sql).ok


@pytest.mark.parametrize("keyword", FORBIDDEN_KEYWORDS)
def test_check_read_only_rejects_each_forbidden_keyword(keyword):
    samples = {
        "INSERT": "INSERT INTO students VALUES (1, 'a')",
        "UPDATE": "UPDATE students SET name = 'a' WHERE id = 1",
        "DELETE": "DELETE FROM students WHERE id = 1",
        "DROP": "DROP TABLE students",
        "ALTER": "ALTER TABLE students ADD COLUMN age INT",
        "TRUNCATE": "TRUNCATE TABLE students",
        "PRAGMA": "PRAGMA table_info(students)",
        "ATTACH": "ATTACH DATABASE 'x.db' AS x",
        "DETACH": "DETACH DATABASE x",
        "CREATE": "CREATE TABLE x (id INT)",
        "REPLACE": "REPLACE INTO students VALUES (1, 'a')",
        "VACUUM": "VACUUM",
        "REINDEX": "REINDEX students",
    }
    assert not check_read_only(samples[keyword]).ok


def test_check_read_only_allows_plain_select():
    assert check_read_only("SELECT * FROM students").ok


def test_check_read_only_ignores_forbidden_word_inside_string_literal():
    sql = "SELECT * FROM students WHERE name = 'please delete this update'"
    assert check_read_only(sql).ok


def test_check_query_length_allows_under_limit():
    assert check_query_length("SELECT 1").ok


def test_check_query_length_rejects_over_limit():
    sql = "SELECT * FROM students WHERE " + "x" * MAX_QUERY_CHARS
    assert not check_query_length(sql).ok


def test_check_query_length_boundary_exact_limit():
    sql = "SELECT 1" + " " * (MAX_QUERY_CHARS - len("SELECT 1"))
    assert len(sql) == MAX_QUERY_CHARS
    assert check_query_length(sql).ok


def test_check_num_joins_allows_up_to_max():
    assert check_num_joins(_joins_query(MAX_TABLE_JOINS)).ok


def test_check_num_joins_rejects_over_max():
    result = check_num_joins(_joins_query(MAX_TABLE_JOINS + 1))
    assert not result.ok
    assert "JOIN" in result.reason


def test_check_num_joins_zero_joins_passes():
    assert check_num_joins("SELECT * FROM students").ok


def test_check_schema_tables_allows_known_table(db_dir, db_id):
    assert check_schema_tables(db_id, "SELECT * FROM students", db_dir).ok


def test_check_schema_tables_rejects_unknown_table(db_dir, db_id):
    result = check_schema_tables(db_id, "SELECT * FROM ghost_table", db_dir)
    assert not result.ok
    assert "ghost_table" in result.reason
    assert "students" in result.reason
    assert "courses" in result.reason


def test_check_schema_tables_allows_multiple_known_tables(db_dir, db_id):
    sql = "SELECT * FROM students JOIN courses ON students.course_id = courses.id"
    assert check_schema_tables(db_id, sql, db_dir).ok


def test_check_schema_tables_handles_quoted_identifiers(db_dir, db_id):
    assert check_schema_tables(db_id, 'SELECT * FROM "students"', db_dir).ok


def test_validate_sql_allows_clean_select(db_dir, db_id):
    assert validate_sql(db_id, "SELECT * FROM students", db_dir).ok


def test_validate_sql_short_circuits_on_first_failure(db_dir, db_id):
    result = validate_sql(db_id, "DELETE FROM ghost_table", db_dir)
    assert not result.ok
    assert "DELETE" in result.reason


def test_check_subquery_depth_allows_flat_select():
    assert check_subquery_depth("SELECT * FROM students").ok


def test_check_subquery_depth_allows_up_to_max_depth():
    assert check_subquery_depth(_nested_from_subquery(MAX_SUBQUERY_DEPTH)).ok


def test_check_subquery_depth_rejects_over_max_depth():
    result = check_subquery_depth(_nested_from_subquery(MAX_SUBQUERY_DEPTH + 1))
    assert not result.ok
    assert "depth" in result.reason.lower() or "nest" in result.reason.lower()


def test_check_subquery_depth_counts_where_clause_subqueries():
    assert check_subquery_depth(_nested_where_subquery(MAX_SUBQUERY_DEPTH)).ok
    result = check_subquery_depth(_nested_where_subquery(MAX_SUBQUERY_DEPTH + 1))
    assert not result.ok


def test_check_subquery_depth_counts_from_clause_subqueries():
    assert check_subquery_depth(_nested_from_subquery(MAX_SUBQUERY_DEPTH)).ok
    result = check_subquery_depth(_nested_from_subquery(MAX_SUBQUERY_DEPTH + 1))
    assert not result.ok


def test_check_subquery_depth_counts_scalar_subquery_in_select_list():
    assert check_subquery_depth(_nested_select_list_subquery(MAX_SUBQUERY_DEPTH)).ok
    result = check_subquery_depth(_nested_select_list_subquery(MAX_SUBQUERY_DEPTH + 1))
    assert not result.ok


def test_check_subquery_depth_sibling_subqueries_do_not_add_up():
    # Five sibling depth-1 subqueries: a naive "sum of all subqueries" implementation
    # would total 5 (> MAX_SUBQUERY_DEPTH) and wrongly reject; the deepest branch is
    # only 1 level deep, so this must pass.
    conditions = " AND ".join(["id IN (SELECT id FROM courses)"] * 5)
    sql = f"SELECT * FROM students WHERE {conditions}"
    assert check_subquery_depth(sql).ok


def test_check_subquery_depth_ignores_flat_cte_definitions():
    sql = "WITH x AS (SELECT * FROM students) SELECT * FROM x"
    assert check_subquery_depth(sql).ok


def test_check_subquery_depth_rejects_over_max_depth_inside_cte():
    cte_body = _nested_from_subquery(MAX_SUBQUERY_DEPTH + 1)
    sql = f"WITH x AS ({cte_body}) SELECT * FROM x"
    result = check_subquery_depth(sql)
    assert not result.ok


def test_check_subquery_depth_handles_malformed_sql_gracefully():
    assert check_subquery_depth("SELECT FROM WHERE (((").ok


def test_validate_sql_blocks_over_nested_subquery(db_dir, db_id):
    sql = _nested_from_subquery(MAX_SUBQUERY_DEPTH + 1)
    result = validate_sql(db_id, sql, db_dir)
    assert not result.ok
