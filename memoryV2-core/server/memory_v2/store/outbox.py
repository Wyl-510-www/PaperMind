"""Outbox worker：消费 outbox 记录，同步到 candidate_index。

真值写 MySQL 和 outbox 在同一事务（repository 保证）。worker 异步消费 pending 记录：
- 成功 → 标 done
- 失败 → retry_count++，设 next_retry_at
- 达到重试上限 → 标 dead（dead-letter）

index adapter 可注入，测试用 fake index 无需真实 Qdrant。
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from ..models import MemoryRecord, Outbox
from .repository import now_utc

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 60
CLAIM_LEASE_SECONDS = 60  # P1-4：claim 租约时长，过期后可被其他 worker 重新领取


def _to_qdrant_id(memory_id: str) -> str:
    """将 memory_id 转为合法的 Qdrant UUID。

    memory_id 格式不定（mem-xxx/evt-xxx/纯uuid），通过 MD5 生成确定性 UUID。
    """
    digest = hashlib.md5(memory_id.encode()).hexdigest()
    return str(uuid.UUID(digest))


class IndexAdapter(Protocol):
    """索引适配器接口（IndexV2 或测试 fake 都实现它）"""

    def upsert(self, point_id: str, vector: list[float], payload: dict) -> None: ...
    def delete(self, point_id: str) -> None: ...


class Embedder(Protocol):
    """embedding 接口"""

    def embed(self, text: str) -> list[float]: ...


class OutboxWorker:
    """消费 outbox 记录，同步到 candidate_index"""

    def __init__(
        self,
        session: Session,
        index: IndexAdapter,
        embedder: Embedder,
        max_retries: int = MAX_RETRIES,
        worker_id: str | None = None,
    ):
        self.session = session
        self.index = index
        self.embedder = embedder
        self.max_retries = max_retries
        # P1-4：每个 worker 实例有唯一 id，用于 claim 归属
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"

    def _claim_batch(self, batch_size: int = 100, now: datetime | None = None) -> list[Outbox]:
        """并发安全地 claim 一批待处理记录（P1-4）。

        可 claim 的条件：pending + (next_retry_at 到期) + (未被 claim 或 claim 租约已过期)。
        claim 动作：条件 UPDATE 打上 claimed_by=self.worker_id 与 claimed_until。
        用行级条件 UPDATE（rowcount 判定）保证并发下同一行只被一个 worker 抢到——
        MySQL 下等价于 SELECT ... FOR UPDATE SKIP LOCKED 的效果，SQLite 下靠事务串行化。

        Returns:
            本 worker 成功 claim 到的 Outbox 记录列表
        """
        now = now or now_utc()
        lease_until = now + timedelta(seconds=CLAIM_LEASE_SECONDS)

        candidates = self.session.query(Outbox).filter(
            Outbox.status == "pending",
        ).filter(
            (Outbox.next_retry_at.is_(None)) | (Outbox.next_retry_at <= now)
        ).filter(
            (Outbox.claimed_until.is_(None)) | (Outbox.claimed_until <= now)
        ).order_by(Outbox.id).limit(batch_size).all()

        claimed: list[Outbox] = []
        for record in candidates:
            # 条件 UPDATE：只有仍满足"未被他人 claim"时才抢到（防并发）
            rows = self.session.query(Outbox).filter(
                Outbox.id == record.id,
                Outbox.status == "pending",
            ).filter(
                (Outbox.claimed_until.is_(None)) | (Outbox.claimed_until <= now)
            ).update(
                {
                    "claimed_by": self.worker_id,
                    "claimed_until": lease_until,
                    "updated_at": now_utc(),
                },
                synchronize_session=False,
            )
            if rows == 1:
                self.session.refresh(record)
                claimed.append(record)
        self.session.commit()
        return claimed

    def process_pending(self, batch_size: int = 100, now: datetime | None = None) -> dict[str, int]:
        """处理一批 pending 记录（先并发安全 claim，再逐条处理）。

        Args:
            batch_size: 单批处理数量
            now: 当前时间（用于判断 next_retry_at 是否到期），默认 now_utc()

        Returns:
            {"done": N, "failed": M, "dead": K}
        """
        now = now or now_utc()
        stats = {"done": 0, "failed": 0, "dead": 0}

        # P1-4：先 claim，只处理本 worker 抢到的记录
        pending = self._claim_batch(batch_size=batch_size, now=now)

        for record in pending:
            try:
                self._process_one(record)
                record.status = "done"
                record.updated_at = now_utc()
                stats["done"] += 1
            except Exception as e:
                record.retry_count += 1
                record.last_error = str(e)[:500]
                if record.retry_count >= self.max_retries:
                    record.status = "dead"
                    stats["dead"] += 1
                else:
                    record.next_retry_at = now + timedelta(
                        seconds=RETRY_BACKOFF_SECONDS * record.retry_count
                    )
                    stats["failed"] += 1
                record.updated_at = now_utc()

        self.session.commit()
        return stats

    def _process_one(self, record: Outbox):
        """处理单条 outbox 记录"""
        if record.operation == "delete":
            agg_id = record.aggregate_id
            self.index.delete(_to_qdrant_id(agg_id))
            return

        # upsert：需要从 MySQL 读真值，embed 后写索引
        memory_id = record.payload_json.get("memory_id", record.aggregate_id)
        mem = self.session.query(MemoryRecord).filter_by(memory_id=memory_id).first()

        if mem is None:
            # 真值不存在（可能已删除），跳过
            return

        # 已删除的记录不索引
        if mem.status == "deleted":
            self.index.delete(memory_id[4:] if memory_id.startswith("mem-") else memory_id)
            return

        vector = self.embedder.embed(mem.text_zh)
        point_id = _to_qdrant_id(memory_id)
        self.index.upsert(
            point_id=point_id,
            vector=vector,
            payload={
                "memory_id": memory_id,
                "text_zh": mem.text_zh,
                "content": mem.text_zh,  # 添加 content 字段用于检索
                "fact_key": mem.fact_key,
                "status": mem.status,
                "tenant_id": mem.tenant_id,
                "user_id": str(mem.user_id),
                "memory_type": mem.memory_type,
                "subject_id": mem.subject_id,
                "modality": mem.modality,
                "confidence": mem.confidence,
                "importance": mem.importance,
                "expires_at": mem.expires_at.isoformat() if mem.expires_at else None,
                "schema_version": 1,
            },
        )

        # Bug #4 修复: 回写 index_status，标记该记录已成功索引到 Qdrant
        mem.index_status = "indexed"
        self.session.flush()
