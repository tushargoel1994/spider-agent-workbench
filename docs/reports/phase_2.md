
# Phase 2: Harden guardrails, iterate the prompt

## Goal
Attack Phase 1's two named failure patterns — the agent burning all 10 turns without ever calling `submit_final_sql` (5/10 of the sample), and the agent over-selecting columns despite correct query logic (2/10) — without touching the tool set or the executor. Phase 2's changes are confined to two places: `guardrails.py` (rewritten to use `sqlglot` instead of regex, plus two new complexity checks) and a new `prompt_v2.md` (structured, with an explicit method and explicit numeric constraints). `prompt_v1.md` is left untouched per the "never edit a prompt in place" rule.

## Scope decisions
- **Guardrails moved from regex-over-text to AST-based checks.** Phase 1's `check_read_only` and `check_schema_tables` matched keywords/table names against the raw SQL string. Phase 2 tokenizes/parses with `sqlglot` instead, closing a real false-positive hole (a string literal like `'please delete this update'` no longer trips the `DELETE` keyword check) and making table-reference extraction robust to quoting.
- **Two new guardrail checks, previously deferred.** Phase 1 explicitly called out "no join/subquery complexity bounds" as out of scope. Phase 2 adds `check_num_joins` (max 5 joins) and `check_subquery_depth` (max 3 nesting levels, CTEs scored as independent roots so `WITH` isn't penalized by itself).
- **Prompt v2 is deliberately explicit about the same numbers the code enforces.** Rather than let the agent discover limits only when a guardrail rejects a query mid-loop, `prompt_v2.md`'s `<Constraints>` block states the join cap, the subquery-depth cap, and the turn budget up front, in the numbers that match `guardrails.py` and `agent.py`.
- **Still no evaluation harness.** `eval/metrics.py` / `eval/runner.py` remain empty; `scripts/phase_2_test.py` is `phase_1_test.py` re-pointed at `prompt_v2` with the same seed and sample shape, not a step toward the real batch runner.

## Components changed

| File | What changed |
|---|---|
| **`guardrails.py`** | - `check_read_only` rewritten on `sqlglot.tokenize`: string-literal tokens are skipped before keyword matching, so forbidden words inside quoted data no longer false-positive<br>- `check_schema_tables` rewritten on `sqlglot.parse_one` + `exp.Table` extraction instead of a `FROM`/`JOIN` regex<br>- New `check_num_joins` — counts `exp.Join` nodes via the parsed AST, rejects above `MAX_TABLE_JOINS = 5`<br>- New `check_subquery_depth` — recursive depth calc over `exp.Select` nodes, rejects above `MAX_SUBQUERY_DEPTH = 3`; CTE bodies are scored as independent roots so a flat `WITH x AS (...) SELECT * FROM x` isn't penalized, but a CTE that itself nests too deep still is<br>- All four keyword/parse-based checks let `sqlglot` parse failures fall through as `ok=True` — malformed SQL isn't this layer's job to catch, sqlite's own error is more informative<br>- `validate_sql` now short-circuits through 5 checks in order: `check_read_only` → `check_query_length` → `check_num_joins` → `check_subquery_depth` → `check_schema_tables` |
| **`tests/test_guardrails.py`** | - 208 lines, new — every Phase 1 guardrail plus both new ones get direct unit coverage, including edge cases the implementation explicitly has to get right: sibling subqueries not summing into a false rejection, CTE definitions not counted by themselves, malformed SQL handled gracefully, forbidden keywords ignored inside string literals and identifiers (`updated_at` is not `UPDATE`) |
| **`tests/test_executor.py`, `test_schema.py`, `test_tools.py`** | - New; Phase 1 had zero test coverage outside guardrails-adjacent code. Paired with `tests/conftest.py`'s `db_dir`/`db_id` fixtures (a throwaway seeded sqlite db) so these run without the gitignored `data/` dataset |
| **`prompts/prompt_v2.md`** | - New, structured prompt (see comparison below); `prompt_v1.md` untouched |
| **`agent.py`** | - `DEFAULT_PROMPT_VERSION` bumped `"prompt_v1"` → `"prompt_v2"` (one-line change) |
| **`scripts/phase_2_test.py`** | - `phase_1_test.py` re-pointed at `prompt_v2`, same `SAMPLE_SEED = 42`, same 2 `db_id`s × 5 questions (`course_teach`, `battle_death`) so the two ad hoc runs are directly comparable question-for-question. `NUM_WORKERS` dropped from 2 to 1 (this run is sequential, not threaded) |

## Prompt v2 vs Prompt v1

`prompt_v1.md` was one unstructured paragraph: role, a read-only instruction, and an output-format instruction, with no method and no explicit numbers. `prompt_v2.md` restructures this into six tagged sections:

| Section | Prompt v1 | Prompt v2 |
|---|---|---|
| Role | Implied ("helpful AI agent") | Explicit `<Role>`: "data analyst and expert SQL user" |
| Inputs | Not named | Explicit `<Inputs>`: `db_name`, `Question Statement` |
| Method | None — the agent had to infer an approach | Explicit 6-step `<Method>` (below) |
| Constraints | One sentence ("don't modify the database") | Explicit `<Constraints>`: read-only, non-null, no restricted keywords, ≤10 AI calls, ≤5 joins, ≤3 subquery levels, "keep it simple to read" |
| Output | "single SQL query...no other information" | Same intent, restated under an explicit `<Output>` tag |

**The `<Method>` section is where tool use becomes explicit rather than inferred**, and it maps directly onto the five tools in `tools.py`:

| Method step | Text in prompt_v2.md | Tool(s) it drives |
|---|---|---|
| 1 | "First use tools to check if the database exist, then list all tables...and then get schema for all the tables" | `list_tables`, `describe_table` |
| 2 | "Identify the columns that are being talked about...understand relationships between different columns (Foreign key relationship)" | Reasoning over `describe_table` output (`CREATE TABLE` text carries FK declarations) |
| 3 | "Separate the columns in multiple categories: select, filter, group by, Order by, limit etc." | Reasoning only — this step is the direct countermeasure for Phase 1's `column_count_mismatch` pattern |
| 4 | "If the answer is distributed across multiple tables, explore how joins can help you..." | `describe_table` (re-checked for join keys), reasoning |
| 5 | "First focus on identifying columns that will...return the value...then learn what filter or group by...operations are to be done" | Reasoning — reinforces step 3's column discipline |
| 6 | "Execute the...query with limited number of rows first to ensure your query is working" | `run_query` (or `sample_rows`) before finalizing |

**What prompt_v2 does *not* do**, despite Phase 1's report naming it as the top suggested fix: it never names `submit_final_sql` by name or says "call it when you're done." The `<Output>` tag only describes the expected final text, not the mechanism for ending the loop. The agent still has to infer, from the tool's own docstring, that calling that specific tool is how the loop terminates — this is discussed further under "What didn't move" below.

## Ad hoc accuracy sample (`results/phase_2_result.json`)

Run via `scripts/phase_2_test.py` against `prompt_v2`, same seed (`42`) and same 10 questions (`course_teach`, `battle_death`) as Phase 1's sample, so the two results are directly comparable:

| | Phase 1 (`prompt_v1`) | Phase 2 (`prompt_v2`) |
|---|---|---|
| Accuracy | 3/10 (30%) | **5/10 (50%)** |
| `match` | 3 | 5 |
| `no_sql` (turn-limit hit) | 5 | 3 |
| `column_count_mismatch` | 2 | 2 |
| `course_teach` | 2/5 | 3/5 |
| `battle_death` | 1/5 | 2/5 |

**One important caveat on attributing this gain**: `phase_1_result.json` was generated on 2026-07-28, before the guardrails rewrite landed (2026-07-29, commit `7c72283`). `phase_2_result.json` runs against both `prompt_v2` *and* the hardened `guardrails.py` at once — `scripts/phase_2_test.py` only ever swept the prompt version, not guardrails in isolation. So this comparison shows "Phase 2 as a whole beats Phase 1 as a whole," not "the prompt change alone is worth +20 points." Isolating the two would need a `prompt_v1` + new-guardrails run, which wasn't done.

### What moved
- **`no_sql` dropped from 5/10 to 3/10.** This is the biggest visible shift, and lines up with Phase 1's hypothesis that a minimal prompt was the main cause: an explicit 6-step `<Method>` that ends in "execute with limited rows to confirm it works" appears to give the model a concrete stopping checkpoint it didn't reliably reach with `prompt_v1`'s single paragraph — even without ever naming `submit_final_sql` directly.
- **`match` rose from 3/10 to 5/10**, consistent with fewer turn-limit failures leaving more room for a correct answer to actually get submitted.

### What didn't move
- **`column_count_mismatch` stayed at 2/10 — the same failure mode, not obviously the same two questions fixed and two new ones appearing.** Despite Method steps 3 and 5 explicitly telling the agent to separate "select" columns from filter/group/order columns and to nail down the return columns first, this didn't eliminate over-selection on this sample. Explicit instruction alone wasn't sufficient here; the underlying tendency to add an extra column the gold query didn't ask for persisted.
- **The two new complexity guardrails (`check_num_joins`, `check_subquery_depth`) don't show up in this sample's aggregate stats at all** — none of the 10 gold queries in `course_teach`/`battle_death` need more than 5 joins or 3 subquery levels, so this slice can't demonstrate whether the new checks (or the matching prompt constraints) change agent behavior. The tokenizer-based `check_read_only` rewrite and the AST-based `check_schema_tables` are the guardrail changes most plausibly exercised here, and even those aren't visible in the aggregate `status` field — a guardrail rejection surfaces as tool output mid-loop, which the agent can retry past, not as a distinct terminal status in `sql_result_scorer`.
- **3/10 questions still hit the turn limit.** The dominant failure mode from Phase 1 is reduced, not solved.

## Explicitly out of scope for Phase 2
- **No evaluation harness, still.** `eval/metrics.py` and `eval/runner.py` remain empty stubs; `scripts/phase_2_test.py` is the same ad hoc pattern as Phase 1's script, not a step toward it.
- **No ablation isolating prompt vs. guardrails.** As noted above, the 30%→50% delta can't be cleanly attributed to either change in isolation.
- **`submit_final_sql` is still not named explicitly in the prompt**, despite being Phase 1's top suggested fix — the improvement in `no_sql` came from a more structured method, not from that specific instruction.
- **No real query execution timeout.** `executor.py`'s `timeout` param still only bounds lock-wait time in `sqlite3.connect`, not runtime of an expensive query — unchanged from Phase 1.
- **Sample size unchanged and still tiny.** Same 10 questions / 2 `db_id`s as Phase 1 — enough to compare two prompt+guardrail configurations directionally, not enough to trust the exact percentages.
- **No Exact Match (EM).** Only the EX-style scorer from Phase 1 is in use.

## Suggested next steps (Phase 3 candidates)
- Run `prompt_v1` once more against the *current* (Phase 2) `guardrails.py` to isolate how much of the 30%→50% gain is attributable to the prompt rewrite alone versus the guardrail rewrite alone.
- Explicitly instruct the prompt to call `submit_final_sql` by name once there's a sample large enough to tell whether that (as opposed to the general Method restructuring) is what's still capping `no_sql` at 3/10.
- Investigate the `column_count_mismatch` cases directly (they're unchanged from Phase 1) — the current Method steps 3/5 evidently aren't sufficient; may need concrete few-shot examples of over-selection vs. correct selection rather than another instruction restatement.
- Build a sample large/varied enough to actually exercise `check_num_joins` and `check_subquery_depth` before drawing any conclusion about whether those two guardrails help, hurt (by blocking a legitimately-needed complex query), or are neutral.
- Finally build `eval/metrics.py` + `eval/runner.py` so prompt/guardrail comparisons stop depending on hand-run scripts with a fixed 10-question sample.