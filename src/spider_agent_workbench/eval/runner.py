"""
Batch runner: runs the agent over a batch of Spider questions (grouped by
db_id), scores each answer, and returns one result record per question.

Generalizes the sampling/threading/scoring pattern that scripts/test_phase.py
already uses for its fixed 10-question sample, so the same logic can run over
any size of sample without being hardcoded to it. scripts/test_phase.py itself
is left untouched — it stays the fixed-sample tool used to compare phases.

agent_factory/answer_fn/score_fn default to the real collaborators (build a
real agent, call the real agent, score with the real scorer) but can be
swapped out — this is what lets tests exercise run_eval's own logic (chunking
threads, building records, writing the log) without making real LLM calls or
touching a real database.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from spider_agent_workbench import agent as agent_workbench
from spider_agent_workbench import agent_builder_factory
from spider_agent_workbench.agent import AgentAnswer
from spider_agent_workbench.eval import exact_match, sql_result_scorer
from spider_agent_workbench.eval.exact_match import ExactMatchResult
from spider_agent_workbench.eval.sql_result_scorer import ScoreResult
from spider_agent_workbench.loaders import SpiderExample


def _split_into_chunks(items: list, num_chunks: int) -> list[list]:
    """Split `items` into `num_chunks` contiguous chunks (last chunk absorbs
    any remainder). If num_chunks > len(items), the leading chunks are empty
    and the last chunk gets everything — no items are lost or duplicated."""
    chunk_size = len(items) // num_chunks
    chunks = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = start + chunk_size if i < num_chunks - 1 else len(items)
        chunks.append(items[start:end])
    return chunks


def _append_json_line(path: Path, record: dict, lock: threading.Lock) -> None:
    """Append `record` as one line of JSON to `path`. Guarded by `lock` since
    multiple worker threads may call this at the same time — without it, two
    threads writing at once could interleave and corrupt a line."""
    line = json.dumps(record)
    with lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _run_chunk(
    db_ids: list[str],
    examples: dict[str, list[SpiderExample]],
    agent_factory: Callable[[], object],
    answer_fn: Callable[[str, str, object], AgentAnswer],
    score_fn: Callable[..., ScoreResult],
    em_fn: Callable[[str, str | None, str], ExactMatchResult],
    log_path: Path | None,
    lock: threading.Lock,
) -> list[dict]:
    if not db_ids:
        return []

    agent = agent_factory()
    records = []

    for db_id in db_ids:
        for example in examples[db_id]:
            answer = answer_fn(db_id, example.question, agent)
            result = score_fn(db_id, answer.sql, example.gold_sql, agent_notes=answer.notes)
            em_result = em_fn(db_id, answer.sql, example.gold_sql)

            record = {
                "db_id": db_id,
                "question": example.question,
                "predicted_sql": answer.sql,
                "gold_sql": example.gold_sql,
                "score": result.score,
                "status": result.status,
                "detail": result.detail,
                "turns": answer.turns,
                "hit_turn_limit": answer.hit_turn_limit,
                "notes": answer.notes,
                "em_score": em_result.score,
                "difficulty": em_result.hardness,
                "latency_seconds": answer.latency_seconds,
                "input_tokens": answer.input_tokens,
                "output_tokens": answer.output_tokens,
            }

            if log_path is not None:
                _append_json_line(log_path, record, lock)

            records.append(record)

    return records


def run_eval(
    examples: dict[str, list[SpiderExample]],
    prompt_version: str,
    num_workers: int = 2,
    agent_factory: Callable[[], object] | None = None,
    answer_fn: Callable[[str, str, object], AgentAnswer] | None = None,
    score_fn: Callable[..., ScoreResult] | None = None,
    em_fn: Callable[[str, str | None, str], ExactMatchResult] | None = None,
    log_path: Path | None = None,
) -> list[dict]:
    """Run the agent over every question in `examples` (grouped by db_id),
    scoring each answer for both Execution Accuracy (score_fn) and Exact
    Match/hardness (em_fn), split across `num_workers` threads (one agent
    instance per worker). Returns one record dict per question.

    If `log_path` is given, each record is also appended as one line of JSON
    to that file as soon as it's produced, so a run's progress survives a
    crash and can be inspected without re-running.
    """
    if agent_factory is None:
        agent_factory = lambda: agent_builder_factory.build_agent(prompt_version=prompt_version)
    if answer_fn is None:
        answer_fn = agent_workbench.answer_question
    if score_fn is None:
        score_fn = sql_result_scorer.score_query
    if em_fn is None:
        em_fn = exact_match.score_exact_match

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    db_ids = list(examples.keys())
    chunks = _split_into_chunks(db_ids, num_workers)
    lock = threading.Lock()

    all_records: list[dict] = []
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(_run_chunk, chunk, examples, agent_factory, answer_fn, score_fn, em_fn, log_path, lock)
            for chunk in chunks
        ]
        for future in futures:
            all_records.extend(future.result())

    return all_records
