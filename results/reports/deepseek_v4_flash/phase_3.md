
# Phase 3 (DeepSeek): Input/output guardrails, schema-column validation, prompt v3

## Goal
Same Phase 3 code as the Anthropic run (see `results/reports/anthropic_sonnet_4_6/phase_3.md` for the guardrail/prompt work itself: split input/SQL/output guardrails, column-level schema validation, `recursion_limit` fix, `prompt_v3`). This report is that same code evaluated against `deepseek-v4-flash` instead of Claude, at a larger sample size.

## What's different from the Anthropic run
- No Phase 3 code changed between providers — `input_guardrails.py`, `output_guardrails.py`, `sql_guardrails.py`, `constants.py`, `prompt_v3.md` are identical.
- Model provider switched to `deepseek-v4-flash`, motivated by the rising per-token cost of Claude on larger eval runs (see `README.md` Phase 3 note).
- Sample size increased from the Anthropic ad hoc runs (10q/2db, later 50q/10db) to 99 questions across 20 `db_id`s (seed 42, validation split).

## Results (`results/deepseek_v4_flash/phase_3_result.json`)

| | Anthropic phase 3 (50q / 10db) | DeepSeek phase 3 (99q / 20db) |
|---|---|---|
| Accuracy | 76% (38/50) | 75.8% (75/99) |
| `match` | 38 | 75 |
| `value_mismatch` | 3 | 13 |
| `row_count_mismatch` | 4 | 5 |
| `column_count_mismatch` | 4 | 1 |
| `no_sql` (turn-limit) | 1 | 5 |

Accuracy on DeepSeek lands within 1 point of the Claude run despite the much cheaper model, on roughly double the sample size — the `MODEL_PROVIDER` abstraction in `agent_builder_factory.py`/`config.py` required no Phase 3 code changes to swap providers.

## Explicitly out of scope
- No ablation isolating the provider swap from the sample-size increase.
- No Exact Match (EM) scoring yet — `eval/metrics.py`, `eval/runner.py`, `eval/exact_match.py` are still empty stubs at this point.
