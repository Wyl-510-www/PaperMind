"""证据等级派生：从 confidence + modality + status 推导 evidence_level。

evidence_level 决定 Claim Guard 对该证据的断言策略（原方案 7.2）：
- confirmed：允许「我记得你不吃香菜」直接断言
- probable：只允许「我印象里好像…对吗」带不确定性表述
- inferred：不得声称用户具体偏好
- none：不得用于任何断言（删除/玩笑/引用等）

阈值为命名常量，不散落魔数。Phase 2 约定「不随意给 confirmed/probable 分界线」，
此处落地为可调常量 + ADR 记录取值依据。

见 ADR 0007（evidence_level 派生规则）。
"""

from __future__ import annotations

from ..contracts import Modality


# 证据等级阈值（可后续调优，记为常量避免魔数）
CONFIRMED_THRESHOLD = 0.8  # >= 0.8 且 fact + active → confirmed
PROBABLE_THRESHOLD = 0.5   # [0.5, 0.8) → probable


def derive_evidence_level(
    confidence: float,
    modality: Modality,
    status: str,
) -> str:
    """从 confidence + modality + status 派生 evidence_level。

    返回 "confirmed" / "probable" / "inferred" / "none" 之一。

    优先级（自上而下）：
    1. status 终止态（deleted/superseded） → none
    2. modality 不可断言（joke/quote/question） → none
    3. confidence + modality 组合推导 confirmed/probable/inferred
    """
    # 优先级 1：status 终止态
    if status in ("deleted", "superseded", "expired"):
        return "none"

    # 优先级 2：modality 不可断言
    if modality in (Modality.JOKE, Modality.QUOTE, Modality.QUESTION):
        return "none"

    # 优先级 3：confidence + modality 组合
    if confidence >= CONFIRMED_THRESHOLD and modality == Modality.FACT:
        return "confirmed"

    if modality in (Modality.HYPOTHESIS, Modality.PLAN, Modality.WISH):
        # 这些模态即使高置信度也不超过 probable
        if confidence >= PROBABLE_THRESHOLD:
            return "probable"
        else:
            return "inferred"

    if modality == Modality.UNCERTAIN:
        return "inferred"

    # fact / 其他模态：按 confidence 分档
    if confidence >= CONFIRMED_THRESHOLD:
        return "confirmed"
    elif confidence >= PROBABLE_THRESHOLD:
        return "probable"
    else:
        return "inferred"
