"""
Builds and freezes a benchmark pool of hard/extra-hard Spider train-split
questions, per docs/hard_question_eval_plan.md.

Usage: uv run scripts/hard_question_eval/select_hard_questions.py
       [--num-dbs 30] [--questions-per-db 5] [--seed 42]
       [--min-hard-fraction 0.4] [--min-extra-fraction 0.4]
       [--output-file <path>]

Picks num_dbs distinct db_ids (each with at least questions_per_db combined
hard+extra questions) and questions_per_db questions from each -- a clean
num_dbs x questions_per_db grid, e.g. 30 x 5 = 150. Within that total, fills
towards >= min_hard_fraction hard and >= min_extra_fraction extra first
(whichever bucket is furthest behind its floor wins the next pick in a given
db); once both floors are met, remaining slots are filled from whatever's
left in that db, with no further ratio.

Hardness comes from eval.exact_match.score_exact_match(), called with
predicted_sql=None -- it computes the official Spider hardness bucket from
gold SQL alone as a side effect of EM scoring, so no agent run is needed
just to classify a question's difficulty.

This script is meant to be run rarely (once, or again only for a deliberately
new/bigger pool) -- it writes a frozen hard_questions_pool.json next to it,
so every future full_eval_test_hard_questions.py run compares prompt
versions against the exact same question set instead of a reshuffled sample.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from spider_agent_workbench import loaders
from spider_agent_workbench.eval.exact_match import score_exact_match
from spider_agent_workbench.loaders import SpiderExample

logger = logging.getLogger(__name__)

DEFAULT_NUM_DBS = 30
DEFAULT_QUESTIONS_PER_DB = 5
DEFAULT_SEED = 42
DEFAULT_MIN_HARD_FRACTION = 0.4
DEFAULT_MIN_EXTRA_FRACTION = 0.4

POOL_PATH = Path(__file__).parent / "hard_questions_pool.json"


def compute_hardness_pools() -> tuple[dict[str, list[SpiderExample]], dict[str, list[SpiderExample]]]:
    """Scan the full train split once, splitting into hard_by_db/extra_by_db
    (kept separate, not combined, so the fill loop in select_pool() can track
    each bucket's running total against its own floor)."""
    examples = loaders.filter_available(list(loaders.iter_examples("train")))
    hard_by_db: dict[str, list[SpiderExample]] = defaultdict(list)
    extra_by_db: dict[str, list[SpiderExample]] = defaultdict(list)

    for example in examples:
        try:
            result = score_exact_match(example.db_id, None, example.gold_sql)
        except Exception:
            logger.warning("Skipping unparseable gold SQL: db_id=%s question=%r", example.db_id, example.question)
            continue

        if result.hardness == "hard":
            hard_by_db[example.db_id].append(example)
        elif result.hardness == "extra":
            extra_by_db[example.db_id].append(example)

    return hard_by_db, extra_by_db


def select_pool(
    num_dbs: int = DEFAULT_NUM_DBS,
    questions_per_db: int = DEFAULT_QUESTIONS_PER_DB,
    seed: int = DEFAULT_SEED,
    min_hard_fraction: float = DEFAULT_MIN_HARD_FRACTION,
    min_extra_fraction: float = DEFAULT_MIN_EXTRA_FRACTION,
) -> tuple[dict[str, list[tuple[SpiderExample, str]]], dict[str, int]]:
    """Select num_dbs db_ids x questions_per_db hard/extra questions each,
    meeting the hard/extra floors. Returns (selected, hardness_breakdown),
    where selected[db_id] is a list of (example, hardness) pairs -- hardness
    is already known from which bucket a pick came from, no need to
    re-classify it later."""
    hard_by_db, extra_by_db = compute_hardness_pools()
    all_dbs = set(hard_by_db) | set(extra_by_db)
    eligible = sorted(
        db_id for db_id in all_dbs
        if len(hard_by_db.get(db_id, [])) + len(extra_by_db.get(db_id, [])) >= questions_per_db
    )
    if len(eligible) < num_dbs:
        raise ValueError(
            f"Only {len(eligible)} db_ids have >= {questions_per_db} combined hard/extra "
            f"questions; need {num_dbs}."
        )

    total_target = num_dbs * questions_per_db
    hard_target = math.ceil(total_target * min_hard_fraction)
    extra_target = math.ceil(total_target * min_extra_fraction)

    rng = random.Random(seed)
    chosen_dbs = rng.sample(eligible, num_dbs)
    rng.shuffle(chosen_dbs)  # fill order -- which dbs get "first pick" isn't alphabetical

    selected: dict[str, list[tuple[SpiderExample, str]]] = {}
    hard_taken = 0
    extra_taken = 0

    for db_id in chosen_dbs:
        db_hard = list(hard_by_db.get(db_id, []))
        db_extra = list(extra_by_db.get(db_id, []))
        rng.shuffle(db_hard)
        rng.shuffle(db_extra)

        picks: list[tuple[SpiderExample, str]] = []
        for _ in range(questions_per_db):
            need_hard = hard_taken < hard_target
            need_extra = extra_taken < extra_target

            if need_hard and need_extra:
                # Further-behind bucket wins; ties go to hard.
                prefer = "hard" if (hard_target - hard_taken) >= (extra_target - extra_taken) else "extra"
            elif need_hard:
                prefer = "hard"
            elif need_extra:
                prefer = "extra"
            else:
                # Both floors met -- take from whichever bucket this db has
                # more of, no further quota ("split the rest as they arrive").
                prefer = "hard" if len(db_hard) >= len(db_extra) else "extra"

            if prefer == "hard" and db_hard:
                picks.append((db_hard.pop(), "hard"))
                hard_taken += 1
            elif prefer == "extra" and db_extra:
                picks.append((db_extra.pop(), "extra"))
                extra_taken += 1
            elif db_hard:
                picks.append((db_hard.pop(), "hard"))
                hard_taken += 1
            elif db_extra:
                picks.append((db_extra.pop(), "extra"))
                extra_taken += 1

        selected[db_id] = picks

    if hard_taken < hard_target or extra_taken < extra_target:
        raise ValueError(
            f"Selected pool doesn't meet the hardness floor: hard={hard_taken} "
            f"(need >={hard_target}), extra={extra_taken} (need >={extra_target}). "
            "Try a different --seed."
        )

    return selected, {"hard": hard_taken, "extra": extra_taken}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-dbs", type=int, default=DEFAULT_NUM_DBS)
    parser.add_argument("--questions-per-db", type=int, default=DEFAULT_QUESTIONS_PER_DB)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--min-hard-fraction", type=float, default=DEFAULT_MIN_HARD_FRACTION)
    parser.add_argument("--min-extra-fraction", type=float, default=DEFAULT_MIN_EXTRA_FRACTION)
    parser.add_argument("--output-file", type=Path, default=POOL_PATH)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = parse_args()

    selected, hardness_breakdown = select_pool(
        num_dbs=args.num_dbs,
        questions_per_db=args.questions_per_db,
        seed=args.seed,
        min_hard_fraction=args.min_hard_fraction,
        min_extra_fraction=args.min_extra_fraction,
    )

    questions = []
    for db_id, examples in selected.items():
        for example, hardness in examples:
            questions.append({
                "db_id": db_id,
                "question": example.question,
                "gold_sql": example.gold_sql,
                "hardness": hardness,
            })

    total_questions = len(questions)
    output = {
        "meta": {
            "seed": args.seed,
            "num_dbs": args.num_dbs,
            "questions_per_db": args.questions_per_db,
            "total_questions": total_questions,
            "min_hard_fraction": args.min_hard_fraction,
            "min_extra_fraction": args.min_extra_fraction,
            "hardness_breakdown": hardness_breakdown,
            "split": "train",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "questions": questions,
    }

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(output, indent=2), encoding="utf-8")
    logger.info(
        "Wrote %s -- %d questions across %d db_ids (hard=%d, extra=%d)",
        args.output_file, total_questions, len(selected), hardness_breakdown["hard"], hardness_breakdown["extra"],
    )


if __name__ == "__main__":
    main()
