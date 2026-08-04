"""Tests for agent.py — load_system_prompt, _extract_final_sql, answer_question, build_agent.

The langchain/langgraph agent graph itself is never invoked for real (no network
calls, no API key required): `agent` is passed into answer_question as a mock
with a canned `.invoke()` return value, and build_agent's collaborators
(ChatAnthropic, create_agent) are monkeypatched.
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from spider_agent_workbench import agent as agent_module
from spider_agent_workbench.agent import (
    AgentAnswer,
    DEFAULT_PROMPT_VERSION,
    TOOLS,
    _extract_final_sql,
    answer_question,
    build_agent,
    load_system_prompt,
)
from spider_agent_workbench.constants import DEFAULT_MAX_TURNS


# load_system_prompt
#   default version loads real prompt_v2.md content
#   leading "<!-- ... -->" changelog lines are stripped
#   unknown version raises


def test_load_system_prompt_returns_non_empty_text_for_default_version():
    prompt = load_system_prompt()
    assert prompt.strip() != ""
    assert not prompt.startswith("<!--")


def test_load_system_prompt_strips_leading_changelog_comment(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "PROMPTS_DIR", tmp_path)
    (tmp_path / "prompt_vtest.md").write_text(
        "<!-- vtest: scratch prompt for this test -->\nYou are a helpful assistant.",
        encoding="utf-8",
    )

    prompt = load_system_prompt("prompt_vtest")

    assert prompt == "You are a helpful assistant."


def test_load_system_prompt_raises_for_unknown_version(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "PROMPTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_system_prompt("prompt_does_not_exist")


# _extract_final_sql
#   finds the submit_final_sql call's query arg among mixed tool calls
#   returns None when submit_final_sql was never called
#   when called more than once, returns the most recent (last) one


def test_extract_final_sql_finds_submit_final_sql_query():
    messages = [
        HumanMessage(content="how many students?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "list_tables", "args": {"db_id": "school"}, "id": "1"}],
        ),
        ToolMessage(content="students,courses", tool_call_id="1"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_final_sql",
                    "args": {"db_id": "school", "query": "SELECT COUNT(*) FROM students"},
                    "id": "2",
                }
            ],
        ),
    ]

    assert _extract_final_sql(messages) == "SELECT COUNT(*) FROM students"


def test_extract_final_sql_returns_none_when_never_submitted():
    messages = [
        HumanMessage(content="how many students?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "run_query", "args": {"db_id": "school", "query": "SELECT 1"}, "id": "1"}],
        ),
        ToolMessage(content="1", tool_call_id="1"),
    ]

    assert _extract_final_sql(messages) is None


def test_extract_final_sql_returns_none_for_empty_messages():
    assert _extract_final_sql([]) is None


def test_extract_final_sql_returns_most_recent_submission():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "submit_final_sql", "args": {"query": "SELECT 1"}, "id": "1"}
            ],
        ),
        ToolMessage(content="Final SQL recorded: SELECT 1", tool_call_id="1"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "submit_final_sql", "args": {"query": "SELECT 2"}, "id": "2"}
            ],
        ),
    ]

    assert _extract_final_sql(messages) == "SELECT 2"


def test_extract_final_sql_ignores_ai_messages_without_tool_calls():
    messages = [AIMessage(content="thinking out loud, no tool call yet")]
    assert _extract_final_sql(messages) is None


# answer_question
#   input guardrail failure short-circuits before the agent is ever invoked
#   a GraphRecursionError from the agent graph is reported as hit_turn_limit
#   on success, extracts the submitted SQL and counts AIMessage turns
#   an output-guardrail failure is surfaced via `notes` but the SQL is still returned


def _ai_turn(tool_name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": call_id}])


def test_answer_question_short_circuits_on_input_guardrail_failure(db_dir, db_id):
    mock_agent = MagicMock()
    question = "x" * 1000  # over QUESTION_MAX_LENGTH

    result = answer_question(db_id, question, agent=mock_agent, db_dir=db_dir)

    mock_agent.invoke.assert_not_called()
    assert result.sql is None
    assert result.turns == 0
    assert result.notes is not None
    assert result.hit_turn_limit is False


def test_answer_question_rejects_missing_database(db_dir):
    mock_agent = MagicMock()

    result = answer_question("ghost_db", "How many students?", agent=mock_agent, db_dir=db_dir)

    mock_agent.invoke.assert_not_called()
    assert result.sql is None
    assert result.notes == "Database not present"
    assert result.hit_turn_limit is False


def test_answer_question_reports_hit_turn_limit_on_recursion_error(db_dir, db_id):
    mock_agent = MagicMock()
    mock_agent.invoke.side_effect = GraphRecursionError("recursion limit reached")

    result = answer_question(
        db_id, "How many students are enrolled?", agent=mock_agent, max_turns=DEFAULT_MAX_TURNS, db_dir=db_dir
    )

    assert result.sql is None
    assert result.hit_turn_limit is True
    assert result.turns == DEFAULT_MAX_TURNS
    assert "AgentError" in result.notes


def test_answer_question_extracts_sql_and_counts_ai_turns_on_success(db_dir, db_id):
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [
            HumanMessage(content="How many students are there?"),
            _ai_turn("list_tables", {"db_id": db_id}, "1"),
            ToolMessage(content="students,courses", tool_call_id="1"),
            _ai_turn(
                "submit_final_sql",
                {"db_id": db_id, "query": "SELECT COUNT(*) FROM students"},
                "2",
            ),
        ]
    }

    result = answer_question(db_id, "How many students are there?", agent=mock_agent, db_dir=db_dir)

    assert result.sql == "SELECT COUNT(*) FROM students"
    assert result.turns == 2
    assert result.hit_turn_limit is False
    assert result.notes is None


def test_answer_question_sets_notes_when_output_guardrail_rejects_sql(db_dir, db_id):
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {
        "messages": [
            _ai_turn(
                "submit_final_sql",
                {"db_id": db_id, "query": "SELECT * FROM ghost_table"},
                "1",
            ),
        ]
    }

    result = answer_question(db_id, "How many ghosts are there?", agent=mock_agent, db_dir=db_dir)

    assert result.sql == "SELECT * FROM ghost_table"
    assert result.notes is not None
    assert "Rejected" in result.notes


def test_answer_question_builds_default_agent_when_none_provided(db_dir, db_id, monkeypatch):
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": []}
    build_agent_mock = MagicMock(return_value=mock_agent)
    monkeypatch.setattr(agent_module, "build_agent", build_agent_mock)

    answer_question(db_id, "How many students are there?", db_dir=db_dir)

    build_agent_mock.assert_called_once()
    mock_agent.invoke.assert_called_once()


def test_answer_question_prompt_includes_db_id_and_question(db_dir, db_id):
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": []}

    answer_question(db_id, "How many students are there?", agent=mock_agent, db_dir=db_dir)

    call_args, call_kwargs = mock_agent.invoke.call_args
    prompt_payload = call_args[0]
    user_prompt = prompt_payload["messages"][0][1]
    assert db_id in user_prompt
    assert "How many students are there?" in user_prompt
    # langgraph's recursion_limit counts graph steps, not LLM turns — the
    # prebuilt ReAct graph has separate "model" and "tools" nodes, so each
    # full agent turn (LLM call + tool call) costs 2 steps. Passing
    # max_turns straight through as recursion_limit only budgets half as
    # many real turns as the prompt tells the model it has.
    assert call_kwargs["config"]["recursion_limit"] == DEFAULT_MAX_TURNS * 2 + 1


def test_answer_question_scales_recursion_limit_with_max_turns(db_dir, db_id):
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": []}

    answer_question(db_id, "How many students are there?", agent=mock_agent, max_turns=3, db_dir=db_dir)

    _, call_kwargs = mock_agent.invoke.call_args
    assert call_kwargs["config"]["recursion_limit"] == 3 * 2 + 1


# build_agent
#   wires ChatAnthropic + create_agent together with the module's tool list
#   and the loaded system prompt, without making a real network call


def test_build_agent_wires_model_tools_and_prompt(monkeypatch):
    mock_model_instance = MagicMock(name="chat_anthropic_instance")
    chat_anthropic_mock = MagicMock(return_value=mock_model_instance)
    create_agent_mock = MagicMock(return_value="compiled-graph")
    monkeypatch.setattr(agent_module, "ChatAnthropic", chat_anthropic_mock)
    monkeypatch.setattr(agent_module, "create_agent", create_agent_mock)

    result = build_agent(model_name="claude-test-model", prompt_version=DEFAULT_PROMPT_VERSION)

    chat_anthropic_mock.assert_called_once()
    assert chat_anthropic_mock.call_args.kwargs["model"] == "claude-test-model"

    create_agent_mock.assert_called_once_with(
        model=mock_model_instance,
        tools=TOOLS,
        system_prompt=load_system_prompt(DEFAULT_PROMPT_VERSION),
    )
    assert result == "compiled-graph"


# AgentAnswer
#   constructible with only the required positional fields (notes/hit_turn_limit default)


def test_agent_answer_defaults_notes_and_hit_turn_limit():
    answer = AgentAnswer(db_id="school", question="q", sql="SELECT 1", turns=1)
    assert answer.notes is None
    assert answer.hit_turn_limit is False