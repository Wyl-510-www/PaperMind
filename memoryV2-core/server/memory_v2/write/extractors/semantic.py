"""SEMANTIC lane extractor: 抽取稳定偏好和长期事实"""

from __future__ import annotations

import logging
from uuid import uuid4

from server.memory_v2.contracts import MemoryCandidate, MemoryType, Modality, SubjectRef, LaneOutcome
from server.memory_v2.write.extractors.base import BaseExtractor, ExtractionInput
from server.memory_v2.lane_prompts import SEMANTIC_PROMPT

logger = logging.getLogger(__name__)


class SemanticExtractor(BaseExtractor):
    """SEMANTIC lane: 稳定偏好、长期事实"""

    async def extract(self, input: ExtractionInput) -> LaneOutcome:
        """P0-3修复：返回LaneOutcome保留完整错误信息"""
        if self.llm_client is None:
            return LaneOutcome(
                lane="semantic",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )

        # P0-3修复：处理新的tuple返回格式 (data, error_code, error_message)
        result, error_code, error_message = await self.llm_client.structured_extract(
            system_prompt=SEMANTIC_PROMPT,
            user_text=input.user_text,
        )

        # P0-3核心修复：错误时返回带错误信息的LaneOutcome
        if result is None:
            if error_code == "PARSE_ERROR":
                return LaneOutcome(
                    lane="semantic",
                    status="parse_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            elif error_code == "API_ERROR":
                return LaneOutcome(
                    lane="semantic",
                    status="api_error",
                    candidates=[],
                    error_code=error_code,
                    error_message=error_message,
                )
            else:
                # 未知错误
                return LaneOutcome(
                    lane="semantic",
                    status="success_empty",
                    candidates=[],
                    error_code=None,
                    error_message=None,
                )

        candidates = []
        for item in result.get("facts", []):
            try:
                text = item.get("text", "")
                predicate = item.get("predicate", "")
                # Ticket 04: 检测 provenance
                provenance = _detect_provenance(input.user_text, text)
                polarity = _detect_polarity(predicate, text) or "positive"
                domain, object_key = _extract_domain_object(predicate, text)

                # P1-3修复：提取condition和exception_of
                condition = item.get("condition", None)
                exception_of = item.get("exception_of", None)

                candidate = MemoryCandidate(
                    candidate_id=f"sem-{uuid4().hex[:12]}",
                    normalized_text_zh=text,
                    subject=SubjectRef(kind="user", canonical_name=input.user_id, is_current_user=True),
                    predicate=predicate,
                    value=text,
                    memory_type=MemoryType.SEMANTIC,
                    modality=Modality(item.get("modality", "fact")),
                    confidence=float(item.get("confidence", 0.8)),
                    durability="stable",
                    source_span=item.get("source_span", ""),
                    provenance=provenance,
                    polarity=polarity,
                    domain=domain,
                    object_key=object_key,
                    preference_strength=_detect_strength(text),
                )

                # P1-3修复：将condition和exception_of保存到value的结构化数据中
                # 扩展value为dict类型以支持更多元数据
                candidate.value = {
                    "text": text,
                    "condition": condition,
                    "exception_of": exception_of,
                }

                if self._validate_source_span(candidate, input.user_text):
                    candidates.append(candidate)
            except Exception:
                logger.warning("SEMANTIC candidate build failed: %s", item, exc_info=True)

        # P0-3修复：返回成功的LaneOutcome
        if candidates:
            return LaneOutcome(
                lane="semantic",
                status="success",
                candidates=candidates,
                error_code=None,
                error_message=None,
            )
        else:
            return LaneOutcome(
                lane="semantic",
                status="success_empty",
                candidates=[],
                error_code=None,
                error_message=None,
            )


# ---- Ticket 04: Preference provenance detection helpers ----

# 显式偏好声明标记（用户明确陈述）
EXPLICIT_PREFERENCE_MARKERS = [
    "我喜欢", "我最喜欢", "我爱", "我热爱", "我超爱", "我超喜欢",
    "我不吃", "我从不吃", "我讨厌", "我最讨厌", "我受不了",
    "我过敏", "我不能吃", "我戒了",
    "我平时", "我一直", "我长期", "我一般",
]

# 行为推断标记（从行为推断偏好，非明确陈述）
INFERRED_MARKERS = [
    "今天吃", "今天喝了", "买了", "刚吃了", "最近在吃",
    "想试试", "想尝", "打算试试",
]


def _detect_provenance(user_text: str, fact_text: str) -> str | None:
    """从用户原文检测偏好的来源质量。

    - confirmed: 用户明确陈述偏好（"我喜欢""我从不吃"）
    - inferred: 从行为推断（"今天吃了""买了"）
    - hypothesis: 其余情况不标记（None），由 Gate 和后续对话确认
    """
    for marker in EXPLICIT_PREFERENCE_MARKERS:
        if marker in user_text:
            return "confirmed"
    for marker in INFERRED_MARKERS:
        if marker in user_text:
            return "inferred"
    return None


def _detect_polarity(predicate: str, text: str) -> str | None:
    """检测偏好极性。"""
    negative_markers = [
        "不吃", "讨厌", "不喜欢", "从不", "受不了", "过敏", "不能", "戒了",
        # 修复: 增强否定偏好识别
        "别叫", "不要叫", "不想被叫", "不喜欢被", "不希望", "拒绝",
    ]
    for m in negative_markers:
        if m in text:
            return "negative"
    positive_markers = ["喜欢", "爱", "最爱", "热爱", "超爱"]
    for m in positive_markers:
        if m in text:
            return "positive"
    if "avoid" in predicate.lower() or "dislike" in predicate.lower() or "allergy" in predicate.lower():
        return "negative"
    if "like" in predicate.lower() or "prefer" in predicate.lower():
        return "positive"
    return None



def _boost_negative_importance(candidate) -> float:
    """为否定偏好/约束提升重要性权重
    
    修复: 提升否定偏好的召回优先级
    """
    importance = getattr(candidate, 'importance', None) or 0.5
    
    # 否定极性的偏好
    if hasattr(candidate, 'polarity') and candidate.polarity == "negative":
        importance = min(1.0, importance + 0.2)
    
    # 包含否定关键词的文本
    negative_keywords = ["不喜欢", "别", "不要", "禁止", "拒绝", "讨厌", "不想"]
    text = getattr(candidate, 'text_zh', '') or ''
    if any(kw in text for kw in negative_keywords):
        importance = min(1.0, importance + 0.15)
    
    return importance


def _extract_domain_object(predicate: str, text: str) -> tuple[str | None, str | None]:
    """从 predicate 和 text 中提取 domain 和 object_key。"""
    domain_map = {
        "diet": "food", "food": "food", "饮食": "food",
        "music": "music", "音乐": "music",
        "sport": "activity", "运动": "activity", "activity": "activity",
        "hobby": "activity", "爱好": "activity",
    }
    domain = None
    for key, val in domain_map.items():
        if key in predicate.lower():
            domain = val
            break
    # object_key 取 predicate 的最后一段或 text 中的关键词
    parts = predicate.split(".")
    object_key = parts[-1] if len(parts) > 1 else None
    return domain, object_key


def _detect_strength(text: str) -> str | None:
    """检测偏好强度。"""
    if any(m in text for m in ["最爱", "最喜欢", "超爱", "超喜欢", "热爱"]):
        return "favorite"
    if any(m in text for m in ["很喜欢", "非常喜欢", "特别爱"]):
        return "strong"
    if any(m in text for m in ["不讨厌", "还行", "一般"]):
        return "weak"
    return "normal"
