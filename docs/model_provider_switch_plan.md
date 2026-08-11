# Model provider switch plan (Anthropic ↔ DeepSeek)

Status: **executed** (2026-08-08) — see `config.py`, `constants.py`,
`agent_builder_factory.py`, `tests/agent_builder_factory_test.py`.

Decisions from review (2026-08-08): API-key `Settings` fields are `Optional`, not
required. `constants.DEFAULT_MODEL` stays in place but gets a comment marking it
unused. Both are folded into the plan below.

## Goal

- `agent_builder_factory.build_agent` should pick its chat model class, API key, and
  default model name based on a `MODEL_PROVIDER` env var, instead of hardcoding
  `ChatAnthropic` + `constants.DEFAULT_MODEL`.
- API keys and default model names come from `.env` (via `config.Settings`) only —
  `constants.py` stops owning a model name.
- Tests are written first (new/changed tests should fail against the current code),
  then `agent_builder_factory.py` is changed to make them pass.

## What's already in place

- `.env` (gitignored, not committed) now has:
  - `MODEL_PROVIDER='anthropic'`
  - `ANTHROPIC_API_KEY`, `ANTHROPIC_DEFAULT_MODEL='claude-haiku-4-5'`
  - `DEEPSEEK_API_KEY`, `DEEPSEEK_DEFAULT_MODEL="deepseek-v4-flash"`
- `pyproject.toml`/`uv.lock` already declare `langchain-deepseek>=1.1.0` as a dependency
  (pulls in `langchain-openai` + `openai`, since DeepSeek's LangChain integration is
  OpenAI-protocol-based) — **not yet installed**, `uv sync` hasn't been run since it
  was added.
- `ChatDeepSeek` (from `langchain_deepseek`) accepts `model=` and `api_key=` exactly
  like `ChatAnthropic` does today (confirmed via its pydantic field aliases), so
  `build_agent`'s two branches can stay structurally symmetric.

## Current state (what's changing)

| File | Today | Problem |
|---|---|---|
| `src/spider_agent_workbench/config.py` | `Settings.anthropic_api_key: str` only | Doesn't declare `model_provider`, `anthropic_default_model`, `deepseek_api_key`, `deepseek_default_model` — pydantic-settings rejects any undeclared `.env` key as `extra_forbidden`, so `deepseek_api_key` currently breaks every test that imports `agent.py`/`agent_builder_factory.py` |
| `src/spider_agent_workbench/constants.py` | `DEFAULT_MODEL = "claude-haiku-4-5"` | Hardcodes an Anthropic model name; per your instruction, default model names should come from `.env`, not `constants.py` |
| `src/spider_agent_workbench/agent_builder_factory.py` | `build_agent` unconditionally does `ChatAnthropic(model=model_name, api_key=Settings.anthropic_api_key)` | No branching on provider at all |

## Proposed changes

### 1. `config.py` — extend `Settings`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env")
    model_provider: str
    anthropic_api_key: str | None = None
    anthropic_default_model: str
    deepseek_api_key: str | None = None
    deepseek_default_model: str
```

- Field names match `.env` keys case-insensitively (pydantic-settings default), so
  `MODEL_PROVIDER` → `model_provider`, etc. — no extra config needed.
- Declaring `deepseek_api_key` here also incidentally fixes the pre-existing
  `extra_forbidden` collection error flagged earlier in this session.
- **API keys are `Optional[str] = None`** (per your decision) — a `.env` that only
  sets the active provider's key (no dummy value for the other) now loads cleanly,
  instead of `Settings()` refusing to construct at import time.
- Default-model fields (`anthropic_default_model`, `deepseek_default_model`) stay
  required `str` — not addressed by your decision, and your `.env` sets both, so no
  reason to loosen them.
- No extra validation is added for "selected provider's key is `None`" — if
  `MODEL_PROVIDER=anthropic` but `anthropic_api_key` is unset, `ChatAnthropic(api_key=None)`
  will surface its own clear error from the SDK when `build_agent()` actually runs.
  That's a real, reachable misconfiguration now (unlike before), but the underlying
  client already reports it — no need to duplicate that check ourselves.

### 2. `constants.py` — mark `DEFAULT_MODEL` unused, keep it in place

Per your decision, `DEFAULT_MODEL` is not deleted — it gets a comment instead:

```python
#agent
# Not in use — model selection now routes through Settings (.env:
# ANTHROPIC_DEFAULT_MODEL / DEEPSEEK_DEFAULT_MODEL) via agent_builder_factory.build_agent.
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TURNS = 7
```

- `agent_builder_factory.py` stops importing/referencing it.
- Confirmed via grep: nothing else in the codebase references `DEFAULT_MODEL`, so
  this is genuinely dead code from here on — kept only per your explicit call, not
  because something still needs it.

### 3. `agent_builder_factory.py` — branch `build_agent` on `Settings.model_provider`

```python
from langchain_deepseek import ChatDeepSeek

