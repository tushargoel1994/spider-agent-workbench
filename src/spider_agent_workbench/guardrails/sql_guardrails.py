"""
Code-based safety checks that sit between the agent's SQL and the executor.
These are plain functions/regexes, not prompt instructions — a prompt telling
the model "don't run DELETE" can be argued around; a check that refuses to
execute cannot.
"""

from __future__ import annotations

from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType

from spider_agent_workbench.paths import DATABASES_DIR
from spider_agent_workbench.schema import get_column_list, get_table_list
from spider_agent_workbench.guardrails.guardrail_result import GuardrailResult
from spider_agent_workbench.constants import MAX_QUERY_CHARS, MAX_TABLE_JOINS, MAX_SUBQUERY_DEPTH

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "PRAGMA",
    "ATTACH",
    "DETACH",
    "CREATE",
    "REPLACE",
    "VACUUM",
    "REINDEX",
)


def check_read_only(sql: str) -> GuardrailResult:
    """Reject anything that isn't a read-only SELECT/CTE/EXPLAIN statement.

    Tokenizes with sqlglot instead of regexing the raw text so a forbidden
    word inside a quoted string literal (data, not a command) isn't mistaken
    for the keyword itself — sqlglot's tokenizer keeps string literals as a
    single STRING token regardless of what text they contain.
    """
    try:
        tokens = sqlglot.tokenize(sql, read="sqlite")
    except Exception:
        # Malformed SQL isn't this check's job to reject — let it fall through
        # to execution, where sqlite reports the real syntax error.
        return GuardrailResult(ok=True)

    for token in tokens:
        if token.token_type == TokenType.STRING:
            continue
        keyword = token.token_type.name
        if keyword not in FORBIDDEN_KEYWORDS:
            keyword = token.text.upper()
        if keyword in FORBIDDEN_KEYWORDS:
            return GuardrailResult(
                ok=False,
                reason=f"Rejected: '{keyword}' is not allowed. Only read-only SELECT queries are permitted.",
            )
    return GuardrailResult(ok=True)


def check_query_length(sql: str, max_chars: int = MAX_QUERY_CHARS) -> GuardrailResult:
    """Reject queries above a basic length bound (stand-in for join/subquery counting)."""
    if len(sql) > max_chars:
        return GuardrailResult(
            ok=False,
            reason=f"Rejected: query is {len(sql)} characters, exceeds the {max_chars}-character limit.",
        )
    return GuardrailResult(ok=True)


def check_schema_tables(db_id: str, sql: str, db_dir: Path = DATABASES_DIR) -> GuardrailResult:
    """Reject queries that reference tables not present in this db_id's schema."""
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        # Malformed SQL isn't this check's job to reject — let it fall through
        # to execution, where sqlite reports the real syntax error.
        return GuardrailResult(ok=True)

    available = get_table_list(db_id, db_dir)
    available_lower = {t.lower() for t in available}
    referenced = {t.name for t in parsed.find_all(exp.Table)}

    unknown = sorted(t for t in referenced if t.lower() not in available_lower)
    if unknown:
        return GuardrailResult(
            ok=False,
            reason=(
                f"Rejected: unknown table(s) {unknown}. "
                f"Available tables in '{db_id}': {', '.join(available)}"
            ),
        )
    return GuardrailResult(ok=True)


