# Spider Agent Workbench

An agentic text-to-SQL system evaluated on the [Spider dataset](https://huggingface.co/datasets/xlangai/spider). Given a natural-language question and a target database, an LLM agent explores the schema via tools, writes and tests SQL against a real SQLite database, and submits a final query — all behind code-level guardrails (read-only enforcement, complexity caps, schema validation) rather than prompt instructions alone.

## Setup

- Requires [uv](https://docs.astral.sh/uv/) for dependency management (`.python-version` pins 3.11).
- Copy `.env.example` to `.env` and fill in `MODEL_PROVIDER` (`anthropic` or `deepseek`) plus that provider's API key and default model.
- Install dependencies: `uv sync`
- Pull the Spider dataset split into a local xlsx cache: `uv run scripts/download_hf_dataset_cache.py`
- Add the official Spider release `.sqlite` files under `data/spider/database/<db_id>/<db_id>.sqlite` (downloaded separately — not bundled with the HF dataset).
- Run the test suite: `uv run pytest`

## Usage

- Run a fixed-sample eval for one phase/prompt version: `uv run scripts/test_phase.py --phase <n>`
- Run a full batch eval (EX + EM) over a question sample: `uv run scripts/run_evals/run_full_eval.py`
- Rerun eval against a specific saved question set: `uv run scripts/run_evals/run_eval_custom_file.py`

See [CLAUDE.md](CLAUDE.md) for the full architecture, repo layout, and non-obvious constraints.

## Results

| Phase | Model | Change | Execution accuracy |
|---|---|---|---|
| 0 | — | Manual SQL walkthrough to gauge task difficulty before writing agent code | — |
| 1 | Claude Sonnet 4.5 | First end-to-end agent loop, minimal guardrails, `prompt_v1` | 38.3% |
| 2 | Claude Sonnet 4.5 | AST-based guardrails, complexity caps, structured `prompt_v2` | 78% |
| 3 | DeepSeek v4 Flash | Guardrails split by pipeline stage, column-level schema validation, `prompt_v3` | 75% |
| 4 | DeepSeek v4 Flash | Evaluation harness targeting hard/extra-hard questions, iterated to `prompt_v4` | 55% → 80% (hard questions only) |

Detailed write-ups per phase and model provider are in [results/reports/](results/reports/).

## Documentation

- [docs/spider_agent_manual.md](docs/spider_agent_manual.md) — design rationale (why guardrails are code not prompts, why EX and EM are both tracked, why val/test must stay separate).
- [CLAUDE.md](CLAUDE.md) — architecture, repo layout, commands, and constraints for anyone (human or agent) working in this codebase.
