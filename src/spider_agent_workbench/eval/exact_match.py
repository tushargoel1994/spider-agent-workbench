"""
Exact Match (EM) scoring, via the official Spider evaluation scripts vendored
unmodified in eval/spider_official/ (process_sql.py, evaluation.py — see
spider_official/notice.md). This module is our own, small adapter around
them: it never re-derives Spider's clause-matching or hardness rules itself,
it only translates between this project's types (db_id, plain SQL strings,
Path objects) and what the vendored code expects.

Also reports "hardness" (easy/medium/hard/extra) as a side effect -- it's
computed by the same vendored code from the gold SQL's structure, so there's
no separate step needed to get Spider's official difficulty bucket.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from spider_agent_workbench.eval.spider_official import process_sql as _process_sql

# evaluation.py has a bare `from process_sql import tokenize, get_schema,
# get_tables_with_alias, Schema, get_sql` -- written assuming it's run as a
# standalone script sitting next to process_sql.py, not as part of a Python
# package. We can't edit either vendored file, so before importing
# evaluation.py we register our real process_sql module under the bare name
# "process_sql" in sys.modules -- Python's import system checks sys.modules
# before searching sys.path, so evaluation.py's import line resolves against
# our already-imported module instead of failing.
sys.modules.setdefault("process_sql", _process_sql)

from spider_agent_workbench.eval.spider_official import evaluation as _evaluation  # noqa: E402

from spider_agent_workbench.paths import DATABASES_DIR, SPIDER_TABLES_JSON  # noqa: E402
from spider_agent_workbench.schema import get_sqlite_path  # noqa: E402


@dataclass(frozen=True)
class ExactMatchResult:
    score: int  # 0 or 1
    hardness: str  # "easy" | "medium" | "hard" | "extra"


_nltk_data_lock = threading.Lock()
_nltk_data_ready = False


def _ensure_nltk_data() -> None:
    """process_sql.py tokenizes SQL with nltk.word_tokenize, which needs the
    punkt/punkt_tab tokenizer data files (not just the nltk pip package)
    downloaded once. Check for them and fetch them on first use instead of
    requiring a separate manual setup step -- guarded by a lock since
    eval/runner.py calls this from multiple worker threads."""
    global _nltk_data_ready
    if _nltk_data_ready:
        return

    with _nltk_data_lock:
        if _nltk_data_ready:
            return

        import nltk

        for resource_path in ("tokenizers/punkt_tab", "tokenizers/punkt"):
            try:
                nltk.data.find(resource_path)
                _nltk_data_ready = True
                return
            except LookupError:
                continue

        for package_name in ("punkt_tab", "punkt"):
            try:
                if nltk.download(package_name, quiet=True):
                    _nltk_data_ready = True
                    return
            except Exception:
                continue

        raise RuntimeError(
            "Exact Match scoring needs NLTK's punkt tokenizer data, and it "
            "could not be downloaded automatically (no network access?). Run "
            "this once, with network access, then retry:\n"
            "    uv run python -m nltk.downloader punkt punkt_tab"
        )


@lru_cache(maxsize=None)
def _load_foreign_key_maps(tables_json_path: Path) -> dict:
    """Cached since a batch run calls score_exact_match once per question,
    but the foreign-key map for a given tables.json never changes."""
    return _evaluation.build_foreign_key_map_from_json(tables_json_path)


def _rebuild_for_comparison(sql: dict, schema: "_evaluation.Schema", kmap: dict) -> dict:
    """Normalize a parsed SQL dict the same way the official evaluate()
    function does before comparing: literal values are dropped (EM compares
    structure, not values) and columns are mapped to their foreign-key
    equivalence class, so e.g. two different-but-joined tables' matching
    columns aren't treated as different columns."""
    valid_col_units = _evaluation.build_valid_col_units(sql["from"]["table_units"], schema)
    sql = _evaluation.rebuild_sql_val(sql)
    sql = _evaluation.rebuild_sql_col(valid_col_units, sql, kmap)
    return sql


def score_exact_match(
    db_id: str,
    predicted_sql: str | None,
    gold_sql: str,
    db_dir: Path = DATABASES_DIR,
    tables_json_path: Path = SPIDER_TABLES_JSON,
) -> ExactMatchResult:
    """Score `predicted_sql` against `gold_sql` for Exact Match, and report
    the gold SQL's official Spider hardness bucket.

    Gold SQL is expected to always parse -- if it doesn't, that's broken
    data/setup, not a wrong answer from the agent, so it's left to raise
    (same principle eval/sql_result_scorer.py applies to gold-SQL execution
    failures). A predicted SQL that fails to parse under the vendored,
    stricter-than-SQLite grammar scores 0 instead of raising, so one bad
    prediction doesn't crash a whole batch run.
    """
    _ensure_nltk_data()

    sqlite_path = get_sqlite_path(db_id, db_dir)
    if sqlite_path is None:
        raise FileNotFoundError(f"No sqlite database found for db_id={db_id!r} under {db_dir}")

    schema = _evaluation.Schema(_evaluation.get_schema(str(sqlite_path)))

    gold_parsed = _process_sql.get_sql(schema, gold_sql)
    hardness = _evaluation.Evaluator().eval_hardness(gold_parsed)

    if not predicted_sql:
        return ExactMatchResult(score=0, hardness=hardness)

    try:
        predicted_parsed = _process_sql.get_sql(schema, predicted_sql)
    except Exception:
        return ExactMatchResult(score=0, hardness=hardness)

    kmaps = _load_foreign_key_maps(Path(tables_json_path))
    kmap = kmaps.get(db_id, {})

    gold_rebuilt = _rebuild_for_comparison(gold_parsed, schema, kmap)
    predicted_rebuilt = _rebuild_for_comparison(predicted_parsed, schema, kmap)

    matched = _evaluation.Evaluator().eval_exact_match(predicted_rebuilt, gold_rebuilt)
    return ExactMatchResult(score=int(bool(matched)), hardness=hardness)
