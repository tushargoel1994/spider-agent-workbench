"""
Phase accuracy check.

Usage: uv run scripts/test_phase.py --phase <phase_number>

Draws a fixed random sample of NUM_DBS db_ids x QUESTIONS_PER_DB questions
each from the validation split, runs the agent (using prompts/prompt_v<phase>.md)
on every question, scores each answer against gold SQL via sql_result_scorer,
and writes results/phase_<phase>_result.json with a summary plus one record
per question. Logs go to logs/phase_<phase>_<timestamp>.log.

Split across NUM_WORKERS worker threads, each with its own independent agent
instance so there's no shared mutable state to worry about between threads.
"""

from __future__ import annotations

import argparse
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
NUM_DBS = 10
QUESTIONS_PER_DB = 5
NUM_WORKERS = 2

# Only prompt_v1.md exists today, so phase 1 is the only value that currently
# resolves to a real prompt file. Later phases (prompt_v2.md, ...) plug in
# once those prompt versions are added, with no further script changes.
PROMPT_VERSION_TEMPLATE = "prompt_v{phase}"
RESULTS_PATH_TEMPLATE = "phase_{phase}_result.json"


def select_sample(seed: int = SAMPLE_SEED) -> dict[str, list[loaders.SpiderExample]]:
    """Pick NUM_DBS db_ids and up to QUESTIONS_PER_DB questions per db_id
    (all questions if a db_id has fewer), deterministically from `seed` so
    reruns are comparable across prompt versions."""
    examples = loaders.filter_available(list(loaders.iter_examples("validation")))
    grouped = loaders.group_by_db(examples)

    available = sorted(grouped.keys())
    if NUM_DBS > len(available):
        raise ValueError(
            f"Validation split only has {len(available)} db_ids; requested NUM_DBS={NUM_DBS}."
        )

    rng = random.Random(seed)
    chosen_dbs = rng.sample(available, NUM_DBS)
    return {
        db_id: rng.sample(grouped[db_id], min(QUESTIONS_PER_DB, len(grouped[db_id])))
        for db_id in chosen_dbs
    }


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


def run_worker(
    worker_id: int, db_examples: dict[str, list[loaders.SpiderExample]], prompt_version: str
) -> list[dict]:
    agent = agent_workbench.build_agent(prompt_version=prompt_version)
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
            result = score_query(db_id, answer.sql, example.gold_sql, agent_notes=answer.notes)
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
                    "notes": answer.notes,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        type=int,
        required=True,
        help="Phase number, e.g. 1 -> prompts/prompt_v1.md, logs/phase_1_<ts>.log, "
        "results/phase_1_result.json. Only 1 is testable today (only prompt_v1.md exists).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    phase = args.phase
    prompt_version = PROMPT_VERSION_TEMPLATE.format(phase=phase)
    results_path = paths.PROJECT_ROOT / "results" / RESULTS_PATH_TEMPLATE.format(phase=phase)

    logging_config.setup_logging(phase_number=phase)

    sample = select_sample()
    worker_chunks = chunk_for_workers(sample, NUM_WORKERS)

    all_records: list[dict] = []
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = [
            executor.submit(run_worker, i, chunk, prompt_version)
            for i, chunk in enumerate(worker_chunks)
        ]
        for future in futures:
            all_records.extend(future.result())

    summary = build_summary(all_records)
    output = {
        "meta": {
            "sample_seed": SAMPLE_SEED,
            "num_db": NUM_DBS,
            "questions_per_db": QUESTIONS_PER_DB,
            "split": "validation",
            "prompt_version": prompt_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": summary,
        "results": all_records,
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    logger.info(
        "Wrote %s — accuracy: %.0f%% (%d/%d)",
        results_path, summary["accuracy"] * 100, summary["total_score"], summary["total_questions"],
    )


if __name__ == "__main__":
    main()
