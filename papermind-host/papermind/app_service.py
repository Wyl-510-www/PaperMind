"""
Phase 2 Streamlit UI 业务服务层契约

定义公共数据结构、固定身份列表和服务接口签名。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Identity:
    """用户身份标识"""
    tenant_id: str
    user_id: str
    label: str


@dataclass(frozen=True)
class EvidenceItem:
    """检索证据项"""
    memory_id: str
    content: str
    memory_type: str
    confidence: float
    created_at: datetime | None


@dataclass(frozen=True)
class AskResult:
    """查询结果"""
    status: str  # answered | no_evidence | retrieval_failed | answer_failed
    answer: str
    evidence: list[EvidenceItem]
    error_code: str | None = None


# 固定的三个身份组合
IDENTITIES: tuple[Identity, Identity, Identity] = (
    Identity(tenant_id="tenant_A", user_id="user_A", label="租户A-用户A"),
    Identity(tenant_id="tenant_A", user_id="user_B", label="租户A-用户B"),
    Identity(tenant_id="tenant_B", user_id="user_A", label="租户B-用户A"),
)


@dataclass(frozen=True)
class WriteResult:
    """写入结果"""
    success: bool
    turn_id: str | None
    error_message: str | None = None


@dataclass(frozen=True)
class SyncResult:
    """同步结果"""
    success: bool
    synced_count: int
    error_message: str | None = None


class LLMClient(Protocol):
    """LLM 客户端协议"""
    async def generate(self, prompt: str) -> str:
        ...


async def save_note(
    identity: Identity,
    title: str,
    conclusion: str,
    *,
    confirmed: bool,
) -> WriteResult:
    """保存笔记到 Outbox，等待同步"""
    raise NotImplementedError("save_note will be implemented in Task Group 2")


async def sync_notes(batch_size: int = 100) -> SyncResult:
    """将 Outbox 中的笔记同步到 Memory V2"""
    raise NotImplementedError("sync_notes will be implemented in Task Group 2")


async def ask_memory(
    identity: Identity,
    question: str,
    *,
    llm_client: LLMClient,
) -> AskResult:
    """查询 Memory V2 并生成答案"""
    raise NotImplementedError("ask_memory will be implemented in Task Group 3")
