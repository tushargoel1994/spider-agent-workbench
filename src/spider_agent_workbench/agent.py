"""
The ReAct loop tying the LLM to the tool set defined in tools.py (which is
itself policed by guardrails.py). This is Phase 1/2's "agentic" agent:
instead of asking for SQL in one shot, the model explores the schema with
tools and only stops once it calls submit_final_sql. Agent construction
itself (model/prompt/tool wiring) lives in agent_builder_factory.py.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.errors import GraphRecursionError

from spider_agent_workbench.agent_builder_factory import build_agent
from spider_agent_workbench.guardrails.input_guardrails import run_input_guardrails
from spider_agent_workbench.guardrails.output_guardrails import run_output_guardrails
from spider_agent_workbench.paths import DATABASES_DIR
from spider_agent_workbench.constants import DEFAULT_MAX_TURNS


@dataclass
class AgentAnswer:
    db_id: str
    question: str
    sql: str | None
    turns: int
    hit_turn_limit: bool = False
    notes: str | None = None
    latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    # messages: list[BaseMessage] = field(default_factory=list)


def _extract_final_sql(messages: list[BaseMessage]) -> str | None:
    """Walk the message trace backwards for the submit_final_sql tool call's SQL arg."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call["name"] == "submit_final_sql":
                    return call["args"].get("query")
    return None


def _sum_token_usage(messages: list[BaseMessage]) -> tuple[int, int]:
    """Sum input/output tokens across every AIMessage's usage_metadata (the
    agent can take several turns per question, so no single message has the
    total). usage_metadata is None on a message that didn't report usage."""
    input_tokens = 0
    output_tokens = 0
    for message in messages:
        if isinstance(message, AIMessage) and message.usage_metadata:
            input_tokens += message.usage_metadata.get("input_tokens", 0)
            output_tokens += message.usage_metadata.get("output_tokens", 0)
    return input_tokens, output_tokens


def answer_question(
    db_id: str,
    question: str,
    agent=None,
    max_turns: int = DEFAULT_MAX_TURNS,
    db_dir: Path = DATABASES_DIR,
) -> AgentAnswer:
    """Run the agent on a single Spider question and return its submitted SQL.

    Entry point for calling the agent end-to-end: input guardrails, the
    agent's tool loop, then output guardrails on whatever SQL it submitted.
    """
    if agent is None:
        agent = build_agent()

    input_guardrail_result = run_input_guardrails(db_id, db_dir, question)
    if not input_guardrail_result.ok:
        return AgentAnswer(
            db_id=db_id, question=question, sql=None, turns=0, notes=input_guardrail_result.reason
        )

    user_prompt = f"db_id:{db_id} :: db_dir:{db_dir}\n Question: {question}"

    # langgraph's recursion_limit counts graph steps, not LLM turns: the
    # prebuilt ReAct graph has separate "model" and "tools" nodes, so each
    # full agent turn (LLM call + tool call) costs 2 steps. max_turns is
    # meant to budget real LLM turns (it's also the number the prompt tells
    # the model it has), so double it, plus one step of headroom for the
    # final turn's tool call.
    recursion_limit = max_turns * 2 + 1

    # Brackets only the agent.invoke(...) call itself, not the guardrail
    # checks before/after it, so latency_seconds measures LLM/tool time only.
    start_time = time.perf_counter()
    try:
        result = agent.invoke(
            {"messages": [("user", user_prompt)]},
            config={"recursion_limit": recursion_limit},
        )
    except GraphRecursionError as e:
        latency_seconds = time.perf_counter() - start_time
        return AgentAnswer(
            db_id=db_id,
            question=question,
            sql=None,
            turns=max_turns,
            hit_turn_limit=True,
            notes=f"Error: AgentError: {e}",
            latency_seconds=latency_seconds,
        )
    latency_seconds = time.perf_counter() - start_time

    messages = result["messages"]
    turns = sum(1 for msg in messages if isinstance(msg, AIMessage))
    extracted_sql = _extract_final_sql(messages)
    input_tokens, output_tokens = _sum_token_usage(messages)

    output_guardrail_result = run_output_guardrails(db_id, db_dir, extracted_sql)
    notes = output_guardrail_result.reason if not output_guardrail_result.ok else None

    return AgentAnswer(
        db_id=db_id,
        question=question,
        sql=extracted_sql,
        turns=turns,
        notes=notes,
        latency_seconds=latency_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )