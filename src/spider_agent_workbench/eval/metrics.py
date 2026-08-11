"""
Aggregate scoring: turns a list of per-question result dicts (the shape
eval/runner.py's batch runs produce, and the shape scripts/test_phase.py's
records already have today) into overall score/accuracy plus a by-field
breakdown for each field name in group_by.
"""

from __future__ import annotations

DEFAULT_GROUP_BY = ["status", "db_id"]


def summarize(records: list[dict], group_by: list[str] | None = None) -> dict:
    """Aggregate total/score/accuracy over `records`, plus a `by_<field>` count
    breakdown for every field name in `group_by`.

    Each record must have a "score" key (0 or 1) and, for every field listed in
    `group_by`, a matching key to group on (e.g. "status", "db_id"). Does not
    mutate `records`.
    """
    if group_by is None:
        group_by = DEFAULT_GROUP_BY

    total_questions = len(records)
    total_score = sum(record["score"] for record in records)
    accuracy = total_score / total_questions if total_questions else 0.0

    result: dict = {
        "total_questions": total_questions,
        "total_score": total_score,
        "accuracy": accuracy,
    }

    for field_name in group_by:
        groups: dict = {}
        for record in records:
            key = record[field_name]
            group = groups.setdefault(key, {"score": 0, "total": 0})
            group["score"] += record["score"]
            group["total"] += 1
        result[f"by_{field_name}"] = groups

    return result


def summarize_by_feature(records: list[dict], feature_keys: list[str]) -> dict:
    """Report score/total/accuracy within each feature's True subset of
    `records`, for every field name in `feature_keys`.

    Unlike summarize()'s group_by (where each record falls into exactly one
    group per field, e.g. one status), a record can have several features
    true at once (e.g. has_join and has_subquery both True) -- so each
    feature is counted independently rather than partitioning `records`.
    Each record must have a "score" key and, for every field listed in
    `feature_keys`, a matching boolean key (e.g. "has_join"). Does not
    mutate `records`.
    """
    result: dict = {}

    for feature in feature_keys:
        matching = [record for record in records if record.get(feature) is True]
        total = len(matching)
        score = sum(record["score"] for record in matching)
        accuracy = score / total if total else 0.0
        result[feature] = {"score": score, "total": total, "accuracy": accuracy}

    return result


def guardrail_hit_rate(records: list[dict]) -> dict:
    """Count how often each non-"match" status occurs in `records` -- not
    only guardrail rejections but any way a question didn't score a match
    (e.g. "no_sql", "value_mismatch") -- overall and broken down by
    difficulty. A record without a "difficulty" key is grouped under
    "unknown". Does not mutate `records`.
    """
    by_status: dict = {}
    by_difficulty: dict = {}

    for record in records:
        status = record["status"]
        if status == "match":
            continue

        by_status[status] = by_status.get(status, 0) + 1

        difficulty = record.get("difficulty", "unknown")
        difficulty_counts = by_difficulty.setdefault(difficulty, {})
        difficulty_counts[status] = difficulty_counts.get(status, 0) + 1

    return {"by_status": by_status, "by_difficulty": by_difficulty}
