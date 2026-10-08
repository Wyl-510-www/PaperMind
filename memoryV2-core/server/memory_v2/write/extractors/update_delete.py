"""UPDATE_DELETE lane extractor: 抽取更新和删除指令"""

from __future__ import annotations

import logging
from uuid import uuid4

from server.memory_v2.contracts import MemoryCandidate, MemoryType, Modality, SubjectRef, LaneOutcome
from server.memory_v2.write.extractors.base import BaseExtractor, ExtractionInput
from server.memory_v2.lane_prompts import UPDATE_DELETE_PROMPT

logger = logging.getLogger(__name__)


class UpdateDeleteExtractor(BaseExtractor):
    """UPDATE_DELETE lane: 显式更新/删除/纠正

    P0-1修复：禁止在无旧truth或prior_source_turn的情况下创造历史陈述。
    查询现有truths并传递给LLM，帮助识别真实的历史陈述。
    """

    async def extract(self, input: ExtractionInput) -> LaneOutcome:
        """P0-3修复：返回LaneOutcome保留完整错误信息

        P0-1修复：禁止在无旧truth或prior_source_turn的情况下创造历史陈述。
        查询现有truths并传递给LLM，帮助识别真实的历史陈述。
        """
        if self.llm_client is None:
            return LaneOutcome(
                lane="update_delete",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )

        # P0-1核心修复：查询现有truths作为LLM上下文
        existing_truths = self._query_related_truths(input.user_id)

        # P0-3修复：处理新的tuple返回格式 (data, error_code, error_message)
        result, error_code, error_message = await self.llm_client.structured_extract(
            system_prompt=UPDATE_DELETE_PROMPT,
            user_text=input.user_text,
            existing_truths=existing_truths,  # P0-1: 传递现有truths
        )

        # P0-3核心修复：错误时返回带错误信息的LaneOutcome
        if result is None:
            if error_code == "PARSE_ERROR":
                return LaneOutcome(
                    lane="update_delete",
                    status="parse_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            elif error_code == "API_ERROR":
                return LaneOutcome(
                    lane="update_delete",
                    status="api_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            else:
                return LaneOutcome(
                    lane="update_delete",
                    status="success_empty",
                    candidates=[],
                    error_code=None,
                    error_message=None,
                )

        candidates = []
        for item in result.get("updates", []):
            try:
                action = item.get("action", "assert")
                polarity = item.get("polarity", "positive")
                temporal = item.get("temporal", "current")
                supersedes_hint = item.get("supersedes_hint")
                event_id_hint = item.get("event_id_hint")  # P2-2新增

                # P0-1核心修复：验证历史claim
                # 如果声称是过去的事实或要supersede，必须有依据
                if temporal == "past" or action == "correct":
                    if not supersedes_hint and temporal == "past":
                        # 声称"之前..."但没有supersede依据，拒绝
                        logger.warning(
                            "P0-1: Rejecting historical claim without evidence. "
                            f"text={item.get('text')}, temporal={temporal}, "
                            f"supersedes_hint={supersedes_hint}"
                        )
                        continue

                    if action == "correct" and not supersedes_hint:
                        # 声称correct但没有目标提示，降级为assert
                        logger.info(
                            "P0-1: Downgrading 'correct' to 'assert' due to missing supersedes_hint. "
                            f"text={item.get('text')}"
                        )
                        action = "assert"

                # P2-2修复：为cancel操作构建特殊的value结构
                if action == "cancel" and event_id_hint:
                    value_dict = {
                        "text": item.get("text", ""),
                        "action": "cancel",
                        "event_id_hint": event_id_hint,
                    }
                else:
                    value_dict = item.get("text", "")

                candidate = MemoryCandidate(
                    candidate_id=f"upd-{uuid4().hex[:12]}",
                    normalized_text_zh=item["text"],
                    subject=SubjectRef(kind="user", canonical_name=input.user_id, is_current_user=True),
                    predicate="memory.update" if action in ("correct", "reschedule") else "memory.assert",
                    value=value_dict,
                    memory_type=MemoryType.SEMANTIC,
                    modality=Modality.FACT,
                    polarity=polarity,  # P0-1: 保留极性
                    confidence=0.9,
                    durability="stable",
                    source_span=item.get("source_span", ""),
                    explicit_update=action in ("correct", "reschedule"),
                    explicit_delete=action in ("delete", "cancel"),
                    target_hint=supersedes_hint or item.get("target_hint"),
                    operation=action,  # P2-2: 保留operation类型
                )

                if self._validate_source_span(candidate, input.user_text):
                    candidates.append(candidate)
                else:
                    logger.warning(
                        "P0-1: Source span validation failed. "
                        f"source_span={item.get('source_span')}, user_text={input.user_text[:100]}"
                    )

            except Exception:
                logger.warning("UPDATE_DELETE candidate build failed: %s", item, exc_info=True)

        # P0-3修复：返回成功的LaneOutcome
        if candidates:
            return LaneOutcome(
                lane="update_delete",
                status="success",
                candidates=candidates,
                error_code=None,
                error_message=None,
            )
        else:
            return LaneOutcome(
                lane="update_delete",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )

    def _query_related_truths(self, user_id: str) -> list[dict]:
        """查询用户现有的活跃truths（P0-1核心功能）

        Args:
            user_id: 用户ID

        Returns:
            truths列表，每个truth包含 subject, predicate, object_value 字段
            如果fact_store未配置，返回空列表
        """
        if self.fact_store is None:
            logger.debug("P0-1: fact_store未配置，无法查询existing truths")
            return []

        try:
            facts = self.fact_store.list_facts(
                tenant_id=self.tenant_id,
                user_id=str(user_id),
                status="active",
                namespace="user_memory"
            )

            # 转换为简化的字典格式供LLM使用
            truths = []
            for fact in facts:
                truths.append({
                    "subject": fact.subject,
                    "predicate": fact.predicate,
                    "value": fact.object_value,
                })

            logger.info(f"P0-1: 查询到 {len(truths)} 条existing truths for user {user_id}")
            return truths

        except Exception:
            logger.warning("P0-1: 查询existing truths失败", exc_info=True)
            return []
