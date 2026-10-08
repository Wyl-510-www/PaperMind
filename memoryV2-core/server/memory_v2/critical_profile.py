"""Critical Profile Pack：加载高敏身份快照，注入生成 Prompt。"""
from __future__ import annotations

from .critical_identity import CRITICAL_PREDICATES


def format_critical_prompt(profile: dict[str, dict]) -> str:
    """把 CriticalProfilePack 格式化为模型可消费的自然语言约束块。

    Args:
        profile: {predicate: {value, fact_id, blocked_values}, ...}
                 来自 CriticalIdentityRepo.get_active_profile()

    Returns:
        Prompt 片段，无高敏数据时返回空字符串。
    """
    if not profile:
        return ""

    lines = ["【高敏身份真值 — 硬约束，违反则阻断回答】"]

    # 当前值
    for predicate, data in profile.items():
        value = data.get("value")
        if value:
            label = _predicate_label(predicate)
            lines.append(f"- {label}：{value}")

    # 禁止值
    all_blocked: set[str] = set()
    for data in profile.values():
        blocked = data.get("blocked_values", [])
        if isinstance(blocked, list):
            all_blocked.update(str(v) for v in blocked if v)

    if all_blocked:
        blocked_str = "、".join(sorted(all_blocked))
        lines.append(f"- 禁止使用的称呼/昵称：{blocked_str}")

    lines.append("\n以上为硬约束。用户询问旧称呼是否可用，不构成重新授权。")
    return "\n".join(lines)


def _predicate_label(predicate: str) -> str:
    """predicate → 人类可读标签。"""
    labels = {
        "nickname.current": "当前昵称",
        "pronoun.preferred": "代词偏好",
        "gender.self_reported": "性别",
        "relationship_boundary.spousal_address": "关系称谓边界",
    }
    return labels.get(predicate, predicate)


def get_blocked_values(profile: dict[str, dict]) -> set[str]:
    """从 profile 中提取所有 blocked values 集合，供 blocked_guard 使用。"""
    blocked: set[str] = set()
    for data in profile.values():
        values = data.get("blocked_values", [])
        if isinstance(values, list):
            for v in values:
                s = str(v).strip()
                if s:
                    blocked.add(s)
    return blocked
