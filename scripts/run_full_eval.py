"""
Phase 4 full evaluation run.

Usage: uv run scripts/run_full_eval.py [--num-dbs N] [--questions-per-db N]
       [--num-workers N] [--seed N] [--prompt-version prompt_v3]

Runs the agent over a larger, deterministic sample of the validation split
than the fixed 10-question sample scripts/test_phase.py uses (unaffected by
this script -- it stays the tool for comparing prompt/guardrail changes
across phases). Scores every answer for both Execution Accuracy (EX) and
Exact Match (EM), tags each question's gold SQL with which SQL features it
needs, and writes the full breakdown (by status, db, difficulty, SQL
feature, and guardrail hit rate) plus every per-question record to
results/phase_4_result.json.

Also writes one JSON line per question to logs/phase_4_run_<timestamp>.jsonl
as the run progresses (eval.runner.run_eval's structured logging), so
progress survives a crash and can be inspected without re-running.

Defaults to 40 db_ids x 5 questions = 200 questions, matching this project's
own guidance (docs/phase_4_plan.md) that at least 200 questions are needed
before trusting an accuracy number. Do a small trial first, e.g.:
    uv run scripts/run_full_eval.py --num-dbs 5 --questions-per-db 4
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from datetime import datetime, timezone

import spider_agent_workbench.loaders as loaders
import spider_agent_workbench.logging_config as logging_config
import spider_agent_workbench.paths as paths
from spider_agent_workbench.eval import metrics, runner
from spider_agent_workbench.eval.sql_features import tag_features

logger = logging.getLogger(__name__)

DEFAULT_SEED = 42
DEFAULT_NUM_DBS = 20
DEFAULT_QUESTIONS_PER_DB = 5
DEFAULT_NUM_WORKERS = 4
DEFAULT_PROMPT_VERSION = "prompt_v3"

FEATURE_KEYS = ["has_join", "has_group_by", "has_subquery", "has_set_op"]


def select_sample(
    num_dbs: int, questions_per_db: int, seed: int
) -> dict[str, list[loaders.SpiderExample]]:
    """Pick num_dbs db_ids and up to questions_per_db questions per db_id
    (all questions if a db_id has fewer), deterministically from `seed` so
    reruns are comparable across prompt/guardrail changes.
    Evals will always run on train and never on validation, validation is only for final testing
    """
    examples = loaders.filter_available(list(loaders.iter_examples("train")))
    grouped = loaders.group_by_db(examples)

    available = sorted(grouped.keys())
    if num_dbs > len(available):
        raise ValueError(f"Validation split only has {len(available)} db_ids; requested num_dbs={num_dbs}.")

    rng = random.Random(seed)
    chosen_dbs = rng.sample(available, num_dbs)
    return {
        db_id: rng.sample(grouped[db_id], min(questions_per_db, len(grouped[db_id])))
        for db_id in chosen_dbs
    }


def tag_record_features(records: list[dict]) -> list[dict]:
    """Add has_join/has_group_by/has_subquery/has_set_op to every record,
    tagged from the record's gold_sql -- a property of the question, not of
    whatever the agent happened to write."""
    for record in records:
        record.update(tag_features(record["gold_sql"]))
    return records


def build_em_summary(records: list[dict]) -> dict:
    """Reuse metrics.summarize() (already tested) for the EM breakdown by
    remapping em_score into the "score" key it expects, instead of
    duplicating summarize()'s counting logic for a second field name."""
    em_records = [{**record, "score": record["em_score"]} for record in records]
    return metrics.summarize(em_records, group_by=["difficulty", "db_id"])


def build_operational_summary(records: list[dict]) -> dict:
    """Average/total turns, latency, and token usage across the run -- the
    "is this practical to run" numbers, alongside correctness."""
    total = len(records)
    if total == 0:
        return {
            "avg_turns": 0.0,
            "avg_latency_seconds": 0.0,
            "avg_input_tokens": 0.0,
            "avg_output_tokens": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

    total_turns = sum(r["turns"] for r in records)
    total_latency_seconds = sum(r["latency_seconds"] for r in records)
    total_input_tokens = sum(r["input_tokens"] for r in records)
    total_output_tokens = sum(r["output_tokens"] for r in records)

    return {
        "avg_turns": total_turns / total,
        "avg_latency_seconds": total_latency_seconds / total,
        "avg_input_tokens": total_input_tokens / total,
        "avg_output_tokens": total_output_tokens / total,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-dbs", type=int, default=DEFAULT_NUM_DBS)
    parser.add_argument("--questions-per-db", type=int, default=DEFAULT_QUESTIONS_PER_DB)
    parser.add_argument("--num-workers", type=int, default=DEFAULT_NUM_WORKERS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--prompt-version", type=str, default=DEFAULT_PROMPT_VERSION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging_config.setup_logging(phase_number="4_full_eval")

    sample = select_sample(args.num_dbs, args.questions_per_db, args.seed)
    total_questions = sum(len(examples) for examples in sample.values())
    logger.info("Sampled %d questions across %d db_ids (seed=%d)", total_questions, len(sample), args.seed)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    log_path = paths.LOGS_DIR / f"phase_4_run_{timestamp}.jsonl"

    records = runner.run_eval(
        sample,
        prompt_version=args.prompt_version,
        num_workers=args.num_workers,
        log_path=log_path,
    )
    records = tag_record_features(records)

    ex_summary = metrics.summarize(records, group_by=["status", "db_id", "difficulty"])
    em_summary = build_em_summary(records)
    feature_summary = metrics.summarize_by_feature(records, feature_keys=FEATURE_KEYS)
    guardrail_summary = metrics.guardrail_hit_rate(records)
    operational_summary = build_operational_summary(records)

    output = {
        "meta": {
            "sample_seed": args.seed,
            "num_db": args.num_dbs,
            "questions_per_db": args.questions_per_db,
            "total_questions": total_questions,
            "split": "validation",
            "prompt_version": args.prompt_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "log_path": str(log_path),
        },
        "ex_summary": ex_summary,
        "em_summary": em_summary,
        "feature_summary": feature_summary,
        "guardrail_summary": guardrail_summary,
        "operational_summary": operational_summary,
        "results": records,
    }

    results_path = paths.PROJECT_ROOT / "results" / "phase_4_result.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    logger.info(
        "Wrote %s -- EX accuracy: %.1f%% (%d/%d), EM accuracy: %.1f%% (%d/%d), "
        "avg turns: %.1f, avg latency: %.1fs",
        results_path,
        ex_summary["accuracy"] * 100,
        ex_summary["total_score"],
        ex_summary["total_questions"],
        em_summary["accuracy"] * 100,
        em_summary["total_score"],
        em_summary["total_questions"],
        operational_summary["avg_turns"],
        operational_summary["avg_latency_seconds"],
    )


if __name__ == "__main__":
    main()
