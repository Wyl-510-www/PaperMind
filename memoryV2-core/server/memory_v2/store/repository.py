"""MySQL 真值事务层。

封装所有真值写入的原子操作：
- fact 版本化 + active pointer 切换（同一事务）
- event 条件更新 + 乐观锁
- tombstone 软删除
- 幂等键去重（P0-2：靠 DB 唯一约束保证）
- active pointer 重建

fact_store/event_store/nickname_store 都通过 repository 落库。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ActiveFact, Event, MemoryRecord, Nickname, Outbox
from ..transitions import EventSnapshot, EventStatus, sql_transition_predicate
from ..tracing.context import get_or_create_write_trace


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class _Unset:
    """哨兵：区分"未传参"与"显式传 None"（P1-3）。"""

    def __repr__(self) -> str:  # pragma: no cover
        return "<UNSET>"


_UNSET = _Unset()


class Repository:
    """真值事务层"""

    def __init__(self, session: Session):
        self.session = session

    # ─── fact 版本化 ─────────────────────────────────────────────────────────

    def write_fact_version(
        self,
        memory_id: str,
        tenant_id: str,
        user_id: str,
        namespace: str,
        fact_key: str,
        fact_data: dict[str, Any],
        source_turn_id: str | None = None,
        candidate_id: str | None = None,
        skip_outbox: bool = False,
    ) -> str:
        """写入新 fact 版本，旧版本标 superseded，active pointer 切换。

        同一事务：插入新 record + 更新旧 record + 切换 active + 写 outbox

        P0-2 幂等：candidate_id 非空时先做预检（快速路径），命中既有记录直接
        返回其 memory_id；真正的去重保证由 DB 唯一约束 uq_idempotency 兜底，
        并发下由 write_fact_version 的调用方（fact_store）捕获 IntegrityError。

        Returns:
            memory_id（若幂等命中，返回既有 memory_id）
        """
        # Chain Trace 集成：获取追踪对象
        w_trace = get_or_create_write_trace()
        
        # P0-2 幂等预检：同一 (scope, turn, candidate) 已存在则直接返回既有
        if candidate_id is not None:
            existing = self.session.query(MemoryRecord).filter_by(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
                source_turn_id=source_turn_id,
                candidate_id=candidate_id,
            ).first()
            if existing is not None:
                return existing.memory_id

        # 查当前 active 版本
        old_active = self.session.query(ActiveFact).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            fact_key=fact_key,
        ).first()

        version = 1
        supersedes_id = None

        if old_active:
            # 已有版本，标记旧版本 superseded
            old_record = self.session.query(MemoryRecord).filter_by(
                memory_id=old_active.memory_id
            ).first()
            if old_record:
                old_record.status = "superseded"
                old_record.updated_at = now_utc()
                version = old_record.version + 1
                supersedes_id = old_record.memory_id

        # 插入新版本
        new_record = MemoryRecord(
            memory_id=memory_id,
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            memory_type=fact_data.get("memory_type", "semantic"),
            fact_key=fact_key,
            subject_id=fact_data.get("subject_id"),
            predicate=fact_data.get("predicate"),
            value_json=fact_data.get("value_json"),
            text_zh=fact_data["text_zh"],
            modality=fact_data["modality"],
            status="active",
            confidence=fact_data.get("confidence", 0.5),
            importance=fact_data.get("importance", 0.5),
            valid_from=fact_data.get("valid_from"),
            valid_to=fact_data.get("valid_to"),
            version=version,
            supersedes_id=supersedes_id,
            source_turn_id=source_turn_id,
            candidate_id=candidate_id,  # P0-2：幂等键
            # Ticket 04: 偏好结构化字段
            domain=fact_data.get("domain"),
            object_key=fact_data.get("object_key"),
            polarity=fact_data.get("polarity"),
            preference_strength=fact_data.get("preference_strength"),
            provenance=fact_data.get("provenance"),
            evidence_type=fact_data.get("provenance") or fact_data.get("evidence_type"),
            # Fix2: occurred_at — 消息发生时间（UTC），用于 scorer recency 和冲突裁决
            occurred_at=fact_data.get("occurred_at"),
            # Phase 3: 笔记元数据
            note_metadata=fact_data.get("note_metadata"),
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.session.add(new_record)

        # 切换 active pointer
        if old_active:
            old_active.memory_id = memory_id
            old_active.updated_at = now_utc()
            # Chain Trace: 记录 truth_active_id (ActiveFact 的指针)
            w_trace.truth_active_ids.append(memory_id)
        else:
            new_active = ActiveFact(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
                fact_key=fact_key,
                memory_id=memory_id,
                updated_at=now_utc(),
            )
            self.session.add(new_active)
            # Chain Trace: 记录 truth_active_id (新建的 ActiveFact)
            w_trace.truth_active_ids.append(memory_id)

        # 写 outbox（BEHAVIOR_POLICY 不写 Qdrant）
        if not skip_outbox:
            outbox_id = self._write_outbox(memory_id, "upsert", {"memory_id": memory_id, "fact_key": fact_key})
            # Chain Trace: 记录 outbox_id
            if outbox_id:
                w_trace.outbox_ids.append(outbox_id)

        return memory_id

    # ─── event 条件更新 ──────────────────────────────────────────────────────

    def transition_event(
        self,
        event_id: str,
        new_status: EventStatus,
        expected_version: int,
        new_start_at: datetime | None | _Unset = _UNSET,
        new_end_at: datetime | None | _Unset = _UNSET,
    ) -> bool:
        """条件更新事件状态（乐观锁）。

        WHERE event_id=? AND version=? AND status IN (scheduled,rescheduled)
        要求 rowcount==1，否则视为冲突或已终止。

        P1-3 修复：new_start_at/new_end_at 用 _UNSET 哨兵——只有显式传入（含显式
        传 None）时才写入 UPDATE，否则不覆盖原时间。避免只改状态时把事件时间清空。

        Returns:
            True 成功，False 冲突
        """
        # Chain Trace 集成：获取追踪对象
        w_trace = get_or_create_write_trace()
        
        pred = sql_transition_predicate(event_id, expected_version)

        update_values: dict[str, Any] = {
            "status": new_status.value,
            "version": expected_version + 1,
            "updated_at": now_utc(),
        }
        if not isinstance(new_start_at, _Unset):
            update_values["start_at"] = new_start_at
        if not isinstance(new_end_at, _Unset):
            update_values["end_at"] = new_end_at

        result = self.session.query(Event).filter(
            Event.event_id == pred["event_id"],
            Event.version == pred["expected_version"],
            Event.status.in_(pred["allowed_current_statuses"]),
        ).update(
            update_values,
            synchronize_session=False,
        )

        if result == 1:
            outbox_id = self._write_outbox(event_id, "upsert", {"event_id": event_id, "status": new_status.value})
            # Chain Trace: 记录 outbox_id
            if outbox_id:
                w_trace.outbox_ids.append(outbox_id)
            return True
        return False

    # ─── tombstone ───────────────────────────────────────────────────────────

    def delete_memory(self, memory_id: str) -> bool:
        """软删除：WHERE status != deleted 标记 deleted。

        P1-2 修复：若被删记录是某 fact_key 的当前 active 版本，同事务维护 ActiveFact
        指针——回退到前一版本（supersedes 链），无前值则删除该 ActiveFact 行，
        避免 active pointer 悬挂指向 deleted 记录。

        Returns:
            True 成功，False 已删除或不存在
        """
        # Chain Trace 集成：获取追踪对象
        w_trace = get_or_create_write_trace()
        
        # 先读记录（拿 fact_key / scope，用于维护 ActiveFact）
        record = self.session.query(MemoryRecord).filter_by(memory_id=memory_id).first()
        if record is None or record.status == "deleted":
            return False

        result = self.session.query(MemoryRecord).filter(
            MemoryRecord.memory_id == memory_id,
            MemoryRecord.status != "deleted",
        ).update(
            {
                "status": "deleted",
                "updated_at": now_utc(),
            },
            synchronize_session=False,
        )

        if result != 1:
            return False

        # P1-2：维护 ActiveFact 指针
        if record.fact_key is not None:
            self._reconcile_active_fact_after_delete(record)

        outbox_id = self._write_outbox(memory_id, "delete", {"memory_id": memory_id})
        # Chain Trace: 记录 outbox_id
        if outbox_id:
            w_trace.outbox_ids.append(outbox_id)
        
        return True

    def _reconcile_active_fact_after_delete(self, deleted_record: MemoryRecord) -> None:
        """删除某记录后，若它是当前 active pointer 目标，回退到前一版本或清除。"""
        active = self.session.query(ActiveFact).filter_by(
            tenant_id=deleted_record.tenant_id,
            user_id=deleted_record.user_id,
            namespace=deleted_record.namespace,
            fact_key=deleted_record.fact_key,
        ).first()

        # 该 fact_key 无 active 指针，或指针不指向被删记录 → 无需处理
        if active is None or active.memory_id != deleted_record.memory_id:
            return

        # 找前一版本：同 fact_key、未删除、version 最大且 < 被删版本
        prior = self.session.query(MemoryRecord).filter(
            MemoryRecord.tenant_id == deleted_record.tenant_id,
            MemoryRecord.user_id == deleted_record.user_id,
            MemoryRecord.namespace == deleted_record.namespace,
            MemoryRecord.fact_key == deleted_record.fact_key,
            MemoryRecord.status != "deleted",
            MemoryRecord.memory_id != deleted_record.memory_id,
        ).order_by(MemoryRecord.version.desc()).first()

        if prior is not None:
            active.memory_id = prior.memory_id
            active.updated_at = now_utc()
        else:
            self.session.delete(active)

    # ─── 幂等键去重 ──────────────────────────────────────────────────────────

    def check_idempotency_key(
        self, tenant_id: str, user_id: str, turn_id: str, candidate_id: str,
        namespace: str = "user_memory",
    ) -> bool:
        """检查幂等键是否已存在（快速预检）。

        P0-2 修复：按 candidate_id 字段精确查询，不再靠 text_zh.contains（原实现
        几乎恒返回 False）。这是快速路径；真正的去重保证由 DB 唯一约束
        uq_idempotency 兜底，见 write_fact_version。

        Returns:
            True 已存在（跳过写入），False 不存在（可写入）
        """
        existing = self.session.query(MemoryRecord).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            source_turn_id=turn_id,
            candidate_id=candidate_id,
        ).first()
        return existing is not None

    # ─── active pointer 重建 ─────────────────────────────────────────────────

    def rebuild_active_pointers(self, tenant_id: str, user_id: str, namespace: str):
        """从 memory_v2_record 重建 active_fact 表。

        清空后重新扫描所有 active 记录，按 fact_key 分组取最新版本。
        """
        # 清空
        self.session.query(ActiveFact).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
        ).delete(synchronize_session=False)

        # 扫描所有 active 记录
        records = self.session.query(MemoryRecord).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            status="active",
        ).filter(
            MemoryRecord.fact_key.isnot(None)
        ).all()

        # 按 fact_key 分组，取最大 version
        fact_map: dict[str, MemoryRecord] = {}
        for rec in records:
            if rec.fact_key not in fact_map or rec.version > fact_map[rec.fact_key].version:
                fact_map[rec.fact_key] = rec

        # 重建 active pointer
        for fact_key, rec in fact_map.items():
            new_active = ActiveFact(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
                fact_key=fact_key,
                memory_id=rec.memory_id,
                updated_at=now_utc(),
            )
            self.session.add(new_active)

    # ─── 辅助 ────────────────────────────────────────────────────────────────

    def _write_outbox(self, aggregate_id: str, operation: str, payload: dict) -> str:
        """写 outbox 记录（同一事务）
        
        Returns:
            outbox_id: 生成的 Outbox 记录 ID (格式: "outbox-{id}")
        """
        ob = Outbox(
            aggregate_id=aggregate_id,
            operation=operation,
            payload_json=payload,
            status="pending",
            retry_count=0,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.session.add(ob)
        # flush 以获取自增 id
        self.session.flush()
        outbox_id = f"outbox-{ob.id}"
        return outbox_id

    def commit(self):
        """提交事务（带异常保护）"""
        try:
            self.session.commit()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Database commit failed: {e}", exc_info=True)
            self.rollback()
            raise

    def rollback(self):
        """回滚事务"""
        self.session.rollback()
