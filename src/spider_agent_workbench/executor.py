"""
Low-level SQL execution. Returns structured data; raises on error.
This is the seam where guardrails will plug in (Phase 3).
"""

from __future__ import annotations
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from spider_agent_workbench.paths import DATABASES_DIR
from spider_agent_workbench.schema import get_sqlite_path


@dataclass(frozen=True)
class QueryResult:
    headers: list[str] | None      # None for statements with no result set
    rows: list[tuple]
    truncated: bool                # True if hit max_rows limit

    @property
    def row_count(self) -> int:
        return len(self.rows)


def execute_query(
    db_id: str,
    query: str,
    db_dir: Path = DATABASES_DIR,
    timeout: float = 5.0,
    max_rows: int = 50,
) -> QueryResult:
    """Execute SQL read-only. Returns structured result; raises sqlite3.Error on failure.

    The caller (tools.py for the LLM, guardrails.py for validation, eval for comparison)
    decides how to present or use the result.
    """
    path = get_sqlite_path(db_id, db_dir)
    if path is None or not path.exists():
        raise sqlite3.Error(f"Database file not found for db_id '{db_id}' in {db_dir}")

    # uri = f"file:{path}?mode=ro"
    with closing(sqlite3.connect(path, timeout=timeout)) as conn:
        cursor = conn.execute(query)
        if cursor.description is None:
            return QueryResult(headers=None, rows=[], truncated=False)
        headers = [d[0] for d in cursor.description]
        rows = cursor.fetchmany(max_rows + 1)  # peek one extra to detect truncation
        truncated = len(rows) > max_rows
        return QueryResult(
            headers=headers,
            rows=rows[:max_rows],
            truncated=truncated,
        )