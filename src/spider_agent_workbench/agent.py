"""
The ReAct loop tying the LLM (via langchain-anthropic) to the tool set defined
in tools.py (which is itself policed by guardrails.py). This is Phase 1/2's
"agentic" agent: instead of asking for SQL in one shot, the model explores the
schema with tools and only stops once it calls submit_final_sql.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.errors import GraphRecursionError

from spider_agent_workbench.config import Settings
from spider_agent_workbench import tools
from spider_agent_workbench.paths import PROMPTS_DIR


DEFAULT_PROMPT_VERSION = "prompt_v2"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TURNS = 10

TOOLS = [
    tools.list_tables,
    tools.describe_table,
    tools.sample_rows,
    tools.run_query,
    tools.submit_final_sql,
]


def load_system_prompt(version: str = DEFAULT_PROMPT_VERSION) -> str:
    """
    Load a versioned prompt file. Never edit a prompt file in place —
    write prompt_v{n+1}.txt instead so eval runs stay comparable.
    """
    path = PROMPTS_DIR / f"{version}.md"
    text = path.read_text(encoding="utf-8")
    # Strip a leading "<!-- v1: ... -->" changelog line if present.
    lines = [line for line in text.splitlines() if not line.strip().startswith("<!--")]
    return "\n".join(lines).strip()


def build_agent(model_name: str = DEFAULT_MODEL, prompt_version: str = DEFAULT_PROMPT_VERSION):
    """Build a compiled tool-using agent graph. Call once, reuse across questions."""
    model = ChatAnthropic(model=model_name, api_key=Settings.anthropic_api_key)
    system_prompt = load_system_prompt(prompt_version)
    return create_agent(model=model, tools=TOOLS, system_prompt=system_prompt)


@dataclass
class AgentAnswer:
    db_id: str
    question: str
    sql: str | None
    turns: int
    hit_turn_limit: bool = False
    # messages: list[BaseMessage] = field(default_factory=list)


def _extract_final_sql(messages: list[BaseMessage]) -> str | None:
    """Walk the message trace backwards for the submit_final_sql tool call's SQL arg."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call["name"] == "submit_final_sql":
                    return call["args"].get("query")
    return None


def answer_question(db_id:str, question: str, agent=None, max_turns:int = DEFAULT_MAX_TURNS) -> AgentAnswer:
    """
    This is the entry point function to call the agent
    Run the agent on a single spider question and return its submitted SQL
    """

    if agent is None:
        agent = build_agent()

    user_prompt = f"db_id:{db_id}\n Question: {question}"

    try:
        result = agent.invoke(
            {"messages":[("user", user_prompt)]},
            config={"recursion_limit":max_turns}
        )
    except GraphRecursionError:
        return AgentAnswer(db_id = db_id, question = question, sql=None, turns=max_turns, hit_turn_limit=True)

    messages = result['messages']
    turns = sum(1 for msg in messages if isinstance(msg, AIMessage))
    return AgentAnswer(db_id=db_id, question=question, sql=_extract_final_sql(messages), turns=turns)