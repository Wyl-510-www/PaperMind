"""Event/task 写入与状态迁移。

router 的 EPISODIC/TASK 路由调用 event_store。scheduled 事件可改期/取消/完成，
状态迁移用 transitions 校验，并发迁移通过 repository 乐观锁互斥。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from ..contracts import MemoryType, WriteDecision
from ..models import Event
from .repository import Repository, now_utc, _UNSET
from ..transitions import EventSnapshot, EventStatus, transition_event


class EventStore:
    """event/task 的状态机写入"""

    def __init__(self, session: Session):
        self.session = session
        self.repo = Repository(session)

    def create_event(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        namespace: str = "user_memory",
        source_turn_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> str:
        """创建新事件。

        Args:
            decision: 门控决策，route 必须是 EPISODIC 或 TASK
            tenant_id/user_id/namespace: 隔离范围
            source_turn_id: 来源轮次

        Returns:
            event_id

        Raises:
            ValueError: route 不是 EPISODIC/TASK
        """
        if decision.route not in (MemoryType.EPISODIC, MemoryType.TASK):
            raise ValueError(f"EventStore 只处理 EPISODIC/TASK 路由，收到 {decision.route}")

        candidate = decision.candidate
        event_id = f"evt-{uuid.uuid4().hex[:16]}"

        # 从 candidate 提取事件信息
        event_type = "task" if decision.route == MemoryType.TASK else "event"
        title = candidate.normalized_text_zh[:255]  # 截断到表字段长度

        evt = Event(
            event_id=event_id,
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            event_type=event_type,
            title=title,
            participants_json=None,  # Phase 2 最小实现，后续扩展
            location_json=None,
            start_at=candidate.time.absolute_start,
            end_at=candidate.time.absolute_end,
            timezone_name="Asia/Shanghai",  # 展示用；absolute_start 已是 UTC
            status=EventStatus.SCHEDULED.value,
            version=1,
            source_turn_id=source_turn_id,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.session.add(evt)
        self.repo._write_outbox(event_id, "upsert", {"event_id": event_id, "status": "scheduled"})
        self.repo.commit()
        return event_id

    def transition(
        self,
        event_id: str,
        new_status: EventStatus,
        expected_version: int,
        now: datetime,
        new_start_at: datetime | None = None,
        new_end_at: datetime | None = None,
    ) -> bool:
        """迁移事件状态。

        Args:
            event_id: 事件 ID
            new_status: 目标状态
            expected_version: 期望版本（乐观锁）
            now: 当前时间（带时区）
            new_start_at: 改期时的新开始时间（None 保持不变，显式传值则更新）
            new_end_at: 新结束时间（None 保持不变，显式传值则更新）

        Returns:
            True 成功，False 乐观锁冲突或已终止

        Raises:
            ValueError: 从 transitions.transition_event 传递的校验异常
        """
        # 读当前事件
        evt = self.session.query(Event).filter_by(event_id=event_id).first()
        if not evt:
            return False

        # 用 transitions 校验
        snapshot = EventSnapshot(
            event_id=event_id,
            status=EventStatus(evt.status),
            version=evt.version,
            start_at=evt.start_at,
            end_at=evt.end_at,
            updated_at=evt.updated_at,
        )
        new_snapshot = transition_event(
            snapshot, new_status, expected_version, now, new_start_at, new_end_at
        )

        # P1-3：传 _UNSET 避免覆盖时间。只有调用方显式传非 None 时才更新时间。
        start_arg = new_start_at if new_start_at is not None else _UNSET
        end_arg = new_end_at if new_end_at is not None else _UNSET

        # repository 条件更新
        ok = self.repo.transition_event(
            event_id, new_status, expected_version, start_arg, end_arg
        )
        if ok:
            self.repo.commit()
        return ok

    def get_event(self, event_id: str) -> Event | None:
        """查询事件"""
        return self.session.query(Event).filter_by(event_id=event_id).first()
