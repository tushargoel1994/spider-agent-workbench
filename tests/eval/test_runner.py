"""Tests for eval/runner.py — run_eval(), which runs the agent over a batch of
questions (grouped by db_id) and collects one result record per question.

All collaborators (building an agent, answering a question, scoring EX,
scoring EM/hardness) are injected via agent_factory/answer_fn/score_fn/em_fn,
so these tests make no real LLM/network calls and don't touch a real sqlite
database — the one test that exercises the *default* collaborators
(test_run_eval_uses_real_collaborators_by_default) still fakes them out via
monkeypatch rather than calling the real thing.
"""

import json

from spider_agent_workbench.agent import AgentAnswer
from spider_agent_workbench.eval import runner as runner_module
from spider_agent_workbench.eval.exact_match import ExactMatchResult
from spider_agent_workbench.eval.runner import run_eval
from spider_agent_workbench.eval.sql_result_scorer import ScoreResult
from spider_agent_workbench.loaders import SpiderExample


def _fake_answer_fn(db_id, question, agent):
    return AgentAnswer(
        db_id=db_id,
        question=question,
        sql=f"SELECT 1 -- {question}",
        turns=1,
        latency_seconds=2.5,
        input_tokens=100,
        output_tokens=20,
    )


def _fake_score_fn(db_id, predicted_sql, gold_sql, agent_notes=None):
    return ScoreResult(score=1, status="match")


def _fake_em_fn(db_id, predicted_sql, gold_sql):
    return ExactMatchResult(score=1, hardness="easy")


def _counting_agent_factory(calls):
    def factory():
        calls.append(1)
        return "fake-agent"

    return factory


# run_eval — record count and shape


def test_run_eval_returns_one_record_per_question():
    examples = {
        "school": [
            SpiderExample(db_id="school", question="How many students?", gold_sql="SELECT COUNT(*) FROM students"),
            SpiderExample(db_id="school", question="How many courses?", gold_sql="SELECT COUNT(*) FROM courses"),
        ],
        "farm": [
            SpiderExample(db_id="farm", question="How many farms?", gold_sql="SELECT COUNT(*) FROM farms"),
        ],
    }

    records = run_eval(
        examples,
        prompt_version="prompt_v3",
        num_workers=2,
        agent_factory=lambda: "fake-agent",
        answer_fn=_fake_answer_fn,
        score_fn=_fake_score_fn,
        em_fn=_fake_em_fn,
    )

    assert len(records) == 3


def test_run_eval_record_has_expected_fields():
    examples = {
        "school": [
            SpiderExample(db_id="school", question="How many students?", gold_sql="SELECT COUNT(*) FROM students"),
        ],
    }

    records = run_eval(
        examples,
        prompt_version="prompt_v3",
        num_workers=1,
        agent_factory=lambda: "fake-agent",
        answer_fn=_fake_answer_fn,
        score_fn=_fake_score_fn,
        em_fn=_fake_em_fn,
    )

    record = records[0]
    assert record["db_id"] == "school"
    assert record["question"] == "How many students?"
    assert record["gold_sql"] == "SELECT COUNT(*) FROM students"
    assert record["predicted_sql"] == "SELECT 1 -- How many students?"
    assert record["score"] == 1
    assert record["status"] == "match"
    assert record["detail"] is None
    assert record["turns"] == 1
    assert record["hit_turn_limit"] is False
    assert record["notes"] is None
    assert record["em_score"] == 1
    assert record["difficulty"] == "easy"
    assert record["latency_seconds"] == 2.5
    assert record["input_tokens"] == 100
    assert record["output_tokens"] == 20


def test_run_eval_covers_every_question_exactly_once_across_multiple_workers():
    examples = {
        "db_a": [SpiderExample(db_id="db_a", question=f"q{i}", gold_sql="SELECT 1") for i in range(3)],
        "db_b": [SpiderExample(db_id="db_b", question=f"q{i}", gold_sql="SELECT 1") for i in range(3)],
        "db_c": [SpiderExample(db_id="db_c", question=f"q{i}", gold_sql="SELECT 1") for i in range(3)],
    }

    records = run_eval(
        examples,
        prompt_version="prompt_v3",
        num_workers=2,
        agent_factory=lambda: "fake-agent",
        answer_fn=_fake_answer_fn,
        score_fn=_fake_score_fn,
        em_fn=_fake_em_fn,
    )

    seen = {(r["db_id"], r["question"]) for r in records}
    expected = {(db_id, ex.question) for db_id, exs in examples.items() for ex in exs}
    assert seen == expected
    assert len(records) == len(expected)


