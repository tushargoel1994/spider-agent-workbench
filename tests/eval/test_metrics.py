"""Tests for eval/metrics.py — summarize(), which turns a list of per-question
result dicts (the shape eval/runner.py will produce) into overall score/accuracy
plus a by-field breakdown for each field name passed in group_by; and
summarize_by_feature(), which reports accuracy within each SQL-feature's True
subset (a record can have several features true at once, unlike group_by's
mutually-exclusive fields).
"""

from spider_agent_workbench.eval.metrics import guardrail_hit_rate, summarize, summarize_by_feature


# summarize — overall totals


def test_summarize_overall_totals():
    records = [
        {"db_id": "school", "status": "match", "score": 1},
        {"db_id": "school", "status": "value_mismatch", "score": 0},
        {"db_id": "farm", "status": "match", "score": 1},
    ]

    result = summarize(records, group_by=["status", "db_id"])

    assert result["total_questions"] == 3
    assert result["total_score"] == 2
    assert result["accuracy"] == 2 / 3


def test_summarize_empty_records_does_not_crash():
    result = summarize([], group_by=["status", "db_id"])

    assert result["total_questions"] == 0
    assert result["total_score"] == 0
    assert result["accuracy"] == 0.0
    assert result["by_status"] == {}
    assert result["by_db_id"] == {}


# summarize — by-field breakdowns


def test_summarize_breaks_down_by_status():
    records = [
        {"db_id": "school", "status": "match", "score": 1},
        {"db_id": "school", "status": "value_mismatch", "score": 0},
        {"db_id": "farm", "status": "match", "score": 1},
    ]

    result = summarize(records, group_by=["status", "db_id"])

    assert result["by_status"]["match"] == {"score": 2, "total": 2}
    assert result["by_status"]["value_mismatch"] == {"score": 0, "total": 1}


def test_summarize_breaks_down_by_db_id():
    records = [
        {"db_id": "school", "status": "match", "score": 1},
        {"db_id": "school", "status": "value_mismatch", "score": 0},
        {"db_id": "farm", "status": "match", "score": 1},
    ]

    result = summarize(records, group_by=["status", "db_id"])

    assert result["by_db_id"]["school"] == {"score": 1, "total": 2}
    assert result["by_db_id"]["farm"] == {"score": 1, "total": 1}


def test_summarize_only_reports_requested_group_by_fields():
    records = [{"db_id": "school", "status": "match", "score": 1}]

    result = summarize(records, group_by=["status"])

    assert "by_status" in result
    assert "by_db_id" not in result


def test_summarize_defaults_to_status_and_db_id_when_group_by_omitted():
    records = [{"db_id": "school", "status": "match", "score": 1}]

    result = summarize(records)

    assert "by_status" in result
    assert "by_db_id" in result


# summarize — must not mutate its input


def test_summarize_does_not_mutate_input_records():
    records = [{"db_id": "school", "status": "match", "score": 1}]
    records_copy = [dict(r) for r in records]

    summarize(records, group_by=["status", "db_id"])

    assert records == records_copy


# summarize_by_feature — accuracy within each feature's True subset


def test_summarize_by_feature_counts_only_records_where_feature_is_true():
    records = [
        {"score": 1, "has_join": True, "has_group_by": False},
        {"score": 0, "has_join": True, "has_group_by": False},
        {"score": 1, "has_join": False, "has_group_by": True},
        {"score": 1, "has_join": False, "has_group_by": False},
    ]

    result = summarize_by_feature(records, feature_keys=["has_join", "has_group_by"])

    assert result["has_join"] == {"score": 1, "total": 2, "accuracy": 0.5}
    assert result["has_group_by"] == {"score": 1, "total": 1, "accuracy": 1.0}


def test_summarize_by_feature_counts_a_record_under_every_true_feature():
    # A single query can need a JOIN *and* a subquery at once -- unlike
    # summarize()'s group_by, this must not be a mutually-exclusive split.
    records = [{"score": 1, "has_join": True, "has_subquery": True}]

    result = summarize_by_feature(records, feature_keys=["has_join", "has_subquery"])

    assert result["has_join"]["total"] == 1
    assert result["has_subquery"]["total"] == 1


def test_summarize_by_feature_reports_zero_accuracy_when_no_records_have_the_feature():
    records = [{"score": 1, "has_join": False}]

    result = summarize_by_feature(records, feature_keys=["has_join"])

    assert result["has_join"] == {"score": 0, "total": 0, "accuracy": 0.0}


def test_summarize_by_feature_does_not_mutate_input_records():
    records = [{"score": 1, "has_join": True}]
    records_copy = [dict(r) for r in records]

    summarize_by_feature(records, feature_keys=["has_join"])

    assert records == records_copy


# guardrail_hit_rate — counts every non-"match" status, overall and per difficulty


def test_guardrail_hit_rate_is_empty_when_everything_matched():
    records = [
        {"status": "match", "difficulty": "easy"},
        {"status": "match", "difficulty": "hard"},
    ]

    result = guardrail_hit_rate(records)

    assert result["by_status"] == {}
    assert result["by_difficulty"] == {}


def test_guardrail_hit_rate_counts_non_match_statuses():
    records = [
        {"status": "match", "difficulty": "easy"},
        {"status": "guardrail_rejected", "difficulty": "hard"},
        {"status": "guardrail_rejected", "difficulty": "hard"},
        {"status": "no_sql", "difficulty": "extra"},
    ]

    result = guardrail_hit_rate(records)

    assert result["by_status"] == {"guardrail_rejected": 2, "no_sql": 1}


def test_guardrail_hit_rate_breaks_down_by_difficulty():
    records = [
        {"status": "guardrail_rejected", "difficulty": "hard"},
        {"status": "guardrail_rejected", "difficulty": "hard"},
        {"status": "no_sql", "difficulty": "extra"},
    ]

    result = guardrail_hit_rate(records)

    assert result["by_difficulty"]["hard"] == {"guardrail_rejected": 2}
    assert result["by_difficulty"]["extra"] == {"no_sql": 1}


def test_guardrail_hit_rate_groups_missing_difficulty_as_unknown():
    records = [{"status": "no_sql"}]

    result = guardrail_hit_rate(records)

    assert result["by_difficulty"]["unknown"] == {"no_sql": 1}


def test_guardrail_hit_rate_does_not_mutate_input_records():
    records = [{"status": "no_sql", "difficulty": "easy"}]
    records_copy = [dict(r) for r in records]

    guardrail_hit_rate(records)

    assert records == records_copy
