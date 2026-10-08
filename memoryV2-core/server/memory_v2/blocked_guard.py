"""Blocked Value Guard：生成后确定性字符串扫描。

检查回答中是否出现 blocked_values 中的禁用称呼/昵称。
违规 → 返回违规列表，供 orchestrator 触发温度=0 的约束重写。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BlockedCheck:
    ok: bool
    violations: list[str] = field(default_factory=list)


def validate_blocked_values(answer: str, blocked_values: set[str]) -> BlockedCheck:
    """确定性检查回答中是否包含 blocked 值。

    Args:
        answer: 模型生成的回答文本
        blocked_values: 禁用称呼/昵称集合（来自 CriticalProfilePack.get_blocked_values()）

    Returns:
        BlockedCheck: .ok=True 表示通过，.violations 列出违规项
    """
    if not blocked_values or not answer:
        return BlockedCheck(ok=True)

    violations: list[str] = []
    for blocked in blocked_values:
        if blocked and blocked in answer:
            violations.append(blocked)

    return BlockedCheck(ok=len(violations) == 0, violations=violations)


def rewrite_remove_blocked(answer: str, violations: list[str]) -> str:
    """生成重写约束 prompt（不由代码直接替换，交给模型重写）。

    返回指导 temperature=0 重写的 prompt，删除违规词。
    """
    if not violations:
        return answer

    blocked_str = "、".join(violations)
    return (
        f"【约束重写指令】原始回答中出现了以下禁止使用的称呼：{blocked_str}。\n"
        "请重写回答，删除这些禁止称呼，替换为当前允许的称呼。不新增事实，保持原意。\n"
        f"原始回答：{answer}"
    )
