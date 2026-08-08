"""
Tags a SQL query with which structural features it uses -- JOIN, GROUP BY,
subquery, set operation (UNION/INTERSECT/EXCEPT) -- so accuracy can be sliced
by "does this question need a JOIN" in addition to difficulty.

Always tag the *gold* SQL, not the agent's predicted SQL: the point is to
know how the agent does on questions that need a given feature, which is a
property of the question, not of whatever the agent happened to write.

Reuses the same sqlglot AST-walking approach already used and tested in
guardrails/sql_guardrails.py (check_num_joins, check_subquery_depth) for a
different purpose -- tagging booleans instead of pass/fail guardrail checks.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_NO_FEATURES = {"has_join": False, "has_group_by": False, "has_subquery": False, "has_set_op": False}


def _top_level_selects(node: exp.Expression) -> list[exp.Select]:
    """The Select nodes that sit at the top of the query: either the query
    itself, or its parallel branches under a root-level set operation
    (UNION/INTERSECT/EXCEPT). Doesn't descend into subqueries, so a UNION's
    two branches count as top-level, not nested."""
    if isinstance(node, exp.Select):
        return [node]
    if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
        return _top_level_selects(node.this) + _top_level_selects(node.expression)
    return []


def tag_features(sql: str) -> dict[str, bool]:
    """Return which SQL features `sql` uses: has_join, has_group_by,
    has_subquery, has_set_op. Unparseable SQL is reported as having none of
    them rather than raising."""
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return dict(_NO_FEATURES)

    has_join = any(parsed.find_all(exp.Join))
    has_group_by = any(parsed.find_all(exp.Group))
    has_set_op = any(parsed.find_all(exp.Union, exp.Intersect, exp.Except))

    top_level_selects = _top_level_selects(parsed)
    all_selects = list(parsed.find_all(exp.Select))
    has_subquery = len(all_selects) > len(top_level_selects)

    return {
        "has_join": has_join,
        "has_group_by": has_group_by,
        "has_subquery": has_subquery,
        "has_set_op": has_set_op,
    }
