"""分类型打分 + 阈值过滤 + token budget 裁剪。

对 hard_filter 后的存活候选打分排序，产出 EvidenceItem 列表。

修复原方案 6.4 的 5 个坑中的 2/3/4：
- 完整 metadata 透传（hard_filter 已 enrich，此处组装成 EvidenceItem）
- token 裁剪遇超预算候选 continue 而非 break（不丢后面更短的候选）
- 最低 rerank 阈值过滤低相关候选

分类型打分（原方案 6.3）：稳定事实 recency 权重低、短期状态依赖 TTL、
事件看状态和时间关系。昵称/禁忌/过敏等 slot 只返回唯一 active 版本。

见 ADR 0005（模块命名）、ADR 0007（evidence_level 派生）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from ..contracts import EvidenceItem, MemoryType, Modality
from .evidence_level import derive_evidence_level


# 打分公式权重（原方案 6.3，命名常量，和为 1.0）
SEMANTIC_WEIGHT = 0.45
LEXICAL_WEIGHT = 0.20
CONFIDENCE_WEIGHT = 0.15
IMPORTANCE_WEIGHT = 0.10
RECENCY_WEIGHT = 0.10

# 默认最低阈值（0 表示不过滤，由调用方按需设置）
DEFAULT_MIN_THRESHOLD = 0.15  # P2-5：默认非零，过滤低分噪音

# P1-1：冲突裁决来源优先级（数字越小优先级越高）
SOURCE_PRIORITY = {
    "user_turn": 1,   # 当前对话轮明确提及（可信度最高）
    "dsm": 2,         # DSM 维护的动态状态
    "persistent": 3,  # 持久化历史记忆
    "inferred": 4,    # 推断/合成记忆（可信度最低）
}
DEFAULT_SOURCE_PRIORITY = 99  # 未知/缺失来源视为最低优先级

# slot 类谓词：只保留唯一 active 版本（昵称/禁忌/过敏等）
SLOT_PREDICATE_MARKERS = ("nickname", "taboo", "allergy", "禁忌", "过敏", "昵称")


class RerankerProtocol(Protocol):
    """重排器接口。rerank 返回带 rerank_score 的候选，按分数降序。"""

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        ...


class Scorer:
    """分类型打分器。

    reranker 通过参数注入（Protocol），token 计数可注入以便测试。
    """

    def __init__(
        self,
        min_threshold: float = DEFAULT_MIN_THRESHOLD,
        count_tokens: Callable[[str], int] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._min_threshold = min_threshold
        self._count_tokens = count_tokens or (lambda text: len(text))
        # P2-4：注入 clock 使 recency 计算可重复（测试/回放）
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def score_and_trim(
        self,
        candidates: list[dict[str, Any]],
        query: str,
        token_budget: int,
        reranker: RerankerProtocol,
    ) -> list[EvidenceItem]:
        """打分排序 → 阈值过滤 → slot 去重 → token 裁剪，返回 EvidenceItem。"""
        if not candidates:
            return []

        # 1. reranker 重排，拿到 rerank_score（作为 semantic_relevance）
        reranked = reranker.rerank(query, candidates)

        # 2. 打分
        scored: list[tuple[float, dict]] = []
        for cand in reranked:
            final_score = self._compute_score(cand)
            scored.append((final_score, cand))

        # 3. 按 final_score 降序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 4. 阈值过滤
        scored = [(s, c) for s, c in scored if s >= self._min_threshold]

        # 5. slot 去重（同一 slot 谓词只留最高分，即排序后第一个）
        scored = self._dedup_slots(scored)

        # 6. 证据优先级冲突裁决（同 subject+predicate 只留胜出方）
        scored = self._resolve_conflicts(scored)

        # Code Review 修复：步骤 6 后重新排序，确保 token 裁剪吞入最高分证据
        scored.sort(key=lambda x: x[0], reverse=True)

        # 7. token budget 裁剪（超预算 continue 而非 break，有截断 fallback）
        items: list[EvidenceItem] = []
        used_tokens = 0
        for final_score, cand in scored:
            content = cand.get("content", "")
            cost = self._count_tokens(content)
            if used_tokens + cost > token_budget:
                # Fallback: 截断内容以适应剩余预算（避免返回空结果）
                remaining = token_budget - used_tokens
                if remaining > 20:  # 至少保留有意义的内容
                    truncated = self._truncate_content(content, remaining)
                    cand["content"] = truncated
                    cand["truncated"] = True
                    items.append(self._to_evidence_item(cand, final_score))
                    used_tokens = token_budget  # 预算用尽，后续不再添加
                    break
                # 剩余预算不足，继续看后面更短的候选
                continue
            used_tokens += cost
            items.append(self._to_evidence_item(cand, final_score))

        return items

    def _compute_score(self, cand: dict[str, Any]) -> float:
        """分类型打分。final_score = 加权和 - 惩罚。"""
        semantic = float(cand.get("rerank_score", cand.get("score", 0.0)))
        lexical = float(cand.get("lexical_score", cand.get("entity_score", 0.0)))
        confidence = float(cand.get("confidence", 0.5))
        importance = float(cand.get("importance", 0.5))
        recency = self._type_specific_recency(cand)

        contradiction_penalty = float(cand.get("contradiction_penalty", 0.0))
        ambiguity_penalty = float(cand.get("ambiguity_penalty", 0.0))

        score = (
            SEMANTIC_WEIGHT * semantic
            + LEXICAL_WEIGHT * lexical
            + CONFIDENCE_WEIGHT * confidence
            + IMPORTANCE_WEIGHT * importance
            + RECENCY_WEIGHT * recency
            - contradiction_penalty
            - ambiguity_penalty
        )
        return score

    def _type_specific_recency(self, cand: dict[str, Any]) -> float:
        """分类型 recency：稳定事实权重低（返回中性 0.5），短期状态依赖新鲜度。

        稳定事实（semantic）不该因为"记得早"就降权——返回中性值。
        短期状态（state）越新越相关，按 TTL 或距今天数衰减。
        事件看时间关系（距今天数）。

        P2-4：用注入的 self._clock() 取当前时间，使计算可重复。
        ⚠️ 简化实现：线性衰减，需结合真实数据调优（Phase 4 技术债）。
        """
        memory_type = cand.get("memory_type", "semantic")

        # 稳定事实/关系：recency 不重要，返回 1.0（不衰减）
        # 理由：昵称、偏好、禁忌等事实不应因记忆时间久远而降权
        if memory_type in ("semantic", "relationship", "behavior_policy"):
            return 1.0

        # 短期状态/任务/事件：越新越相关
        source_date = cand.get("source_date")
        if source_date is None:
            return 0.5  # 缺时间戳时中性

        # 计算距今天数
        if isinstance(source_date, str):
            try:
                source_dt = datetime.fromisoformat(source_date.replace("Z", "+00:00"))
            except ValueError:
                return 0.5
        elif isinstance(source_date, datetime):
            source_dt = source_date
        else:
            return 0.5

        now = self._clock()
        # 确保 source_dt 是 timezone-aware，避免时区不匹配错误
        if source_dt.tzinfo is None:
            # naive datetime 视为 UTC
            from datetime import timezone as tz
            source_dt = source_dt.replace(tzinfo=tz.utc)
        
        days_ago = (now - source_dt).days

        # 简化衰减：30 天内线性衰减 1.0 → 0.3，超过 30 天固定 0.3
        if days_ago < 0:
            return 1.0  # 未来时间（异常）
        elif days_ago <= 30:
            return 1.0 - (days_ago / 30) * 0.7  # [1.0, 0.3]
        else:
            return 0.3  # 旧记忆保底

    def _dedup_slots(
        self, scored: list[tuple[float, dict]]
    ) -> list[tuple[float, dict]]:
        """slot 类谓词按 (subject_id, predicate) 去重，不同主体独立（P2-6）。

        修复前：只看 predicate，导致不同主体的同名 slot 相互覆盖（错）。
        修复后：(subject_id, predicate) 组合 key，不同主体各保留一条最高分。
        """
        seen_slots: set[tuple[str, str]] = set()
        result: list[tuple[float, dict]] = []
        for final_score, cand in scored:
            predicate = cand.get("predicate") or ""
            if self._is_slot_predicate(predicate):
                subject_id = cand.get("subject_id") or ""
                slot_key = (subject_id, predicate)
                if slot_key in seen_slots:
                    continue  # 已有更高分的同 slot，跳过
                seen_slots.add(slot_key)
            result.append((final_score, cand))
        return result

    def _resolve_conflicts(
        self, scored: list[tuple[float, dict]]
    ) -> list[tuple[float, dict]]:
        """证据优先级冲突裁决（P1-1 修复）：同 subject+predicate 按来源优先级去重。

        冲突判定：两条 active 证据 subject_id + predicate 相同（如两条"user:diet.preference"）。

        裁决规则（多级排序）：
        1. source_kind 优先级（user_turn > dsm > persistent > inferred）
        2. observed_at 越新越优先（同来源时比时间）
        3. final_score 越高越优先（兜底）

        ⚠️ 技术债：observed_at 需上游填充（当前默认 None），真实数据验证后调优。
        """
        # 按 (subject_id, predicate) 分组
        groups: dict[tuple[str, str], list[tuple[float, dict]]] = {}
        non_conflict: list[tuple[float, dict]] = []

        for final_score, cand in scored:
            subject_id = cand.get("subject_id") or ""
            predicate = cand.get("predicate") or ""

            # 无 subject 或 predicate 时不参与冲突裁决
            if not subject_id or not predicate:
                non_conflict.append((final_score, cand))
                continue

            key = (subject_id, predicate)
            groups.setdefault(key, []).append((final_score, cand))

        # 每组内按优先级排序取首个
        result: list[tuple[float, dict]] = non_conflict[:]
        for key, group in groups.items():
            if len(group) == 1:
                result.append(group[0])
            else:
                # 按 source_kind 优先级 → observed_at 降序 → final_score 降序
                def sort_key(item: tuple[float, dict]) -> tuple:
                    final_score, cand = item
                    source_kind = cand.get("source_kind", "")
                    priority = SOURCE_PRIORITY.get(source_kind, DEFAULT_SOURCE_PRIORITY)
                    observed_at = cand.get("observed_at")
                    # observed_at 越新越优先：用负时间戳（None 视为最早）
                    observed_ts = (
                        -observed_at.timestamp() if observed_at is not None else float("inf")
                    )
                    return (priority, observed_ts, -final_score)

                group.sort(key=sort_key)
                result.append(group[0])

        return result

    @staticmethod
    def _is_slot_predicate(predicate: str) -> bool:
        """判断谓词是否为唯一 slot（昵称/禁忌/过敏）。"""
        return any(marker in predicate for marker in SLOT_PREDICATE_MARKERS)

    @staticmethod
    def _to_evidence_item(cand: dict[str, Any], final_score: float) -> EvidenceItem:
        """把候选组装成 EvidenceItem，填充 evidence_level（usage 字段）。"""
        modality_str = cand.get("modality", "fact")
        modality = Modality(modality_str)
        status = cand.get("status", "active")
        confidence = float(cand.get("confidence", 0.5))

        # 派生 evidence_level 填入 usage 字段
        evidence_level = derive_evidence_level(confidence, modality, status)

        memory_type_str = cand.get("memory_type", "semantic")
        memory_type = MemoryType(memory_type_str)

        # source_turn_id 可能是单个字符串，转 list
        source_turn_id = cand.get("source_turn_id")
        source_turn_ids = [source_turn_id] if source_turn_id else []

        return EvidenceItem(
            memory_id=str(cand.get("memory_id", cand.get("event_id", ""))),
            memory_type=memory_type,
            content=cand.get("content", cand.get("title", "")),
            subject_id=str(cand.get("subject_id") or "user"),
            predicate=cand.get("predicate") or "",
            status=status,
            modality=modality,
            confidence=confidence,
            importance=float(cand.get("importance", 0.5)),
            source_turn_ids=source_turn_ids,
            source_date=_parse_dt(cand.get("source_date")),
            expires_at=_parse_dt(cand.get("expires_at")),
            source_kind=cand.get("source_kind", "persistent"),
            observed_at=_parse_dt(cand.get("observed_at")),
            usage=evidence_level,
            source="long_term_index",  # 问题 #6 修复：标识记忆来源为长期索引
            semantic_score=float(cand.get("rerank_score", cand.get("score", 0.0))),
            lexical_score=float(cand.get("lexical_score", 0.0)),
            entity_score=float(cand.get("entity_score", 0.0)),
            final_score=final_score,
        )

    @staticmethod
    def _truncate_content(content: str, max_tokens: int) -> str:
        """截断内容以适应 token 预算，尽量保留完整句子。

        用字符数近似 token 数（中英文混合），在预算边界处截断到最后一个句末标点。
        如果内容本身不超过 max_tokens，直接返回原文。
        """
        if len(content) <= max_tokens:
            return content

        # 在 max_tokens 附近找最后一个句末标点
        cutoff = max_tokens
        # 往前找最近的句末标点（最多回溯 50 字符）
        search_start = max(0, max_tokens - 50)
        for i in range(max_tokens - 1, search_start - 1, -1):
            if content[i] in ("。", "！", "？", ".", "!", "?", "\n"):
                cutoff = i + 1  # 包含标点
                break

        truncated = content[:cutoff]
        return truncated + "…" if len(truncated) < len(content) else truncated


def _parse_dt(value: Any) -> datetime | None:
    """把 str/datetime 归一为 datetime，其余返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