def check_schema_columns(db_id: str, sql: str, db_dir: Path = DATABASES_DIR) -> GuardrailResult:
    """Reject queries that reference columns not present on their table in this db_id's schema.

    A qualified column (alias.column) is checked against that alias's table only; an
    unqualified column is checked against the union of all referenced tables' columns,
    since resolving it to one specific table would require full join-aware name
    resolution that isn't worth it for a guardrail.
    """
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        # Malformed SQL isn't this check's job to reject — let it fall through
        # to execution, where sqlite reports the real syntax error.
        return GuardrailResult(ok=True)

    tables = list(parsed.find_all(exp.Table))
    if not tables:
        return GuardrailResult(ok=True)

    table_columns: dict[str, list[str]] = {}
    alias_to_table: dict[str, str] = {}
    for table in tables:
        table_name = table.name
        if table_name not in table_columns:
            table_columns[table_name] = get_column_list(db_id, table_name, db_dir)
        alias_to_table[(table.alias or table_name).lower()] = table_name

    all_columns_lower = {
        column.lower() for columns in table_columns.values() for column in columns
    }

    unknown = set()
    for column in parsed.find_all(exp.Column):
        column_name = column.name
        if not column_name:
            continue
        qualifier = column.table
        if qualifier:
            resolved_table = alias_to_table.get(qualifier.lower())
            if resolved_table is None:
                # Unknown table/alias reference — check_schema_tables' job to reject.
                continue
            valid_columns = {c.lower() for c in table_columns.get(resolved_table, [])}
            if column_name.lower() not in valid_columns:
                unknown.add(column_name)
        elif column_name.lower() not in all_columns_lower:
            unknown.add(column_name)

    if unknown:
        return GuardrailResult(
            ok=False,
            reason=(
                f"Rejected: unknown column(s) {sorted(unknown)}. "
                f"Available columns: {table_columns}"
            ),
        )
    return GuardrailResult(ok=True)


def check_num_joins(sql: str, max_join: int = MAX_TABLE_JOINS) -> GuardrailResult:
    """Ensure there are no more than max_join JOINs in the query, counted via sqlglot's parsed AST."""
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        # Malformed SQL isn't this check's job to reject — let it fall through
        # to execution, where sqlite reports the real syntax error.
        return GuardrailResult(ok=True)

    num_joins = len(list(parsed.find_all(exp.Join)))
    if num_joins > max_join:
        return GuardrailResult(
            ok=False,
            reason=f"Rejected: query has {num_joins} JOINs, exceeds the {max_join}-join limit.",
        )
    return GuardrailResult(ok=True)


def _direct_child_selects(select: exp.Select) -> list[exp.Select]:
    """Selects nested exactly one level below `select` (i.e. not inside a further-nested
    select, and not inside a CTE definition, which is scored as its own independent root)."""
    children = []
    for node in select.find_all(exp.Select):
        if node is select:
            continue
        ancestor = node.parent
        crossed_cte = False
        while ancestor is not None and not isinstance(ancestor, exp.Select):
            if isinstance(ancestor, exp.With):
                crossed_cte = True
                break
            ancestor = ancestor.parent
        if not crossed_cte and ancestor is select:
            children.append(node)
    return children


def _select_depth(select: exp.Select) -> int:
    """0 for a select with no nested subqueries; otherwise 1 + the deepest child branch
    (siblings at the same level don't add up, only the deepest one counts)."""
    children = _direct_child_selects(select)
    if not children:
        return 0
    return 1 + max(_select_depth(child) for child in children)


def check_subquery_depth(sql: str, max_depth: int = MAX_SUBQUERY_DEPTH) -> GuardrailResult:
    """Reject queries whose subqueries nest deeper than max_depth.

    Each CTE body is scored as its own independent root alongside the main query body,
    so using WITH isn't penalized by itself, but a CTE that itself nests too deeply is
    still rejected.
    """
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        # Malformed SQL isn't this check's job to reject — let it fall through
        # to execution, where sqlite reports the real syntax error.
        return GuardrailResult(ok=True)

    root_select = parsed if isinstance(parsed, exp.Select) else parsed.find(exp.Select)
    if root_select is None:
        return GuardrailResult(ok=True)

    roots = [root_select]
    with_clause = root_select.args.get("with_")
    if with_clause is not None:
        for cte in with_clause.expressions:
            if isinstance(cte.this, exp.Select):
                roots.append(cte.this)

    depth = max(_select_depth(root) for root in roots)
    if depth > max_depth:
        return GuardrailResult(
            ok=False,
            reason=f"Rejected: query nests subqueries {depth} levels deep, exceeds the {max_depth}-level nesting limit.",
        )
    return GuardrailResult(ok=True)


def validate_sql(db_id: str, sql: str, db_dir: Path = DATABASES_DIR) -> GuardrailResult:
    """Run all guardrail checks in order, short-circuiting on the first failure."""
    for check in (check_read_only, check_query_length, check_num_joins, check_subquery_depth):
        result = check(sql)
        if not result.ok:
            return result

    result = check_schema_tables(db_id, sql, db_dir)
    if not result.ok:
        return result

    return check_schema_columns(db_id, sql, db_dir)