# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation style

- Prefer bullet points over paragraphs whenever a section covers multiple distinct points about the same topic — a paragraph packing several facts together is harder to scan than a list.
- Use a short paragraph only when the content is genuinely one flowing thought that doesn't split cleanly into separate points.
- If a single bullet grows to cover more than one distinct fact, split it into separate bullets.

## Current state of the repo

- Past the planning stage — Phase 0 (manual SQL walkthrough, see `docs/reports/phase_0.md`), Phase 1 (first working agent, see `docs/reports/phase_1.md`), and Phase 2 (hardened guardrails + `prompt_v2`, see `docs/reports/phase_2.md`) are done.
- Phase 3 (input/output guardrails, schema-column validation, `prompt_v3`) is in progress on the `phase-3` branch — see `README.md` for current results; no `docs/reports/phase_3.md` write-up yet.
- The `spider_agent_workbench` package under `src/` is implemented and runnable end-to-end for a single question: agent → tools → guardrails → executor.
- `src/spider_agent_workbench/eval/sql_result_scorer.py` (single-query EX-style scorer, used by `scripts/phase_1_test.py`/`scripts/phase_test.py` and importable from notebooks) is implemented.
- `metrics.py` and `runner.py` are still empty — no batch EX/EM scoring or batch runner yet.
- Before assuming a module works a given way, read it; this file only tracks the broad shape.

## Commands

This project uses **uv** for dependency and environment management (`.python-version` pins 3.11, `uv.lock` is checked in).

- Add a dependency: `uv add <package>`
- Add a dev-only dependency: `uv add --dev <package>`
- Run any script inside the project's venv: `uv run <script>.py`
- Run the test suite: `uv run pytest`
- Run a single test file: `uv run pytest tests/guardrails/test_sql_guardrails.py -q`
- Pull the Spider dataset split from HF into local xlsx cache: `uv run scripts/download_hf_dataset_cache.py`
- Requires a `.env` at the repo root with `MODEL_PROVIDER` (`anthropic` or `deepseek`) plus that provider's API key and default model — `ANTHROPIC_API_KEY`/`ANTHROPIC_DEFAULT_MODEL` and/or `DEEPSEEK_API_KEY`/`DEEPSEEK_DEFAULT_MODEL` (all loaded via `pydantic-settings` in `config.py`)

There is no lint or format tooling configured yet (no ruff config in `pyproject.toml`). If asked to add linting, check `pyproject.toml` first since this file will go stale. `scripts/phase_1_test.py` (runs the agent end-to-end and scores it via `eval/sql_result_scorer.py`) is a separate manual eval script, not part of the `pytest` suite — see the Testing section below for that.

## Testing

- Tests live under `tests/` and run via `uv run pytest` — `pytest` is a dev dependency (`[dependency-groups] dev` in `pyproject.toml`), configured with `testpaths = ["tests"]` under `[tool.pytest.ini_options]`.
- `tests/conftest.py` provides `db_dir`/`db_id` fixtures: a throwaway fixture sqlite database (`students`/`courses` tables, seeded with a few rows) built fresh in a `tmp_path` per test, so tests never depend on the gitignored `data/` dataset.
- Current coverage: `tests/guardrails/` (`test_input_guardrail.py`, `test_output_guardrail.py`, `test_sql_guardrails.py`), `tests/test_schema.py`, `tests/test_tools.py`, `tests/test_executor.py`, `tests/agent_test.py`, `tests/agent_builder_factory_test.py`, `tests/eval/test_sql_result_scorer.py`. `loaders.py` and `utils.py` have no tests yet.
- **Write the test before writing the implementation.** For any new function, guardrail, or bugfix: add (or update) a failing test in the relevant `tests/test_*.py` file first, run `uv run pytest` to confirm it fails for the expected reason, then write the minimal code to make it pass. This applies to bugfixes too — reproduce the bug as a failing test before patching it.

## What this project is

An **agentic text-to-SQL system** evaluated on the Spider dataset (`xlangai/spider` on Hugging Face). The full design rationale, phased build order, and worked examples live in `docs/spider_agent_manual.md` — read it before implementing any agent/tool/guardrail/eval code, since it encodes decisions (e.g. why guardrails must be code and not prompt text, why EX and EM are both tracked, why a val/test split must stay separate) that aren't obvious from code alone. Note: the manual originally called for a hand-rolled ReAct loop with no framework; the actual implementation uses `langchain` + `langgraph` (`create_agent`) for the tool loop — treat the manual as the rationale doc, not a literal spec of what's on disk.

### Architecture (as built)

Data flow, in order:

