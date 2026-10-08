"""LLM client wrapper for DashScope API.

This module provides a unified interface for calling LLM models via DashScope
using the OpenAI-compatible API.
"""

import logging
from typing import Any

from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError

from papermind.config import Config

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Base exception for LLM client errors."""

    pass


class LLMAPIError(LLMClientError):
    """Exception raised when LLM API call fails."""

    pass


class LLMRateLimitError(LLMClientError):
    """Exception raised when rate limit is exceeded."""

    pass


class LLMConnectionError(LLMClientError):
    """Exception raised when connection to LLM API fails."""

    pass


class LLMClient:
    """Client for calling LLM models via DashScope API.

    This class wraps the OpenAI SDK to provide a simplified interface
    for making LLM calls to DashScope (Qwen models).

    Attributes:
        config: Configuration object containing API credentials and settings
        client: AsyncOpenAI client instance

    Example:
        >>> config = get_config()
        >>> client = LLMClient(config)
        >>> messages = [{"role": "user", "content": "Hello"}]
        >>> reply = await client.chat(messages)
        >>> print(reply)
    """

    def __init__(self, config: Config) -> None:
        """Initialize LLM client.

        Args:
            config: Configuration object with API key and model settings
        """
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.bailian_api_key,
            base_url=config.llm_base_url,
        )
        logger.info(f"Initialized LLM client with model: {config.llm_model}")

    async def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Call LLM with messages and return response text.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional arguments to pass to the API (e.g., temperature, max_tokens)

        Returns:
            Response text from the LLM

        Raises:
            LLMRateLimitError: If rate limit is exceeded
            LLMConnectionError: If connection to API fails
            LLMAPIError: If API returns an error

        Example:
            >>> messages = [
            ...     {"role": "system", "content": "You are a helpful assistant."},
            ...     {"role": "user", "content": "What is the capital of France?"}
            ... ]
            >>> reply = await client.chat(messages)
        """
        try:
            logger.debug(f"Calling LLM with {len(messages)} messages")

            response = await self.client.chat.completions.create(
                model=self.config.llm_model,
                messages=messages,  # type: ignore
                **kwargs,
            )

            reply = response.choices[0].message.content
            if reply is None:
                raise LLMAPIError("LLM returned empty response")

            logger.debug(f"LLM response length: {len(reply)} characters")
            return reply

        except RateLimitError as e:
            logger.error(f"Rate limit exceeded: {e}")
            raise LLMRateLimitError(f"Rate limit exceeded: {e}") from e

        except APIConnectionError as e:
            logger.error(f"Connection error: {e}")
            raise LLMConnectionError(f"Failed to connect to LLM API: {e}") from e

        except LLMAPIError:
            # Re-raise our own exceptions without wrapping
            raise

        except APIError as e:
            logger.error(f"API error: {e}")
            raise LLMAPIError(f"LLM API error: {e}") from e

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise LLMClientError(f"Unexpected error during LLM call: {e}") from e

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Synchronous version of chat method.

        This is a convenience method that wraps the async chat() call.
        For better performance, use the async version directly.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional arguments to pass to the API

        Returns:
            Response text from the LLM

        Raises:
            LLMRateLimitError: If rate limit is exceeded
            LLMConnectionError: If connection to API fails
            LLMAPIError: If API returns an error
        """
        import asyncio

        return asyncio.run(self.chat(messages, **kwargs))

    async def chat_with_memory(
        self,
        user_message: str,
        tenant_id: str,
        user_id: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """支持记忆检索的对话接口。

        此方法在调用 LLM 前先检索用户的长期记忆，将检索到的记忆注入到 prompt 中，
        使 LLM 的回复能够基于用户的历史信息。

        Args:
            user_message: 用户的输入消息
            tenant_id: 租户 ID，用于记忆隔离
            user_id: 用户 ID，用于记忆隔离
            system_prompt: 可选的系统提示词，如果不提供则只使用记忆上下文
            **kwargs: 传递给 LLM API 的其他参数

        Returns:
            LLM 的回复文本

        Raises:
            LLMRateLimitError: 如果超过速率限制
            LLMConnectionError: 如果连接 API 失败
            LLMAPIError: 如果 API 返回错误

        Example:
            >>> client = LLMClient(config)
            >>> reply = await client.chat_with_memory(
            ...     user_message="我的研究方向是什么",
            ...     tenant_id="tenant_default",
            ...     user_id="alice"
            ... )
            >>> print(reply)

        Note:
            记忆检索失败不会阻断 LLM 回复，会使用降级策略（见 memory_retrieval 模块）。
        """
        from papermind.memory_retrieval import retrieve_memory_context

        # 1. 检索用户长期记忆
        memory_context = await retrieve_memory_context(
            query=user_message,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=self.config.memory_retrieval_limit,
        )

        logger.debug(
            f"Retrieved memory context for user {user_id} in tenant {tenant_id}: "
            f"{len(memory_context)} characters"
        )

        # 2. 构造包含记忆的 prompt
        messages = []

        # 系统提示词（如果提供）
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 记忆上下文（作为系统消息注入）
        messages.append({"role": "system", "content": memory_context})

        # 用户消息
        messages.append({"role": "user", "content": user_message})

        # 3. 调用 LLM
        return await self.chat(messages, **kwargs)
