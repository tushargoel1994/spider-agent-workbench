# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation style

- Prefer bullet points over paragraphs whenever a section covers multiple distinct points about the same topic.
- Use a short paragraph only when the content is genuinely one flowing thought that doesn't split cleanly into separate points.
- If a single bullet grows to cover more than one distinct fact, split it into separate bullets.

## What this project is

- An **agentic text-to-SQL system** evaluated on the [Spider dataset](https://huggingface.co/datasets/xlangai/spider): given a natural-language question and a target database, an LLM agent explores the schema via tools, writes and tests SQL against a real SQLite database, and submits a final query.
- All agent activity runs behind **code-level guardrails** (read-only enforcement, complexity caps, schema validation) rather than relying on prompt instructions alone.
- `docs/spider_agent_manual.md` has the full design rationale (why guardrails are code not prompts, why EX and EM are both tracked, why val/test must stay separate) — read it before implementing agent/tool/guardrail/eval code. It predates the current implementation choice of `langchain` + `langgraph` (`create_agent`) for the tool loop, so treat it as a rationale doc, not a literal spec.
- `README.md` has the phase-by-phase build history and result numbers; `results/reports/<provider>/phase_N.md` has the detailed write-up per phase per model provider.

## Architecture

Request flow, in order:

1. `loaders.py` reads the cached HF Spider xlsx and groups examples by `db_id`.
2. `agent_builder_factory.py` builds a langchain/langgraph tool-calling agent: picks the chat model class (Anthropic or DeepSeek) from `.env`, loads a versioned system prompt, and binds the tools.
3. `agent.py::answer_question` runs `guardrails.input_guardrails`, then the agent loop (via the built agent) until `submit_final_sql` is called or `max_turns` is hit, then runs `guardrails.output_guardrails` on the final SQL.
4. `tools.py` (`list_tables`, `describe_table`, `sample_rows`, `run_query`, `submit_final_sql`) each route through `guardrails.sql_guardrails.validate_sql` before touching the database.
5. `executor.py` runs the validated query against sqlite with a timeout and row cap.
6. `eval/` scores a run: `sql_result_scorer.py` (EX — set/multiset row comparison), `exact_match.py` (EM — wraps the official Spider eval scripts in `eval/spider_official/`), `sql_features.py` (tags gold SQL with structural features), `metrics.py` + `runner.py` (batch aggregation across a question set).

## Repo layout

```
src/spider_agent_workbench/
  paths.py, config.py       # PROJECT_ROOT paths + pydantic-settings Settings (loads .env)
  loaders.py, schema.py     # dataset loading, schema introspection
  executor.py, constants.py # sqlite execution, shared limits (query length, join/subquery caps, max turns)
  logging_config.py         # setup_logging() -> logs/
  guardrails/                # input_guardrails, sql_guardrails, output_guardrails, guardrail_result
  tools.py                   # LangChain @tool wrappers, guardrail-checked
  agent_builder_factory.py   # build_agent / load_system_prompt (model + prompt + tool wiring)
  agent.py                   # answer_question — the agent run loop
  utils.py                   # output formatting (pipe tables)
  prompts/prompt_v{1..4}.md  # versioned system prompts, never edited in place
  eval/                      # sql_result_scorer (EX), exact_match (EM), sql_features, metrics, runner
  eval/spider_official/      # vendored official Spider eval scripts (taoyds/spider) — reuse, don't reimplement
scripts/
  download_hf_dataset_cache.py    # pulls the HF Spider split into data/hf_xlangai_spider/
  test_phase.py                    # fixed-sample agent run + EX scoring for one phase/prompt version
  select_questions/select_hard_questions.py  # freezes a hard/extra-hard question pool for eval
  run_evals/run_full_eval.py       # large batch eval run (EX + EM) over a question sample
  run_evals/run_eval_custom_file.py # rerun eval against a specific saved question set
tests/            # pytest suite, mirrors src/ layout (guardrails/, eval/, hard_question_eval/, ...)
docs/             # spider_agent_manual.md (rationale) + per-initiative plan docs
data/, logs/      # gitignored — see "Gitignored files" below
```

## Commands

Uses **uv** for dependency/environment management (`.python-version` pins 3.11, `uv.lock` checked in).

- Install dependencies: `uv sync`
- Add a dependency: `uv add <package>` — add a dev-only dependency: `uv add --dev <package>`
- Run any script: `uv run <path/to/script>.py`
- Run the full test suite: `uv run pytest`
- Run a single test file: `uv run pytest tests/guardrails/test_sql_guardrails.py -q`
- Pull the Spider HF split into local xlsx cache: `uv run scripts/download_hf_dataset_cache.py`
- Requires a `.env` at the repo root (see `.env.example`): `MODEL_PROVIDER` (`anthropic` or `deepseek`) plus that provider's API key and default model — `ANTHROPIC_API_KEY`/`ANTHROPIC_DEFAULT_MODEL` and/or `DEEPSEEK_API_KEY`/`DEEPSEEK_DEFAULT_MODEL`.
- No lint/format tooling is configured (no ruff config in `pyproject.toml`) — check `pyproject.toml` before assuming otherwise, since this file will go stale.

## Testing

- Tests live under `tests/`, run via `uv run pytest` (`testpaths = ["tests"]` in `pyproject.toml`).
- `tests/conftest.py` provides `db_dir`/`db_id` fixtures — a throwaway sqlite database built fresh in `tmp_path` per test, so tests never depend on the gitignored `data/` dataset.
- **Write the test before writing the implementation.** For any new function, guardrail, or bugfix: add a failing test first, confirm it fails for the expected reason, then write the minimal code to pass it. Applies to bugfixes too — reproduce the bug as a failing test before patching it.
- `scripts/test_phase.py` and `scripts/run_evals/*.py` are manual eval runs against real data, not part of the `pytest` suite.

## Non-obvious constraints worth preserving

- **Guardrails are code, not prompt instructions.** They run at three separate points, not just one:
  - `input_guardrails` — gates the question before the agent loop starts (length cap, prompt-injection screen, db-existence check).
  - `sql_guardrails.validate_sql` — gates every `run_query`/`submit_final_sql` tool call (read-only enforcement, query-length cap, join/subquery-depth caps, schema-table + schema-column validation against the current `db_id`).
  - `output_guardrails` — re-parses/validates/dry-run-executes whatever SQL the agent finally submitted.
- **The Spider HF parquet has no `.sqlite` files** — those come separately from the official Spider release and are joined against `db_id` locally under `data/spider/database/`.
- **Prompts are versioned as separate files**, never mutated in place, so eval runs stay comparable across versions. `agent_builder_factory.DEFAULT_PROMPT_VERSION` pins which one is used by default.
- **Val and held-out test must stay separate** — only the val split is used for iterative tuning; a final test slice is touched once, at the end, to check for overfitting to val.
- **EX** (`eval/sql_result_scorer.py`) compares result rows as sets/multisets (SQL row order is unordered without `ORDER BY`), and re-runs guardrails on the predicted SQL before executing it, since a query that already failed guardrails can still show up as the agent's "final" submission.
- **EM** (`eval/exact_match.py`) compares SQL clause-by-clause via the vendored official Spider eval scripts, and doubles as the source of a question's official hardness bucket (easy/medium/hard/extra) when called with `predicted_sql=None`.

## Gitignored files

- `data/` and `logs/` are gitignored — a fresh checkout has neither the dataset nor the sqlite files.
- To populate `data/`: `scripts/download_hf_dataset_cache.py` for the HF xlsx cache, plus the official Spider release `.sqlite` files under `data/spider/database/<db_id>/<db_id>.sqlite`.
