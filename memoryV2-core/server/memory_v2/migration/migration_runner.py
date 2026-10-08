"""MigrationRunner：幂等、可复用的迁移执行器（Phase 4A）。

读旧 mem0 记忆，调用 MigrationMapper 分类，写入 Phase 2 真值表。关键设计：
- **幂等**：按 source_turn_id（= 旧 memory_id）去重，重跑不产生重复
- **dry_run**：只输出迁移计划，不落库
- **可重跑**：清库后能重新迁移，不依赖上次状态
- **可回滚**：按 batch_id 删除本轮迁移写入的记录

⚠️ 测试环境可复用设计：rollback 按内部跟踪的 batch_id→processed_old_ids 映射。
跨进程重启后回滚需重新推导 old_ids（或扩展为持久化跟踪）。

见 Phase 4A spec、ADR 0008（迁移幂等设计）。
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from ..contracts import MigrationResult
from .migration_mapper import MigrationMapper
from ..models import Event, MemoryRecord


class OldMemorySource(Protocol):
    """旧记忆数据源协议（抽象 mem0 或其他来源）。"""

    def fetch_all(self) -> list[dict[str, Any]]:
        """返回所有旧记忆。每条结构：{memory_id, content, created_at, metadata?}"""
        ...


class MigrationRunner:
    """迁移执行器（可复用、幂等、可回滚）。

    使用示例：
        source = OldMem0Source(old_session)
        runner = MigrationRunner(source, new_session, MigrationMapper(), "t1", "u1")
        result = runner.migrate(dry_run=True)  # 验证迁移计划
        result = runner.migrate()               # 执行迁移
        runner.rollback(result.batch_id)        # 回滚
    """

    def __init__(
        self,
        old_source: OldMemorySource,
        new_session: Session,
        mapper: MigrationMapper,
        tenant_id: str,
        user_id: str,
    ):
        self._old_source = old_source
        self._new_session = new_session
        self._mapper = mapper
        self._tenant_id = tenant_id
        self._user_id = user_id
        # 回滚跟踪：batch_id → processed_old_ids
        self._batch_registry: dict[str, list[str]] = {}

    def migrate(
        self,
        dry_run: bool = False,
        incremental: bool = False,
    ) -> MigrationResult:
        """执行迁移。

        Args:
            dry_run: True 时只输出迁移计划，不写库
            incremental: True 时只迁移新增/变更记录（⚠️ 当前未实现，全量）

        Returns:
            MigrationResult：总数/成功数/跳过数/失败数/按类型统计/错误详情
        """
        batch_id = str(uuid4())
        old_memories = self._old_source.fetch_all()

        total = len(old_memories)
        success = 0
        skipped = 0
        failed = 0
        by_type: dict[str, int] = {}
        errors: list[dict[str, Any]] = []
        processed_old_ids: list[str] = []

        for old_mem in old_memories:
            old_id = old_mem.get("memory_id") or ""
            content = old_mem.get("content", "")

            # 幂等性检查：该 old_id 或 content_hash 已迁移过？
            if self._already_migrated(old_id, content):
                skipped += 1
                continue

            # 调用 mapper 分类
            new_record = self._mapper.classify(old_mem, self._tenant_id, self._user_id)

            # mapper 返回 None → 跳过（如 joke）
            if new_record is None:
                skipped += 1
                continue

            # dry_run 模式：只统计不写库
            if dry_run:
                success += 1
                mem_type = getattr(new_record, "memory_type", "episodic")
                by_type[mem_type] = by_type.get(mem_type, 0) + 1
                continue

            # 写库
            try:
                self._new_session.add(new_record)
                self._new_session.flush()  # 先 flush 验证约束
                success += 1
                processed_old_ids.append(old_id)

                # 按 memory_type 统计
                mem_type = getattr(new_record, "memory_type", "episodic")
                by_type[mem_type] = by_type.get(mem_type, 0) + 1

            except Exception as e:
                failed += 1
                errors.append({"old_id": old_id, "reason": str(e)})
                self._new_session.rollback()

        # 非 dry_run 时 commit
        if not dry_run and (success > 0 or failed > 0):
            try:
                self._new_session.commit()
            except Exception as e:
                self._new_session.rollback()
                # 所有成功变失败
                failed += success
                success = 0
                errors.append({"batch": "commit_failed", "reason": str(e)})

        # 记录 batch 用于回滚
        if not dry_run:
            self._batch_registry[batch_id] = processed_old_ids

        return MigrationResult(
            batch_id=batch_id,
            total=total,
            success=success,
            skipped=skipped,
            failed=failed,
            by_type=by_type,
            errors=errors,
        )

    def rollback(self, batch_id: str) -> int:
        """回滚指定批次的迁移（删除本轮写入的记录）。

        Args:
            batch_id: migrate() 返回的 batch_id

        Returns:
            删除的记录数

        ⚠️ 基于内部跟踪的 processed_old_ids。跨进程重启后需重新推导或持久化跟踪。
        """
        processed_old_ids = self._batch_registry.get(batch_id, [])
        if not processed_old_ids:
            return 0

        # 删除 source_turn_id 在 processed_old_ids 中的记录
        deleted = 0

        # MemoryRecord
        mem_deleted = (
            self._new_session.query(MemoryRecord)
            .filter(MemoryRecord.source_turn_id.in_(processed_old_ids))
            .delete(synchronize_session=False)
        )
        deleted += mem_deleted

        # Event
        event_deleted = (
            self._new_session.query(Event)
            .filter(Event.source_turn_id.in_(processed_old_ids))
            .delete(synchronize_session=False)
        )
        deleted += event_deleted

        self._new_session.commit()

        # 清理跟踪
        self._batch_registry.pop(batch_id, None)

        return deleted

    def _already_migrated(self, old_id: str, content: str) -> bool:
        """检查该 old_id 或 content_hash 是否已迁移（幂等性保证）。

        双重去重：
        1. source_turn_id = old_id（记录级去重，重跑同一批次）
        2. content_hash（内容级去重，语义重复但不同 old_id）
        """
        if not old_id:
            return False

        # 1. 按 source_turn_id 查（记录级去重）
        exists_mem = (
            self._new_session.query(MemoryRecord.memory_id)
            .filter(MemoryRecord.source_turn_id == old_id)
            .first()
        )
        if exists_mem:
            return True

        exists_event = (
            self._new_session.query(Event.event_id)
            .filter(Event.source_turn_id == old_id)
            .first()
        )
        if exists_event:
            return True

        # 2. 按 content_hash 查（内容级去重，防止语义重复）
        from .migration_mapper import MigrationMapper
        chash = MigrationMapper.content_hash(content)

        # 查 MemoryRecord.text_zh hash
        mem_records = (
            self._new_session.query(MemoryRecord)
            .filter(
                MemoryRecord.tenant_id == self._tenant_id,
                MemoryRecord.user_id == self._user_id,
            )
            .all()
        )
        for rec in mem_records:
            if MigrationMapper.content_hash(rec.text_zh) == chash:
                return True

        # Event.title hash
        events = (
            self._new_session.query(Event)
            .filter(
                Event.tenant_id == self._tenant_id,
                Event.user_id == self._user_id,
            )
            .all()
        )
        for ev in events:
            if MigrationMapper.content_hash(ev.title) == chash:
                return True

        return False
