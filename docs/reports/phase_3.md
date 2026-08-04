
# Phase 3: Input/output guardrails, schema-column validation, prompt v3

## Goal
Extend Phase 2's SQL-level guardrails to cover the full request lifecycle (question in, SQL out), close the remaining schema gap (columns, not just tables), fix a turn-budget bug, and give the agent a more structured prompt for simple vs. multi-table/subquery questions.

## Scope decisions
- **Guardrails split by pipeline stage**, not just by check type: `input_guardrails.py` gates the question before the agent loop starts, `sql_guardrails.py` (renamed from `guardrails.py`) still gates every tool call, and a new `output_guardrails.py` re-validates whatever the agent finally submits.
- **Schema validation extended from tables to columns.** Phase 2 only checked that referenced tables exist; a hallucinated column on a real table still passed.
- **Query-length cap tightened from 2000 to 300 characters**, enforced in both `constants.py` and `prompt_v3`'s stated constraints.

## Components changed

| File | What changed |
|---|---|
| **`guardrails/input_guardrails.py`** | New — `check_question_max_length` (200 chars), `check_for_prompt_injection` (keyword screen for off-topic/injection phrases like "ignore previous instructions"), `check_db_exist`; run via `run_input_guardrails` before the agent is invoked |
| **`guardrails/output_guardrails.py`** | New — `check_output_valid_sql` parses the agent's final SQL with `sqlglot`, runs it through `sql_guardrails.validate_sql`, then dry-run executes it (`max_rows=5`); catches anything that slipped through mid-loop guardrail checks but still ended up as the "final" answer |
| **`guardrails/sql_guardrails.py`** (renamed from `guardrails.py`) | New `check_schema_columns` — rejects columns not present on their table; qualified (`alias.col`) checked against that alias's table, unqualified checked against the union of all referenced tables' columns. `validate_sql` now chains 6 checks, ending in this one |
| **`schema.py`** | New `get_column_list(db_id, table_name)` — column names via `PRAGMA table_info`, backing the new column guardrail |
| **`agent.py`** | Wires in `run_input_guardrails`/`run_output_guardrails`; fixed `recursion_limit` — langgraph's ReAct graph costs 2 graph steps per LLM turn, so it was silently halving the agent's real turn budget. Now `max_turns * 2 + 1` |
| **`constants.py`** | New — centralizes `MAX_QUERY_CHARS` (300, down from 2000), `MAX_TABLE_JOINS`, `MAX_SUBQUERY_DEPTH`, `QUESTION_MAX_LENGTH`, `DEFAULT_MAX_TURNS` |
| **`prompts/prompt_v3.md`** | New — branches the method into a simple single-table path and a multi-table/subquery path, adds a step to verify a subquery's result before building on top of it, states the 300-char cap explicitly |
| **Tests** | `tests/guardrails/test_input_guardrail.py`, `test_output_guardrail.py` (new); `test_sql_guardrails.py` extended with `check_schema_columns` cases; `tests/agent_test.py` extended for the `recursion_limit` fix; `tests/test_schema.py` extended for `get_column_list` |

## Results (`results/phase_3_result.json`)

Same ad hoc 10-question sample as Phases 1–2 (`course_teach`, `battle_death`, seed `42`), run against `prompt_v3` + Phase 3 guardrails:

| | Phase 2 (`prompt_v2`) | Phase 3 (`prompt_v3`) |
|---|---|---|
| Accuracy | 5/10 (50%) | **7/10 (70%)** |
| `match` | 5 | 7 |
| `no_sql` (turn-limit hit) | 3 | 0 |
| `column_count_mismatch` | 2 | 1 |
| `row_count_mismatch` | 0 | 1 |
| `value_mismatch` | 0 | 1 |
| `course_teach` | 3/5 | 4/5 |
| `battle_death` | 2/5 | 3/5 |

**What moved:** `no_sql` dropped to zero — the `recursion_limit` fix (previously giving the agent half its intended turn budget) plausibly explains most of this, separate from the prompt/guardrail changes. `column_count_mismatch` also improved (2→1), the first movement on that failure mode since Phase 1.

**What didn't move / new noise:** `row_count_mismatch` and `value_mismatch` are new failure modes on this sample, not present in Phase 1 or 2 — with `no_sql` no longer masking them, previously-unseen near-miss logic errors are now visible. As in Phase 2, the gain can't be cleanly attributed between the prompt rewrite, the new guardrails, and the turn-budget fix; no ablation was run.

## Explicitly out of scope for Phase 3
- No ablation isolating the `recursion_limit` fix, the prompt rewrite, and the new guardrails from each other.
- No evaluation harness — `eval/metrics.py`/`eval/runner.py` still empty stubs; `scripts/phase_test.py` is still the same ad hoc, fixed-10-question pattern.
- No Exact Match (EM).
- Sample size unchanged (10 questions / 2 `db_id`s).
