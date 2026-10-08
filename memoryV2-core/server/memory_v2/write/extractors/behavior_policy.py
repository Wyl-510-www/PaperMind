"""BEHAVIOR_POLICY lane extractor: 抽取行为约束和边界"""

from __future__ import annotations

import logging
from uuid import uuid4

from server.memory_v2.contracts import MemoryCandidate, MemoryType, Modality, SubjectRef, LaneOutcome
from server.memory_v2.write.extractors.base import BaseExtractor, ExtractionInput
from server.memory_v2.lane_prompts import BEHAVIOR_POLICY_PROMPT

logger = logging.getLogger(__name__)


class BehaviorPolicyExtractor(BaseExtractor):
    """BEHAVIOR_POLICY lane: 行为边界、称呼偏好、回复风格

    P1-2修复：支持称呼方向识别
    """

    async def extract(self, input: ExtractionInput) -> LaneOutcome:
        """P0-3修复：返回LaneOutcome保留完整错误信息"""
        if self.llm_client is None:
            return LaneOutcome(
                lane="behavior_policy",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )

        # P0-3修复：处理新的tuple返回格式 (data, error_code, error_message)
        result, error_code, error_message = await self.llm_client.structured_extract(
            system_prompt=BEHAVIOR_POLICY_PROMPT,
            user_text=input.user_text,
        )

        # P0-3核心修复：错误时返回带错误信息的LaneOutcome
        if result is None:
            if error_code == "PARSE_ERROR":
                return LaneOutcome(
                    lane="behavior_policy",
                    status="parse_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            elif error_code == "API_ERROR":
                return LaneOutcome(
                    lane="behavior_policy",
                    status="api_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            else:
                return LaneOutcome(
                    lane="behavior_policy",
                    status="success_empty",
                    candidates=[],
                    error_code=None,
                    error_message=None,
                )

        candidates = []
        for item in result.get("policies", []):
            try:
                # P1-2修复：根据direction确定subject
                direction = item.get("direction", "assistant_to_user")
                subject_kind = item.get("subject", "user")
                target_kind = item.get("target", None)

                # 确定主体引用
                if subject_kind == "current_user":
                    subject = SubjectRef(kind="user", canonical_name=input.user_id, is_current_user=True)
                elif subject_kind == "assistant":
                    subject = SubjectRef(kind="assistant", canonical_name="assistant", is_current_user=False)
                else:
                    # 默认是用户
                    subject = SubjectRef(kind="user", canonical_name=input.user_id, is_current_user=True)

                candidate = MemoryCandidate(
                    candidate_id=f"pol-{uuid4().hex[:12]}",
                    normalized_text_zh=item["text"],
                    subject=subject,
                    predicate=f"policy.{item.get('kind', 'unknown')}",
                    value=item.get("text", ""),
                    memory_type=MemoryType.BEHAVIOR_POLICY,
                    modality=Modality.FACT,
                    confidence=0.9,
                    durability="stable",
                    source_span=item.get("source_span", ""),
                )

                # P1-2修复：保存direction和target到metadata（通过value字段的扩展或新字段）
                # 注意：MemoryCandidate的value字段是Any类型，可以存储结构化数据
                candidate.value = {
                    "text": item.get("text", ""),
                    "direction": direction,
                    "target": target_kind,
                    "forbidden_terms": item.get("forbidden_terms", []),
                    "allowed_terms": item.get("allowed_terms", []),
                }

                if self._validate_source_span(candidate, input.user_text):
                    candidates.append(candidate)
            except Exception:
                logger.warning("BEHAVIOR_POLICY candidate build failed: %s", item, exc_info=True)

        # P0-3修复：返回成功的LaneOutcome
        if candidates:
            return LaneOutcome(
                lane="behavior_policy",
                status="success",
                candidates=candidates,
                error_code=None,
                error_message=None,
            )
        else:
            return LaneOutcome(
                lane="behavior_policy",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )
