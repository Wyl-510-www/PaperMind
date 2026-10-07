"""Tests for configuration module."""

import os
import pytest
from pydantic import ValidationError

from papermind.config import Config, get_config


def test_config_with_valid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test configuration loads successfully with valid API key."""
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-valid-test-key-12345")

    config = get_config()

    assert config.bailian_api_key == "sk-valid-test-key-12345"
    assert config.llm_model == "qwen-max"  # default value
    assert config.llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.log_level == "INFO"


def test_config_with_custom_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test configuration with custom values."""
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-custom-key")
    monkeypatch.setenv("LLM_MODEL", "qwen-turbo")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    config = get_config()

    assert config.bailian_api_key == "sk-custom-key"
    assert config.llm_model == "qwen-turbo"
    assert config.log_level == "DEBUG"


def test_config_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that missing API key raises ValidationError."""
    # Clear any existing API key
    monkeypatch.delenv("BAILIAN_API_KEY", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        get_config()

    error_msg = str(exc_info.value)
    # Pydantic raises "Field required" error when field is missing
    assert "bailian_api_key" in error_msg
    assert "Field required" in error_msg


def test_config_empty_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that empty API key raises ValidationError."""
    monkeypatch.setenv("BAILIAN_API_KEY", "")

    with pytest.raises(ValidationError) as exc_info:
        get_config()

    error_msg = str(exc_info.value)
    assert "BAILIAN_API_KEY is required" in error_msg


def test_config_placeholder_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that placeholder API key raises ValidationError."""
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-xxx")

    with pytest.raises(ValidationError) as exc_info:
        get_config()

    error_msg = str(exc_info.value)
    assert "BAILIAN_API_KEY is required" in error_msg


def test_config_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid log level raises ValidationError."""
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-valid-key")
    monkeypatch.setenv("LOG_LEVEL", "INVALID")

    with pytest.raises(ValidationError) as exc_info:
        get_config()

    error_msg = str(exc_info.value)
    assert "Invalid log_level" in error_msg


def test_config_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that environment variables are case-insensitive."""
    monkeypatch.setenv("bailian_api_key", "sk-lowercase-key")
    monkeypatch.setenv("log_level", "debug")

    config = get_config()

    assert config.bailian_api_key == "sk-lowercase-key"
    assert config.log_level == "DEBUG"  # normalized to uppercase


def test_config_extra_fields_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that extra environment variables are ignored."""
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-valid-key")
    monkeypatch.setenv("UNKNOWN_FIELD", "some-value")

    config = get_config()

    assert config.bailian_api_key == "sk-valid-key"
    assert not hasattr(config, "unknown_field")
