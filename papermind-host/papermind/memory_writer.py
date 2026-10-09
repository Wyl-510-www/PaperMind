"""Memory V2 写入链路封装模块。

此模块封装 Memory V2 的事实写入功能，提供统一的写入接口。
核心功能：
1. 封装 Memory V2 的写入调用（仅 semantic 事实抽取）
2. 实现 Speech Act 门控和确认机制
3. 格式化写入结果为五种状态：saved/partial/skipped/no_memory/failed
4. 提供错误处理和状态反馈
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """写入结果。

    Attributes:
        status: 写入状态
            - saved: 至少一条有效事实提交回执，且没有报告抽取/提交错误
            - partial: 部分事实已提交，同时存在抽取/提交错误
            - skipped: 未确认、查询、歧义、填充或不支持的操作
            - no_memory: 无有效提交，且没有抽取或提交错误
            - failed: 输入、模型、解析或数据库错误，且无已知成功提交
        speech_act: Speech Act 分类结果（未完成分类时为 None）
        memory_ids: 成功提交的 Memory ID 列表
        turn_id: 本次写入的轮次 ID
        message: 用户可读的反馈消息
        error_code: 错误代码（无错误时为 None）
    """
    status: Literal["saved", "partial", "skipped", "no_memory", "failed"]
    speech_act: str | None
    memory_ids: list[str]
    turn_id: str
    message: str
    error_code: str | None = None


def _configure_core_logging() -> None:
    """配置核心模块日志输出。

    抑制核心 memory_v2 命名空间的原始日志，避免输出笔记内容和凭据。
    宿主使用 papermind 命名空间记录状态、数量、耗时与脱敏错误码。
    """
    core_logger = logging.getLogger("server.memory_v2")
    core_logger.handlers = [logging.NullHandler()]
    core_logger.propagate = False


# 首次导入时配置日志
_configure_core_logging()


@contextmanager
def _fact_writer():
    """创建事实写入器资源上下文。

    装配 MemoryWriter，仅提供 semantic 抽取器及事实后端。
    其他 Lane（event_task, entity_relation, behavior_policy）不提供抽取器。

    Yields:
        MemoryWriter: 配置好的写入器实例

    Note:
        - 使用独立的数据库 session，在 finally 中确保关闭
        - llm_client=None 关闭规划器额外模型补漏
        - SemanticExtractor 注入真实抽取客户端（DashScopeClient）
    """
    from server.database.connection_pool import db_pool
    from server.memory_v2.llm_gate import DashScopeClient
    from server.memory_v2.write.writer import MemoryWriter
    from server.memory_v2.write.extractors.semantic import SemanticExtractor
    from server.memory_v2.write.gate import MemoryGate
    from server.memory_v2.write.router import MemoryDispatcher
    from server.memory_v2.store.fact_store import FactStore

    session = db_pool.sync_session_factory()
    try:
        yield MemoryWriter(
            extractors={"semantic": SemanticExtractor(DashScopeClient())},
            gate=MemoryGate(),
            dispatcher=MemoryDispatcher(fact_store=FactStore(session)),
            llm_client=None,
        )
    finally:
        session.close()


def _normalize_write_result(raw, turn_id: str) -> WriteResult:
    """将核心 V2WriteResult 归一化为宿主 WriteResult。

    根据 lane_outcomes、failed_lanes、v2_write_success 和 commits 判断五种状态：
    - saved: 至少一条有效 CommitReceipt，且 truth_committed=True，无错误
    - partial: 部分提交成功，同时存在抽取/提交错误
    - skipped: speech_act 为 query_existing/ambiguous/filler
    - no_memory: 零提交且无错误（抽取为空或被门控拒绝）
    - failed: 有错误且无有效提交

    Args:
        raw: 核心返回的 V2WriteResult
        turn_id: 本次写入的轮次 ID

    Returns:
        WriteResult: 归一化后的结果
    """
    from server.memory_v2.contracts import CommitReceipt

    speech_act = raw.speech_act

    # 提取有效的 Memory ID（只接受 truth_committed=True 的 MemoryRecord）
    memory_ids = []
    for commit in raw.commits:
        if isinstance(commit, CommitReceipt):
            if commit.truth_committed and commit.aggregate_type == "MemoryRecord":
                memory_ids.append(commit.aggregate_id)

    # 判断是否有错误
    has_errors = len(raw.failed_lanes) > 0
    for outcome in raw.lane_outcomes:
        if outcome.status in ["api_error", "parse_error", "schema_error"]:
            has_errors = True
            break

    # 状态判定
    if speech_act in ["query_existing", "ambiguous", "filler"]:
        return WriteResult(
            status="skipped",
            speech_act=speech_act,
            memory_ids=[],
            turn_id=turn_id,
            message=f"已跳过：{_get_skip_reason(speech_act)}",
            error_code=None,
        )

    if speech_act in ["explicit_update", "explicit_delete"]:
        return WriteResult(
            status="skipped",
            speech_act=speech_act,
            memory_ids=[],
            turn_id=turn_id,
            message="已跳过：本阶段不支持修改或删除操作",
            error_code=None,
        )

    if memory_ids:
        if has_errors:
            return WriteResult(
                status="partial",
                speech_act=speech_act,
                memory_ids=memory_ids,
                turn_id=turn_id,
                message=f"部分已保存（{len(memory_ids)} 条），存在错误。Memory IDs: {', '.join(memory_ids[:3])}{'...' if len(memory_ids) > 3 else ''}",
                error_code="PARTIAL_COMMIT",
            )
        else:
            return WriteResult(
                status="saved",
                speech_act=speech_act,
                memory_ids=memory_ids,
                turn_id=turn_id,
                message=f"已保存 {len(memory_ids)} 条记忆，等待索引同步。Memory IDs: {', '.join(memory_ids[:3])}{'...' if len(memory_ids) > 3 else ''}",
                error_code=None,
            )
    else:
        if has_errors:
            error_code = _extract_error_code(raw)
            return WriteResult(
                status="failed",
                speech_act=speech_act,
                memory_ids=[],
                turn_id=turn_id,
                message=f"保存失败：{_get_error_message(error_code)}",
                error_code=error_code,
            )
        else:
            return WriteResult(
                status="no_memory",
                speech_act=speech_act,
                memory_ids=[],
                turn_id=turn_id,
                message="未生成可保存的事实（抽取为空或被门控拒绝）",
                error_code=None,
            )


def _get_skip_reason(speech_act: str) -> str:
    """获取跳过原因的用户友好描述。"""
    reasons = {
        "query_existing": "这是查询请求，不会写入记忆",
        "ambiguous": "表述不够明确",
        "filler": "无实质内容",
    }
    return reasons.get(speech_act, "不适合写入记忆")


def _extract_error_code(raw) -> str:
    """从 V2WriteResult 中提取错误代码。"""
    for outcome in raw.lane_outcomes:
        if outcome.error_code:
            return outcome.error_code
    return "UNKNOWN_ERROR"


def _get_error_message(error_code: str) -> str:
    """将错误代码转换为用户友好的错误消息。"""
    messages = {
        "API_ERROR": "模型调用失败",
        "PARSE_ERROR": "结果解析失败",
        "SCHEMA_ERROR": "数据格式错误",
        "DB_ERROR": "数据库错误",
        "UNKNOWN_ERROR": "未知错误",
    }
    return messages.get(error_code, "系统错误")


async def save_turn_to_memory(
    user_text: str,
    tenant_id: str,
    user_id: str,
    turn_id: str,
    *,
    confirmed: bool = False,
    metadata: dict | None = None,
) -> WriteResult:
    """保存用户确认的论文笔记到 Memory V2。

    此函数是 papermind-host 层调用 Memory V2 写入的统一入口。
    实现租户和用户隔离，确保不同租户/用户的记忆相互隔离。

    Args:
        user_text: 用户输入原文（论文笔记）
        tenant_id: 租户 ID，用于隔离不同租户的记忆
        user_id: 用户 ID，用于隔离同一租户下不同用户的记忆
        turn_id: 轮次 ID（UUID 字符串），用于溯源
        confirmed: 用户是否已确认保存（默认 False）
        metadata: Phase 3 笔记元数据（标签、阅读日期等），将保存到数据库

    Returns:
        WriteResult: 写入结果，包含状态、Memory IDs 和反馈消息

    Example:
        >>> from uuid import uuid4
        >>> result = await save_turn_to_memory(
        ...     user_text="我的论文《注意力机制研究》的阅读结论是：自注意力有效提升了模型性能。",
        ...     tenant_id="tenant_A",
        ...     user_id="user_alice",
        ...     turn_id=uuid4().hex,
        ...     confirmed=True
        ... )
        >>> print(result.status)  # 'saved'
        >>> print(result.memory_ids)  # ['mem-abc123...']
    """
    start_time = datetime.now(timezone.utc)

    # 输入验证
    if not user_text or not user_text.strip():
        return WriteResult(
            status="failed",
            speech_act=None,
            memory_ids=[],
            turn_id=turn_id,
            message="保存失败：输入文本为空",
            error_code="EMPTY_INPUT",
        )

    if not tenant_id or not user_id or not turn_id:
        return WriteResult(
            status="failed",
            speech_act=None,
            memory_ids=[],
            turn_id=turn_id,
            message="保存失败：缺少必要的身份信息",
            error_code="MISSING_IDENTITY",
        )

    # 未确认时直接返回 skipped
    if not confirmed:
        return WriteResult(
            status="skipped",
            speech_act=None,
            memory_ids=[],
            turn_id=turn_id,
            message="已跳过：用户未确认保存",
            error_code=None,
        )

    # Speech Act 分类
    try:
        # 动态添加 memoryV2-core 路径
        import sys
        from pathlib import Path
        memoryv2_core = Path(__file__).resolve().parent.parent.parent / "memoryV2-core"
        if str(memoryv2_core) not in sys.path:
            sys.path.insert(0, str(memoryv2_core))

        from server.memory_v2.speech_act import classify_speech_act
        speech_act = classify_speech_act(user_text)

        # 查询、歧义、填充直接跳过
        if speech_act in ["query_existing", "ambiguous", "filler"]:
            return WriteResult(
                status="skipped",
                speech_act=speech_act,
                memory_ids=[],
                turn_id=turn_id,
                message=f"已跳过：{_get_skip_reason(speech_act)}",
                error_code=None,
            )

        # 修改、删除本阶段不支持
        if speech_act in ["explicit_update", "explicit_delete"]:
            return WriteResult(
                status="skipped",
                speech_act=speech_act,
                memory_ids=[],
                turn_id=turn_id,
                message="已跳过：本阶段不支持修改或删除操作",
                error_code=None,
            )

    except Exception as e:
        logger.error("Speech Act 分类失败: turn_id=%s, error=%s", turn_id, str(e), exc_info=True)
        return WriteResult(
            status="failed",
            speech_act=None,
            memory_ids=[],
            turn_id=turn_id,
            message="保存失败：分类错误",
            error_code="CLASSIFICATION_ERROR",
        )

    # 调用核心写入
    try:
        with _fact_writer() as writer:
            # 直接 await 异步的 write_turn
            # Phase 3: 如果提供了 metadata，通过 write_turn 传递
            raw_result = await writer.write_turn(
                user_text=user_text,
                user_id=user_id,
                turn_id=turn_id,
                occurred_at=datetime.now(timezone.utc),
                tenant_id=tenant_id,
                metadata=metadata,
            )

            # 归一化结果
            result = _normalize_write_result(raw_result, turn_id)

            # 记录日志（不输出笔记全文）
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "Memory write completed: turn_id=%s, status=%s, speech_act=%s, "
                "memory_count=%d, elapsed=%.2fs, error_code=%s",
                turn_id, result.status, result.speech_act,
                len(result.memory_ids), elapsed, result.error_code,
            )

            return result

    except Exception as e:
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.error(
            "Memory write failed: turn_id=%s, tenant=%s, user=%s, elapsed=%.2fs, error=%s",
            turn_id, tenant_id, user_id, elapsed, str(e), exc_info=True,
        )
        return WriteResult(
            status="failed",
            speech_act=speech_act if 'speech_act' in locals() else None,
            memory_ids=[],
            turn_id=turn_id,
            message=f"保存失败：系统错误",
            error_code="SYSTEM_ERROR",
        )
