
QUESTION_MAX_LENGTH = 200

MAX_QUERY_CHARS = 300
MAX_TABLE_JOINS = 5
MAX_SUBQUERY_DEPTH = 3

#agent
# Not in use — model selection now routes through Settings (.env:
# ANTHROPIC_DEFAULT_MODEL / DEEPSEEK_DEFAULT_MODEL) via agent_builder_factory.build_agent.
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TURNS = 7