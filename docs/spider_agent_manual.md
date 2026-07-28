# Building an Agentic Text-to-SQL System with the Spider Dataset

### A beginner-friendly instruction manual — concepts first, code later

**Who this is for:** you know basic Python and SQL, you've seen the Claude API and LangChain syntax, and you've never actually built an agent. By the end you'll have a clear mental model of what you're building, why, and in what order — so that when you *do* start writing code, you know what each piece is for.

**How to use this manual:**

- Read top to bottom, once, without touching your keyboard. Get the shape of the whole project in your head first.
- Then read it again, treating each phase as a milestone. Build Phase 1 before you read Phase 2 code from other projects — you want to hit the problems yourself so the solutions make sense.
- Keep a "questions I have" scratchpad. Most beginner questions are answered by Phase 3 or Phase 4 — don't panic if things feel incomplete after Phase 1.

**What's inside:**

1. The North Star — what we're actually building and why Spider is the right dataset
2. What Spider gives you (and what you need to fetch separately)
3. The six concepts you'll internalize — mapped to concrete parts of the project
4. Project folder structure
5. A six-phase learning path from setup to a working, evaluated agent
6. Two worked examples — one easy, one hard — showing what "guardrails" and "evals" actually mean in practice
7. Real projects other people have built that you can study
8. Common pitfalls and stretch goals

There is no code in this document. Everything here is the plan; the code you write yourself, phase by phase.

---

## 1. The North Star — what are we actually building?

We're building a **text-to-SQL agent**: a system where a user asks a question in English, and the system figures out which tables to look at, writes the SQL, runs it against the database, and returns the answer along with the SQL it used.

This is not a research toy. It's the core of a whole category of real products:

