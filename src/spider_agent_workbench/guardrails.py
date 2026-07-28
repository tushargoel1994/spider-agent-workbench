"""
Code-based safety checks that sit between the agent's SQL and the executor.
These are plain functions/regexes, not prompt instructions — a prompt telling
the model "don't run DELETE" can be argued around; a check that refuses to
execute cannot.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

from spider_agent_workbench.paths import DATABASES_DIR
from spider_agent_workbench.schema import get_table_list

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

MAX_QUERY_CHARS = 2000

_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([`\"\[]?\w+[`\"\]]?)", re.IGNORECASE)


@dataclass(frozen=True)
class GuardrailResult:
    ok: bool
    reason: str | None = None


def check_read_only(sql: str) -> GuardrailResult:
    """Reject anything that isn't a read-only SELECT/CTE/EXPLAIN statement."""
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", sql, re.IGNORECASE):
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
    available = get_table_list(db_id, db_dir)
    available_lower = {t.lower() for t in available}
    referenced = {m.strip("`\"[]") for m in _TABLE_REF_RE.findall(sql)}

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


def validate_sql(db_id: str, sql: str, db_dir: Path = DATABASES_DIR) -> GuardrailResult:
    """Run all guardrail checks in order, short-circuiting on the first failure."""
    for check in (check_read_only, check_query_length):
        result = check(sql)
        if not result.ok:
            return result

    return check_schema_tables(db_id, sql, db_dir)
