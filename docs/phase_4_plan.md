# Phase 4 Plan: Evaluation Harness & Batch Scoring

## Who this is for

You've just joined software engineering and know basic Python — variables, functions, `if`/`for`, lists, dictionaries. You haven't worked with AI agents, LLMs, or SQL parsing libraries before, and that's fine — every new idea below is explained in plain language before any code shows up. Read this document top to bottom once before writing anything. Then come back to Milestone 1 and start.

If a term confuses you and this document doesn't explain it, check `docs/spider_agent_manual.md` — it's a longer, slower-paced background document for this whole project.

## Ground rules — read these before you start

These apply to every milestone below, so they're stated once, up front, instead of repeated seven times.

- **Never edit, rename, or delete `scripts/test_phase.py`.** It's the tool this project has used since Phase 1 to check "did this phase's changes make the agent better or worse?" — it always runs the same fixed 10-question sample, so results stay comparable across phases. You will see logic inside it that looks a lot like what you're about to build. **Copy the *idea* / the *pattern* into a new file. Do not move code out of `test_phase.py`, and do not import from it.** Treat it as a read-only reference, like a textbook example.
- **Write a failing test before you write the real function.** For every new function below: create the test file, write one or two small test cases calling a function that doesn't exist yet, run `uv run pytest <that test file> -q` and confirm it fails (it should fail because the function is missing — that's the "correct" kind of failure), and only then write the actual function until the test passes. This is how the whole project has been built so far (see `CLAUDE.md`).
- **All new code for this phase goes in the `eval/` folder** (`src/spider_agent_workbench/eval/`), except one small change to `agent.py` in Milestone 5. Don't scatter new logic into random scripts.
- **Never run anything against the held-out test split.** This project only ever evaluates against the "validation" split until the very last phase of the whole project. If you're not sure which split a piece of code is using, stop and check — `loaders.py`'s `load_split("validation")` is the only one you should call.
- **One milestone at a time.** Finish a milestone, get its tests green, before starting the next one. Don't jump ahead — later milestones assume earlier ones already work.

## What Phase 4 is, in plain terms

Phases 1 through 3 built an agent that reads a question, looks at a database, and writes SQL to answer it. Every phase so far has been checked by hand, on the same fixed 10 questions, using `scripts/test_phase.py`. That's fine for a quick sanity check, but it can't tell you *where* the agent is weak — 10 questions is too small a sample to trust, and there's no breakdown by question difficulty or SQL complexity.

Phase 4 does not change the agent. It builds better ways to **measure** it:

1. A way to run the agent over hundreds of questions instead of 10, reusably (Milestones 1-2).
2. A second correctness score, alongside the one that already exists (Milestone 3).
3. A breakdown of accuracy by "how hard was this question" and "what SQL features did it need" (Milestones 3-4).
4. Some basic performance numbers — how long each question takes, how many tokens it costs (Milestone 5).
5. One real, large run producing real numbers, and a written report (Milestones 6-7).

## Two ideas you need before you start

### Idea 1: two ways to check if the SQL was "correct"

There's already a scoring function in this project: `score_query()` in `src/spider_agent_workbench/eval/sql_result_scorer.py`. It works like this: run the agent's SQL, run the known-correct ("gold") SQL, compare the *rows they return*. If the rows match, the score is 1 (correct). This is called **Execution Accuracy**, or **EX** for short.

EX has a weakness: on a small database, a wrong query can sometimes return the right rows by accident. So Spider (the research project this whole dataset comes from) also defines a second score called **Exact Match**, or **EM**: instead of comparing the *results*, it compares the *structure* of the SQL — does the SELECT list match, does the FROM match, does the WHERE match, and so on. EM has its own, opposite weakness: two queries that are structured differently but logically equivalent (e.g. one uses `INTERSECT`, the other uses a nested `WHERE ... IN (...)`) will be marked as *not* matching under EM, even though they're both correct.

Because each metric has a blind spot, Phase 4 reports both, side by side. Milestone 3 below adds EM — EX already exists.

### Idea 2: "how hard was the question, and what did it need?"

Every Spider question secretly has a **difficulty** — easy, medium, hard, or extra hard — based on how complicated its SQL is (how many tables, aggregations, nested queries, etc.). This isn't a column you can read out of the dataset; it has to be *computed* from the SQL by a specific set of rules that the original Spider research team wrote. You will reuse their code for this in Milestone 3, rather than writing the rules yourself — it's exactly the kind of thing `CLAUDE.md` means when it says "reuse, don't reimplement."

Separately, Milestone 4 tags each question with which SQL features it needed — does it require a JOIN, a GROUP BY, a subquery, a set operation like UNION? This is simpler and you'll write it yourself.