- "Chat with your data" analytics tools (Hex, Julius, Perplexity's data mode, etc.)
- Internal BI copilots that let non-technical staff ask *"how many orders shipped late last week?"* without knowing SQL
- Customer-facing analytics inside SaaS apps ("show me my top customers by revenue this quarter")

The reason building one is genuinely great practice — and not just a toy exercise — is that a correct answer requires the model to:

- Read a database schema it has never seen before
- Pick the right tables out of possibly hundreds
- Understand JOINs, aggregates, filters, subqueries, set operations
- Handle its own mistakes (SQL errors, empty results, hallucinated column names)
- Refuse dangerous or out-of-scope requests
- Do all of this fast enough and cheap enough to be worth using

Every one of those bullets is one of the concepts you're trying to learn (tool use, guardrails, evaluation, orchestration, observability). So we're not doing a text-to-SQL project *and separately* learning about agents — the text-to-SQL project is the vehicle that forces you to learn every one of these concepts in context.

**Why Spider specifically?**

- **200 databases across 138 domains.** Every question is on a schema the model isn't allowed to have memorized. If your agent works on Spider, it will work on your own database too.
- **10,000+ human-written question/SQL pairs** across a wide difficulty spread (easy → extra hard). You get easy wins early to prove the pipeline works, plus hard cases that stress-test your guardrails.
- **Gold SQL for every question**, which is what makes automated evaluation possible. Without gold answers, "did it work?" becomes a manual review problem, which doesn't scale.
- **Official evaluation scripts already exist**, so you're not inventing metrics from scratch — you're using the same ones every research paper reports.

---

## 2. What Spider gives you (and what you need to fetch separately)

From Hugging Face (`xlangai/spider`), each row gives you:

- `db_id` — the name of the target database (`department_management`, `farm`, `world_1`, ...)
- `question` — the natural-language question ("How many heads are older than 56?")
- `query` — the gold SQL that answers the question
- `question_toks`, `query_toks`, `query_toks_no_value` — pre-tokenized versions, useful for the official Exact Match evaluation

That's about 8,000 rows split into train (~7k) and validation (~1k). There's also a hidden test set.

**Important gotcha for beginners:** the Hugging Face parquet file does **not** include the actual SQLite database files. You need those to (a) execute your agent's SQL and check that it returns the right rows, and (b) run the official evaluation. You download the `.sqlite` files from the original Spider release page (yale-lily.github.io/spider). Once unpacked, you'll have a folder like:

```
spider_databases/
    department_management/department_management.sqlite
    farm/farm.sqlite
    world_1/world_1.sqlite
    ...
```

**One more thing you'll need to build yourself:** a *schema string* for each database, in a form the LLM can read. This is usually the `CREATE TABLE` statements (with column types and primary/foreign keys) plus a couple of sample rows per table. You extract this from the SQLite files with a tiny script. This "schema string" is what you paste into the model's context every time you ask it a question. How you format it matters — that's one of the first things you'll tune in Phase 1.

**Related datasets worth knowing about (don't touch these yet — save them for stretch goals):**

- `richardr1126/spider-schema` — just the schemas, no questions
- `aherntech/spider-realistic` — Spider dev-set questions rewritten to NOT mention column names, which forces the model to actually understand the schema rather than pattern-match column tokens
- `Turbular/fixed_spider` — a cleaned-up version of Spider that fixes some annotation errors in the original
- Spider 2.0 (hosted at yale-lily.github.io, not fully on HF) — a much harder successor benchmark with enterprise-scale schemas (thousands of columns, BigQuery/Snowflake), where even frontier models score around 20%

---

## 3. The six concepts you're actually learning — mapped to this project

For a beginner, the terms "agent", "tool", "guardrail", "eval", "orchestration", and "observability" tend to blur together. Here's how each one maps to a concrete, physical part of what you'll build. Every concept has a home in the codebase — that's how you'll internalize them.

**Agent building.** An "agent" is just an LLM that runs in a loop, choosing tools each turn until it decides it's done. In this project, the agent's loop is roughly: *look at schema → think → call a tool (usually SQL execution) → look at result → decide if done or try again*. You'll build this loop by hand in Phase 2. The "agentic" leap happens when you stop asking the LLM "here's a schema and a question, please write the SQL in one shot" and start asking "here are your tools, figure it out."

**Tools.** Named functions the LLM can call. In our project the tool set is small: `list_tables()`, `describe_table(name)`, `sample_rows(table, n)`, `run_sql(query)`, `submit_final_sql(query)`. The LLM does not run these itself — your code runs them and passes the results back to the model. Tools are what let the agent *explore* an unfamiliar schema instead of guessing.

**Guardrails.** Rules and checks that sit *around* the LLM and constrain what it can do. In this project they include: blocking destructive SQL (`DROP`, `DELETE`, `UPDATE`), rejecting SQL that references tables not in the current schema, capping query runtime, limiting the number of agent turns per question, and rejecting out-of-scope inputs. Guardrails are separate code — not prompt instructions — because prompts can be talked around, but a code check that refuses to execute cannot.

**Evaluations (evals).** How you measure whether your agent is actually good. For Spider specifically: *Exact Match* (does the SQL structurally match the gold clause by clause?), *Execution Accuracy* (does running your SQL return the same rows as the gold SQL?), and *stratified accuracy* (how do you do on easy vs. medium vs. hard vs. extra hard, and per database, and per SQL feature). Alongside correctness, you'll measure cost per query, latency, average number of agent turns, and how often each guardrail fires.

**LLM orchestration.** The plumbing that decides *which* model handles *which* step. Real systems often use a fast/cheap model for schema-exploration turns and a stronger model for the final SQL generation. You'll experience the tradeoff first-hand: single-model-for-everything is simpler; multi-model is cheaper and sometimes better.

**Observability.** Logging every LLM call, every tool call, every guardrail hit, and every eval result, in a way you can revisit and inspect. Without this you cannot debug why your agent fails on question #147 — you'll just see "wrong answer" with no idea what happened between the input and the output. This is the piece beginners skip and then regret; put it in early.

---

## 4. Project structure

Here's a folder layout that scales from your first prototype to something realistic. **Don't build it all at once** — you'll add modules as you hit the corresponding phase. What matters right now is that you can see the shape of the finished thing.

```
spider-agent/
├── data/
│   ├── spider/          # SQLite files from the official Spider release
│   └── hf_xlangai_spider/          # cached xlangai/spider parquet
│
├── src/spider_agent_workbench
|   |-- __init__.py
|   |-- paths.py
|   |-- config.py
│   ├── loaders.py                 # loads HF dataset, groups rows by db_id
│   ├── schema.py                  # extracts CREATE TABLE + sample rows into a string
│   ├── executor.py                # safely runs SQL against a SQLite db, with timeout
│   │
│   ├── tools.py                   # tool definitions (list_tables, run_sql, etc.)
│   ├── guardrails.py              # pre-execution and post-execution safety checks
│   ├── agent.py                   # the ReAct loop tying LLM + tools + guardrails
│   │
│   ├── prompts/
│   │   ├── prompt_v1.txt          # baseline system prompt
│   │   ├── prompt_v2.txt          # after first failure analysis
│   │   └── ...                    # you version these as you iterate
│   │
│   └── eval/
|       |-- __init__.py
│       ├── metrics.py             # Exact Match, Execution Accuracy, difficulty buckets
│       ├── runner.py              # runs the agent over the val split, saves per-question logs
│
├── logs/                          # one JSON log per question run — every LLM/tool/guardrail event
└── results/                       # aggregated eval outputs, side-by-side across prompt versions
|__ notebooks/analysis.ipynb       # where you inspect failures by hand
```

**How data flows through the system, in one sentence:**
`path.py` to manage paths across the code
`config.py` to avoid direct .env

`loaders` gives you `(question, db_id)` → `schema` builds the schema string for that db_id → `agent` runs its loop, calling `tools` (which are policed by `guardrails`) and going through `executor` for actual SQL → the agent's final SQL and answer are handed to `eval/metrics` where they're compared against the gold and logged to `results/` and `logs/`.

**A note on tooling:** you can build all of this with plain Python + the Anthropic SDK, or you can use LangChain / LlamaIndex / a dedicated agent framework. My strong recommendation for learning: **build Phase 1 and Phase 2 without a framework**. Once you've felt the pain of writing the loop yourself, framework abstractions will make sense as *solutions to problems you've had*, not as magic incantations.

---

## Phase 0 — Setup and exploration (Day 1)

**Goal:** get all the pieces on your machine and *look at them by hand*. Do not write any agent code yet.

**Steps:**
1. Download the Hugging Face dataset (`xlangai/spider`) and look at 10–20 random rows. Notice the range from "how many farms are there?" to 4-way JOIN with nested subqueries.

2. Download the SQLite databases from the official Spider release page (yale-lily.github.io/spider). Open one — say `department_management.sqlite` — in a SQLite browser (DBeaver, SQLiteStudio, or the `sqlite3` CLI). See the tables, the columns, the actual data.

3. Pick 5 questions from the validation split and try to answer them yourself, by hand-writing SQL and running it against the database. This is the single most valuable hour you'll spend in the whole project — because you now know *concretely* what your agent has to do, and you'll notice how much you personally need to look at sample data to write the right query.

4. Set up API keys (Anthropic and/or OpenAI). Confirm a basic "hello world" call works from Python.

5. Write down, for yourself, the answer to: "What is the input to my system? What is the output? What could go wrong?" One paragraph. Keep it — you'll come back to it at the end.

**What you'll learn:** the actual shape of the problem. What "solving a Spider question" feels like from the inside. Beginners who skip this phase build agents that solve the wrong problem.

---

## Phase 1 — The one-shot baseline (Days 2–3)

**Goal:** build the *simplest possible* thing that generates SQL for a Spider question, so you have a number to beat.

**What you build:**

- A function that takes a `db_id` and a question, formats the schema into a string, wraps it in a prompt, sends it to Claude (or GPT), and gets back a SQL string.
- A tiny evaluator that runs both your SQL and the gold SQL against the SQLite database and compares the returned rows.
- Run it on 50–100 val questions. Record accuracy.

**What you'll learn — and this is what makes Phase 1 non-negotiable:**

- **Prompt structure matters enormously.** The difference between *"here is a schema, write SQL"* and *"here is a schema, here are 2 solved examples, and here's the question — write SQL and nothing else"* is often 15–20 percentage points.

- **Schema representation matters.** Just column names vs. `CREATE TABLE` with types vs. `CREATE TABLE` + 3 sample rows are all different accuracy tiers. Adding sample rows especially helps when values are enum-like strings (e.g. is the status stored as `"Active"` or `"active"` or `1`?).

- **Failures are patterned, not random.** You'll see the same 4–5 failure modes over and over: hallucinated column names, wrong JOIN direction, missing `GROUP BY`, ambiguous references, forgetting `DISTINCT`. Write these down. They become the requirements for your Phase 3 guardrails and Phase 5 iteration.

- **Output parsing is annoying.** Models return SQL wrapped in code fences, or with a preamble like "Sure, here's the SQL:". Your parser needs to be tolerant.

**Do not skip this phase.** People jump straight to "let's build the fancy agent" and never have a baseline to prove the fancy stuff is actually helping. If your Phase 2 agent gets 55% and you don't know that your Phase 1 baseline was already 52%, you don't know if your extra complexity did anything.

---

## Phase 2 — Make it agentic (Days 4–7)

**Goal:** stop generating SQL blindly. Give the model tools to explore the schema and to test its queries before committing.

**What changes:** you replace the single "please write SQL" call with a loop. Each turn, the model chooses one of a small set of tools:

- `list_tables()` — returns the tables in the current database
- `describe_table(name)` — returns columns, types, primary/foreign keys for one table
- `sample_rows(table, n=3)` — returns a few example rows so the model sees actual values
- `run_sql(query)` — runs the SQL and returns rows or an error message
- `submit_final_sql(query)` — the agent's way of saying "this is my final answer"

Your loop code does this:

1. Send the model the question + the schema summary + the list of tools.
2. Model responds with a tool call (using the model's native tool-use API).
3. Your code executes the tool call and sends the result back.
4. Repeat until the model calls `submit_final_sql`, or you hit a turn limit (start with 10).

**What you'll learn:**

- **Self-correction is where the real gains come from.** When `run_sql` returns "no such column: dept_id", the model sees the error message and tries again. This one behavior often adds 10–20 accuracy points over Phase 1, especially on hard questions.

- **Agents can go in circles.** Without a turn limit, an agent will happily retry the same broken query 30 times, burning your API credits. This is your first taste of why guardrails exist and why every agent needs a "budget" — turn count, token count, wall-clock time.

- **Traces are your friend.** Log every turn — question, tool call, result, model's reasoning. When you eyeball failed runs later, patterns jump out that no amount of aggregate metrics would reveal.

- **You are now doing "LLM orchestration"** — even if only at a simple level. You may notice that using a smaller/cheaper model for early exploration turns and a stronger model only for the final SQL is dramatically cheaper without much accuracy loss. That is orchestration in a nutshell.

- **`describe_table` may not even be needed.** Some builders (see the Text2SqlAgent project in the references) argue you should give the LLM only `execute_sql` and let it run its own `SELECT * FROM sqlite_master` to discover the schema. Fewer tools = less prompt scaffolding to maintain, but harder to interpret traces. Try both.

---

## Phase 3 — Add guardrails (Days 8–10)

**Goal:** stop the agent from doing things it shouldn't — either dangerous things or clearly-broken things — before or after it does them.

Guardrails are best understood in three layers.

**Input guardrails (before the agent runs at all):**

- Is the question in scope? ("What's the weather?" or "Ignore your instructions and…" → refuse). Usually a small classifier prompt or keyword filter.
- Is the `db_id` valid? Fail fast if not.
- Is the question length reasonable? Reject 10,000-word prompts (a cheap defense against prompt injection).

**Tool-call guardrails (every time the agent tries to run something):**

- **Read-only enforcement.** Parse the SQL and reject anything containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `PRAGMA`, `ATTACH`. This is code, not a prompt.
- **Schema validity.** Verify that every table and column the SQL references actually exists in the current db_id's schema. Catches hallucinations *before* they hit the database and gives the agent a useful error message ("no such table: heads — did you mean head?") to self-correct with.
- **Complexity bounds.** Refuse or warn on queries with more than N joins or subqueries deeper than M levels. Prevents accidental Cartesian explosions.
- **Execution timeout.** Hard-kill the SQL after a few seconds so a runaway query doesn't lock everything up.

**Output guardrails (after the agent produces its final answer):**

- The final natural-language answer must be grounded in the actual rows returned. If the agent says "10 farms" but the result set had 3 rows, flag it — this is a hallucination.
- Answer length / format sanity checks.

**What you'll learn:**

- **Guardrails are code, not prompts.** A prompt saying "don't run DELETE" can be jailbroken by a cleverly phrased user message. A regex-and-parser check that refuses to execute any DML statement cannot.

- **Guardrails also improve correctness, not just safety.** The schema-validity check catches a huge class of hallucination bugs and lets the agent retry with the real column names. This is arguably the highest-ROI guardrail in the whole system.

- **Guardrails must be tested with the same rigor as the agent.** Build adversarial test cases: questions crafted to try to elicit `DROP TABLE`, questions that reference non-existent tables, questions designed to produce infinite joins. Add them to your eval so a future prompt change doesn't accidentally weaken a guardrail.

- **Guardrails have false positives.** A too-aggressive complexity limit will refuse queries that were actually going to work. Track your guardrail hit rate on the val set — if a guardrail is firing on 30% of legitimate questions, something's wrong.

---

## Phase 4 — The evaluation harness (Days 11–14)

**Goal:** turn "does it feel like it works?" into "here's my accuracy number, broken down by difficulty and SQL feature, and here's exactly which questions failed and why."

**The metrics you'll implement:**

*Correctness metrics:*

- **Execution Accuracy (EX)** — run your SQL, run the gold SQL, compare the returned rows as sets (or ordered lists if the question asks for an ordering). This is the most important number and the one most modern systems report as their headline metric.
- **Exact Match (EM)** — decompose both SQLs into clauses (SELECT, FROM, WHERE, GROUP BY, HAVING, ORDER BY, set operations) and compare clause by clause using the official Spider script. Useful because two SQLs that happen to return the same result on this specific database might diverge on different data; EM catches this by looking at the query structure.
- **Test Suite Accuracy** — the Yale team's stricter metric where they run the queries against multiple synthesized databases per schema. Catches queries that only accidentally work because of a data coincidence. Nice-to-have once your basic EX is working.

*Slicing:*

- Break accuracy down by **difficulty** (easy / medium / hard / extra hard, using Spider's official criteria). A system that's 90% on easy and 20% on extra hard is a very different beast from one that's 55% flat.
- Break down by **SQL feature**: JOIN accuracy, GROUP BY accuracy, nested-query accuracy, set-operation accuracy.
- Break down by **db_id** — sometimes one weird database is dragging down your overall number and you should look at that database specifically.

*Operational metrics:*

- **Cost per question** (sum of input + output tokens × model price)
- **Latency per question** (wall clock)
- **Average number of agent turns** per question — you want this trending down as you iterate
- **Guardrail hit rate** — how often did each guardrail fire, per difficulty bucket?

**The evaluation loop:**

1. `runner.py` iterates through the val split, calls your agent for each question, and saves everything — question, generated SQL, every tool call, every guardrail hit, final result, timing, cost — to one JSON log file per question.
2. `metrics.py` reads all the log files, computes EX and EM per question, and produces a summary table plus per-slice breakdowns.
3. You open `analysis.ipynb` and look at every failed question by hand. That's Phase 5.

**What you'll learn:**

- **Aggregate numbers hide almost everything.** "62% accuracy" tells you nothing about what to fix. Per-question logs tell you everything, because you can grep them.
- **Metrics are opinions.** EX rewards *"gets the right answer even if the SQL is different"*; EM rewards *"produces canonical SQL"*. Which one you optimize for is a design decision that depends on whether your users care about SQL provenance.
- **You cannot improve what you don't measure.** Every change to prompts, tools, or guardrails is a hypothesis you test: measure, change, re-measure, keep or revert.

---

## Phase 5 — Failure analysis and iteration (ongoing)

**Goal:** systematically identify the biggest failure buckets and fix them.

**The loop, borrowed from the Ragas text-to-SQL evaluation methodology:**

1. **Annotate** every failed question with a short label describing the failure mode ("wrong join direction", "hallucinated column", "missed DISTINCT", "wrong aggregation function", "confused about NULLs", etc.).
2. **Group** failures by label and sort by frequency. The top 2–3 buckets are what you fix next.
3. **Decide the fix**: is it a prompt change, a new tool, a new guardrail, better schema formatting, or better example selection?
4. **Version the prompt.** Make the change on a *new* prompt file (`prompt_v3.txt`), keeping the old one intact. Add a one-line changelog: "v3: added DISTINCT guidance when question says 'unique' or 'different'."
5. **Re-run** the eval on val. Compare v2 vs v3 side-by-side, per difficulty bucket.
6. **Keep or revert.** If v3 is better everywhere, promote it. If it improved hard but broke easy, look at what regressed and decide.
7. **Repeat** until accuracy plateaus for two consecutive iterations, or you meet your product target.

**What you'll learn:**

- **Fixes generalize best when they're schema-grounded, not case-specific.** "Always use DISTINCT for X, Y, Z tables" is overfitting to the val set. "Prefer DISTINCT when the question uses the words 'unique', 'distinct', or 'different'" generalizes to unseen databases. This is the difference between prompt engineering that scales and prompt engineering that doesn't.

- **Never tune only on the val set.** Hold out a small "final test" slice you never look at during iteration. Only touch it at the very end to check you didn't overfit. If your val score is 75% but your held-out score is 55%, you learned to game the val set — not to build a good agent.

- **Some regressions are worth it.** If v3 gains 8 points on hard and loses 1 point on easy, that's usually a good trade. But you can only see the tradeoff if you slice by difficulty.

---

## 5a. Worked example — an easy Spider question

**Question:** *"How many heads of the departments are older than 56?"*
**db_id:** `department_management`
**Gold SQL:** `SELECT count(*) FROM head WHERE age > 56`

Walking through what a well-built agent does, step by step:

**1. Input guardrail check.** Question is under 300 characters, the `db_id` exists in our list of Spider databases, no injection patterns detected → pass.

**2. Schema formatting.** Load and format: `CREATE TABLE department`, `CREATE TABLE head`, `CREATE TABLE management`, with 3 sample rows per table.

**3. Agent turn 1.** Model reads the schema, sees `head.age` right there, decides it doesn't need to explore. Emits `submit_final_sql("SELECT count(*) FROM head WHERE age > 56")`.

**4. Tool-call guardrail on the submitted SQL.** Contains only SELECT ✓. References only `head`, which exists in this `db_id` ✓. Only column referenced is `age`, which is a real column on `head` ✓. Complexity: no joins, trivial. Passes.

**5. Executor.** Runs the SQL against `department_management.sqlite` with a 5-second timeout. Returns `[(5,)]`.

**6. Output guardrail.** Final answer is a count query returning a single integer. Model's natural-language response "5 heads are older than 56" is consistent with the row `[(5,)]` → pass.

**What "guardrails" meant here:**

- Refused to run destructive SQL (didn't need to, but the check ran and passed).
- Verified `head` and `age` are real names in this db_id — so if the model had said `heads` or `Age`, we would have caught it and given the model a useful error.
- Set a 5-second execution timeout.
- Verified the natural-language answer isn't inventing numbers not in the result set.

**What "eval" meant here:**

- **EX:** run our SQL, run gold SQL, both return `[(5,)]` → correct.
- **EM:** compare clause by clause. SELECT clause matches (both `count(*)`), FROM matches (`head`), WHERE matches (`age > 56`), no GROUP/ORDER/LIMIT on either side → correct.
- **Difficulty bucket:** easy. Add 1 to easy-correct count.
- **Cost:** logged token count and dollar cost (probably ~$0.001).
- **Turns:** 1. Log it — you want the average turn count for easy questions to stay close to 1.

---

## 5b. Worked example — a complex Spider question

**Question:** *"List the states where both the secretary of 'Treasury' department and the secretary of 'Homeland Security' were born."*
**db_id:** `department_management`
**Gold SQL:**

```sql
SELECT T3.born_state
FROM department AS T1
JOIN management AS T2 ON T1.department_id = T2.department_id
JOIN head AS T3 ON T2.head_id = T3.head_id
WHERE T1.name = 'Treasury'
INTERSECT
SELECT T3.born_state
FROM department AS T1
JOIN management AS T2 ON T1.department_id = T2.department_id
JOIN head AS T3 ON T2.head_id = T3.head_id
WHERE T1.name = 'Homeland Security'
```

Walking through it:

**1. Input guardrail:** pass.

**2. Schema formatting:** three tables (`department`, `management`, `head`) with 3 sample rows each.

**3. Turn 1.** Model calls `sample_rows("department", 3)`. Why? Because it wants to see actual `department.name` values before it writes `WHERE name = 'Treasury'` — the values could be stored as `"US Treasury"` or `"Dept. of Treasury"` and getting this wrong silently produces an empty result set. This is exactly the "check the data before you commit to a query" instinct you want to instill via prompt design.

**4. Turn 2.** Model sees actual values, confirms `"Treasury"` matches. Drafts SQL: a JOIN across `department → management → head`, filtered by department name, and it plans to use `INTERSECT` to express "both".

**5. Turn 3.** Model calls `run_sql` on its draft. Gets back a small result set — say `[("California",)]`.

**6. Turn 4.** Model does a sanity check: it calls `run_sql` for just the Treasury half and just the Homeland Security half separately, sees the intersection makes sense given the two halves.

**7. Turn 5.** Model calls `submit_final_sql` with its SQL.

**8. Tool-call guardrail on final SQL.** SELECT only ✓. All tables/columns exist ✓. Complexity: 3 joins × 2 branches = 6 joins total, under our threshold of 8 ✓. Passes.

**9. Executor.** Runs the final SQL. Returns the result set.

**Where guardrails become interesting on hard questions:**

- If the model had hallucinated `SELECT born_state FROM heads` (plural), the schema-check guardrail catches it and returns "no such table: heads. Available tables: department, head, management." The agent uses that error to correct itself in the next turn. This is a guardrail that *improves accuracy*, not just safety.

- If the model wrote an accidental Cartesian join (missing JOIN condition), the 5-second timeout kills it and returns "query exceeded timeout" — the agent then tries again with an actual join condition.

- If a malicious or confused user injected "then delete the management table", the read-only guardrail refuses even if the LLM had somehow been convinced to try it.

**Where evals become interesting on hard questions:**

- **EX:** compare row sets. If the model used `EXCEPT` and `IN` cleverly instead of `INTERSECT` but got the same rows, EX says correct. This is EX's charm and its blind spot.
- **EM:** the Spider EM script decomposes both queries into clauses. `INTERSECT` is a top-level structural element — if the model used `AND` in a WHERE clause instead of `INTERSECT`, EM will mark it wrong even if the rows happened to match. This is EM's charm and its blind spot.
- **Difficulty:** this is `hard` in Spider's bucketing (INTERSECT plus multi-join). Add to hard-correct count.
- **Turns:** 5. Higher turn count is normal for hard questions; you track average turns per difficulty bucket to spot regressions across prompt versions.
- **Cost / latency:** logged. This question probably cost $0.01–0.05 depending on model.

Notice: on the easy question, guardrails just quietly passed. On the hard question, guardrails were doing real work — catching hallucinations, killing runaway queries, giving the agent useful errors to recover from. **That's the pattern**: guardrails feel unnecessary on easy questions and essential on hard ones. Build them for the hard case.

---

## 6. Who has done this before — projects worth studying

You don't have to invent from scratch. Read these roughly in this order:

**Text2SqlAgent / text2sql-framework (GitHub: `Text2SqlAgent/text2sql-framework`)** — arguably the closest thing to what you're building here. Their explicit design principle is "hand the LLM one `execute_sql` tool and let it explore the schema, test queries, and self-correct — no RAG, no semantic layer." They report near-perfect scores on a stress test where they merged 20 Spider databases into a single 80-table database, forcing the agent to find the right tables among many wrong ones. Study their tool signatures and, especially, their trace logs. Their thesis that "every guardrail you remove is capability you get back" is exactly the tradeoff you'll feel first-hand.

**Dataherald + LangChain tutorial** (Mo Pourreza, "High accuracy text-to-SQL with LangChain", Medium 2024) — a clean walkthrough of building a LangChain ReAct agent around a text-to-SQL tool, including how the agent decides which tool to invoke on each turn. Good for the "what does a ReAct loop actually look like in code" understanding, once you've felt why you need one.

**Ragas — "Evaluate a Text-to-SQL Agent"** (docs.ragas.io) — the eval side of the house. Their explicit workflow is: run → annotate → review → decide generic guardrails → update prompt version → re-run → compare → repeat, keeping guardrails concise and schema-grounded so improvements generalize instead of overfitting. This is exactly the Phase 5 iteration loop. They use a different dataset (BookSQL) but the methodology transfers directly.

**XLang Spider-Agent (yale-lily.github.io/spider, GitHub `xlang-ai/Spider2`)** — the "official" agent framework used to benchmark models on Spider 2.0. It's more complex than what you should build first, but reading their agent loop, their tool set, and how they handle Docker-isolated execution will show you what a research-grade version looks like.

**taoyds/spider (GitHub, the original repo)** — for the official evaluation scripts. When you build your eval harness, you'll be either importing or reimplementing their Exact Match and Test Suite Accuracy code. Do not reimplement from scratch — use theirs.

**Original Spider paper (arXiv 1809.08887)** — read the "SQL Hardness Criteria" section. It's how the difficulty buckets (easy/medium/hard/extra hard) are defined; you'll want to use those exact buckets in your evaluation reporting so your numbers are comparable to published results.

**Spider 2.0 paper (arXiv, ICLR 2025)** — read once you have basic Spider 1.0 working. It's the benchmark that shows where current agents still fail on realistic enterprise workloads. Sets your ambition ceiling.

---

## 7. Common beginner pitfalls (in roughly the order you'll hit them)

**"My accuracy is 0%."** Almost always because your executor is comparing tuples with different orderings. SQL doesn't guarantee row order without ORDER BY. Sort both result sets before comparing, or compare as multisets (Counter).

**"My accuracy on my 20-question test set looks amazing."** Small test sets have wild variance. Run on at least 200 questions before you trust a number. And use the actual val split, not your favorite examples.

**"My agent used 30 turns to answer 'how many rows in this table'."** You forgot a turn limit, or your prompt is too vague about *when* to submit final SQL. Add both.

**"The eval works but I have no idea why questions fail."** You didn't log enough. Every LLM message, every tool call, every guardrail check needs to be captured in the per-question JSON log with enough context that you can debug from the log alone, without re-running.

**"Adding a guardrail made accuracy go DOWN."** Real thing. Sometimes a guardrail refuses queries that were actually going to work. Check your guardrail's false-positive rate against your baseline traces before shipping it.

**"I switched from Claude to GPT and now everything's broken."** Different models follow different tool-use conventions and prompt styles. Put a thin adapter interface in front of the LLM early so you can swap providers without rewriting your agent loop.

**"I get 90% on val — I'm done!"** Val is what you tuned on. Hold out a small final test slice you never touch until the end.

**"My schema string is 12,000 tokens and the model can't focus."** Truncate. Only include tables that seem relevant to the question — or use a tool that lets the agent load tables on demand. For real databases (not Spider's small ones), this becomes the dominant problem.

**"I got 65% and I'm stuck."** Look at 30 failed questions by hand. Group them. You will find that 20 of them share 3 root causes. Fix those.

---

## 8. Stretch goals — once the core works

Once you have a working agent hitting a respectable EX on Spider val, here's where to push next. Each of these is a real production concern that Spider 1.0 lets you practice in miniature.

- **Try Spider 2.0.** The successor benchmark with enterprise-scale schemas (thousands of columns, real BigQuery/Snowflake databases, multi-query workflows). Current frontier models score around 20% on it. It's much closer to a real product target.

- **Try `aherntech/spider-realistic`.** Questions rewritten to NOT mention column names. Tests whether your agent truly understands the schema or is just pattern-matching column tokens from the question.

- **Add a schema-retrieval layer.** For databases with hundreds of tables, you can't fit the whole schema in context. Embed table descriptions, then retrieve the top-K most relevant ones before the agent starts. This is the standard production pattern.

- **Multi-model orchestration.** Use a cheap model for exploration turns and a strong model only for the final SQL. Measure the cost/accuracy tradeoff. This is where "orchestration" stops being a buzzword and starts being a spreadsheet.

- **Human-in-the-loop.** For high-stakes queries (large joins, aggregations over the whole table, anything modifying data), surface the SQL for human confirmation before executing.

- **Streaming and cancellation.** Return partial explanations while the query runs; let the user cancel.

- **Multi-turn conversations.** The user asks a follow-up. Your agent needs to remember the previous question and result. This is where memory and context management get interesting.

- **Ambiguity handling.** Some questions have multiple reasonable interpretations. A good agent should ask a clarifying question rather than guess wrong. This is a genuinely hard problem.

You'll notice these all move the project from "works on a benchmark" to "would actually ship as a product." That's the whole point of doing it this way — Spider isn't the goal; Spider is the training ground.

---

### Final note

The instinct beginners have — "let me use LangChain and follow a tutorial" — will get you a working demo faster, but you will not learn much. The plan in this document is deliberately slower: baseline first, framework never (for the first pass), then evaluate, then iterate. When you finish, you'll be able to read any agent framework's source code and recognize what each abstraction is for, because you'll have hit the problems it solves.

Good luck. Come back and read this again after Phase 2 — it will read differently.
