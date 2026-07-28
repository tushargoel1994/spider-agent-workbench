# Spider Agent Workbench

An agentic text-to-SQL system evaluated on the [Spider dataset](https://huggingface.co/datasets/xlangai/spider) (`xlangai/spider` on Hugging Face).

Given a natural-language question and a target database, an LLM-driven agent explores the schema via tools, writes and tests SQL queries against a real SQLite database, and submits a final query — all behind code-level guardrails (read-only enforcement, query length caps, schema validation).

## Setup

- Requires [uv](https://docs.astral.sh/uv/) for dependency and environment management.
- Requires a `.env` file at the repo root with `ANTHROPIC_API_KEY=...`.
- Pull the Spider dataset split into a local xlsx cache: `uv run scripts/download_hf_dataset_cache.py`
- The official Spider release `.sqlite` files are also required under `data/spider/database/` (not bundled with the HF dataset).

## Project phases

- **Phase 0 — Manual SQL walkthrough**: hand-wrote SQL for a sample of Spider questions against one database to understand the difficulty the agent would need to handle before writing any agent code.
- **Phase 1 — First working agent**: built the first end-to-end loop (agent → tools → guardrails → executor) for a single question at a time, using `langchain`/`langgraph` for the tool-calling loop, plus a basic execution-accuracy scorer for spot-checking results.
- **Later phases** (batch evaluation, exact-match scoring, prompt iteration, etc.) are tracked as they land — see `docs/` for current status.

For detailed write-ups of each phase, see the [docs/](docs/) folder, in particular [docs/reports/](docs/reports/) and [docs/spider_agent_manual.md](docs/spider_agent_manual.md).
