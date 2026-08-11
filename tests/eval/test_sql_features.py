"""Tests for eval/sql_features.py — tag_features(), which tags a SQL query
with which structural features it uses (JOIN, GROUP BY, subquery, set
operation). Used to slice accuracy by "does this question need a JOIN"
rather than difficulty alone.

sqlglot AST-walking patterns here mirror the ones already used and tested in
guardrails/sql_guardrails.py (check_num_joins, check_subquery_depth) — this
module doesn't reimplement those checks, it reuses the same approach for a
different purpose (tagging, not rejecting).
"""

from spider_agent_workbench.eval.sql_features import tag_features


_ALL_FALSE = {"has_join": False, "has_group_by": False, "has_subquery": False, "has_set_op": False}


# tag_features — one feature true at a time


def test_tag_features_plain_query_has_no_features():
    sql = "SELECT name FROM students WHERE id = 1"
    assert tag_features(sql) == _ALL_FALSE


def test_tag_features_detects_join():
    sql = "SELECT s.name FROM students s JOIN courses c ON s.course_id = c.id"
    tags = tag_features(sql)
    assert tags["has_join"] is True
    assert tags["has_group_by"] is False
    assert tags["has_subquery"] is False
    assert tags["has_set_op"] is False


def test_tag_features_detects_group_by():
    sql = "SELECT course_id, count(*) FROM students GROUP BY course_id"
    tags = tag_features(sql)
    assert tags["has_group_by"] is True
    assert tags["has_join"] is False
    assert tags["has_subquery"] is False
    assert tags["has_set_op"] is False


def test_tag_features_detects_subquery():
    sql = "SELECT name FROM students WHERE course_id IN (SELECT id FROM courses WHERE title = 'Math')"
    tags = tag_features(sql)
    assert tags["has_subquery"] is True
    assert tags["has_join"] is False
    assert tags["has_group_by"] is False
    assert tags["has_set_op"] is False


def test_tag_features_detects_union_as_set_op_not_subquery():
    sql = "SELECT name FROM students UNION SELECT title FROM courses"
    tags = tag_features(sql)
    assert tags["has_set_op"] is True
    # A UNION's two branches are parallel top-level queries, not one nested
    # inside the other -- this must not also count as a subquery.
    assert tags["has_subquery"] is False


def test_tag_features_detects_intersect_as_set_op():
    sql = "SELECT name FROM students INTERSECT SELECT name FROM students"
    assert tag_features(sql)["has_set_op"] is True


def test_tag_features_detects_except_as_set_op():
    sql = "SELECT name FROM students EXCEPT SELECT name FROM students"
    assert tag_features(sql)["has_set_op"] is True


# tag_features — multiple features true at once


def test_tag_features_detects_join_and_group_by_together():
    sql = "SELECT c.title, count(*) FROM students s JOIN courses c ON s.course_id = c.id GROUP BY c.title"
    tags = tag_features(sql)
    assert tags["has_join"] is True
    assert tags["has_group_by"] is True
    assert tags["has_subquery"] is False


# tag_features — malformed SQL is reported as having no features, not a crash


def test_tag_features_returns_all_false_for_unparseable_sql():
    assert tag_features("not valid sql at all") == _ALL_FALSE
