"""DashScope OpenAI 兼容网关 — 结构化抽取客户端。

模型：qwen3.5-plus。使用 response_format json_object + enable_thinking=false。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from server.core.settings import Config_Bailian

logger = logging.getLogger(__name__)

_client: DashScopeClient | None = None


class DashScopeClient:
    """qwen3.5-plus 结构化抽取客户端"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=Config_Bailian.API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=30.0,
        )
        self.model = Config_Bailian.MODEL_QWEN_35_PLUS  # "qwen3.5-plus"

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """纯文本对话。失败返回 None。"""
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs,
            )
            return resp.choices[0].message.content or ""
        except Exception:
            logger.warning("DashScope chat 失败", exc_info=True)
            return None

    async def structured_extract(
        self,
        system_prompt: str,
        user_text: str,
        existing_truths: list[dict] | None = None,  # P0-1新增参数
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        """结构化抽取。使用 response_format json_object。

        Args:
            system_prompt: 抽取指令 + JSON Schema 描述
            user_text: 用户输入原文
            existing_truths: 现有truths列表（P0-1），用于UPDATE_DELETE lane识别真实的历史陈述

        Returns:
            tuple: (解析后的JSON dict或None, error_code或None, error_message或None)
            - 成功: (data, None, None)
            - JSON解析失败: (None, "PARSE_ERROR", error_message)
            - API调用失败: (None, "API_ERROR", error_message)
        """
        try:
            # P0-1修复：如果提供了existing_truths，附加到system_prompt末尾
            effective_system_prompt = system_prompt
            if existing_truths:
                truths_text = "\n\n【用户已存在的truths】\n"
                for truth in existing_truths:
                    truths_text += f"- {truth.get('subject', 'user')}: {truth.get('predicate', '')}: {truth.get('value', '')}\n"
                truths_text += "\n只有这些truths是真实存在的旧值。如果要形成supersede关系，必须引用这些truths中的某一条。"
                effective_system_prompt = system_prompt + truths_text

            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": effective_system_prompt},
                    {"role": "user", "content": user_text},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=1024,
                extra_body={"enable_thinking": False},
            )
            content = resp.choices[0].message.content or ""
            parsed_data = json.loads(content)
            # P0-3修复：成功时返回数据和None错误
            return (parsed_data, None, None)
        except json.JSONDecodeError as e:
            error_msg = f"JSON 解析失败: {str(e)}, content: {content[:200] if 'content' in locals() else 'N/A'}"
            logger.warning("DashScope structured_extract %s", error_msg)
            # P0-3修复：返回错误码和错误消息
            return (None, "PARSE_ERROR", error_msg)
        except Exception as e:
            error_msg = f"API 调用失败: {str(e)}"
            logger.warning("DashScope structured_extract %s", exc_info=True)
            # P0-3修复：返回错误码和错误消息
            return (None, "API_ERROR", error_msg)


def get_client() -> DashScopeClient:
    """模块级单例"""
    global _client
    if _client is None:
        _client = DashScopeClient()
    return _client
