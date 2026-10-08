"""Precision-first write gate for extracted memory candidates.

LLM 负责抽取候选，本模块负责裁决：
- 是否接受写入
- 写到哪一层（semantic / state / entity_relation / discard 等）
- 生成 fact_key（semantic 层）或 ttl_seconds（state 层）

按 ADR 0001 错误代价不对称原则：不确定时默认拒绝。
规则只降级不升级：代码校验只能把 LLM 的 fact 降为 discard，不能反向升级。
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

from ..contracts import (
    DeterministicSignals,
    MemoryCandidate,
    MemoryType,
    Modality,
    WriteDecision,
)

# 这些 modality 的候选直接拒绝，不进入任何可检索存储
DISALLOWED_MODALITIES = {
    Modality.HYPOTHESIS,
    Modality.JOKE,
    Modality.QUOTE,
    Modality.QUESTION,
}

def detect_signals(text: str) -> DeterministicSignals:
    """从原文中检测确定性信号（关键词匹配）。

    只标记，不修改候选。检测到冲突时由 MemoryGate.decide() 降级处理。
    """
    return DeterministicSignals(
        has_hypothesis=any(x in text for x in ("如果", "假如", "要是", "万一")),
        has_joke_marker=any(x in text for x in ("开玩笑", "逗你的", "乱说的", "哈哈哈")),
        has_quote_marker=any(x in text for x in ("小说里", "台词是", "原文是", "引用", "书里")),
        has_temporary_marker=any(x in text for x in ("今天", "现在", "这次", "突然", "临时")),
        has_persistent_marker=any(x in text for x in ("一直", "长期", "从不", "平时", "总是")),
        has_cancel_marker=any(x in text for x in ("取消", "不去了", "不用了", "撤销", "算了")),
        has_complete_marker=any(x in text for x in ("完成了", "交了", "做完了", "结束了", "搞定了")),
    )


# P2-7 / ADR 0010：谓词基数。set 型多值共存，single 型单值覆盖。
# 未登记谓词默认 single（保守，符合 ADR 0001）。
# B5 修复：增加更多 SET 型谓词，支持多值共存
SET_CARDINALITY_PREDICATES: frozenset[str] = frozenset({
    # Preference 类（多个偏好对象应共存）
    "diet.dislike",   # 可不吃多种食物
    "diet.like",      # 可喜欢多种食物
    "hobby",          # 可有多个爱好
    "hobby.like",     # 喜欢的爱好
    "allergy",        # 可对多物过敏
    "taboo",          # 可有多个禁忌

    # Policy 类（多条行为规则应累加）
    "policy.safety",              # 安全底线（可有多条）
    "policy.privacy",             # 隐私边界（可有多条）
    "policy.content_exclusion",   # 内容排除（可有多条）
    "policy.relationship_boundary",  # 称呼边界（可禁止多个称呼）
    "policy.style",               # 回复风格（可有多个风格要求）
    "policy.repair",              # 纠错方式（可有多条偏好）
    "policy.uncertainty",         # 不确定时处理（可有多条规则）
})


def _predicate_cardinality(predicate: str) -> str:
    """返回谓词基数：'set'（多值共存）或 'single'（单值覆盖）。默认 single。"""
    return "set" if predicate in SET_CARDINALITY_PREDICATES else "single"


def build_fact_key(candidate: MemoryCandidate) -> str:
    """生成 fact_key，用于同一事实的版本化更新（P2-7 / ADR 0010）。

    - single 型谓词：{subject_id}:{predicate}，新值 supersede 旧值（如昵称、当前状态）
    - set 型谓词：{subject_id}:{predicate}:{value_hash}，不同 value 独立版本化，
      相同 value 的更新仍 supersede（如饮食禁忌可同时存多条）

    例：
      用户:nickname.current            （single）
      用户:diet.dislike:3a7bd3e2...    （set，含 value hash）

    注意：fact_key 与 MemoryRecord.subject_id 服务不同目的，故格式不同：
    - fact_key 是版本分组键，已被 (tenant_id, user_id, namespace, fact_key) 作用域限定，
      不需要 tenant/user 前缀，只需在同一 scope 内区分不同逻辑事实。
    - subject_id（由 fact_store 调 identity.build_subject_id 构造，带 current_user:t:u
      前缀）用于 hard_filter 的主体匹配。两者独立，不应混用。
    """
    # fact_key 的 subject 部分：entity_id 或 canonical_name（scope 已由存储层限定）
    subject_part = candidate.subject.entity_id or candidate.subject.canonical_name
    base = f"{subject_part}:{candidate.predicate}"

    if _predicate_cardinality(candidate.predicate) == "set":
        value_repr = str(candidate.value)
        value_hash = hashlib.sha256(value_repr.encode("utf-8")).hexdigest()[:12]
        return f"{base}:{value_hash}"
    return base


class MemoryGate:
    """写入门控。

    执行 7 条硬规则，输出 WriteDecision（accepted + route + reason_code）。
    所有不确定的情况默认拒绝（ADR 0001：错误代价不对称）。
    """

    def __init__(
        self,
        minimum_confidence: float = 0.60,
        semantic_minimum_confidence: float = 0.85,
    ) -> None:
        self.minimum_confidence = minimum_confidence
        self.semantic_minimum_confidence = semantic_minimum_confidence

    def decide(
        self,
        candidate: MemoryCandidate,
        signals: DeterministicSignals,
    ) -> WriteDecision:
        """裁决候选是否写入、写到哪一层。

        规则执行顺序（顺序有意义，越早的越宽泛）：
        1. 置信度过低 → 拒绝
        2. modality 本身不允许 → 拒绝
        3. 交叉校验：信号与 LLM 输出冲突 → 拒绝（只降级不升级）
        4. 第三方实体 → 路由到 entity_relation
        5. semantic 但非稳定 → 拒绝
        6. semantic 但置信度不足 → 拒绝
        7. state → 接受，带 TTL
        8. 其他已知类型 → 接受
        """
        # 规则 0：UPDATE_DELETE lane 的显式指令 → 降低置信度门槛
        is_explicit = getattr(candidate, 'explicit_update', False) or getattr(candidate, 'explicit_delete', False)
        effective_min_confidence = 0.40 if is_explicit else self.minimum_confidence

        # 规则 1：置信度过低
        if candidate.confidence < effective_min_confidence:
            return self._reject(candidate, "LOW_CONFIDENCE")

        # 规则 2：modality 本身不允许进入任何可检索存储
        if candidate.modality in DISALLOWED_MODALITIES:
            return self._reject(
                candidate,
                f"MODALITY_{candidate.modality.value.upper()}",
            )

        # 规则 3：交叉校验（略）
        if signals.has_hypothesis and candidate.modality == Modality.FACT:
            return self._reject(candidate, "HYPOTHESIS_CONFLICT")
        if signals.has_joke_marker and candidate.modality == Modality.FACT:
            return self._reject(candidate, "JOKE_CONFLICT")

        # 规则 3b：BEHAVIOR_POLICY 直接接受（错误代价结构不同于 semantic fact）
        if candidate.memory_type == MemoryType.BEHAVIOR_POLICY:
            return self._accept(
                candidate,
                MemoryType.BEHAVIOR_POLICY,
                "BEHAVIOR_POLICY_ACCEPTED",
                fact_key=build_fact_key(candidate),
            )

        # Ticket 05: Preference Provenance Guard —— 校验偏好来源质量
        provenance_check = self._check_provenance(candidate)
        if provenance_check is not None:
            return provenance_check

        # 规则 4：第三方实体 → entity_relation
        # P1-6 / ADR 0009：第三方实体的 semantic 门槛与用户画像一致（0.85），
        # 先检查置信度门槛再路由，避免低置信度第三方关系污染。
        if candidate.memory_type == MemoryType.SEMANTIC and not candidate.subject.is_current_user:
            if candidate.confidence < self.semantic_minimum_confidence:
                return self._reject(candidate, "SEMANTIC_LOW_CONFIDENCE")
            return self._accept(
                candidate,
                route=MemoryType.ENTITY_RELATION,
                reason="THIRD_PARTY_ROUTE",
            )

        # 规则 5 & 6：semantic 类型的额外要求
        if candidate.memory_type == MemoryType.SEMANTIC:
            if candidate.durability != "stable":
                return self._reject(candidate, "SEMANTIC_NOT_STABLE")
            if candidate.confidence < self.semantic_minimum_confidence:
                return self._reject(candidate, "SEMANTIC_CONFIDENCE")
            return self._accept(
                candidate,
                route=MemoryType.SEMANTIC,
                reason="STABLE_SEMANTIC",
                fact_key=build_fact_key(candidate),
            )

        # 提取器已标记为 discard
        if candidate.memory_type == MemoryType.DISCARD:
            return self._reject(candidate, "EXTRACTOR_DISCARD")

        # 其他已知类型（episodic / task / relationship）→ 接受并按类型路由
        return self._accept(
            candidate,
            route=candidate.memory_type,
            reason="ACCEPTED",
        )

    def _check_provenance(self, candidate: MemoryCandidate) -> WriteDecision | None:
        """Ticket 05: 校验偏好来源质量。

        - hypothesis（模型推测）→ confidence 降权 + 降级为 inferred，不可为 confirmed
        - inferred（行为推断）→ confidence -0.05 惩罚
        - confirmed（用户明确陈述）→ 正常通过
        - 无 provenance 标记 → 不干预（向后兼容旧候选）
        - "可以吃"≠"喜欢"、"喜欢"≠"最喜欢" → 强度不可自动升级，由 extractor 保证

        Returns:
            None 表示通过；WriteDecision 表示拒绝或降权后的决策。
        """
        provenance = getattr(candidate, "provenance", None) or getattr(candidate, "evidence_type", None)
        if not provenance:
            return None  # 无标记，不干预

        if provenance == "hypothesis":
            # 模型推测：不可写入 confirmed，降为 inferred + 降低置信度
            candidate.provenance = "inferred"
            candidate.confidence = min(candidate.confidence, 0.55)
            logger.debug("Provenance downgrade: hypothesis→inferred, confidence capped at 0.55")
            return None  # 不拒绝，只降级

        if provenance == "inferred":
            # 行为推断：微小置信度惩罚
            candidate.confidence = max(0.0, candidate.confidence - 0.05)
            logger.debug("Provenance penalty: inferred confidence -0.05 → %.2f", candidate.confidence)
            return None  # 不拒绝，只惩罚

        if provenance == "confirmed":
            # 用户明确陈述：无惩罚，正常通过
            return None

        return None

    @staticmethod
    def _accept(
        candidate: MemoryCandidate,
        route: MemoryType,
        reason: str,
        *,
        fact_key: str | None = None,
        ttl_seconds: int | None = None,
    ) -> WriteDecision:
        return WriteDecision(
            candidate=candidate,
            accepted=True,
            route=route,
            reason_code=reason,
            fact_key=fact_key,
            ttl_seconds=ttl_seconds,
        )

    @staticmethod
    def _reject(candidate: MemoryCandidate, reason: str) -> WriteDecision:
        return WriteDecision(
            candidate=candidate,
            accepted=False,
            route=MemoryType.DISCARD,
            reason_code=reason,
        )


# ─── 兼容层：Phase 0 接口 ────────────────────────────────────────────────────

# mem_zero 还在调用这个函数，保留作为兼容接口
# Phase 1 的完整门控在 MemoryGate.decide()

LOW_VALUE_PATTERNS = (
    "随便聊聊",
    "聊点别的",
    "嗯嗯",
    "好的",
    "哈哈",
)


def should_write_memory(user_text: str) -> tuple[bool, str]:
    """Phase 0 兼容接口：判断是否应尝试写入记忆。

    B1 修复：低价值判断改为完整匹配，避免误杀包含关键词的长文本。
    - "先聊点别的" → 拒绝（整句低价值）
    - "A/B尚未决定，先聊点别的" → 接受（包含状态信息）

    Args:
        user_text: 用户输入文本（prompt）

    Returns:
        (是否允许写入, 拒绝原因)
        - (True, "") 表示允许
        - (False, reason_code) 表示拒绝，reason_code 用于 trace
    """
    text = user_text.strip()

    # 规则 1：长度 < 4
    if len(text) < 4:
        return False, "text_too_short"

    # 规则 2：B1 修复 - 低价值 pattern 完整匹配
    # 只有整句是低价值填充词时才拒绝，避免误杀包含有价值内容的长文本
    if len(text) <= 10:
        # 短文本：检查是否完全匹配低价值模式
        for pattern in LOW_VALUE_PATTERNS:
            if text == pattern or text.startswith(pattern + "。") or text.startswith(pattern + "，"):
                return False, "low_value_filler"

    # 长文本（> 10字符）可能包含有价值信息，即使包含低价值词也接受
    # 例："A/B 封面未决定，先聊点别的" - 包含状态信息，不应拒绝

    return True, ""