# run_eval — one agent instance is built per worker, not per question


def test_run_eval_builds_one_agent_per_worker_with_work_not_per_question():
    calls = []
    examples = {
        "school": [SpiderExample(db_id="school", question=f"q{i}", gold_sql="SELECT 1") for i in range(5)],
    }

    run_eval(
        examples,
        prompt_version="prompt_v3",
        num_workers=2,
        agent_factory=_counting_agent_factory(calls),
        answer_fn=_fake_answer_fn,
        score_fn=_fake_score_fn,
        em_fn=_fake_em_fn,
    )

    # Only 1 db_id, so only 1 of the 2 workers ends up with any db_ids to
    # process — agent_factory should be called once per worker that actually
    # has work, not once per question, and not for the idle worker.
    assert len(calls) == 1


# run_eval — structured JSONL logging


def test_run_eval_writes_one_jsonl_line_per_record(tmp_path):
    log_path = tmp_path / "logs" / "run.jsonl"
    examples = {
        "school": [
            SpiderExample(db_id="school", question="q1", gold_sql="SELECT 1"),
            SpiderExample(db_id="school", question="q2", gold_sql="SELECT 1"),
        ],
    }

    records = run_eval(
        examples,
        prompt_version="prompt_v3",
        num_workers=1,
        agent_factory=lambda: "fake-agent",
        answer_fn=_fake_answer_fn,
        score_fn=_fake_score_fn,
        em_fn=_fake_em_fn,
        log_path=log_path,
    )

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(records) == 2

    logged_questions = {json.loads(line)["question"] for line in lines}
    assert logged_questions == {"q1", "q2"}


def test_run_eval_does_not_create_a_log_file_when_log_path_is_none(tmp_path):
    examples = {"school": [SpiderExample(db_id="school", question="q1", gold_sql="SELECT 1")]}

    run_eval(
        examples,
        prompt_version="prompt_v3",
        num_workers=1,
        agent_factory=lambda: "fake-agent",
        answer_fn=_fake_answer_fn,
        score_fn=_fake_score_fn,
        em_fn=_fake_em_fn,
    )

    assert list(tmp_path.iterdir()) == []


# run_eval — falls back to the real agent/scoring collaborators when the
# caller doesn't inject fakes (still faked here via monkeypatch, so this test
# makes no real LLM/network calls either)


def test_run_eval_uses_real_collaborators_by_default(monkeypatch):
    build_agent_calls = []
    answer_calls = []
    score_calls = []
    em_calls = []

    def fake_build_agent(prompt_version):
        build_agent_calls.append(prompt_version)
        return "fake-agent"

    def fake_answer_question(db_id, question, agent):
        answer_calls.append((db_id, question, agent))
        return AgentAnswer(db_id=db_id, question=question, sql="SELECT 1", turns=1)

    def fake_score_query(db_id, predicted_sql, gold_sql, agent_notes=None):
        score_calls.append((db_id, predicted_sql, gold_sql))
        return ScoreResult(score=1, status="match")

    def fake_score_exact_match(db_id, predicted_sql, gold_sql):
        em_calls.append((db_id, predicted_sql, gold_sql))
        return ExactMatchResult(score=1, hardness="easy")

    monkeypatch.setattr(runner_module.agent_builder_factory, "build_agent", fake_build_agent)
    monkeypatch.setattr(runner_module.agent_workbench, "answer_question", fake_answer_question)
    monkeypatch.setattr(runner_module.sql_result_scorer, "score_query", fake_score_query)
    monkeypatch.setattr(runner_module.exact_match, "score_exact_match", fake_score_exact_match)

    examples = {"school": [SpiderExample(db_id="school", question="q1", gold_sql="SELECT 1")]}

    records = run_eval(examples, prompt_version="prompt_v3", num_workers=1)

    assert build_agent_calls == ["prompt_v3"]
    assert len(answer_calls) == 1
    assert len(score_calls) == 1
    assert len(em_calls) == 1
    assert records[0]["score"] == 1
    assert records[0]["em_score"] == 1
    assert records[0]["difficulty"] == "easy"
