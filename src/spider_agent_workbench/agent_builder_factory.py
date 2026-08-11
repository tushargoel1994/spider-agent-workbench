"""
Agent construction, kept separate from answer_question's run loop (agent.py)
so swapping models/providers only touches this file.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek

from spider_agent_workbench.config import Settings
from spider_agent_workbench import tools
from spider_agent_workbench.paths import PROMPTS_DIR


DEFAULT_PROMPT_VERSION = "prompt_v3"


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


def build_agent(model_name: str | None = None, prompt_version: str = DEFAULT_PROMPT_VERSION):
    """Build a compiled tool-using agent graph. Call once, reuse across questions.

    The chat model class, its default model name, and its API key are picked
    from Settings.model_provider (.env: MODEL_PROVIDER) — model_name overrides
    the provider's default when given.
    """
    provider = Settings.model_provider.strip().lower()
    if provider == "anthropic":
        model = ChatAnthropic(
            model=model_name or Settings.anthropic_default_model,
            api_key=Settings.anthropic_api_key,
        )
    elif provider == "deepseek":
        model = ChatDeepSeek(
            model=model_name or Settings.deepseek_default_model,
            api_key=Settings.deepseek_api_key,
        )
    else:
        raise ValueError(f"Unsupported MODEL_PROVIDER: {Settings.model_provider!r}")

    system_prompt = load_system_prompt(prompt_version)
    return create_agent(model=model, tools=TOOLS, system_prompt=system_prompt)
