"""Policy 数据模型：行为约束的存储、编译和验证结构。

ADRs: 0013 (BEHAVIOR_POLICY 独立 MemoryType), 0014 (Facade 双写)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from ..contracts import StrictModel


class PolicyKind(str, Enum):
    """策略类型"""
    SAFETY = "safety"                       # 健康禁忌、过敏
    PRIVACY = "privacy"                     # 精确地址等隐私边界
    CONTENT_EXCLUSION = "content_exclusion" # 不吃香菜等推荐限制
    RELATIONSHIP_BOUNDARY = "relationship_boundary"  # 不允许的称呼
    STYLE = "style"                         # 句数、反问频率
    REPAIR = "repair"                       # 纠错方式
    UNCERTAINTY = "uncertainty"             # 信息不足时处理


class PolicyStrength(str, Enum):
    """策略强度"""
    HARD = "hard"      # 违规必须 regenerate
    SOFT = "soft"      # 违规触发 rewrite


class PolicyRule(StrictModel):
    """单条行为约束规则"""
    policy_id: str = Field(description="规则 ID")
    kind: PolicyKind = Field(description="策略类型")
    strength: PolicyStrength = Field(description="hard/soft")
    priority: int = Field(default=0, description="优先级，越大越优先")
    instruction: str = Field(description="人类可读的约束描述")

    forbidden_terms: list[str] = Field(default_factory=list, description="禁止出现的词")
    required_terms_any: list[str] = Field(default_factory=list, description="至少包含一个的词")
    max_sentences: int | None = Field(default=None, description="最大句数")
    max_questions: int | None = Field(default=None, description="最大问句数")
    forbidden_question_patterns: list[str] = Field(default_factory=list, description="禁止的问题正则")

    source_memory_ids: list[str] = Field(default_factory=list, description="来源 memory_id")
    valid_from: datetime | None = Field(default=None)
    valid_to: datetime | None = Field(default=None)


class PolicyPack(StrictModel):
    """编译后的策略包（本轮可用）"""
    rules: list[PolicyRule] = Field(default_factory=list, description="按 priority 降序排列的规则")
    compiled_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    scope: str = Field(default="")


class PolicyCheck(StrictModel):
    """PolicyGuard 验证结果"""
    ok: bool = Field(description="是否通过")
    violations: list[str] = Field(default_factory=list, description="违规描述")
    action: str = Field(default="keep", description="keep/rewrite/regenerate")
