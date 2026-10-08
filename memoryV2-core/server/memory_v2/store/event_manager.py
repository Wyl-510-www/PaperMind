"""Event 状态管理模块

M2 实施：完整实现 Event/State 管理（Case 099: PPT 已提交状态未持久化）。

设计原则：
- 支持 4 种状态：PLANNED, IN_PROGRESS, COMPLETED, CANCELLED
- 保存 valid_from/valid_to/timezone
- 状态转换的完整生命周期
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class EventStatus(str, Enum):
    """事件状态枚举"""
    PLANNED = "planned"         # 计划中
    IN_PROGRESS = "in_progress" # 进行中
    COMPLETED = "completed"     # 已完成
    CANCELLED = "cancelled"     # 已取消


class EventStore:
    """Event 存储：管理任务、约会、截止日期等事件

    职责：
    1. 创建事件（valid_from, valid_to, timezone）
    2. 更新事件状态（PLANNED → IN_PROGRESS → COMPLETED）
    3. 取消事件
    4. 查询活跃事件（未完成且未取消）
    """

    def __init__(self, db_session: Session):
        """
        Args:
            db_session: SQLAlchemy session
        """
        self.db = db_session

    async def create_event(
        self,
        tenant_id: str,
        user_id: str,
        namespace: str,
        event_type: str,
        title: str,
        description: str | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        timezone: str = "UTC",
        status: EventStatus = EventStatus.PLANNED,
        related_memory_ids: list[str] | None = None,
    ) -> str:
        """创建新事件

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            event_type: 事件类型（task | appointment | deadline）
            title: 标题
            description: 描述
            valid_from: 开始时间
            valid_to: 结束时间
            timezone: 时区
            status: 初始状态
            related_memory_ids: 关联的 memory_id 列表

        Returns:
            str: event_id
        """
        from server.memory_v2.models import EventRecord
        from server.memory_v2.write.id_gen import generate_id
        import json

        event = EventRecord(
            event_id=generate_id("evt"),
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            event_type=event_type,
            title=title,
            description=description,
            valid_from=valid_from,
            valid_to=valid_to,
            timezone=timezone,
            status=status.value,
            related_memory_ids=json.dumps(related_memory_ids or []),
            active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(event)
        self.db.commit()

        return event.event_id

    async def update_event_status(
        self,
        event_id: str,
        new_status: EventStatus,
        tenant_id: str,
        user_id: str,
    ) -> bool:
        """更新事件状态

        状态转换规则：
        - PLANNED → IN_PROGRESS
        - IN_PROGRESS → COMPLETED
        - 任意状态 → CANCELLED

        Args:
            event_id: 事件 ID
            new_status: 新状态
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            bool: 是否更新成功
        """
        from server.memory_v2.models import EventRecord

        event = self.db.query(EventRecord).filter(
            EventRecord.event_id == event_id,
            EventRecord.tenant_id == tenant_id,
            EventRecord.user_id == user_id,
            EventRecord.active == True,
        ).first()

        if not event:
            return False

        # 验证状态转换合法性
        if not self._is_valid_transition(event.status, new_status):
            import logging
            logging.warning(
                f"非法状态转换: {event.status} → {new_status.value}"
            )
            return False

        event.status = new_status.value
        event.updated_at = datetime.utcnow()
        self.db.commit()

        return True

    def _is_valid_transition(self, old_status: str, new_status: EventStatus) -> bool:
        """验证状态转换是否合法

        Args:
            old_status: 旧状态
            new_status: 新状态

        Returns:
            bool: 是否合法
        """
        # 允许的转换
        VALID_TRANSITIONS = {
            EventStatus.PLANNED.value: {
                EventStatus.IN_PROGRESS,
                EventStatus.CANCELLED,
            },
            EventStatus.IN_PROGRESS.value: {
                EventStatus.COMPLETED,
                EventStatus.CANCELLED,
            },
            EventStatus.COMPLETED.value: set(),  # 完成后不可转换
            EventStatus.CANCELLED.value: set(),  # 取消后不可转换
        }

        return new_status in VALID_TRANSITIONS.get(old_status, set())

    async def get_active_events(
        self,
        tenant_id: str,
        user_id: str,
        namespace: str,
        current_time: datetime | None = None,
    ) -> list:
        """获取活跃事件（未完成且未取消）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            current_time: 当前时间（用于过滤过期事件）

        Returns:
            list[EventRecord]: 活跃事件列表
        """
        from server.memory_v2.models import EventRecord

        query = self.db.query(EventRecord).filter(
            EventRecord.tenant_id == tenant_id,
            EventRecord.user_id == user_id,
            EventRecord.namespace == namespace,
            EventRecord.active == True,
            EventRecord.status.in_([
                EventStatus.PLANNED.value,
                EventStatus.IN_PROGRESS.value,
            ]),
        )

        # 可选：过滤未过期的事件
        if current_time:
            query = query.filter(
                (EventRecord.valid_to.is_(None)) |
                (EventRecord.valid_to >= current_time)
            )

        events = query.order_by(EventRecord.valid_from).all()

        return events

    async def cancel_event(
        self,
        event_id: str,
        tenant_id: str,
        user_id: str,
    ) -> bool:
        """取消事件

        Args:
            event_id: 事件 ID
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            bool: 是否取消成功
        """
        return await self.update_event_status(
            event_id=event_id,
            new_status=EventStatus.CANCELLED,
            tenant_id=tenant_id,
            user_id=user_id,
        )
