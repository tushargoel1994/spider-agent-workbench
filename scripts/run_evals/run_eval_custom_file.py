"""
Runs the agent against the frozen hard/extra-hard question pool built by
select_hard_questions.py, and writes a report JSON (results/hard_question_report.json
by default, override with --output-file) -- per docs/hard_question_eval_plan.md.

Usage: uv run scripts/hard_question_eval/full_eval_test_hard_questions.py
       [--prompt-version prompt_v3] [--num-workers 4]
       [--input-file <path>] [--output-file <path>]

Requires the input pool file (hard_questions_pool.json next to this script,
by default) to already exist -- run select_hard_questions.py first if it
doesn't. This script never regenerates the pool itself, so every prompt
version is measured against the exact same question set. The input file must
follow the {"meta": {...}, "questions": [...]} shape select_hard_questions.py
produces.

The run log is written next to the other logs, named after the output file's
stem (e.g. --output-file results/foo.json -> logs/foo_<timestamp>.jsonl), so
multiple runs against different output files don't clobber each other's log.

Reuses eval.runner.run_eval, eval.metrics, and eval.sql_features exactly as
scripts/run_full_eval.py already does -- same summary shapes (by status, db,
difficulty, SQL feature, guardrail hit rate), plus a "failures" list (just
the non-matching records) as a convenience view for prompt debugging, on top
of the full per-question "results".
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import spider_agent_workbench.logging_config as logging_config
import spider_agent_workbench.paths as paths
from spider_agent_workbench.eval import metrics, runner
from spider_agent_workbench.eval.sql_features import tag_features
from spider_agent_workbench.loaders import SpiderExample

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_VERSION = "prompt_v3"
DEFAULT_NUM_WORKERS = 4

FEATURE_KEYS = ["has_join", "has_group_by", "has_subquery", "has_set_op"]

POOL_PATH = Path(__file__).parent / "hard_questions_pool.json"
REPORT_PATH = paths.PROJECT_ROOT / "results" / "hard_question_report.json"


def load_pool(pool_path: Path) -> tuple[dict[str, list[SpiderExample]], dict]:
    """Load the frozen pool JSON into the {db_id: [SpiderExample]} shape
    eval.runner.run_eval expects. Errors clearly if the pool hasn't been
    built yet, instead of silently generating a new one."""
    if not pool_path.exists():
        raise FileNotFoundError(
            f"{pool_path} not found. Run "
            "'uv run scripts/hard_question_eval/select_hard_questions.py' first."
        )

    data = json.loads(pool_path.read_text(encoding="utf-8"))

    examples: dict[str, list[SpiderExample]] = {}
    for question in data["questions"]:
        examples.setdefault(question["db_id"], []).append(
            SpiderExample(db_id=question["db_id"], question=question["question"], gold_sql=question["gold_sql"])
        )

    return examples, data["meta"]


def tag_record_features(records: list[dict]) -> list[dict]:
    """Add has_join/has_group_by/has_subquery/has_set_op to every record,
    tagged from the record's gold_sql -- a property of the question, not of
    whatever the agent happened to write."""
    for record in records:
        record.update(tag_features(record["gold_sql"]))
    return records


def build_em_summary(records: list[dict]) -> dict:
    """Reuse metrics.summarize() for the EM breakdown by remapping em_score
    into the "score" key it expects, instead of duplicating its counting
    logic for a second field name."""
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
    parser.add_argument("--prompt-version", type=str, default=DEFAULT_PROMPT_VERSION)
    parser.add_argument("--num-workers", type=int, default=DEFAULT_NUM_WORKERS)
    parser.add_argument("--input-file", type=Path, default=POOL_PATH)
    parser.add_argument("--output-file", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging_config.setup_logging(phase_number="hard_question_eval")

    examples, pool_meta = load_pool(args.input_file)
    total_questions = sum(len(v) for v in examples.values())
    logger.info(
        "Loaded %d hard/extra-hard questions across %d db_ids from %s",
        total_questions, len(examples), args.input_file,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    log_path = paths.LOGS_DIR / f"{args.output_file.stem}_{timestamp}.jsonl"

    records = runner.run_eval(
        examples,
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
    failures = [record for record in records if record["score"] == 0]

    output = {
        "meta": {
            "input_file": str(args.input_file),
            "pool_seed": pool_meta["seed"],
            "num_dbs": pool_meta["num_dbs"],
            "questions_per_db": pool_meta["questions_per_db"],
            "total_questions": total_questions,
            "pool_hardness_breakdown": pool_meta["hardness_breakdown"],
            "prompt_version": args.prompt_version,
            "num_workers": args.num_workers,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "log_path": str(log_path),
        },
        "ex_summary": ex_summary,
        "em_summary": em_summary,
        "feature_summary": feature_summary,
        "guardrail_summary": guardrail_summary,
        "operational_summary": operational_summary,
        "failures": failures,
        "results": records,
    }

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(output, indent=2), encoding="utf-8")

    logger.info(
        "Wrote %s -- EX accuracy: %.1f%% (%d/%d), EM accuracy: %.1f%% (%d/%d), "
        "failures: %d, avg turns: %.1f, avg latency: %.1fs",
        args.output_file,
        ex_summary["accuracy"] * 100,
        ex_summary["total_score"],
        ex_summary["total_questions"],
        em_summary["accuracy"] * 100,
        em_summary["total_score"],
        em_summary["total_questions"],
        len(failures),
        operational_summary["avg_turns"],
        operational_summary["avg_latency_seconds"],
    )


if __name__ == "__main__":
    main()
