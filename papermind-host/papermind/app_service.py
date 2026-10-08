"""
Phase 2 Streamlit UI 业务服务层契约

定义公共数据结构、固定身份列表和服务接口签名。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, date
from typing import Protocol, Optional, List

# 导入 Phase 1.3 的数据结构
from papermind.memory_writer import WriteResult, save_turn_to_memory
from papermind.outbox_sync import SyncResult, sync_outbox_batch
from papermind.models import NoteMetadata


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
    metadata: Optional[NoteMetadata] = None,
) -> WriteResult:
    """保存笔记到 Memory V2（支持 Phase 3 元数据）。

    封装 Phase 1.3 的 save_turn_to_memory，提供适合页面调用的业务接口。
    实现二次确认门控、空输入验证、身份透传和状态直传。

    Args:
        identity: 用户身份标识（tenant_id, user_id）
        title: 论文标题
        conclusion: 阅读结论
        confirmed: 用户是否确认保存
        metadata: 笔记元数据（Phase 3 新增，可选）

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
        - Phase 3: 如果提供 metadata，将序列化后存入 Memory V2 metadata 字段
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

    # Phase 3: 如果提供元数据，将其附加到用户消息中
    # 注意：当前 save_turn_to_memory 不直接支持 metadata 参数
    # 作为过渡方案，将元数据编码到 user_text 中
    # TODO: Phase 3.2 需要修改 memory_writer.py 支持 metadata 参数
    if metadata:
        metadata_text = f"\n\n[元数据]\n作者: {metadata.author or '未知'}\n年份: {metadata.year or '未知'}\n阅读日期: {metadata.read_date}\n标签: {', '.join(metadata.tags)}\n类型: {metadata.note_type}"
        user_text += metadata_text

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
    tags: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> AskResult:
    """查询 Memory V2 并生成答案（Phase 3: 支持标签和时间过滤）。

    基于用户身份检索历史记忆，并使用 LLM 生成基于证据的回答。
    Phase 3: 支持两阶段检索——先硬过滤（标签+时间），再语义检索。

    Args:
        identity: 用户身份标识（tenant_id, user_id）
        question: 用户问题
        llm_client: LLM 客户端，用于生成回答
        tags: 标签列表（Phase 3 新增），使用 OR 逻辑（匹配任一标签）
        start_date: 起始日期（Phase 3 新增），过滤 read_date >= start_date 的笔记
        end_date: 结束日期（Phase 3 新增），过滤 read_date <= end_date 的笔记

    Returns:
        AskResult: 查询结果，包含四种状态之一
            - answered: 检索到证据，LLM 成功生成回答
            - no_evidence: 未检索到相关记忆（不调用 LLM）
            - retrieval_failed: 检索失败或超时（不调用 LLM）
            - answer_failed: 检索成功但 LLM 生成失败（保留证据）

    Note:
        - 只有检索到证据时才调用 LLM
        - 检索失败不伪装成无证据
        - LLM 失败时保留已检索到的证据
        - 系统提示要求只基于证据回答，禁止使用模型知识补充用户经历
    """
    import asyncio
    import logging
    from papermind.memory_retrieval import retrieve_structured_evidence

    logger = logging.getLogger(__name__)

    # 步骤 1: 调用结构化检索（Phase 3: 传递过滤参数）
    try:
        evidence_list = await retrieve_structured_evidence(
            query=question,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            limit=5,
            tags=tags,
            start_date=start_date,
            end_date=end_date,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Memory retrieval timeout for ask_memory: tenant=%s, user=%s, question=%s",
            identity.tenant_id,
            identity.user_id,
            question[:50],
        )
        return AskResult(
            status="retrieval_failed",
            answer="记忆检索超时，请稍后重试。",
            evidence=[],
            error_code="RETRIEVAL_TIMEOUT",
        )
    except Exception as e:
        logger.error(
            "Memory retrieval failed for ask_memory: tenant=%s, user=%s, question=%s, error=%s",
            identity.tenant_id,
            identity.user_id,
            question[:50],
            str(e),
            exc_info=True,
        )
        return AskResult(
            status="retrieval_failed",
            answer="记忆检索失败，请稍后重试。",
            evidence=[],
            error_code="RETRIEVAL_ERROR",
        )

    # 步骤 2: 无证据 → 返回 no_evidence，不调用 LLM
    if not evidence_list:
        return AskResult(
            status="no_evidence",
            answer="未找到相关历史记忆。",
            evidence=[],
            error_code=None,
        )

    # 步骤 3: 有证据 → 构建 prompt
    evidence_text = "\n\n".join(
        f"{idx}. {item.content}"
        for idx, item in enumerate(evidence_list, start=1)
    )

    prompt = f"""你是用户的个人记忆助手。请仅根据以下历史记忆回答用户问题。

历史记忆：
{evidence_text}

重要约束：
1. 只使用上述历史记忆中的信息
2. 不要使用常识或模型知识补充用户的经历
3. 如果历史记忆不足以回答，明确说明

用户问题：{question}"""

    # 步骤 4: 调用 LLM
    try:
        answer = await llm_client.generate(prompt)
        return AskResult(
            status="answered",
            answer=answer,
            evidence=evidence_list,
            error_code=None,
        )
    except Exception as e:
        logger.error(
            "LLM generation failed for ask_memory: tenant=%s, user=%s, question=%s, error=%s",
            identity.tenant_id,
            identity.user_id,
            question[:50],
            str(e),
            exc_info=True,
        )
        return AskResult(
            status="answer_failed",
            answer="回答生成失败，但已找到相关记忆。",
            evidence=evidence_list,  # 保留证据
            error_code="LLM_ERROR",
        )
