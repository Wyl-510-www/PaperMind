"""Decision Sufficiency Guard：信息不足时强制询问用户，禁止编造。

比较/选择类请求 → 检查是否有足够的特征信息 → 不足则告知模型询问用户。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SufficiencyCheck:
    sufficient: bool
    missing_fields: list[str] = field(default_factory=list)
    prompt_hint: str = ""


# 比较/选择请求的检测特征
_COMPARISON_MARKERS = [
    "帮我选", "选哪个", "哪个好", "推荐一个", "你觉得哪个",
    "帮我挑", "选一个", "怎么选", "A和B", "二选一",
    "对比", "比较", "帮我决定",
]


def check_comparison_sufficiency(
    query: str,
    available_fields: set[str],
    required_fields: set[str],
) -> SufficiencyCheck:
    """检查决策信息充分性。

    Args:
        query: 用户查询
        available_fields: EvidencePack 中已有的字段（如 subject/predicate 集合）
        required_fields: 做出决策所需的字段集合

    Returns:
        SufficiencyCheck: .sufficient 为 False 时需询问用户
    """
    is_comparison = any(m in query for m in _COMPARISON_MARKERS)
    if not is_comparison:
        return SufficiencyCheck(sufficient=True)

    missing = required_fields - available_fields
    if not missing:
        return SufficiencyCheck(sufficient=True)

    return SufficiencyCheck(
        sufficient=False,
        missing_fields=sorted(missing),
        prompt_hint=(
            "注意：用户请求帮助决策，但缺少以下关键信息："
            + "、".join(sorted(missing))
            + "。请询问用户这些信息，不要编造或假设。"
        ),
    )
