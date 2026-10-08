"""真值变更存储：UPDATE 和 DELETE 的事务保证

M2 实施：实现完整的更新/删除事务，确保 truth + active + outbox + index 的原子性。

设计原则：
- UPDATE: 创建新版本，supersede 旧版本
- DELETE: tombstone + 索引删除 + blocked value
- Benchmark 模式同步索引，生产模式异步（通过 Outbox）
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session


class MutationResult(BaseModel):
    """变更操作结果"""
    success: bool
    action: Literal["update", "delete", "needs_clarification"]
    old_truth_id: str | None = None
    new_truth_id: str | None = None
    blocked_value: str | None = None
    outbox_id: str | None = None
    error_code: str | None = None


class MutationStore:
    """变更存储：确保 truth + active + outbox + index 原子性

    职责：
    1. UPDATE: 创建新版本 + supersede 旧版本
    2. DELETE: tombstone + blocked value
    3. Outbox 事件（触发异步索引更新）
    4. Benchmark 模式同步索引
    """

    def __init__(self, db_session: Session, index_client=None):
        """
        Args:
            db_session: SQLAlchemy session
            index_client: Qdrant 索引客户端（可选）
        """
        self.db = db_session
        self.index = index_client

    async def apply_update(
        self,
        tenant_id: str,
        user_id: str,
        namespace: str,
        target_id: str,
        new_value: str,
        occurred_at: datetime,
    ) -> MutationResult:
        """应用 UPDATE：创建新版本，supersede 旧版本

        事务步骤：
        1. 查询旧 truth (active=True)
        2. 创建新版本 (同一 fact_key)
        3. Supersede 旧版本 (active=False, superseded_by)
        4. 写 Outbox 事件
        5. Commit 事务
        6. 同步索引（Benchmark 模式）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            target_id: 目标 memory_id
            new_value: 新值
            occurred_at: 发生时间

        Returns:
            MutationResult: 变更结果
        """
        from server.memory_v2.models import MemoryRecord, OutboxEvent
        from server.memory_v2.write.id_gen import generate_id

        # 1. 查询旧 truth
        old_record = self.db.query(MemoryRecord).filter(
            MemoryRecord.memory_id == target_id,
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.namespace == namespace,
            MemoryRecord.active == True,
        ).first()

        if not old_record:
            return MutationResult(
                success=False,
                action="needs_clarification",
                error_code="TARGET_NOT_FOUND",
            )

        # 2. 创建新版本
        new_record = MemoryRecord(
            memory_id=generate_id("mem"),
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            fact_key=old_record.fact_key,
            predicate=old_record.predicate,
            subject_id=old_record.subject_id,
            value=new_value,
            memory_type=old_record.memory_type,
            active=True,
            supersedes=old_record.memory_id,
            occurred_at=occurred_at,
            created_at=datetime.utcnow(),
        )
        self.db.add(new_record)

        # 3. Supersede 旧版本
        old_record.active = False
        old_record.superseded_by = new_record.memory_id
        old_record.superseded_at = datetime.utcnow()

        # 4. 写 Outbox（触发异步索引更新）
        outbox = OutboxEvent(
            outbox_id=generate_id("outbox"),
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="memory.updated",
            aggregate_id=new_record.memory_id,
            aggregate_type="MemoryRecord",
            payload={
                "old_id": old_record.memory_id,
                "new_id": new_record.memory_id,
                "predicate": new_record.predicate,
                "new_value": new_value,
            },
            status="pending",
            created_at=datetime.utcnow(),
        )
        self.db.add(outbox)

        # 5. Commit 事务
        self.db.commit()

        # 6. 同步索引（Benchmark 模式）
        if self.index and os.getenv("BENCHMARK_MODE", "false").lower() == "true":
            try:
                # 删除旧向量
                await self.index.delete_by_memory_ids([old_record.memory_id])
                # 插入新向量
                await self.index.upsert_memory(new_record)
            except Exception as e:
                # 索引失败不影响事务成功（已落库）
                import logging
                logging.warning(f"索引更新失败（事务已提交）: {e}")

        return MutationResult(
            success=True,
            action="update",
            old_truth_id=old_record.memory_id,
            new_truth_id=new_record.memory_id,
            outbox_id=outbox.outbox_id,
        )

    async def apply_delete(
        self,
        tenant_id: str,
        user_id: str,
        namespace: str,
        target_id: str,
        occurred_at: datetime,
    ) -> MutationResult:
        """应用 DELETE：tombstone + 索引删除 + blocked value

        事务步骤：
        1. 查询目标 (active=True)
        2. Tombstone (active=False, deleted_at)
        3. Blocked value（高敏字段）
        4. 写 Outbox 事件
        5. Commit 事务
        6. 同步索引删除（Benchmark 模式）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            target_id: 目标 memory_id
            occurred_at: 发生时间

        Returns:
            MutationResult: 变更结果
        """
        from server.memory_v2.models import MemoryRecord, OutboxEvent
        from server.memory_v2.write.id_gen import generate_id

        # 1. 查询目标
        target = self.db.query(MemoryRecord).filter(
            MemoryRecord.memory_id == target_id,
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.namespace == namespace,
            MemoryRecord.active == True,
        ).first()

        if not target:
            return MutationResult(
                success=False,
                action="needs_clarification",
                error_code="TARGET_NOT_FOUND",
            )

        # 2. Tombstone（设置 active=False + deleted_at）
        target.active = False
        target.deleted_at = datetime.utcnow()

        # 3. Blocked value（高敏字段，如昵称）
        blocked_value = None
        if target.predicate in ("nickname.current", "diet.dislike", "allergy"):
            # TODO: 实现 BlockedValueStore
            # from server.memory_v2.guard.blocked_guard import BlockedValueStore
            # blocked_store = BlockedValueStore(self.db)
            # blocked_store.add_blocked_value(...)
            blocked_value = target.value

        # 4. Outbox
        outbox = OutboxEvent(
            outbox_id=generate_id("outbox"),
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="memory.deleted",
            aggregate_id=target.memory_id,
            aggregate_type="MemoryRecord",
            payload={
                "deleted_id": target.memory_id,
                "predicate": target.predicate,
                "value": target.value,
            },
            status="pending",
            created_at=datetime.utcnow(),
        )
        self.db.add(outbox)

        # 5. Commit
        self.db.commit()

        # 6. 同步索引删除（Benchmark 模式）
        if self.index and os.getenv("BENCHMARK_MODE", "false").lower() == "true":
            try:
                await self.index.delete_by_memory_ids([target.memory_id])
            except Exception as e:
                import logging
                logging.warning(f"索引删除失败（事务已提交）: {e}")

        return MutationResult(
            success=True,
            action="delete",
            old_truth_id=target.memory_id,
            blocked_value=blocked_value,
            outbox_id=outbox.outbox_id,
        )