def build_agent(model_name: str | None = None, prompt_version: str = DEFAULT_PROMPT_VERSION):
    provider = Settings.model_provider.strip().lower()
    if provider == "anthropic":
        model = ChatAnthropic(
            model=model_name or Settings.anthropic_default_model,
            api_key=Settings.anthropic_api_key,
        )
    elif provider == "deepseek":
        model = ChatDeepSeek(
            model=model_name or Settings.deepseek_default_model,
            api_key=Settings.deepseek_api_key,
        )
    else:
        raise ValueError(f"Unsupported MODEL_PROVIDER: {Settings.model_provider!r}")

    system_prompt = load_system_prompt(prompt_version)
    return create_agent(model=model, tools=TOOLS, system_prompt=system_prompt)
```

- `model_name` becomes an optional override (`None` default) instead of defaulting to
  `constants.DEFAULT_MODEL` — when omitted, the provider's `.env` default is used.
  Passing it explicitly (as the existing test already does) still overrides.
- Provider string is lowercased/stripped before comparison so `.env` casing
  (`Anthropic` vs `anthropic`) doesn't matter.
- Unknown `MODEL_PROVIDER` values raise `ValueError` at `build_agent()` call time —
  this is a real, reachable misconfiguration (typo in `.env`), so it gets a real
  check, unlike the `Optional` question above.
- `DEFAULT_PROMPT_VERSION`, `TOOLS`, `load_system_prompt` are unchanged.

## Tests (written first)

Replaces the current single `test_build_agent_wires_model_tools_and_prompt` in
`tests/agent_builder_factory_test.py` with provider-specific cases:

1. **`test_build_agent_uses_chat_anthropic_when_provider_is_anthropic`**
   Monkeypatch `Settings.model_provider = "anthropic"`,
   `Settings.anthropic_default_model = "claude-test-model"`,
   `Settings.anthropic_api_key = "anthropic-key"`; monkeypatch `ChatAnthropic` and
   `create_agent`. Call `build_agent()` with no `model_name`. Assert `ChatAnthropic`
   called with `model="claude-test-model", api_key="anthropic-key"`, and
   `create_agent` called with that model instance + `TOOLS` + the loaded prompt.

2. **`test_build_agent_uses_chat_deepseek_when_provider_is_deepseek`**
   Mirror of #1 with `Settings.model_provider = "deepseek"`,
   `deepseek_default_model = "deepseek-test-model"`, `deepseek_api_key = "deepseek-key"`,
   monkeypatching `ChatDeepSeek` instead. Asserts `ChatDeepSeek` called with the
   DeepSeek default model + key.

3. **`test_build_agent_model_name_override_takes_precedence_over_provider_default`**
   Provider `"anthropic"`, call `build_agent(model_name="custom-model")` — asserts
   `ChatAnthropic` is called with `model="custom-model"`, not
   `Settings.anthropic_default_model`.

4. **`test_build_agent_raises_for_unsupported_provider`**
   `Settings.model_provider = "openai"` (unsupported) → `build_agent()` raises
   `ValueError` whose message mentions the bad value.

5. **`test_build_agent_provider_match_is_case_insensitive`**
   `Settings.model_provider = "Anthropic"` (mixed case, as a typo/formatting
   variance) still resolves to the Anthropic branch.

6. **`test_build_agent_passes_none_api_key_through_when_unset`**
   Provider `"anthropic"`, `Settings.anthropic_api_key = None` (now reachable, since
   the field is `Optional`) — asserts `ChatAnthropic` is still called (with
   `api_key=None`), i.e. `build_agent` doesn't add its own guard/raise for this;
   whatever happens next is the SDK's error to raise, not ours.

- `load_system_prompt` tests (already in this file) are untouched.
- Not planning a dedicated `tests/test_config.py` for the new `Settings` fields —
  every other test's successful collection already exercises `Settings()` loading
  cleanly with all five `.env` keys declared. Call it out if you'd like explicit
  coverage there too.

## Execution order (once you approve)

1. `uv sync` — actually installs `langchain-deepseek` (currently only staged in
   `pyproject.toml`/`uv.lock`, not installed).
2. Rewrite `tests/agent_builder_factory_test.py`'s `build_agent` tests per the list
   above; run `uv run pytest tests/agent_builder_factory_test.py -q` and confirm they
   fail for the expected reason (old code doesn't branch on provider).
3. Update `config.py` (`Settings` fields).
4. Update `constants.py` (comment marking `DEFAULT_MODEL` unused).
5. Update `agent_builder_factory.py` (`build_agent` branching, drops `DEFAULT_MODEL` import).
6. Run `uv run pytest tests/agent_builder_factory_test.py -q`, confirm green.
7. Run the full `uv run pytest` suite, confirm no regressions elsewhere.
8. Update `CLAUDE.md`/`README.md`'s `.env` requirement line (currently says
   "`ANTHROPIC_API_KEY=...`" only) to mention `MODEL_PROVIDER` and the DeepSeek keys.

## Open questions for you

- Resolved: API-key fields are `Optional`; `constants.DEFAULT_MODEL` stays with an
  unused-marker comment (see decisions note at the top).
- Still open: any other provider you want stubbed into the `if/elif` now, or just
  these two (Anthropic, DeepSeek)?
