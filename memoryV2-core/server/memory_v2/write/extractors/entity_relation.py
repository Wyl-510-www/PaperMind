"""ENTITY_RELATION lane extractor: 抽取第三方实体关系"""

from __future__ import annotations

import logging
from uuid import uuid4

from server.memory_v2.contracts import MemoryCandidate, MemoryType, Modality, SubjectRef, LaneOutcome
from server.memory_v2.write.extractors.base import BaseExtractor, ExtractionInput
from server.memory_v2.lane_prompts import ENTITY_RELATION_PROMPT

logger = logging.getLogger(__name__)


class EntityRelationExtractor(BaseExtractor):
    """ENTITY_RELATION lane: 第三方实体关系"""

    async def extract(self, input: ExtractionInput) -> LaneOutcome:
        """P0-3修复：返回LaneOutcome保留完整错误信息"""
        if self.llm_client is None:
            return LaneOutcome(
                lane="entity_relation",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )

        # P0-3修复：处理新的tuple返回格式 (data, error_code, error_message)
        result, error_code, error_message = await self.llm_client.structured_extract(
            system_prompt=ENTITY_RELATION_PROMPT,
            user_text=input.user_text,
        )

        # P0-3核心修复：错误时返回带错误信息的LaneOutcome
        if result is None:
            if error_code == "PARSE_ERROR":
                return LaneOutcome(
                    lane="entity_relation",
                    status="parse_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            elif error_code == "API_ERROR":
                return LaneOutcome(
                    lane="entity_relation",
                    status="api_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            else:
                return LaneOutcome(
                    lane="entity_relation",
                    status="success_empty",
                    candidates=[],
                    error_code=None,
                    error_message=None,
                )

        candidates = []
        for item in result.get("relations", []):
            try:
                candidate = MemoryCandidate(
                    candidate_id=f"rel-{uuid4().hex[:12]}",
                    normalized_text_zh=item["text"],
                    subject=SubjectRef(kind="person", canonical_name=item.get("entity_name", "第三方"), is_current_user=False),
                    predicate=item.get("relation_type", "unknown"),
                    value=item.get("text", ""),
                    memory_type=MemoryType.ENTITY_RELATION,
                    modality=Modality.FACT,
                    confidence=0.8,
                    durability="stable",
                    source_span=item.get("source_span", ""),
                )
                if self._validate_source_span(candidate, input.user_text):
                    candidates.append(candidate)
            except Exception:
                logger.warning("ENTITY_RELATION candidate build failed: %s", item, exc_info=True)

        # P0-3修复：返回成功的LaneOutcome
        if candidates:
            return LaneOutcome(
                lane="entity_relation",
                status="success",
                candidates=candidates,
                error_code=None,
                error_message=None,
            )
        else:
            return LaneOutcome(
                lane="entity_relation",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )
