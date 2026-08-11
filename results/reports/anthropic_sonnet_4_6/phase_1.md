
# Phase 1: Write the basic code of the agent and query prompt

## Goal
Get a single question through the full loop — natural language in, a submitted SQL string out — for one database at a time, with no evaluation harness yet. The target was a working v1, not a good one: basic tools, basic guardrails, a one-paragraph prompt. Phase 0 established (by hand) that even "simple" Spider questions have sharp edges (missing `ON`, ambiguous joins); Phase 1's job was to let the agent hit those edges itself via tool calls instead of being handed the schema up front.

## Scope decisions
- **One `db_id` per run.** The agent is not given the whole Spider database catalog — it's told which `db_id` it's working against in the user prompt and has to call `list_tables`/`describe_table`/`sample_rows` to learn the schema. This mirrors how Spider questions are actually posed (one question, one target DB).
- **Framework used, contrary to the original plan.** `docs/spider_agent_manual.md` calls for a hand-rolled ReAct loop with no agent framework. Phase 1 instead builds on `langchain.agents.create_agent` + `langgraph` (see `agent.py`) to get a working tool-calling loop quickly. This is a deliberate shortcut for v1, not a reversal of the manual's reasoning — worth revisiting once the eval harness exists and there's a reason to compare a hand-rolled loop against it.
- **Guardrails are minimal on purpose.** Only three checks exist (read-only keywords, query length, table existence) — see below. Column-level validation, join/subquery complexity bounds, and a true query execution timeout are explicitly deferred, not forgotten.

## Components Built

| File | What it does |
|---|---|
| **`schema.py`** | - `list_databases` — which `db_id`s have a matching `.sqlite` on disk<br>- `get_table_list` — table names via `sqlite_master`<br>- `get_table_info` — raw `CREATE TABLE` SQL for one table<br>- No column/foreign-key introspection beyond what's already in the `CREATE TABLE` text |
| **`executor.py`** | - `execute_query` opens a fresh `sqlite3` connection per call<br>- Returns a `QueryResult(headers, rows, truncated)` dataclass; raises `sqlite3.Error` on failure rather than swallowing it<br>- Row count capped by fetching `max_rows + 1` and truncating<br>- ⚠️ `timeout` is passed straight to `sqlite3.connect(timeout=...)`, which only bounds the wait on a database lock — it does **not** cap the runtime of a slow/expensive query. A real execution timeout (e.g. a watchdog thread or `interrupt()`) is still open |
| **`guardrails.py`** | - `validate_sql` runs three checks in order, short-circuiting on the first failure<br>- `check_read_only` — regex-rejects `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`TRUNCATE`/`PRAGMA`/`ATTACH`/`DETACH`/`CREATE`/`REPLACE`/`VACUUM`/`REINDEX`<br>- `check_query_length` — 2000-char cap<br>- `check_schema_tables` — every `FROM`/`JOIN` target must exist in the current `db_id` (regex over the SQL, not a real parser)<br>- Runs both on query execution (`run_query`) and on final submission (`submit_final_sql`), so a hallucinated table can't sneak through as the final answer just because it was never test-run |
| **`tools.py`** | - Five LangChain `@tool`-wrapped functions the agent can call<br>- `list_tables`, `describe_table`, `sample_rows` (delegates to `run_query` with a `LIMIT`)<br>- `run_query` — guardrail-checked execution, formats results as a pipe table<br>- `submit_final_sql` — guardrail-checked, does not execute; detected by name to end the loop |
| **`agent.py`** | - `build_agent()` wires a `ChatAnthropic` model, the tool list, and a versioned system prompt into a `langgraph` tool-calling agent via `create_agent`<br>- `answer_question()` is the entry point: sends `db_id` + question as the first user message, runs until `submit_final_sql` is called or `recursion_limit` (`max_turns`, default 10) is hit<br>- Walks the returned message list backwards to pull the SQL out of the `submit_final_sql` tool call's arguments<br>- Returns an `AgentAnswer` dataclass (`sql`, `turns`, `hit_turn_limit`) |
| **`utils.py`** | - `format_result_table` — pipe-separated, column-aligned text renderer for query results, so tool output is easy for the LLM (and a human reading logs) to scan |
| **`prompts/prompt_v1.md`** | - First system prompt: one paragraph telling the agent it has schema-exploration tools, that it must not write/modify data, and that its final response should be a single SQL query with no surrounding commentary<br>- Deliberately minimal — no few-shot examples, no schema-formatting guidance, no explicit "call `submit_final_sql` when done" instruction (the agent has to infer that from the tool's own description) |

## Manual smoke testing
Ran the agent by hand (`scripts/test.py`, `notebokks/analysis_v1.ipynb`) against small `train_spider` databases — `soccer_1` (14 questions), `company_1` (7), `local_govt_mdm` (14) — chosen specifically because each has fewer than 15 questions, small enough to eyeball every answer against the gold SQL without any aggregate scoring. This is a stand-in for eval, not a replacement: no pass/fail counts were tallied, just spot checks that the plumbing works end to end.

## Ad hoc accuracy sample (`results/phase_1_result.json`)

Manual eyeballing wasn't enough to say anything quantitative, but the real eval harness (`eval/metrics.py`, `eval/runner.py`) still doesn't exist. As a stopgap, `scripts/phase_1_test.py` + `scripts/sql_result_scorer.py` were written to get one number: a deterministic sample (seed `42`) of 2 validation `db_id`s x 5 questions each (`course_teach`, `battle_death`; 10 questions total) run through `prompt_v1` end to end, each answer scored by re-running guardrails, executing predicted vs. gold SQL, and comparing result rows (multiset compare, or ordered if gold has `ORDER BY`). This is **execution accuracy on 10 questions from 2 databases** — a smoke-test-sized sample, not a substitute for the real val/test eval planned for Phase 2, and not the official Spider `taoyds/spider` scoring either.

**Result: 3/10 correct (30% EX-style accuracy).**

| status | count | meaning |
|---|---|---|
| `match` | 3 | predicted and gold result sets matched |
| `no_sql` | 5 | agent hit the `max_turns=10` limit without ever calling `submit_final_sql` |
| `column_count_mismatch` | 2 | predicted query ran fine but selected more columns than gold |

By db: `course_teach` 2/5, `battle_death` 1/5.

Two failure patterns stood out, both plausibly traceable to `prompt_v1` being deliberately minimal (no "call `submit_final_sql` when done" instruction, no column-selection guidance):
- **Half the sample never submitted an answer at all.** All 5 `no_sql` cases ran the full 10 turns without calling `submit_final_sql` — this is a bigger problem than wrong SQL, since the agent apparently didn't reliably infer when/how to end the loop from the tool's description alone.
- **Both `column_count_mismatch` cases over-selected columns** despite matching gold on logic/joins — e.g. `SELECT name, date, result FROM battle` vs. gold's `SELECT name, date FROM battle`, and a ship-injury query that added a `SUM(...)` column gold didn't ask for. The underlying query logic was right; the agent just didn't limit itself to exactly what was asked.

## Explicitly out of scope for Phase 1
- **No evaluation harness.** `eval/metrics.py` and `eval/runner.py` exist as empty files but implement nothing — no Execution Accuracy, no Exact Match, no difficulty-bucketed scoring, no batch runner across a split.
- **No run logging.** There's no `logs/` output yet capturing per-question LLM/tool/guardrail events, despite the manual calling for it.
- **No prompt iteration.** Only `prompt_v1.md` exists; nothing has been learned yet about where it under- or over-specifies.
- **Guardrails don't cover complexity bounds or a real timeout** — see the notes on `executor.py` and `guardrails.py` above.

## Suggested next steps (Phase 2 candidates)
- Build `eval/metrics.py` (EX via row-set/multiset comparison, EM via the official `taoyds/spider` scripts) and `eval/runner.py` (batch over the validation split, write one JSON log per question to `logs/`, aggregate to `results/`) — this should absorb/replace the ad hoc `scripts/phase_1_test.py` + `scripts/sql_result_scorer.py` path once it exists.
- Investigate the 5/10 `no_sql` turn-limit hits first — an agent that doesn't submit an answer scores 0 regardless of SQL quality, so this is likely the highest-leverage fix available before touching prompt SQL-writing guidance at all. Start with `prompt_v2`: make calling `submit_final_sql` explicit rather than inferred.
- Tighten column-selection guidance in the prompt (`SELECT` only what's asked) to address the `column_count_mismatch` pattern.
- Replace the lock-wait `timeout` in `execute_query` with an actual query execution timeout.
- Re-run `analysis_v1.ipynb` end to end now that the message-shape bug is fixed, and this time record pass/fail against gold SQL per question instead of eyeballing one at a time.
- Widen the ad hoc sample (more `db_id`s, more questions per db) before drawing conclusions from accuracy — 10 questions from 2 databases is too small to trust as anything but a directional signal.

