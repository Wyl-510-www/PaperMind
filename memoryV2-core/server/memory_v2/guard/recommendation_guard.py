"""Recommendation Constraint Filter：推荐硬过滤，不依赖模型自觉。

⚠️ 注意：此文件包含数据结构定义和辅助函数。
实际的 Recommendation Guard 检查逻辑已在 orchestrator.py (L340-390) 中实现。

该实现直接从 evidence 提取过敏原/禁忌项，并对最终回答全文扫描，
无需依赖此文件的 filter_recommendations() 函数。

维护建议：
- 选项1：保留此文件作为数据结构定义
- 选项2：将 orchestrator.py 中的逻辑迁移到此文件
- 选项3：删除此文件，文档化 orchestrator.py 的实现
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecommendationConstraints:
    """推荐约束（从 PolicyPack + confirmed preferences 编译）"""
    allergies: frozenset[str] = field(default_factory=frozenset)
    forbidden: frozenset[str] = field(default_factory=frozenset)
    dislikes: frozenset[str] = field(default_factory=frozenset)
    confirmed_likes: frozenset[str] = field(default_factory=frozenset)
    hypotheses: frozenset[str] = field(default_factory=frozenset)


def compile_constraints(
    policy_pack=None,
    confirmed_preferences: list[str] | None = None,
    hypothesis_preferences: list[str] | None = None,
    allergies: list[str] | None = None,
    forbidden_tags: list[str] | None = None,
) -> RecommendationConstraints:
    """从 PolicyPack 和 confirmed/hypothesis preferences 编译约束。

    Args:
        policy_pack: PolicyPack 实例（含 safety/privacy/content_exclusion rules）
        confirmed_preferences: confirmed 层级的偏好值列表（如 ["微辣", "运动鞋"]）
        hypothesis_preferences: hypothesis 层级的偏好值列表
        allergies: 过敏标签列表（如 ["花生", "海鲜"]）
        forbidden_tags: 禁止标签列表（如 ["特辣", "酒精"]）

    Returns:
        RecommendationConstraints
    """
    all_forbidden: set[str] = set(forbidden_tags or [])
    all_allergies: set[str] = set(allergies or [])
    all_dislikes: set[str] = set()

    # 从 policy_pack 提取 hard constraints
    if policy_pack:
        for rule in getattr(policy_pack, "rules", []):
            kind = getattr(rule, "kind", "")
            if kind == "safety":
                for term in getattr(rule, "forbidden_terms", []):
                    all_allergies.add(term)
            elif kind == "content_exclusion":
                for term in getattr(rule, "forbidden_terms", []):
                    all_forbidden.add(term)
                    all_dislikes.add(term)

    return RecommendationConstraints(
        allergies=frozenset(all_allergies),
        forbidden=frozenset(all_forbidden),
        dislikes=frozenset(all_dislikes),
        confirmed_likes=frozenset(confirmed_preferences or []),
        hypotheses=frozenset(hypothesis_preferences or []),
    )


def filter_recommendations(
    items: list[str],
    constraints: RecommendationConstraints,
) -> list[str]:
    """硬过滤推荐列表。

    Args:
        items: 推荐候选项（如 ["特辣火锅", "微辣串串", "日式刺身"]）
        constraints: 编译好的约束

    Returns:
        过滤排序后的列表。确认喜欢的排前面，被禁止的直接删除。
    """
    safe = []
    for item in items:
        item_lower = item.lower()
        # 过敏 → 硬删除
        if any(a.lower() in item_lower for a in constraints.allergies):
            continue
        # 禁止 → 硬删除
        if any(f.lower() in item_lower for f in constraints.forbidden):
            continue
        # 不喜欢 → 硬删除
        if any(d.lower() in item_lower for d in constraints.dislikes):
            continue
        safe.append(item)

    # 加权排序：confirmed likes 排前面
    def _score(item: str) -> int:
        item_lower = item.lower()
        if any(l.lower() in item_lower for l in constraints.confirmed_likes):
            return 2
        if any(h.lower() in item_lower for h in constraints.hypotheses):
            return 1
        return 0

    safe.sort(key=_score, reverse=True)
    return safe


def prompt_for_empty_likes() -> str:
    """confirmed_likes 为空时的行为指导文本。"""
    return (
        "注意：当前没有确认的用户偏好数据。\n"
        "推荐时应使用中性表述（如「这些是热门选择」），"
        "不得声称「这是你喜欢的」「你应该会喜欢」等确定性偏好断言。"
    )
