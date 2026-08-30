import yaml
import pytest
from pathlib import Path
from vibe_trading.config.llm_config import _resolve_value, _PROVIDER_TO_API, LLMConfig


def test_resolve_empty_unset_returns_none(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _resolve_value("", "openai") is None


def test_resolve_empty_set_returns_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert _resolve_value("", "openai") == "sk-test"


def test_resolve_var_set(monkeypatch):
    monkeypatch.setenv("MY_VAR", "hello")
    assert _resolve_value("${MY_VAR}", "openai") == "hello"


def test_resolve_var_unset_returns_none(monkeypatch):
    monkeypatch.delenv("MY_VAR", raising=False)
    assert _resolve_value("${MY_VAR}", "openai") is None


def test_resolve_var_default_set(monkeypatch):
    monkeypatch.setenv("MY_VAR", "from_env")
    assert _resolve_value("${MY_VAR:default123}", "openai") == "from_env"


def test_resolve_var_default_unset(monkeypatch):
    monkeypatch.delenv("MY_VAR", raising=False)
    assert _resolve_value("${MY_VAR:default123}", "openai") == "default123"


def test_resolve_var_default_with_colon_unset(monkeypatch):
    monkeypatch.delenv("MY_VAR", raising=False)
    assert (
        _resolve_value("${MY_VAR:http://127.0.0.1:8415/v1}", "openai")
        == "http://127.0.0.1:8415/v1"
    )


def test_resolve_var_default_with_colon_set(monkeypatch):
    monkeypatch.setenv("MY_VAR", "http://example.com/v1")
    assert (
        _resolve_value("${MY_VAR:http://127.0.0.1:8415/v1}", "openai")
        == "http://example.com/v1"
    )


def test_resolve_switchboard_api_key_unset(monkeypatch):
    monkeypatch.delenv("SWITCHBOARD_API_KEY", raising=False)
    assert _resolve_value("${SWITCHBOARD_API_KEY:}", "custom_openai") is None


def test_resolve_switchboard_base_url_unset(monkeypatch):
    monkeypatch.delenv("SWITCHBOARD_BASE_URL", raising=False)
    assert (
        _resolve_value(
            "${SWITCHBOARD_BASE_URL:http://127.0.0.1:8415/v1}", "custom_openai"
        )
        == "http://127.0.0.1:8415/v1"
    )


def test_resolve_switchboard_base_url_set(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_BASE_URL", "http://example.com/v1")
    assert (
        _resolve_value(
            "${SWITCHBOARD_BASE_URL:http://127.0.0.1:8415/v1}", "custom_openai"
        )
        == "http://example.com/v1"
    )


def test_resolve_var_empty_env_treated_as_unset(monkeypatch):
    monkeypatch.setenv("MY_VAR", "")
    assert _resolve_value("${MY_VAR:default123}", "openai") == "default123"
    assert _resolve_value("${MY_VAR}", "openai") is None


def test_resolve_literal():
    assert _resolve_value("literal_value", "openai") == "literal_value"
    assert _resolve_value("literal_value", "custom_openai") == "literal_value"


def test_provider_to_api_contains_custom_openai():
    assert "custom_openai" in _PROVIDER_TO_API
    assert _PROVIDER_TO_API["custom_openai"] == "openai-completions"


def test_llmconfig_get_model_custom_openai(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_BASE_URL", "http://example.com/v1")
    monkeypatch.setenv("SWITCHBOARD_API_KEY", "sk-sb")
    cfg = {
        "use_llm": "my_custom",
        "llms": {
            "my_custom": {
                "provider": "custom_openai",
                "api_key": "${SWITCHBOARD_API_KEY:}",
                "base_url": "${SWITCHBOARD_BASE_URL:http://127.0.0.1:8415/v1}",
                "model": "mimo-v2.5",
                "description": "test",
            }
        },
    }
    p = tmp_path / "llm.yaml"
    p.write_text(yaml.safe_dump(cfg))
    lc = LLMConfig(config_path=str(p))
    model = lc.get_model("my_custom")
    assert model.api == "openai-completions"
    assert model.base_url == "http://example.com/v1"
    assert model.provider == "custom_openai"
    assert model.id == "mimo-v2.5"


def test_llmconfig_get_model_custom_openai_default_base_url(tmp_path, monkeypatch):
    monkeypatch.delenv("SWITCHBOARD_BASE_URL", raising=False)
    cfg = {
        "use_llm": "my_custom",
        "llms": {
            "my_custom": {
                "provider": "custom_openai",
                "api_key": "${SWITCHBOARD_API_KEY:}",
                "base_url": "${SWITCHBOARD_BASE_URL:http://127.0.0.1:8415/v1}",
                "model": "mimo-v2.5",
                "description": "test",
            }
        },
    }
    p = tmp_path / "llm.yaml"
    p.write_text(yaml.safe_dump(cfg))
    lc = LLMConfig(config_path=str(p))
    model = lc.get_model("my_custom")
    assert model.api == "openai-completions"
    assert model.base_url == "http://127.0.0.1:8415/v1"