- `loaders.py` — reads cached HF Spider xlsx, groups examples by `db_id`.
- `schema.py` — lists tables / renders a table's `CREATE TABLE` via `sqlite_master`.
- `agent_builder_factory.py` — builds a langchain/langgraph tool-calling agent from a versioned system prompt (model/provider wiring lives here, kept separate so swapping models doesn't touch the run loop).
- `agent.py` — runs the agent loop (via a `build_agent`-constructed agent) until `submit_final_sql` is called or `max_turns` is hit.
- `tools.py` — `list_tables`, `describe_table`, `sample_rows`, `run_query`, `submit_final_sql`, each routed through `guardrails.sql_guardrails.validate_sql`. `agent.py` also runs `guardrails.input_guardrails` before the loop starts and `guardrails.output_guardrails` on the final submitted SQL.
- `executor.py` — raw sqlite3 execution with timeout + row cap, raises on error.
- `eval/sql_result_scorer.py` — scores one predicted SQL query against gold SQL, EX-style set/multiset row comparison.
- `eval/metrics.py` + `eval/runner.py` — aggregate EX/EM + batch runner, not yet implemented.

Actual layout:
```
data/spider/database/<db_id>/<db_id>.sqlite   # official Spider release SQLite files
data/hf_xlangai_spider/{train,validation}_spider.xlsx  # cached via scripts/download_hf_dataset_cache.py
src/spider_agent_workbench/
  paths.py         # PROJECT_ROOT-relative path constants, loads .env
  config.py        # pydantic-settings Settings (MODEL_PROVIDER + per-provider API key/default model)
  loaders.py       # HF split -> SpiderExample, grouped/filtered by db_id
  schema.py        # list_databases, get_table_list, get_table_info, get_column_list
  executor.py       # execute_query -> QueryResult (headers/rows/truncated)
  constants.py      # shared limits (query length, join/subquery caps, max turns, model name)
  logging_config.py # setup_logging() for scripts/phase_*_test.py runs -> logs/
  guardrails/
    guardrail_result.py    # GuardrailResult(ok, reason) dataclass shared by all checks
    input_guardrails.py    # question length cap, prompt-injection screen, db-existence check
    sql_guardrails.py      # validate_sql: read-only, length cap, join/subquery caps, schema-table + schema-column checks
    output_guardrails.py   # dry-run parses/validates/executes the agent's final submitted SQL
  tools.py          # LangChain @tool wrappers around schema/executor, guardrail-checked
  agent_builder_factory.py   # build_agent / load_system_prompt / TOOLS (model+prompt+tool wiring)
  agent.py          # answer_question (langchain+langgraph ReAct loop), calls build_agent when no agent is passed in
  utils.py          # format_result_table (pipe-table rendering for tool output)
  prompts/prompt_v*.md   # versioned system prompts, never edited in place
  eval/sql_result_scorer.py   # score_query(): predicted vs gold SQL, binary EX-style match; importable from notebooks and scripts
  eval/metrics.py, eval/runner.py   # stubs — aggregate EX/EM scoring + batch runner not yet built
scripts/            # one-off/setup scripts (dataset download, connection smoke tests, phase_N_test.py)
tests/              # pytest suite — conftest.py fixtures + guardrails/, test_schema.py, test_tools.py, test_executor.py, agent_test.py, agent_builder_factory_test.py, eval/
docs/reports/       # phase-by-phase progress notes (phase_0.md, phase_1.md, phase_2.md, ...)
```

### Non-obvious constraints worth preserving in any implementation

- **Guardrails are code, not prompt instructions** (`guardrails/` package) — read-only SQL enforcement (rejects `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`TRUNCATE`/`PRAGMA`/`ATTACH`/etc.), a query-length cap, join/subquery-depth caps, and schema-validity checks (referenced tables *and* columns must exist in the current `db_id`) all run outside the LLM call before a query executes or is submitted.
- **Guardrails run at three points, not just one**: `input_guardrails` gate the question before the agent loop starts, `sql_guardrails.validate_sql` gates every `run_query`/`submit_final_sql` tool call, and `output_guardrails` re-parses/validates/dry-run-executes whatever SQL the agent finally submitted.
- **The Spider HF parquet has no `.sqlite` files** — those come separately from the official Spider release and are joined against `db_id` locally under `data/spider/database/`.
- **Prompts are versioned as separate files** (`prompts/prompt_v1.md`, `prompt_v2.md`, ...) with a changelog comment, never mutated in place, so eval runs stay comparable across versions.
- **Val and held-out test must stay separate** — only the val split is used for iterative tuning; a final test slice is touched once, at the end, to check for overfitting to val.
- **Execution Accuracy (EX)** compares result rows as sets/multisets, since SQL row order is unordered without `ORDER BY`.
  - Implemented per-query in `eval/sql_result_scorer.py::score_query`.
  - That scorer re-runs guardrails on the predicted SQL before executing it, since a query that already failed guardrails can still show up as the agent's "final" submission.
- **Exact Match (EM)** compares SQL clause-by-clause using the official Spider eval scripts (from `taoyds/spider` — reuse, don't reimplement) and is not implemented yet.
- Batch aggregation of either metric across a dataset split (`eval/metrics.py`, `eval/runner.py`) is also not implemented yet.

## Gitignored files

- `data/` and `logs/` are gitignored — don't assume dataset files are present in a fresh checkout.
- To populate `data/`, use `scripts/download_hf_dataset_cache.py` for the HF cache and the official Spider release for the `.sqlite` files.
