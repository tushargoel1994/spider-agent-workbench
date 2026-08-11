# NOTICE — vendored code

`process_sql.py` and `evaluation.py` in this folder are copied, unmodified,
from the official Spider evaluation scripts. Per `CLAUDE.md`'s "reuse, don't
reimplement" rule for Exact Match / hardness scoring, this project uses the
original research team's own scripts rather than re-deriving their SQL
clause-matching and hardness rules.

- **Source repository**: https://github.com/taoyds/spider
- **License**: Apache License 2.0, Copyright 2024 XLANG NLP Lab (see
  https://github.com/taoyds/spider/blob/master/LICENSE for the full text).
- **Copied from commit**:
  - `evaluation.py` — `cccfe7bc99c4f5b7229890bbff75bfed50f2b008` (2020-05-27,
    "revert back to not including join cols")
  - `process_sql.py` — `4d065ee5afe5bb6fc8e73e28d371b7fccef0d6ef` (2020-04-02,
    "updated to fit python 3")
  - (both are each file's most recent commit on the `master` branch as of
    2026-08-05, the date these files were vendored into this project)
- **Modifications**: none. Both files are byte-for-byte copies of the
  upstream source. Do not edit them in place — if a bug or upstream change
  needs picking up, re-copy the file from the source repository instead.

## Why these files can't just be imported directly

`evaluation.py` contains a bare `from process_sql import tokenize, get_schema,
get_tables_with_alias, Schema, get_sql` — written assuming both files sit
next to each other as top-level scripts, not as part of a Python package.
Since these files are not modified in place, `src/spider_agent_workbench/eval/exact_match.py`
(this project's own adapter code, not vendored) works around this by
registering this package's real `process_sql` module under the bare name
`"process_sql"` in `sys.modules` *before* importing `evaluation`, so
`evaluation.py`'s import line resolves against it. See the comment at the top
of `exact_match.py` for the exact mechanism.

## Runtime dependency this vendored code introduces

`process_sql.py` calls `nltk.word_tokenize`, which needs the `punkt`/
`punkt_tab` tokenizer data files (not just the `nltk` pip package) to be
present. `exact_match.py` checks for this data and downloads it on first use
if missing (requires network access once); see `_ensure_nltk_data()` there.
