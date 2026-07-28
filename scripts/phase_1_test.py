"""
Phase 1 accuracy check.

Draws a fixed random sample of 20 db_ids x 5 questions each (100 total) from
the validation split, runs the Phase 1 agent on every question, scores each
answer against gold SQL via sql_result_scorer, and writes
results/phase_1_result.json with a summary plus one record per question.

Split across 2 worker threads (10 db_ids x 5 questions = 50 each), each with
its own independent agent instance so there's no shared mutable state to
worry about between threads.
"""

from __future__ import annotations

import json
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import spider_agent_workbench.agent as agent_workbench
import spider_agent_workbench.loaders as loaders
import spider_agent_workbench.logging_config as logging_config
import spider_agent_workbench.paths as paths
from spider_agent_workbench.eval.sql_result_scorer import score_query

logger = logging.getLogger(__name__)

SAMPLE_SEED = 42
NUM_DBS = 2
QUESTIONS_PER_DB = 5
NUM_WORKERS = 1

RESULTS_PATH = paths.PROJECT_ROOT / "results" / "phase_1_result.json"


def select_sample(seed: int = SAMPLE_SEED) -> dict[str, list[loaders.SpiderExample]]:
    """Pick NUM_DBS db_ids (each with >= QUESTIONS_PER_DB validation
    questions available) and QUESTIONS_PER_DB questions per db_id,
    deterministically from `seed` so reruns are comparable across prompt
    versions."""
    examples = loaders.filter_available(list(loaders.iter_examples("validation")))
    grouped = loaders.group_by_db(examples)

    eligible = sorted(db_id for db_id, ex in grouped.items() if len(ex) >= QUESTIONS_PER_DB)
    if len(eligible) < NUM_DBS:
        raise ValueError(
            f"Only {len(eligible)} validation db_ids have >= {QUESTIONS_PER_DB} questions; need {NUM_DBS}."
        )

    rng = random.Random(seed)
    chosen_dbs = rng.sample(eligible, NUM_DBS)
    return {db_id: rng.sample(grouped[db_id], QUESTIONS_PER_DB) for db_id in chosen_dbs}


def chunk_for_workers(
    sample: dict[str, list[loaders.SpiderExample]], num_workers: int
) -> list[dict[str, list[loaders.SpiderExample]]]:
    """Split db_ids across workers in contiguous blocks (10 db_ids per
    worker for NUM_DBS=20, NUM_WORKERS=2)."""
    db_ids = list(sample.keys())
    chunk_size = len(db_ids) // num_workers
    chunks = []
    for i in range(num_workers):
        start = i * chunk_size
        end = start + chunk_size if i < num_workers - 1 else len(db_ids)
        chunks.append({db_id: sample[db_id] for db_id in db_ids[start:end]})
    return chunks


def run_worker(worker_id: int, db_examples: dict[str, list[loaders.SpiderExample]]) -> list[dict]:
    agent = agent_workbench.build_agent()
    total = sum(len(examples) for examples in db_examples.values())
    total_dbs = len(db_examples)
    done = 0
    records = []

    for db_idx, (db_id, examples) in enumerate(db_examples.items(), start=1):
        for example in examples:
            answer = agent_workbench.answer_question(db_id, example.question, agent)
            logger.info(
                "[worker %d] [db %d/%d] db=%s\nQuestion=%s\nAI_answer=%s\nCorrect_Answer=%s",
                worker_id, db_idx, total_dbs, db_id, example.question, answer.sql, example.gold_sql,
            )
            result = score_query(db_id, answer.sql, example.gold_sql)
            done += 1
            logger.info(
                "[worker %d] [db %d/%d] [%d/%d] db=%s status=%s score=%s",
                worker_id, db_idx, total_dbs, done, total, db_id, result.status, result.score,
            )
            logger.info("[worker %d] *=====================================*\n", worker_id)
            records.append(
                {
                    "db_id": db_id,
                    "question": example.question,
                    "predicted_sql": answer.sql,
                    "gold_sql": example.gold_sql,
                    "score": result.score,
                    "status": result.status,
                    "detail": result.detail,
                    "turns": answer.turns,
                    "hit_turn_limit": answer.hit_turn_limit,
                }
            )

    return records


def build_summary(records: list[dict]) -> dict:
    total = len(records)
    total_score = sum(r["score"] for r in records)

    by_status: dict[str, int] = {}
    by_db: dict[str, dict[str, int]] = {}
    for r in records:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        db_stats = by_db.setdefault(r["db_id"], {"score": 0, "total": 0})
        db_stats["score"] += r["score"]
        db_stats["total"] += 1

    return {
        "total_questions": total,
        "total_score": total_score,
        "accuracy": total_score / total if total else 0.0,
        "by_status": by_status,
        "by_db": by_db,
    }


def main() -> None:
    logging_config.setup_logging(phase_number=1)

    sample = select_sample()
    worker_chunks = chunk_for_workers(sample, NUM_WORKERS)

    all_records: list[dict] = []
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = [executor.submit(run_worker, i, chunk) for i, chunk in enumerate(worker_chunks)]
        for future in futures:
            all_records.extend(future.result())

    summary = build_summary(all_records)
    output = {
        "meta": {
            "sample_seed": SAMPLE_SEED,
            "num_db": NUM_DBS,
            "questions_per_db": QUESTIONS_PER_DB,
            "split": "validation",
            "prompt_version": agent_workbench.DEFAULT_PROMPT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": summary,
        "results": all_records,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    logger.info(
        "Wrote %s — accuracy: %.0f%% (%d/%d)",
        RESULTS_PATH, summary["accuracy"] * 100, summary["total_score"], summary["total_questions"],
    )


if __name__ == "__main__":
    main()
