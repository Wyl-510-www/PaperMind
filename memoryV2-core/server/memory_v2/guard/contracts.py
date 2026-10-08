"""Guard 共享契约 - 0913 统一接口

D3 修复：统一 Guard 系统的数据结构和接口
解决导入断裂、DTO 不一致、枚举类型不兼容等问题
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional


class GuardAction(str, Enum):
    """Guard 决策动作 - 统一枚举"""
    KEEP = "keep"                  # 保留原回答
    DELETE = "delete"              # 删除不支持的主张
    TO_QUESTION = "to_question"    # 转为澄清问题
    REGENERATE = "regenerate"      # 需要重新生成
    ERROR = "error"                # Guard 执行失败


@dataclass
class Claim:
    """单个主张"""
    id: str
    text: str
    span: Optional[tuple] = None  # 原文位置 (start, end)
    confidence: Optional[float] = None


@dataclass
class Evidence:
    """支持证据"""
    memory_id: str
    content: str
    relevance_score: float
    supports_claims: List[str] = field(default_factory=list)  # 支持的 claim IDs


@dataclass
class EvidencePack:
    """证据包 - 向后兼容

    0913 修复：统一字段名为 'items'，同时支持旧的 'evidence' 字段访问
    添加 Pydantic 兼容方法以支持 orchestrator 的 model_validate/model_dump 调用
    """
    items: List[Evidence]
    query: str
    scope: Optional[dict] = None

    # 向后兼容：允许访问 .evidence
    @property
    def evidence(self) -> List[Evidence]:
        """向后兼容的 evidence 字段"""
        return self.items

    @classmethod
    def model_validate(cls, data: dict):
        """Pydantic 兼容方法：从字典创建实例"""
        if isinstance(data, cls):
            return data
        # 支持 'items' 或 'evidence' 字段名
        items_data = data.get('items') or data.get('evidence', [])
        items = [
            Evidence(**item) if isinstance(item, dict) else item
            for item in items_data
        ]
        return cls(
            items=items,
            query=data.get('query', ''),
            scope=data.get('scope')
        )

    def model_dump(self, **kwargs) -> dict:
        """Pydantic 兼容方法：转换为字典"""
        from dataclasses import asdict
        return asdict(self)


@dataclass
class ClaimDecision:
    """单个主张的决策"""
    claim_id: str
    action: GuardAction
    supporting_evidence_ids: List[str]
    reason: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class GuardResult:
    """Guard 最终结果"""
    overall_action: GuardAction
    original_answer: str
    modified_answer: Optional[str]
    claim_decisions: List[ClaimDecision]
    error: Optional[str] = None

    # 统计信息
    verified_claims_count: int = 0
    removed_claims_count: int = 0
    clarification_needed_count: int = 0


# 导出所有接口
__all__ = [
    "GuardAction",
    "Claim",
    "Evidence",
    "EvidencePack",
    "ClaimDecision",
    "GuardResult",
]
