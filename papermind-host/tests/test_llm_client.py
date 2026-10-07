"""Tests for LLM client module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from openai import APIError, RateLimitError, APIConnectionError

from papermind.config import Config
from papermind.llm_client import (
    LLMClient,
    LLMAPIError,
    LLMRateLimitError,
    LLMConnectionError,
)


@pytest.fixture
def mock_config() -> Config:
    """Create a mock configuration for testing."""
    return Config(
        bailian_api_key="sk-test-key-12345",
        llm_model="qwen-max",
        llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        log_level="INFO",
    )


@pytest.fixture
def llm_client(mock_config: Config) -> LLMClient:
    """Create an LLM client instance for testing."""
    return LLMClient(mock_config)


@pytest.mark.asyncio
async def test_chat_success(llm_client: LLMClient) -> None:
    """Test successful LLM chat call."""
    # Mock the OpenAI client response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello! How can I help you?"

    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        messages = [{"role": "user", "content": "Hello"}]
        reply = await llm_client.chat(messages)

        assert reply == "Hello! How can I help you?"


@pytest.mark.asyncio
async def test_chat_with_system_message(llm_client: LLMClient) -> None:
    """Test LLM chat with system message."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Paris is the capital of France."

    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_create:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France?"},
        ]
        reply = await llm_client.chat(messages)

        assert reply == "Paris is the capital of France."
        # Verify that the correct messages were passed
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["messages"] == messages


@pytest.mark.asyncio
async def test_chat_with_kwargs(llm_client: LLMClient) -> None:
    """Test LLM chat with additional kwargs."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test response"

    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_create:
        messages = [{"role": "user", "content": "Test"}]
        reply = await llm_client.chat(
            messages,
            temperature=0.5,
            max_tokens=100,
        )

        assert reply == "Test response"
        # Verify that kwargs were passed through
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 100


@pytest.mark.asyncio
async def test_chat_empty_response(llm_client: LLMClient) -> None:
    """Test handling of empty LLM response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = None

    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        messages = [{"role": "user", "content": "Hello"}]

        with pytest.raises(LLMAPIError) as exc_info:
            await llm_client.chat(messages)

        assert "empty response" in str(exc_info.value)


@pytest.mark.asyncio
async def test_chat_rate_limit_error(llm_client: LLMClient) -> None:
    """Test handling of rate limit error."""
    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        side_effect=RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        ),
    ):
        messages = [{"role": "user", "content": "Hello"}]

        with pytest.raises(LLMRateLimitError) as exc_info:
            await llm_client.chat(messages)

        assert "Rate limit exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_chat_connection_error(llm_client: LLMClient) -> None:
    """Test handling of connection error."""
    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        side_effect=APIConnectionError(request=MagicMock()),
    ):
        messages = [{"role": "user", "content": "Hello"}]

        with pytest.raises(LLMConnectionError) as exc_info:
            await llm_client.chat(messages)

        assert "Failed to connect" in str(exc_info.value)


@pytest.mark.asyncio
async def test_chat_api_error(llm_client: LLMClient) -> None:
    """Test handling of general API error."""
    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        side_effect=APIError(
            message="Invalid request",
            request=MagicMock(),
            body=None,
        ),
    ):
        messages = [{"role": "user", "content": "Hello"}]

        with pytest.raises(LLMAPIError) as exc_info:
            await llm_client.chat(messages)

        assert "API error" in str(exc_info.value)


def test_chat_sync(llm_client: LLMClient) -> None:
    """Test synchronous chat method."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Sync response"

    with patch.object(
        llm_client.client.chat.completions,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        messages = [{"role": "user", "content": "Hello"}]
        reply = llm_client.chat_sync(messages)

        assert reply == "Sync response"


def test_client_initialization(mock_config: Config) -> None:
    """Test LLM client initialization."""
    client = LLMClient(mock_config)

    assert client.config == mock_config
    assert client.client is not None
    assert client.client.api_key == "sk-test-key-12345"
    # OpenAI client normalizes base_url by adding trailing slash
    assert (
        str(client.client.base_url).rstrip("/")
        == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
