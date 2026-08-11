"""Tests for agent_builder_factory.py — load_system_prompt, build_agent.

build_agent's collaborators (ChatAnthropic, ChatDeepSeek, create_agent) and the
provider/config values it reads from Settings are all monkeypatched, so no real
network call, .env file, or API key is required.
"""

from unittest.mock import MagicMock

import pytest

from spider_agent_workbench import agent_builder_factory as factory_module
from spider_agent_workbench.agent_builder_factory import (
    DEFAULT_PROMPT_VERSION,
    TOOLS,
    build_agent,
    load_system_prompt,
)


# load_system_prompt
#   default version loads real prompt_v3.md content
#   leading "<!-- ... -->" changelog lines are stripped
#   unknown version raises


def test_load_system_prompt_returns_non_empty_text_for_default_version():
    prompt = load_system_prompt()
    assert prompt.strip() != ""
    assert not prompt.startswith("<!--")


def test_load_system_prompt_strips_leading_changelog_comment(tmp_path, monkeypatch):
    monkeypatch.setattr(factory_module, "PROMPTS_DIR", tmp_path)
    (tmp_path / "prompt_vtest.md").write_text(
        "<!-- vtest: scratch prompt for this test -->\nYou are a helpful assistant.",
        encoding="utf-8",
    )

    prompt = load_system_prompt("prompt_vtest")

    assert prompt == "You are a helpful assistant."


def test_load_system_prompt_raises_for_unknown_version(tmp_path, monkeypatch):
    monkeypatch.setattr(factory_module, "PROMPTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_system_prompt("prompt_does_not_exist")


# build_agent
#   picks ChatAnthropic vs ChatDeepSeek based on Settings.model_provider, using
#   each provider's default model + API key from Settings when model_name isn't
#   given explicitly, and wires the result into create_agent with TOOLS + the
#   loaded system prompt


def _patch_create_agent(monkeypatch):
    create_agent_mock = MagicMock(return_value="compiled-graph")
    monkeypatch.setattr(factory_module, "create_agent", create_agent_mock)
    return create_agent_mock


def test_build_agent_uses_chat_anthropic_when_provider_is_anthropic(monkeypatch):
    monkeypatch.setattr(factory_module.Settings, "model_provider", "anthropic")
    monkeypatch.setattr(factory_module.Settings, "anthropic_default_model", "claude-test-model")
    monkeypatch.setattr(factory_module.Settings, "anthropic_api_key", "anthropic-key")

    mock_model_instance = MagicMock(name="chat_anthropic_instance")
    chat_anthropic_mock = MagicMock(return_value=mock_model_instance)
    chat_deepseek_mock = MagicMock()
    monkeypatch.setattr(factory_module, "ChatAnthropic", chat_anthropic_mock)
    monkeypatch.setattr(factory_module, "ChatDeepSeek", chat_deepseek_mock)
    create_agent_mock = _patch_create_agent(monkeypatch)

    result = build_agent(prompt_version=DEFAULT_PROMPT_VERSION)

    chat_anthropic_mock.assert_called_once_with(model="claude-test-model", api_key="anthropic-key")
    chat_deepseek_mock.assert_not_called()
    create_agent_mock.assert_called_once_with(
        model=mock_model_instance,
        tools=TOOLS,
        system_prompt=load_system_prompt(DEFAULT_PROMPT_VERSION),
    )
    assert result == "compiled-graph"


def test_build_agent_uses_chat_deepseek_when_provider_is_deepseek(monkeypatch):
    monkeypatch.setattr(factory_module.Settings, "model_provider", "deepseek")
    monkeypatch.setattr(factory_module.Settings, "deepseek_default_model", "deepseek-test-model")
    monkeypatch.setattr(factory_module.Settings, "deepseek_api_key", "deepseek-key")

    mock_model_instance = MagicMock(name="chat_deepseek_instance")
    chat_deepseek_mock = MagicMock(return_value=mock_model_instance)
    chat_anthropic_mock = MagicMock()
    monkeypatch.setattr(factory_module, "ChatDeepSeek", chat_deepseek_mock)
    monkeypatch.setattr(factory_module, "ChatAnthropic", chat_anthropic_mock)
    create_agent_mock = _patch_create_agent(monkeypatch)

    result = build_agent(prompt_version=DEFAULT_PROMPT_VERSION)

    chat_deepseek_mock.assert_called_once_with(model="deepseek-test-model", api_key="deepseek-key")
    chat_anthropic_mock.assert_not_called()
    create_agent_mock.assert_called_once_with(
        model=mock_model_instance,
        tools=TOOLS,
        system_prompt=load_system_prompt(DEFAULT_PROMPT_VERSION),
    )
    assert result == "compiled-graph"


def test_build_agent_model_name_override_takes_precedence_over_provider_default(monkeypatch):
    monkeypatch.setattr(factory_module.Settings, "model_provider", "anthropic")
    monkeypatch.setattr(factory_module.Settings, "anthropic_default_model", "claude-default-model")
    monkeypatch.setattr(factory_module.Settings, "anthropic_api_key", "anthropic-key")

    chat_anthropic_mock = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(factory_module, "ChatAnthropic", chat_anthropic_mock)
    _patch_create_agent(monkeypatch)

    build_agent(model_name="custom-model", prompt_version=DEFAULT_PROMPT_VERSION)

    chat_anthropic_mock.assert_called_once_with(model="custom-model", api_key="anthropic-key")


def test_build_agent_raises_for_unsupported_provider(monkeypatch):
    monkeypatch.setattr(factory_module.Settings, "model_provider", "openai")

    with pytest.raises(ValueError, match="openai"):
        build_agent()


def test_build_agent_provider_match_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(factory_module.Settings, "model_provider", "  Anthropic  ")
    monkeypatch.setattr(factory_module.Settings, "anthropic_default_model", "claude-test-model")
    monkeypatch.setattr(factory_module.Settings, "anthropic_api_key", "anthropic-key")

    chat_anthropic_mock = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(factory_module, "ChatAnthropic", chat_anthropic_mock)
    _patch_create_agent(monkeypatch)

    build_agent()

    chat_anthropic_mock.assert_called_once_with(model="claude-test-model", api_key="anthropic-key")


def test_build_agent_passes_none_api_key_through_when_unset(monkeypatch):
    monkeypatch.setattr(factory_module.Settings, "model_provider", "anthropic")
    monkeypatch.setattr(factory_module.Settings, "anthropic_default_model", "claude-test-model")
    monkeypatch.setattr(factory_module.Settings, "anthropic_api_key", None)

    chat_anthropic_mock = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(factory_module, "ChatAnthropic", chat_anthropic_mock)
    _patch_create_agent(monkeypatch)

    build_agent()

    chat_anthropic_mock.assert_called_once_with(model="claude-test-model", api_key=None)
