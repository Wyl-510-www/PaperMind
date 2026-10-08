"""
Phase 2 Streamlit UI 业务服务层契约

定义公共数据结构、固定身份列表和服务接口签名。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

# 导入 Phase 1.3 的数据结构
from papermind.memory_writer import WriteResult, save_turn_to_memory
from papermind.outbox_sync import SyncResult, sync_outbox_batch


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
    """保存笔记到 Memory V2。

    封装 Phase 1.3 的 save_turn_to_memory，提供适合页面调用的业务接口。
    实现二次确认门控、空输入验证、身份透传和状态直传。

    Args:
        identity: 用户身份标识（tenant_id, user_id）
        title: 论文标题
        conclusion: 阅读结论
        confirmed: 用户是否确认保存

    Returns:
        WriteResult: Phase 1.3 的完整写入结果，包含五种状态
            - saved: 至少一条有效事实已提交
            - partial: 部分成功，存在错误
            - skipped: 未确认、查询、歧义、填充或不支持的操作
            - no_memory: 无有效提交且无错误
            - failed: 有错误且无有效提交

    Note:
        - confirmed=False 时直接返回 skipped，不调用 Phase 1.3
        - 空标题或空正文时返回 skipped
        - 每次调用生成新的 UUID turn_id
        - 用户消息格式：论文：{title}\n\n阅读结论：{conclusion}
    """
    # 空输入验证
    if not title or not title.strip():
        return WriteResult(
            status="skipped",
            speech_act=None,
            memory_ids=[],
            turn_id=uuid.uuid4().hex,
            message="已跳过：标题为空",
            error_code=None,
        )

    if not conclusion or not conclusion.strip():
        return WriteResult(
            status="skipped",
            speech_act=None,
            memory_ids=[],
            turn_id=uuid.uuid4().hex,
            message="已跳过：阅读结论为空",
            error_code=None,
        )

    # 生成新的 turn_id
    turn_id = uuid.uuid4().hex

    # confirmed=False 门控
    if not confirmed:
        return WriteResult(
            status="skipped",
            speech_act=None,
            memory_ids=[],
            turn_id=turn_id,
            message="已跳过：用户未确认保存",
            error_code=None,
        )

    # 组合用户消息
    user_text = f"论文：{title}\n\n阅读结论：{conclusion}"

    # 调用 Phase 1.3 写入，透传身份和结果
    result = await save_turn_to_memory(
        user_text=user_text,
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        turn_id=turn_id,
        confirmed=True,
    )

    return result


async def sync_notes(batch_size: int = 100) -> SyncResult:
    """将 Outbox 中的笔记同步到 Memory V2 索引。

    封装 Phase 1.3 的 sync_outbox_batch，提供显式同步接口。
    批次处理的是队列中所有待同步记录，不限于当前会话的笔记。

    Args:
        batch_size: 单批处理数量（默认 100）

    Returns:
        SyncResult: Phase 1.3 的完整同步结果
            - status: "completed" 或 "failed"
            - done: 成功同步的记录数
            - failed: 失败需要重试的记录数
            - dead: 达到重试上限的记录数
            - message: 用户可读的反馈消息

    Note:
        - 批次完成不等价于当前 Memory ID 已可检索
        - done > 0 不能证明当前笔记已同步
        - 零条处理是合法的空批次
    """
    # 直接调用 Phase 1.3 同步，透传结果
    result = await sync_outbox_batch(batch_size=batch_size)
    return result


async def ask_memory(
    identity: Identity,
    question: str,
    *,
    llm_client: LLMClient,
) -> AskResult:
    """查询 Memory V2 并生成答案"""
    raise NotImplementedError("ask_memory will be implemented in Task Group 3")
