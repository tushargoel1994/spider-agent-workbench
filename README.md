# Spider Agent Workbench

## Objective

- Build an agentic text-to-SQL system evaluated on the [Spider dataset](https://huggingface.co/datasets/xlangai/spider).
- Given a natural-language question and a target database, an LLM-driven agent explores the schema via tools, writes and tests SQL against a real SQLite database, and submits a final query.
- All agent activity runs behind code-level guardrails (read-only enforcement, complexity caps, schema validation) rather than relying on prompt instructions alone.

## File source

- Dataset: [`xlangai/spider`](https://huggingface.co/datasets/xlangai/spider) on Hugging Face, cached locally as xlsx via `scripts/download_hf_dataset_cache.py`.
- Databases: the official Spider release provides the `.sqlite` files (not bundled with the HF dataset) — required under `data/spider/database/<db_id>/<db_id>.sqlite`.
- `data/` and `logs/` are gitignored — a fresh checkout has neither the dataset nor the sqlite files until the setup steps below are run.

## Project setup

- Requires [uv](https://docs.astral.sh/uv/) for dependency and environment management (`.python-version` pins 3.11).
- Requires a `.env` file at the repo root with `MODEL_PROVIDER=anthropic` (or `deepseek`), plus that provider's API key and default model — `ANTHROPIC_API_KEY`/`ANTHROPIC_DEFAULT_MODEL` and/or `DEEPSEEK_API_KEY`/`DEEPSEEK_DEFAULT_MODEL`.
- Install dependencies: `uv sync`
- Pull the Spider dataset split into a local xlsx cache: `uv run scripts/download_hf_dataset_cache.py`
- Add the official Spider release `.sqlite` files under `data/spider/database/` (downloaded separately, not via the HF cache).
- Run the test suite: `uv run pytest`

## Project phases

### Phase 0 — Manual SQL walkthrough

- Hand-wrote SQL for a sample of Spider questions against one database (`battle_death`) to understand the difficulty the agent would need to handle before writing any agent code.
- **Result**: 4/5 questions answered correctly by hand; the one miss was a manual join mistake, not a conceptual gap — confirmed the problem was worth automating.

### Phase 1 — First working agent

- Built the first end-to-end loop (agent → tools → guardrails → executor) for a single question at a time, using `langchain`/`langgraph` for the tool-calling loop.
- Shipped minimal guardrails (read-only check, query-length cap, table-existence check) and a one-paragraph prompt (`prompt_v1`).
- Added a basic execution-accuracy scorer for spot-checking results.
- **Result**: 30% execution accuracy (3/10) on an ad hoc 10-question sample. Half the sample never submitted an answer at all (hit the turn limit), and column over-selection accounted for most of the rest.

### Phase 2 — Hardened guardrails, iterated prompt

- Rewrote guardrails from regex-over-text to AST-based checks, and added complexity guardrails (max joins, max subquery depth).
- Replaced the minimal `prompt_v1` with a structured `prompt_v2` (explicit role, step-by-step method, and constraints matching the guardrail limits).
- **Result**: execution accuracy rose to 50% (5/10). Turn-limit failures dropped sharply; column over-selection was unchanged. The prompt and guardrail changes landed together, so the gain isn't attributable to either alone.

### Phase 3 — Input/output guardrails, schema-column validation (in progress, `phase-3` branch)

- Split guardrails by pipeline stage: input guardrails gate the question before the agent loop starts, SQL guardrails gate every tool call, output guardrails re-validate whatever the agent finally submits.
- Extended schema validation from tables to columns, closing a gap where a hallucinated column on a real table could pass.
- Fixed a turn-budget bug where the agent was silently getting half its intended number of turns.
- Restructured the prompt again (`prompt_v3`) with separate guidance for simple vs. multi-table/subquery questions.
- **Result**: execution accuracy rose to 70% (7/10) on the same sample, with turn-limit failures eliminated entirely. Remaining misses are logic near-misses (row-count, column-count, value mismatches) rather than the agent failing to answer at all.

### Phase 4 — Evaluation harness & batch scoring

- Implement `eval/metrics.py` (aggregate EX) and `eval/runner.py` (batch runner across the validation split), replacing the ad hoc fixed-10-question scripts used in Phases 1–3.
- Wire in official Exact Match (EM) scoring via the `taoyds/spider` evaluation scripts.
- Add structured per-question run logging to `logs/` for post-hoc failure analysis.

### Phase 5 — Ablation & robustness

- Isolate the individual contribution of prompt changes vs. guardrail changes vs. the turn-budget fix, since every phase so far has changed multiple things at once.
- Widen the evaluation sample (more databases, more questions per database) before trusting exact accuracy numbers.
- Target the persistent failure modes directly (column over-selection, row/value mismatches), likely via few-shot examples rather than further instruction restatement.
- Replace the lock-wait `timeout` in the executor with a real query execution timeout.

### Phase 6 — Held-out test & final reporting

- Run the held-out test split once, at the end, to check for overfitting to the validation split used throughout tuning.
- Produce a final consolidated report comparing all prompt/guardrail iterations on EX and EM.
- Assess production-readiness considerations (cost/latency tracking, error handling for real deployment) if the project moves past the evaluation stage.

## Status

- Phases 0–2 are complete and merged; Phase 3 is in progress on the `phase-3` branch, with results tracked in `README.md` pending a `docs/reports/phase_3.md` write-up.
- Execution accuracy on the fixed ad hoc sample has climbed each phase — 30% → 50% → 70% — driven primarily by eliminating turn-limit failures rather than by improving SQL correctness on logic near-misses.
- The core gap going into Phase 4 is evaluative, not architectural: every result so far comes from the same 10-question, 2-database sample with no ablation between changes, and both `metrics.py` and `runner.py` remain empty stubs. Batch evaluation across the full split is the highest-leverage next step before further prompt or guardrail tuning.

For detailed write-ups of each phase, see [docs/reports/](docs/reports/) and [docs/spider_agent_manual.md](docs/spider_agent_manual.md).