Once both exist, you can turn "62% accuracy" into something actually useful, like "92% accuracy on easy questions, but only 20% on questions that need a subquery" — which tells you exactly what to work on next (that's Phase 5, not this one).

## What already exists — study this before writing anything

Open `scripts/test_phase.py` and read it end to end before starting Milestone 1. Do not change it. It already contains a rough draft of almost everything you're about to build:

| Function in `test_phase.py` | What it does | What you'll build instead |
|---|---|---|
| `select_sample()` | Picks a fixed random set of questions | Milestone 6 — you'll pick a *bigger* sample, in a new script |
| `chunk_for_workers()` + `run_worker()` | Splits questions across threads, runs the agent, scores each answer | Milestone 2 — you'll write a reusable version of this in `runner.py` |
| `build_summary()` | Counts up scores, overall and by status/db | Milestone 1 — you'll write a reusable version of this in `metrics.py` |

Every milestone below tells you exactly which lines to look at for inspiration. You are allowed to copy small snippets of logic (e.g. "how do I split a list across N workers") — what you must not do is import from `test_phase.py` or change it.

---

## Milestone 1 — `eval/metrics.py`: counting up scores

**Goal:** write one small, fully-tested function with no dependencies on databases, agents, or the network — the safest possible place to start.

**What "metrics" means here:** a metric is just a number that summarizes how well the agent did. "62% accuracy" is a metric. "5 out of 10 easy questions correct" is a metric. This milestone writes the code that turns a big list of individual question results into those summary numbers.

**Look at (don't touch):** `build_summary()` in `scripts/test_phase.py`, around line 122. It loops over a list of result dictionaries and counts things up by `status` and by `db_id`.

**New file:** `src/spider_agent_workbench/eval/metrics.py` (currently an empty file — write into it directly).

**Function to write:**

```
summarize(records, group_by)
```

| | Type | Meaning |
|---|---|---|
| **Input** `records` | `list[dict]` | One dict per question. Each dict must at least have a `"score"` key (`1` or `0`), plus whatever fields you list in `group_by`. |
| **Input** `group_by` | `list[str]` | Field names to break results down by, e.g. `["status", "db_id"]`. |
| **Output** | `dict` | See shape below. |

Output shape (example, for `group_by=["status", "db_id"]`):

```python
{
    "total_questions": 10,
    "total_score": 7,
    "accuracy": 0.7,
    "by_status": {
        "match": {"score": 7, "total": 7},
        "value_mismatch": {"score": 0, "total": 3},
    },
    "by_db_id": {
        "course_teach": {"score": 4, "total": 5},
        "battle_death": {"score": 3, "total": 5},
    },
}
```

**Pseudocode:**

```
function summarize(records, group_by):
    total_questions = length of records
    total_score = sum of record["score"] for every record in records
    accuracy = total_score / total_questions   # but see precaution below!

    result = {
        "total_questions": total_questions,
        "total_score": total_score,
        "accuracy": accuracy,
    }

    for each field_name in group_by:
        groups = {}   # empty dict

        for each record in records:
            key = record[field_name]
            if key is not already in groups:
                groups[key] = {"score": 0, "total": 0}
            groups[key]["score"] = groups[key]["score"] + record["score"]
            groups[key]["total"] = groups[key]["total"] + 1

        result["by_" + field_name] = groups

    return result
```

**Precautions:**

- If `records` is an empty list, `total_questions / 0` would crash the program. Check for this and return `accuracy = 0.0` instead of dividing.
- Don't modify the `records` list or the dicts inside it — just read from them. A function that quietly changes its input is a common source of confusing bugs later.
- `group_by` defaults to `["status", "db_id"]` if the caller doesn't pass anything — that matches what `test_phase.py`'s `build_summary()` already reports, so nothing downstream breaks if you don't specify it.

**Test file to write first:** `tests/eval/test_metrics.py` (new folder if it doesn't exist yet — check, `tests/eval/` already exists from an earlier phase). No database, no agent — just hand-type a small list:

```python
def test_summarize_basic():
    records = [
        {"db_id": "school", "status": "match", "score": 1},
        {"db_id": "school", "status": "value_mismatch", "score": 0},
        {"db_id": "farm", "status": "match", "score": 1},
    ]

    result = summarize(records, group_by=["status", "db_id"])

    assert result["total_questions"] == 3
    assert result["total_score"] == 2
    assert result["by_db_id"]["school"] == {"score": 1, "total": 2}
```

Also write a test for the empty-list case (`summarize([], group_by=["status"])` should not crash and should return `accuracy == 0.0`).

**Done when:** `uv run pytest tests/eval/test_metrics.py -q` is green.

---

## Milestone 2 — `eval/runner.py`: running the agent over many questions

**Goal:** a reusable function that runs the agent on a batch of questions and collects the results — without being hardwired to "10 questions" the way `test_phase.py` is.

**New concept — what's a "thread"?** Calling the LLM for one question takes a few seconds. If you had 200 questions and ran them one after another, you'd wait a long time. A `ThreadPoolExecutor` (from Python's built-in `concurrent.futures` module) lets you run several questions *at the same time*, using multiple "worker" threads. `test_phase.py` already does this — you're going to reuse the same pattern.

**New concept — "dependency injection" (don't worry, it's simpler than it sounds).** Your new function needs to call the real agent and the real scorer when actually evaluating. But when you *test* this function, you don't want to make real network calls to Claude — that's slow, costs money, and gives a different answer every time. The fix: let the caller *pass in* which "agent-builder" function and which "scorer" function to use, with sensible defaults. In your tests, you pass in fake ones. In real use, you don't pass anything and it uses the real ones.

**Look at (don't touch):** `chunk_for_workers()` and `run_worker()` in `scripts/test_phase.py`, around lines 66-119.

**New file:** `src/spider_agent_workbench/eval/runner.py` (currently empty).

**Function to write:**

```
run_eval(examples, prompt_version, num_workers, agent_factory, score_fn, log_path)
```

| | Type | Meaning |
|---|---|---|
| **Input** `examples` | `dict[str, list[SpiderExample]]` | Questions grouped by `db_id` — same shape `loaders.group_by_db()` already returns. |
| **Input** `prompt_version` | `str` | e.g. `"prompt_v3"` — which prompt file the agent should use. |
| **Input** `num_workers` | `int`, default `2` | How many threads to run in parallel. |
| **Input** `agent_factory` | function, no arguments → agent object, default `None` | If `None`, build the real agent. Tests pass a fake one. |
| **Input** `score_fn` | function `(db_id, predicted_sql, gold_sql, agent_notes) → ScoreResult`, default `None` | If `None`, use the real `score_query`. Tests pass a fake one. |
| **Input** `log_path` | `Path` or `None`, default `None` | If given, every result is also appended to this file (see "structured logging" below). |
| **Output** | `list[dict]` | One dict per question — same shape as the records `test_phase.py` already builds (see below). |

Each output record should look like this (same fields `test_phase.py`'s `run_worker()` already builds):

```python
{
    "db_id": "course_teach",
    "question": "How many courses are there?",
    "predicted_sql": "SELECT COUNT(*) FROM course",
    "gold_sql": "SELECT count(*) FROM course",
    "score": 1,
    "status": "match",
    "detail": None,
    "turns": 2,
    "hit_turn_limit": False,
    "notes": None,
}
```

**Pseudocode:**

```
function run_eval(examples, prompt_version, num_workers=2, agent_factory=None, score_fn=None, log_path=None):

    if agent_factory is None:
        agent_factory = a function that calls agent_workbench.build_agent(prompt_version=prompt_version)
    if score_fn is None:
        score_fn = score_query   # imported from sql_result_scorer.py

    db_ids = list of keys in examples
    chunks = split db_ids into num_workers roughly-equal groups   # copy this idea from chunk_for_workers()

    all_records = []
    create a ThreadPoolExecutor with num_workers threads:
        for each chunk of db_ids:
            submit a task: run_one_chunk(chunk, examples, agent_factory, score_fn, log_path)
        wait for every task to finish, and extend all_records with each task's result

    return all_records


function run_one_chunk(db_ids, examples, agent_factory, score_fn, log_path):
    agent = agent_factory()   # one agent instance per worker thread
    records = []

    for each db_id in db_ids:
        for each example in examples[db_id]:
            answer = agent_workbench.answer_question(db_id, example.question, agent)
            result = score_fn(db_id, answer.sql, example.gold_sql, agent_notes=answer.notes)

            record = {
                "db_id": db_id,
                "question": example.question,
                "predicted_sql": answer.sql,
                "gold_sql": example.gold_sql,
                "score": result.score,
                "status": result.status,
                "detail": result.detail,
                "turns": answer.turns,
                "hit_turn_limit": answer.hit_turn_limit,
                "notes": answer.notes,
            }

            if log_path is not None:
                append_json_line(log_path, record)   # see below

            records.append(record)

    return records
```

**Structured logging — the "add a per-question log file" part of Phase 4.** `README.md` calls for "structured per-question run logging" — meaning, as each question finishes, save its full result as one line of JSON text in a log file, so you can look back later at exactly what happened on question #147 without re-running anything. This format (one JSON object per line) is called **JSONL**. Write a small helper:

```
function append_json_line(path, record):
    convert record to a JSON string
    open the file at path in "append" mode
    write the JSON string followed by a newline character
    close the file
```

**Precautions:**

- Multiple worker threads will call `append_json_line` at the same time. Two threads writing to the same file at the same moment can interleave and corrupt a line. Protect the file write with a `threading.Lock()` — look up how `with lock:` works, it's a few lines.
- Do **not** call the real Claude API inside your tests for this function. Always pass a fake `agent_factory`/`score_fn` in tests (see below).
- If `num_workers` is larger than the number of `db_id`s, some threads will simply get an empty chunk — that's fine, just don't crash.

**Test file to write first:** `tests/eval/test_runner.py`. Build fake stand-ins instead of the real agent and scorer:

```python
class FakeAgent:
    pass  # run_eval never actually calls methods on this in the fake path — see below

def fake_answer_question(db_id, question, agent):
    return AgentAnswer(db_id=db_id, question=question, sql="SELECT 1", turns=1)

def fake_score_fn(db_id, predicted_sql, gold_sql, agent_notes=None):
    return ScoreResult(score=1, status="match")
```

You will likely need to also fake `agent_workbench.answer_question` itself (not just `agent_factory`), since `run_eval`/`run_one_chunk` calls it directly — the simplest way is to make `agent_factory` and the call to `answer_question` both injectable, or to use `pytest`'s `monkeypatch` fixture to replace `agent_workbench.answer_question` for the duration of one test. Ask a teammate or check `tests/agent_test.py` for an existing example of faking agent behavior in this codebase before deciding which approach to use.

Assert that:
- `run_eval(...)` returns the right *number* of records (matching how many questions were in `examples`).
- Each record has the fields listed above.
- If you pass a `log_path` pointing at a file inside `tmp_path` (a pytest built-in temporary directory), that file exists afterward and has one line per record.

**Done when:** `uv run pytest tests/eval/test_runner.py -q` is green, and it runs in well under a second (proof that it isn't making real network calls).

---

## Milestone 3 — Exact Match (EM) and difficulty

**Goal:** add the second correctness score (EM) and the difficulty label (easy/medium/hard/extra), by reusing code from the original Spider research team instead of writing the matching rules yourself.

This is the hardest milestone here. Give yourself more time for it than the others, and don't be surprised if a few things don't go exactly as described below — that's expected, see the warning in Step 1.

### Step 1 — find and read the source code (do this before writing anything)

Open `https://github.com/taoyds/spider` in a browser. You're looking for two files, most likely at the top level of the repository: one that parses a SQL string into a structured representation given a database schema (likely called `process_sql.py`), and one containing an `Evaluator`-type class with a "how hard is this SQL" method and a "do these two SQLs match" method (likely called `evaluation.py`).

**Warning:** the file names and function names above are what this project's documentation *expects* to find, based on general knowledge of this well-known repository — they were not confirmed by opening the repository while writing this plan. Before you write a single line of adapter code in Step 3, open the actual files on GitHub, read through their functions, and write down the *real* names and how to call them. If something here turns out to be wrong, that's fine — update your notes to match reality, not this document.

Also check the repository's license (usually a `LICENSE` file at the root) — `CLAUDE.md` for this project says to reuse the official evaluation scripts rather than reimplementing them, so make sure you understand the terms you're reusing them under.

### Step 2 — copy the files in ("vendoring")

"Vendoring" means copying someone else's source code directly into your own project, instead of installing it as a package (these scripts aren't published anywhere you can `uv add` them from).

1. Create a new folder: `src/spider_agent_workbench/eval/spider_official/`.
2. Copy the two files you found in Step 1 into it, **unmodified** — don't reformat them, don't rename functions, don't "clean them up." They're borrowed code, not code you own.
3. Add a file `NOTICE.md` in that same folder, noting: the URL you copied from, the date, and the license you found in Step 1. This is just good practice for tracking where borrowed code came from.

These two files are the *only* exception to this project's normal coding style rules (no comments, TDD, etc.) — leave them exactly as you found them.

### Step 3 — write your own small adapter

**New concept — "adapter":** the vendored code speaks its own language (its own function names, its own way of representing a parsed SQL query). Your project speaks a different language (`db_id`, plain SQL strings, `Path` objects). An adapter is a small piece of code whose only job is translating between the two, so the rest of your project never has to know the vendored code's internal details.

**New file:** `src/spider_agent_workbench/eval/exact_match.py`.

**What to write:**

```
class ExactMatchResult:
    score: int       # 0 or 1
    hardness: str    # one of "easy", "medium", "hard", "extra"
```

```
score_exact_match(db_id, predicted_sql, gold_sql, db_dir)
```

| | Type | Meaning |
|---|---|---|
| **Input** `db_id` | `str` | Which database, e.g. `"course_teach"`. |
| **Input** `predicted_sql` | `str` or `None` | What the agent submitted. |
| **Input** `gold_sql` | `str` | The known-correct SQL. |
| **Input** `db_dir` | `Path` | Same `db_dir` used everywhere else in this project (see `paths.DATABASES_DIR`). |
| **Output** | `ExactMatchResult` | `score` (0 or 1) and `hardness` (string). |

**Pseudocode** (the exact function names inside here are placeholders — replace them with whatever you found in Step 1):

```
function score_exact_match(db_id, predicted_sql, gold_sql, db_dir):
    sqlite_path = get_sqlite_path(db_id, db_dir)     # already exists in schema.py

    schema = build_schema_object(sqlite_path)         # from the vendored code — pass it
                                                        # data/spider/tables.json too, if it needs it

    gold_parsed = parse_sql(schema, gold_sql)          # from the vendored code
                                                        # do NOT wrap this in try/except — if gold
                                                        # SQL fails to parse, something is genuinely
                                                        # broken and you want to see the crash

    hardness = classify_hardness(gold_parsed)          # from the vendored code

    if predicted_sql is empty or None:
        return ExactMatchResult(score=0, hardness=hardness)

    try:
        predicted_parsed = parse_sql(schema, predicted_sql)
    except (any parsing error):
        return ExactMatchResult(score=0, hardness=hardness)

    matched = compare_exact_match(predicted_parsed, gold_parsed)   # from the vendored code
    score = 1 if matched else 0

    return ExactMatchResult(score=score, hardness=hardness)
```

**Precautions:**

- The vendored parser is stricter about SQL grammar than SQLite is. The agent's SQL might run fine in `executor.py` but fail to parse here. **This must not crash your whole evaluation run** — catch the parsing error for the *predicted* SQL specifically and score it as `0`, the same way `sql_result_scorer.py` already treats a rejected/broken query as a `0` instead of raising.
- Do **not** wrap the *gold* SQL parse in a try/except. If the known-correct SQL fails to parse, that's a bug in your data or your setup, not a wrong answer from the agent — you want that to fail loudly so you notice it, exactly like `sql_result_scorer.py::_score` already does for gold-SQL execution failures (read that function for the pattern).
- `data/spider/tables.json` already exists on disk (downloaded as part of the official Spider release, alongside the `.sqlite` files) — check whether the vendored code needs it before writing any code to generate it yourself.

**Test file to write first:** `tests/eval/test_exact_match.py`. Reuse the `db_dir`/`db_id` fixtures already defined in `tests/conftest.py` (don't write new fixtures — these already give you a tiny two-table SQLite database to test against). Start with the simplest cases:

```python
def test_identical_sql_is_exact_match(db_dir, db_id):
    result = score_exact_match(db_id, "SELECT COUNT(*) FROM students", "SELECT COUNT(*) FROM students", db_dir)
    assert result.score == 1

def test_garbage_sql_is_not_exact_match_and_does_not_crash(db_dir, db_id):
    result = score_exact_match(db_id, "not valid sql at all", "SELECT COUNT(*) FROM students", db_dir)
    assert result.score == 0

def test_missing_predicted_sql_is_not_exact_match(db_dir, db_id):
    result = score_exact_match(db_id, None, "SELECT COUNT(*) FROM students", db_dir)
    assert result.score == 0
```

Once those pass, add one case where the predicted SQL returns the same rows as gold but is structurally different (e.g. a `WHERE ... IN (...)` version of a query the gold answers with a JOIN) — this should score `0` under EM even though it would score `1` under EX. This proves your adapter is really checking structure, not results.

Do **not** try to write deep tests of the vendored files' internals — that code isn't yours to test. Your tests should only prove your adapter calls it correctly.

### Step 4 — connect it to the batch runner

Go back to `run_one_chunk` inside `eval/runner.py` (Milestone 2) and add two lines: call `score_exact_match(...)` alongside the existing `score_fn(...)` call, and add its `score` and `hardness` to the record dict as `"em_score"` and `"difficulty"`.

**Done when:** `uv run pytest tests/eval/test_exact_match.py -q` is green, and a record coming out of `run_eval()` now has both `"score"` (EX) and `"em_score"` (EM) filled in.

---

## Milestone 4 — tagging which SQL features a question needs

**Goal:** know not just "easy vs. hard" but *which specific things* the agent struggles with — JOINs? GROUP BY? subqueries? UNION/INTERSECT/EXCEPT?

**New concept — parsing SQL into a tree (AST).** To reliably detect "does this SQL contain a JOIN," you can't just search the text for the word "JOIN" — it might appear inside a quoted string value that has nothing to do with SQL syntax. Instead, you use a **parser** that turns the SQL text into a tree structure representing its real meaning (called an **AST**, "abstract syntax tree"), and then you look for specific shapes in that tree. This project already uses a library called `sqlglot` for exactly this, in `guardrails/sql_guardrails.py` — go read `check_num_joins()` and `check_subquery_depth()` in that file now; you're about to do the same kind of thing.

**New file:** `src/spider_agent_workbench/eval/sql_features.py`.

**Function to write:**

```
tag_features(sql)
```

| | Type | Meaning |
|---|---|---|
| **Input** `sql` | `str` | A SQL query — you'll call this with the **gold** SQL, not the agent's SQL (explained below). |
| **Output** | `dict[str, bool]` | `{"has_join": ..., "has_group_by": ..., "has_subquery": ..., "has_set_op": ...}` |

**Why the gold SQL, not the agent's SQL:** the point of this breakdown is to answer "how does the agent do on questions that *need* a JOIN" — that's a property of the question itself, not of whatever the agent happened to write. Using the agent's SQL would mix up "the question needed a JOIN" with "the agent decided to use one," which is a different (and less useful) question.

**Pseudocode:**

```
function tag_features(sql):
    try:
        parsed = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return {"has_join": False, "has_group_by": False, "has_subquery": False, "has_set_op": False}

    has_join = (count of exp.Join nodes found in parsed) > 0

    has_group_by = parsed has a "group" clause
        # look at parsed.args.get("group") — copy this pattern from how sql_guardrails.py
        # reads other parts of the parsed query

    has_subquery = (count of exp.Select nodes found anywhere inside parsed) > 1
        # more than 1 because the outermost query itself is also an exp.Select —
        # copy the nested-select-detection idea from check_subquery_depth() in
        # guardrails/sql_guardrails.py

    has_set_op = (count of exp.Union nodes) > 0
                 or (count of exp.Intersect nodes) > 0
                 or (count of exp.Except nodes) > 0

    return {
        "has_join": has_join,
        "has_group_by": has_group_by,
        "has_subquery": has_subquery,
        "has_set_op": has_set_op,
    }
```

**Precautions:**

- If the SQL doesn't parse at all, return all `False` rather than crashing — same defensive pattern used everywhere else in this project's guardrails.
- Don't copy-paste `sql_guardrails.py`'s functions wholesale — they return a `GuardrailResult` (pass/fail with a reason), which isn't what you want here. You want plain `True`/`False` values. Read those functions for the *pattern* (how to walk the tree), then write your own, simpler function.

**Now add to `metrics.py` from Milestone 1:**

```
summarize_by_feature(records, feature_keys)
```

| | Type | Meaning |
|---|---|---|
| **Input** `records` | `list[dict]` | Each record must have `"score"` plus boolean fields matching `feature_keys` (e.g. `"has_join": True`). |
| **Input** `feature_keys` | `list[str]` | Which feature fields to report on, e.g. `["has_join", "has_group_by", "has_subquery", "has_set_op"]`. |
| **Output** | `dict` | One entry per feature — see below. |

```python
{
    "has_join": {"score": 3, "total": 5, "accuracy": 0.6},
    "has_group_by": {"score": 1, "total": 2, "accuracy": 0.5},
}
```

**Why this can't just reuse `summarize()`'s `group_by`:** `summarize()` assumes every record falls into exactly *one* group per field (a question has exactly one `status`, exactly one `db_id`). But a single question can need a JOIN *and* a subquery at the same time — `has_join` and `has_subquery` can both be `True` on the same record. So this needs its own, slightly different counting logic: for each feature, look only at the records where that feature is `True`, and compute accuracy within that subset.

**Pseudocode:**

```
function summarize_by_feature(records, feature_keys):
    result = {}

    for each feature in feature_keys:
        matching = [record for record in records if record.get(feature) == True]
        total = length of matching
        score = sum of record["score"] for record in matching
        accuracy = score / total if total > 0 else 0.0

        result[feature] = {"score": score, "total": total, "accuracy": accuracy}

    return result
```

**Test file to write first:** `tests/eval/test_sql_features.py`. Hand-write a handful of SQL strings, one obviously containing each feature, and one plain query with none of them:

```python
def test_tag_features_detects_join():
    sql = "SELECT s.name FROM students s JOIN courses c ON s.course_id = c.id"
    assert tag_features(sql)["has_join"] is True

def test_tag_features_plain_query_has_no_features():
    sql = "SELECT name FROM students WHERE id = 1"
    tags = tag_features(sql)
    assert tags["has_join"] is False
    assert tags["has_group_by"] is False
    assert tags["has_subquery"] is False
    assert tags["has_set_op"] is False
```

Then add one test each for `has_group_by`, `has_subquery` (a query with a `SELECT` inside a `WHERE ... IN (SELECT ...)`), and `has_set_op` (a query using `UNION`). Add a small test for `summarize_by_feature()` too, in `tests/eval/test_metrics.py`, using a hand-built record list like Milestone 1's.

**Done when:** `uv run pytest tests/eval/test_sql_features.py tests/eval/test_metrics.py -q` is green.

---

## Milestone 5 — how long and how expensive each question is

**Goal:** track two "is this practical to run" numbers per question: how long it took, and how many tokens (units the LLM is priced by) it used.

**File to change:** `src/spider_agent_workbench/agent.py` — this is the **one exception** to "all new code goes in `eval/`." Timing and token usage have to be measured at the exact moment the agent is called, so they belong next to that call, in `answer_question()`, not reconstructed afterward from the outside.

**What to add to `AgentAnswer`:** three new fields — `latency_seconds` (a number, e.g. `2.4`), `input_tokens` (a whole number), `output_tokens` (a whole number).

**New concept — measuring elapsed time.** Python's `time.perf_counter()` returns a number that increases as time passes. Call it once before the slow operation, once after, and subtract — the difference is how long it took, in seconds.

**New concept — token usage.** Each reply the LLM sends back (an `AIMessage`, already used elsewhere in `agent.py`) carries a `usage_metadata` field with how many tokens went in and out for that one reply. Since the agent can take several turns per question, you need to add these up across every `AIMessage` in the conversation, not just look at the last one.

**Pseudocode — the part of `answer_question()` you're changing:**

```
function answer_question(db_id, question, agent, ...):
    ... existing code above stays the same ...

    start_time = time.perf_counter()
    result = agent.invoke(...)          # this line already exists — just wrap it
    end_time = time.perf_counter()
    latency_seconds = end_time - start_time

    input_tokens = 0
    output_tokens = 0
    for each message in result["messages"]:
        if message is an AIMessage and message.usage_metadata is not empty:
            input_tokens = input_tokens + message.usage_metadata.get("input_tokens", 0)
            output_tokens = output_tokens + message.usage_metadata.get("output_tokens", 0)

    ... existing code below stays the same ...

    return AgentAnswer(
        ... existing fields ...,
        latency_seconds=latency_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
```

**Precautions:**

- Before writing the token-summing code, actually run the agent once (e.g. in a throwaway script, or `python` interactive shell) and print out one `AIMessage`'s `usage_metadata` so you can see its real shape with your own eyes. Field names can differ slightly between library versions — don't guess blind.
- Make sure `start_time`/`end_time` wrap *only* the `agent.invoke(...)` call, not the guardrail checks before/after it — otherwise your latency number is measuring the wrong thing.
- This project is **not** building a dollars-and-cents cost calculator. That would need a table of "price per token" that goes stale every time a model's pricing changes, and it isn't something `README.md` asks for in Phase 4. Reporting raw token counts is enough — anyone who needs a dollar figure later can multiply by a current price themselves.

**Also add to `metrics.py`:**

```
guardrail_hit_rate(records)
```

| | Type | Meaning |
|---|---|---|
| **Input** `records` | `list[dict]` | Each record has `"status"` (from Milestone 2) and, once Milestone 3 is done, `"difficulty"`. |
| **Output** | `dict` | Counts of how often each non-`"match"` status happened, overall and per difficulty. |

```python
{
    "by_status": {"guardrail_rejected": 3, "no_sql": 1},
    "by_difficulty": {
        "easy": {"guardrail_rejected": 1},
        "hard": {"guardrail_rejected": 2, "no_sql": 1},
    },
}
```

**Pseudocode:**

```
function guardrail_hit_rate(records):
    by_status = {}
    by_difficulty = {}

    for each record in records:
        status = record["status"]
        if status != "match":
            by_status[status] = by_status.get(status, 0) + 1

            difficulty = record.get("difficulty", "unknown")
            if difficulty not in by_difficulty:
                by_difficulty[difficulty] = {}
            by_difficulty[difficulty][status] = by_difficulty[difficulty].get(status, 0) + 1

    return {"by_status": by_status, "by_difficulty": by_difficulty}
```

**Test file to write first:** extend `tests/agent_test.py` (it already has tests for `answer_question`) to check that a real (or minimally faked) call produces `latency_seconds > 0`, `input_tokens >= 0`, `output_tokens >= 0`. Add a small hand-built-record test for `guardrail_hit_rate()` to `tests/eval/test_metrics.py`.

**Done when:** `uv run pytest tests/agent_test.py tests/eval/test_metrics.py -q` is green.

---

## Milestone 6 — one real run, at a real size

**Goal:** actually produce Phase 4's numbers, not just working code.

**New file:** a brand-new script — do **not** add this to `test_phase.py`. A reasonable name is `scripts/run_full_eval.py`. Its job is only to wire together everything you've built; it shouldn't contain new logic of its own.

**Pseudocode for the new script:**

```
function main():
    setup logging (reuse logging_config.setup_logging — same as test_phase.py does)

    examples = loaders.filter_available(list(loaders.iter_examples("validation")))
    grouped = loaders.group_by_db(examples)

    # pick a sample bigger than 10 questions — see precaution below
    sample = pick a random subset of `grouped`, with a fixed seed for reproducibility

    records = runner.run_eval(sample, prompt_version="prompt_v3", num_workers=2, log_path=<a new .jsonl path under logs/>)

    ex_summary = metrics.summarize(records, group_by=["status", "db_id", "difficulty"])
    feature_summary = metrics.summarize_by_feature(records, feature_keys=["has_join", "has_group_by", "has_subquery", "has_set_op"])
    guardrail_summary = metrics.guardrail_hit_rate(records)

    write a JSON file to results/phase_4_result.json containing:
        - meta info (sample size, seed, prompt version, timestamp)
        - ex_summary
        - feature_summary
        - guardrail_summary
        - the full records list

main()
```

**Precautions:**

- Stay on the **validation split only** — never the held-out test split (see Ground rules above).
- Running hundreds of questions costs real time and real API money. Do a small trial run first (e.g. 20-30 questions) to make sure the whole pipeline works end to end before committing to a bigger run.
- The project's own background reading recommends **at least 200 questions** before trusting an accuracy number — smaller samples swing around too much to mean anything. Aim for that once your trial run works.
- A run this size will take a while. It's fine to start it and go do something else — you don't need to watch it live (that's what the JSONL log file from Milestone 2 is for: checking progress or debugging afterward without having to re-run).

**Done when:** `results/phase_4_result.json` exists and has real numbers in every section listed above.

---

## Milestone 7 — write up `docs/reports/phase_4.md`

**Goal:** every phase in this project ends with a short written report — `docs/reports/phase_0.md` through `phase_3.md` already exist and all follow the same shape. Phase 4 should too.

**What to do:** once Milestone 6 has real numbers, open `docs/reports/phase_3.md` as a template and write `docs/reports/phase_4.md` with the same sections:

- **Goal** — one paragraph.
- **Scope decisions** — the non-obvious calls you made along the way (e.g. JSONL instead of one file per question, no dollar-cost tracking, vendoring instead of rewriting EM).
- **Components changed** — a table, one row per file you added or changed, one line describing what.
- **Results** — a table comparing Phase 4's numbers (bigger sample) against Phase 3's (10-question sample). Say clearly that the sample sizes are different, so the two numbers aren't directly comparable apples-to-apples — that's a genuinely useful thing to point out, not something to hide.
- **Explicitly out of scope** — things you deliberately didn't build (e.g. Test Suite Accuracy, dollar-cost tracking, figuring out *why* specific things failed — that's Phase 5's job per `README.md`).

**Also update:** the "Status" section and the Phase 4 bullet in `README.md`, the same way it was updated when earlier phases finished.

**Done when:** `docs/reports/phase_4.md` exists, and `README.md` reflects that Phase 4 is complete.

---

## Quick reference: what you're creating

| File | Status today | What you do |
|---|---|---|
| `src/spider_agent_workbench/eval/metrics.py` | empty | write `summarize()`, `summarize_by_feature()`, `guardrail_hit_rate()` |
| `src/spider_agent_workbench/eval/runner.py` | empty | write `run_eval()` |
| `src/spider_agent_workbench/eval/exact_match.py` | doesn't exist | create — small adapter around vendored code |
| `src/spider_agent_workbench/eval/sql_features.py` | doesn't exist | create — `tag_features()` |
| `src/spider_agent_workbench/eval/spider_official/` | doesn't exist | create — vendored files + `NOTICE.md`, copied unmodified |
| `src/spider_agent_workbench/agent.py` | has `AgentAnswer` | add three fields + timing/token code inside `answer_question()` |
| `scripts/run_full_eval.py` | doesn't exist | create — new script, wires `runner` + `metrics` together |
| `scripts/test_phase.py` | exists, works | **do not touch** |
| `tests/eval/test_metrics.py`, `test_runner.py`, `test_exact_match.py`, `test_sql_features.py` | don't exist | create, one per milestone above |
| `results/phase_4_result.json` | doesn't exist | produced by Milestone 6 |
| `docs/reports/phase_4.md` | doesn't exist | Milestone 7 write-up |

## Pacing

Treat each milestone as its own self-contained chunk of work, tested and working before you move on. Don't try to do two in one sitting. If a milestone is taking much longer than the others (Milestone 3 probably will), that's expected — it's the one doing the most unfamiliar thing (reading and safely wrapping someone else's code). Slow down there, not the others.
