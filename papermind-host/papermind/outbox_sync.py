"""Memory V2 Outbox 同步模块。

此模块封装 Memory V2 的 Outbox 同步功能，提供显式同步接口。
核心功能：
1. 显式触发 Outbox 批次消费
2. 将 MySQL 记录同步到 Qdrant 向量索引
3. 返回同步统计（done/failed/dead）
4. 保留核心重试与退避机制
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """同步结果。

    Attributes:
        status: 同步状态
            - completed: 批次处理完成（done > 0 或全部为空）
            - failed: 至少一条失败或 dead
        done: 成功同步的记录数
        failed: 失败需要重试的记录数
        dead: 达到重试上限的记录数（dead-letter）
        message: 用户可读的反馈消息
    """
    status: Literal["completed", "failed"]
    done: int
    failed: int
    dead: int
    message: str


def _process_batch(batch_size: int) -> dict[str, int]:
    """在当前线程中处理一批 Outbox 记录。

    此函数创建独立的数据库 session 和索引连接，执行同步后释放资源。
    复用核心 OutboxWorker.process_pending，保留重试与退避机制。

    Args:
        batch_size: 单批处理数量

    Returns:
        统计字典：{"done": N, "failed": M, "dead": K}

    Raises:
        Exception: 数据库、索引或 embedding 错误
    """
    from server.database.connection_pool import db_pool
    from server.memory_v2.retrieve.index_v2 import IndexV2
    from server.memory_v2.retrieve.embedder import RealEmbedder
    from server.memory_v2.store.outbox import OutboxWorker

    session = db_pool.sync_session_factory()
    try:
        # 初始化索引和 embedder
        index = IndexV2()
        index.create_collection_if_not_exists()

        embedder = RealEmbedder()
        embedder.validate_dimension(index.embedding_dim)

        # 创建 worker 并处理批次
        worker = OutboxWorker(session, index, embedder)
        stats = worker.process_pending(batch_size)

        return stats

    finally:
        session.close()


async def sync_outbox_batch(batch_size: int = 100) -> SyncResult:
    """显式同步一批 Outbox 记录。

    此函数是宿主层触发 Outbox 消费的统一入口。
    同步将 MySQL 中已提交的记忆记录索引到 Qdrant，使其可被检索。

    Args:
        batch_size: 单批处理数量（默认 100）

    Returns:
        SyncResult: 同步结果，包含状态和统计信息

    Note:
        - 批次处理的是数据库待处理队列，可能包含其他记忆
        - done > 0 不能证明当前 memory_ids 已可检索
        - 零条处理是合法的空批次，不是当前笔记已同步的证明
        - 重试复用核心 next_retry_at、retry_count、dead 状态
        - 同步失败不否定已经成功提交的 MySQL 事实

    Example:
        >>> result = await sync_outbox_batch(batch_size=100)
        >>> print(result.status)  # 'completed'
        >>> print(result.done, result.failed, result.dead)  # 5 0 0
    """
    # 输入验证
    if batch_size <= 0:
        return SyncResult(
            status="failed",
            done=0,
            failed=0,
            dead=0,
            message="同步失败：batch_size 必须为正整数",
        )

    try:
        # 在线程池中执行同步（因为核心是同步代码）
        stats = await asyncio.to_thread(_process_batch, batch_size)

        done = stats.get("done", 0)
        failed = stats.get("failed", 0)
        dead = stats.get("dead", 0)

        # 判断状态
        if failed > 0 or dead > 0:
            status = "failed"
            if done > 0:
                message = f"部分完成：{done} 条成功，{failed} 条失败，{dead} 条 dead"
            else:
                message = f"同步失败：{failed} 条失败，{dead} 条 dead"
        else:
            status = "completed"
            if done > 0:
                message = f"同步完成：{done} 条记录已索引"
            else:
                message = "同步完成：当前批次为空"

        # 记录日志
        logger.info(
            "Outbox sync completed: batch_size=%d, status=%s, done=%d, failed=%d, dead=%d",
            batch_size, status, done, failed, dead,
        )

        return SyncResult(
            status=status,
            done=done,
            failed=failed,
            dead=dead,
            message=message,
        )

    except Exception as e:
        logger.error(
            "Outbox sync failed: batch_size=%d, error=%s",
            batch_size, str(e), exc_info=True,
        )
        return SyncResult(
            status="failed",
            done=0,
            failed=0,
            dead=0,
            message=f"同步失败：系统错误 - {str(e)[:100]}",
        )
