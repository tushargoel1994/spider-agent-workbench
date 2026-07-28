"""
Compares the result of an agent-generated SQL query against gold SQL for the
same question, and produces a binary score (1 = results match, 0 = they
don't) plus enough detail to see why a mismatch happened.

Used by scripts/phase_1_test.py; also runnable standalone to check any two
queries against each other, e.g.:

    uv run src/spider_agent_workbench/eval/sql_result_scorer.py soccer_1 "SELECT ..." "SELECT ..."
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from spider_agent_workbench.executor import execute_query
from spider_agent_workbench.guardrails import validate_sql
from spider_agent_workbench.paths import DATABASES_DIR

# Large enough that Spider's dev/train databases never get row-truncated —
# a truncated comparison would silently bias the score.
SCORING_MAX_ROWS = 100_000

_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


@dataclass(frozen=True)
class ScoreResult:
    score: int  # 0 or 1
    # "match" | "no_sql" | "guardrail_rejected" | "execution_error"
    # | "row_count_mismatch" | "column_count_mismatch" | "value_mismatch"
    status: str
    detail: str | None = None


def has_order_by(sql: str) -> bool:
    """Heuristic: does the query specify row order? If not, SQLite's row
    order is undefined and results must be compared regardless of order."""
    return bool(_ORDER_BY_RE.search(sql))


def _normalize_row(row: tuple) -> tuple:
    return tuple(round(value, 6) if isinstance(value, float) else value for value in row)


def _normalize_rows(rows: list[tuple]) -> Counter:
    return Counter(_normalize_row(row) for row in rows)


def score_query(
    db_id: str,
    predicted_sql: str | None,
    gold_sql: str,
    db_dir: Path = DATABASES_DIR,
) -> ScoreResult:
    """Score a predicted SQL query against the gold SQL for the same question.

    Re-runs guardrails on `predicted_sql` before executing it. The agent's
    submit_final_sql tool call can carry SQL that guardrails already
    rejected once (the tool returns an error string back to the agent, but
    the call itself still happened and is what gets extracted as the
    "final" answer) — this must not execute unfiltered agent output.
    """
    if not predicted_sql:
        return ScoreResult(0, "no_sql", "Agent did not submit a query.")

    guardrail_result = validate_sql(db_id, predicted_sql, db_dir)
    if not guardrail_result.ok:
        return ScoreResult(0, "guardrail_rejected", guardrail_result.reason)

    try:
        predicted = execute_query(db_id, predicted_sql, db_dir, max_rows=SCORING_MAX_ROWS)
    except sqlite3.Error as e:
        return ScoreResult(0, "execution_error", str(e))

    try:
        gold = execute_query(db_id, gold_sql, db_dir, max_rows=SCORING_MAX_ROWS)
    except sqlite3.Error as e:
        # A gold-SQL failure means the harness/data is broken, not that the
        # agent got the question wrong — surface it loudly instead of
        # silently scoring it as a mismatch.
        raise RuntimeError(
            f"Gold SQL failed to execute for db_id={db_id!r}: {e}\nSQL: {gold_sql}"
        ) from e

    if has_order_by(gold_sql):
        matched = [_normalize_row(r) for r in gold.rows] == [_normalize_row(r) for r in predicted.rows]
    else:
        matched = _normalize_rows(gold.rows) == _normalize_rows(predicted.rows)

    if matched:
        return ScoreResult(1, "match")

    if len(gold.rows) != len(predicted.rows):
        return ScoreResult(
            0,
            "row_count_mismatch",
            f"gold={len(gold.rows)} rows, predicted={len(predicted.rows)} rows",
        )

    gold_cols = len(gold.rows[0]) if gold.rows else len(gold.headers or [])
    pred_cols = len(predicted.rows[0]) if predicted.rows else len(predicted.headers or [])
    if gold_cols != pred_cols:
        return ScoreResult(
            0,
            "column_count_mismatch",
            f"gold has {gold_cols} columns, predicted has {pred_cols}",
        )

    return ScoreResult(0, "value_mismatch", "Same row/column shape, different values.")


def _main() -> None:
    parser = argparse.ArgumentParser(description="Score a predicted SQL query against gold SQL.")
    parser.add_argument("db_id")
    parser.add_argument("predicted_sql")
    parser.add_argument("gold_sql")
    args = parser.parse_args()

    result = score_query(args.db_id, args.predicted_sql, args.gold_sql)
    print(f"score={result.score} status={result.status} detail={result.detail}")


if __name__ == "__main__":
    _main()
