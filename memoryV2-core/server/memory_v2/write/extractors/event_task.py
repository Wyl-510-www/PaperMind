"""EVENT_TASK lane extractor: 抽取事件和任务"""

from __future__ import annotations

import logging
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional
import re

from server.memory_v2.contracts import MemoryCandidate, MemoryType, Modality, SubjectRef, TimeCandidate, LaneOutcome
from server.memory_v2.write.extractors.base import BaseExtractor, ExtractionInput
from server.memory_v2.lane_prompts import EVENT_TASK_PROMPT

logger = logging.getLogger(__name__)


class EventTaskExtractor(BaseExtractor):
    """EVENT_TASK lane: 事件/任务 + 时间范围"""

    async def extract(self, input: ExtractionInput) -> LaneOutcome:
        """P0-3修复：返回LaneOutcome保留完整错误信息"""
        if self.llm_client is None:
            return LaneOutcome(
                lane="event_task",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )

        # P0-3修复：处理新的tuple返回格式 (data, error_code, error_message)
        result, error_code, error_message = await self.llm_client.structured_extract(
            system_prompt=EVENT_TASK_PROMPT,
            user_text=input.user_text,
        )

        # P0-3核心修复：错误时返回带错误信息的LaneOutcome
        if result is None:
            if error_code == "PARSE_ERROR":
                return LaneOutcome(
                    lane="event_task",
                    status="parse_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            elif error_code == "API_ERROR":
                return LaneOutcome(
                    lane="event_task",
                    status="api_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            else:
                return LaneOutcome(
                    lane="event_task",
                    status="success_empty",
                    candidates=[],
                    error_code=None,
                    error_message=None,
                )

        candidates = []
        for item in result.get("events", []):
            try:
                memory_type = MemoryType.TASK if item.get("event_type") == "task" else MemoryType.EPISODIC

                # P2-1修复：处理时间规范化
                time_candidate = self._normalize_time_expression(
                    original_expression=item.get("original_time_expression") or item.get("start_expr"),
                    timezone_mentioned=item.get("timezone_mentioned"),
                    message_time=input.message_time,
                    user_timezone=input.user_timezone,
                )

                # P2-2修复：处理有效期和截止时间
                valid_from = None
                valid_to = None
                due_time = None

                if item.get("valid_from_expr"):
                    valid_from = self._normalize_time_expression(
                        original_expression=item.get("valid_from_expr"),
                        timezone_mentioned=item.get("timezone_mentioned"),
                        message_time=input.message_time,
                        user_timezone=input.user_timezone,
                    )

                if item.get("valid_to_expr"):
                    valid_to = self._normalize_time_expression(
                        original_expression=item.get("valid_to_expr"),
                        timezone_mentioned=item.get("timezone_mentioned"),
                        message_time=input.message_time,
                        user_timezone=input.user_timezone,
                    )

                if item.get("due_time_expr"):
                    due_time = self._normalize_time_expression(
                        original_expression=item.get("due_time_expr"),
                        timezone_mentioned=item.get("timezone_mentioned"),
                        message_time=input.message_time,
                        user_timezone=input.user_timezone,
                    )

                # 构建value字段，包含时间元数据和生命周期信息
                value_dict = {
                    "text": item.get("text", ""),
                    "status": item.get("status", "scheduled"),
                    "recurrence": item.get("recurrence"),
                    "original_time_expression": item.get("original_time_expression"),
                    "timezone_mentioned": item.get("timezone_mentioned"),
                    "valid_from": valid_from.absolute_start.isoformat() if valid_from and valid_from.absolute_start else None,
                    "valid_to": valid_to.absolute_start.isoformat() if valid_to and valid_to.absolute_start else None,
                    "due_time": due_time.absolute_start.isoformat() if due_time and due_time.absolute_start else None,
                }

                candidate = MemoryCandidate(
                    candidate_id=f"evt-{uuid4().hex[:12]}",
                    normalized_text_zh=item["text"],
                    subject=SubjectRef(kind="user", canonical_name=input.user_id, is_current_user=True),
                    predicate="event.occurrence" if memory_type == MemoryType.EPISODIC else "task.pending",
                    value=value_dict,
                    memory_type=memory_type,
                    modality=Modality.PLAN,
                    confidence=0.85,
                    durability="episodic",
                    source_span=item.get("source_span", ""),
                    time=time_candidate,
                )
                if self._validate_source_span(candidate, input.user_text):
                    candidates.append(candidate)
            except Exception:
                logger.warning("EVENT_TASK candidate build failed: %s", item, exc_info=True)

        # P0-3修复：返回成功的LaneOutcome
        if candidates:
            return LaneOutcome(
                lane="event_task",
                status="success",
                candidates=candidates,
                error_code=None,
                error_message=None,
            )
        else:
            return LaneOutcome(
                lane="event_task",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )

    def _normalize_time_expression(
        self,
        original_expression: Optional[str],
        timezone_mentioned: Optional[str],
        message_time: Optional[str],
        user_timezone: Optional[str],
    ) -> TimeCandidate:
        """P2-1: 规范化时间表达

        Args:
            original_expression: 用户原始时间表达（"明天"、"周六"、"下周三"）
            timezone_mentioned: 用户提到的时区
            message_time: 消息发送时间（ISO 8601格式）
            user_timezone: 用户时区

        Returns:
            TimeCandidate with resolved absolute time
        """
        if not original_expression:
            return TimeCandidate(
                original_expression=None,
                absolute_start=None,
                absolute_end=None,
                precision="unknown",
                resolved_by="none",
            )

        # 尝试解析相对时间表达
        resolved_time = None
        precision = "unknown"
        resolved_by = "deterministic"

        if message_time:
            try:
                # 解析message_time为datetime对象
                anchor_time = datetime.fromisoformat(message_time.replace('Z', '+00:00'))

                # 相对时间表达的确定性规则
                expr_lower = original_expression.lower()

                # "明天"
                if "明天" in expr_lower or "tomorrow" in expr_lower:
                    resolved_time = anchor_time + timedelta(days=1)
                    precision = "day"

                # "后天"
                elif "后天" in expr_lower:
                    resolved_time = anchor_time + timedelta(days=2)
                    precision = "day"

                # "今天"
                elif "今天" in expr_lower or "today" in expr_lower:
                    resolved_time = anchor_time
                    precision = "day"

                # "这周" / "本周"
                elif "这周" in expr_lower or "本周" in expr_lower or "this week" in expr_lower:
                    resolved_time = anchor_time
                    precision = "day"

                # "下周"
                elif "下周" in expr_lower or "next week" in expr_lower:
                    resolved_time = anchor_time + timedelta(days=7)
                    precision = "day"

                # "N天后" / "N天内"
                day_match = re.search(r'(\d+)\s*天[后内]', original_expression)
                if day_match:
                    days = int(day_match.group(1))
                    resolved_time = anchor_time + timedelta(days=days)
                    precision = "day"

                # "N小时后"
                hour_match = re.search(r'(\d+)\s*[个]?小时后', original_expression)
                if hour_match:
                    hours = int(hour_match.group(1))
                    resolved_time = anchor_time + timedelta(hours=hours)
                    precision = "minute"

            except Exception as e:
                logger.warning(f"Time normalization failed for '{original_expression}': {e}")
                resolved_by = "none"

        return TimeCandidate(
            original_expression=original_expression,
            absolute_start=resolved_time,
            absolute_end=None,
            precision=precision,
            resolved_by=resolved_by,
        )

