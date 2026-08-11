
# Phase 4 (DeepSeek): Evaluation harness & hard-question focus, prompt v4

## Goal
Standard-question accuracy plateaued around 75-76% across Phases 2-3. Build a real batch evaluation harness (EX + EM, not just an ad hoc sample script), shift the eval focus to Spider's hard/extra-hard questions where headroom actually exists, then use per-failure-mode error analysis on that harder set to iterate `prompt_v3` -> `prompt_v4`.

## Components changed since Phase 3
| File | What changed |
|---|---|
| `eval/metrics.py` | New — aggregates a batch run into status buckets: `column_count_mismatch`, `row_count_mismatch`, `value_mismatch`, `no_sql` |
| `eval/runner.py` | New — batch runner: runs agent + guardrails + EX/EM scoring over a question set with structured per-question logging |
| `eval/sql_features.py` | New — tags gold SQL with structural features (`has_join`, `has_group_by`, `has_subquery`, `has_set_op`) for breakdown-by-feature analysis |
| `eval/exact_match.py` + `eval/spider_official/` | New — EM scoring via the vendored official Spider eval scripts; also derives the official hardness bucket (easy/medium/hard/extra) from gold SQL alone |
| `scripts/select_questions/select_hard_questions.py` | New — freezes a 150-question hard/extra-hard pool (30 dbs x 5) so prompt versions are compared on the same fixed set |
| `scripts/run_evals/run_full_eval.py`, `run_eval_custom_file.py` | New — batch eval entrypoints (full pool, or a specific saved failure subset for targeted re-testing) |
| `prompts/prompt_v4.md` | Rewrite of `prompt_v3` — adds an "Important" section (only show requested columns) and a 9-case "Notes" section written from Phase 3 failure analysis (string over/under-matching, junction-table cardinality, union/intersect wording, DISTINCT misuse, relationship direction, set-operator construction, superlative/pivot handling, never hardcoding a looked-up id) |
| Tool-call budget | Raised from 7 to 10 calls (per `README.md`), giving `prompt_v4`'s extra per-case verification steps room to run before the turn limit hits |

## Results

**Hard/extra-hard pool (150q, 30 dbs) — `data/evals_testing/output_files/report_hard_questions_v{3,4}_run_1.json`**

| | prompt_v3 | prompt_v4 |
|---|---|---|
| EX accuracy | 55.3% (83/150) | 79.3% (119/150) |
| EM accuracy | 24.0% (36/150) | 32.7% (49/150) |
| `no_sql` (turn-limit) | 34 | 5 |
| `column_count_mismatch` | 11 | 2 |
| `row_count_mismatch` | 12 | 10 |
| `value_mismatch` | 10 | 14 |
| hard bucket | 45/75 | 65/75 |
| extra bucket | 38/75 | 54/75 |

**Standard sample (same 99q/20db as Phase 3) — `results/deepseek_v4_flash/phase_4_result.json`**
- `prompt_v4` accuracy: 75.8% (75/99) — identical to Phase 3's `prompt_v3` result on this sample.

**What moved:** `no_sql` collapsed from 34 to 5 — the larger call budget plus `prompt_v4`'s explicit "stop exploring and submit your best query" instruction mostly eliminated turn-limit failures. `column_count_mismatch` dropped sharply (11 -> 2), tracking the new "only show requested columns" guidance. Both difficulty buckets improved by roughly the same margin (+20pp hard, +21pp extra), so no single Note case is skewing gains toward one difficulty level.

**What didn't move / new noise:** `value_mismatch` rose slightly (10 -> 14) — with `no_sql`/`column_count_mismatch` no longer masking most failures, some questions that previously hit the turn limit now produce a fuller but still logically-wrong query. Standard-sample accuracy is unchanged from Phase 3, so the hard-question gains didn't come at the cost of regressing the easier questions.

## Explicitly out of scope
- No ablation isolating individual `prompt_v4` Notes cases from each other or from the call-budget increase.
- EM remains well below EX (32.7% vs 79.3%) on the hard pool — clause-level exact match is a much stricter bar than result-set match; not investigated further this phase.
