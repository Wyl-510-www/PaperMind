"""Extractor 基类：统一接口定义

每个 lane 的 extractor 实现此接口，用独立 Prompt + Schema 抽取。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from server.memory_v2.contracts import MemoryCandidate, LaneOutcome


class ExtractionInput:
    """抽取输入（统一结构）"""
    def __init__(
        self,
        user_text: str,
        user_id: str,
        turn_id: str,
        occurred_at: str,
        previous_user_text: str | None = None,
        message_time: str | None = None,
        user_timezone: str | None = None,
    ):
        self.user_text = user_text
        self.user_id = user_id
        self.turn_id = turn_id
        self.occurred_at = occurred_at
        # P1-1: 前一轮用户消息，供 extractor 作为抽取上下文（可选）
        self.previous_user_text = previous_user_text
        # P2-1: 消息时间和用户时区，用于相对时间表达的规范化
        self.message_time = message_time  # ISO 8601格式的消息发送时间
        self.user_timezone = user_timezone  # IANA时区标识符，如"America/New_York"


class BaseExtractor(ABC):
    """抽取器基类：每个 lane 实现此接口"""

    def __init__(self, llm_client=None, fact_store=None, tenant_id: str = "default"):
        """Args:
            llm_client: DashScopeClient 或兼容接口。None 时仅用于测试
            fact_store: FactStore 实例，用于查询现有truths（P0-1）。None 时不查询
            tenant_id: 租户ID，用于查询truths时的过滤（P0-1）
        """
        self.llm_client = llm_client
        self.fact_store = fact_store  # P0-1新增
        self.tenant_id = tenant_id  # P0-1新增

    @abstractmethod
    async def extract(self, input: ExtractionInput) -> LaneOutcome:
        """抽取记忆候选

        P0-3修复：返回LaneOutcome以保留完整的错误信息，避免信息丢失

        Args:
            input: 抽取输入（user_text + 元数据）

        Returns:
            LaneOutcome包含:
            - status: success/success_empty/api_error/parse_error/extraction_error
            - candidates: MemoryCandidate列表
            - error_code/error_message: 错误时的详细信息
        """
        pass

    def _validate_source_span(self, candidate: MemoryCandidate, user_text: str) -> bool:
        """校验 source_span 存在于 user_text 中。

        采用宽松匹配：LLM 返回的 source_span 常在数字、空白等细节上与原文存在
        差异（如 "25 分钟" vs "25分钟"、"11 月 8 日" vs "11月8日"），
        精确子串匹配会把这类合法候选误判为幻觉而丢弃。

        修复策略（由严格到宽松，逐级降级）：
        1. 精确子串匹配（原行为）
        2. 去除所有空白字符后子串匹配
        3. 去除空白 + 标点后子串匹配
        仍不命中才判定为无效（保留对明显幻觉的拦截能力）。
        """
        span = candidate.source_span or ""
        if not span:
            # 无 source_span 时放宽通过（部分 LLM 可能未返回该字段）
            return True

        if span in user_text:
            return True

        # 归一化：去空白
        def _strip_ws(s: str) -> str:
            return re.sub(r"\s+", "", s)

        if _strip_ws(span) in _strip_ws(user_text):
            return True

        # 归一化：去空白 + 常见中英文标点
        def _strip_ws_punct(s: str) -> str:
            return re.sub(r"[\s\u3000-\u303f\uff00-\uffef，。！？、；：（）,.!?;:()\[\]]+", "", s)

        if _strip_ws_punct(span) in _strip_ws_punct(user_text):
            return True

        return False
