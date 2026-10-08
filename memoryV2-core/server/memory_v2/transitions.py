"""Deterministic event/task state transitions.

纯函数实现，无副作用。repository 层调用 transition_event() 校验状态迁移合法性。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class EventStatus(str, Enum):
    SCHEDULED = "scheduled"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


TERMINAL_STATES = {EventStatus.CANCELLED, EventStatus.COMPLETED}

ALLOWED_TRANSITIONS = {
    EventStatus.SCHEDULED: {
        EventStatus.RESCHEDULED,
        EventStatus.CANCELLED,
        EventStatus.COMPLETED,
    },
    EventStatus.RESCHEDULED: {
        EventStatus.RESCHEDULED,  # 可多次改期
        EventStatus.CANCELLED,
        EventStatus.COMPLETED,
    },
    EventStatus.CANCELLED: set(),  # 终止态
    EventStatus.COMPLETED: set(),  # 终止态
}


class InvalidTransition(ValueError):
    """非法状态迁移"""
    pass


class OptimisticLockConflict(RuntimeError):
    """乐观锁冲突：版本不匹配"""
    pass


@dataclass(frozen=True)
class EventSnapshot:
    """事件快照（不可变）"""
    event_id: str
    status: EventStatus
    version: int
    start_at: datetime | None
    end_at: datetime | None
    updated_at: datetime


def validate_transition(old_status: EventStatus, new_status: EventStatus):
    """校验状态迁移是否合法"""
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise InvalidTransition(
            f"Cannot transition from {old_status.value} to {new_status.value}"
        )


def transition_event(
    event: EventSnapshot,
    new_status: EventStatus,
    expected_version: int,
    now: datetime,
    new_start_at: datetime | None = None,
    new_end_at: datetime | None = None,
) -> EventSnapshot:
    """迁移事件状态（纯函数，返回新快照）。

    Args:
        event: 当前快照
        new_status: 目标状态
        expected_version: 期望版本（乐观锁）
        now: 当前时间（必须带时区）
        new_start_at: 改期时的新开始时间
        new_end_at: 新结束时间（可选）

    Returns:
        新快照（version+1）

    Raises:
        OptimisticLockConflict: 版本不匹配
        InvalidTransition: 非法迁移
        ValueError: now 无时区 / rescheduled 缺 new_start_at
    """
    if now.tzinfo is None:
        raise ValueError("now 必须带时区信息")

    if event.version != expected_version:
        raise OptimisticLockConflict(
            f"Version mismatch: expected {expected_version}, got {event.version}"
        )

    validate_transition(event.status, new_status)

    if new_status == EventStatus.RESCHEDULED and new_start_at is None:
        raise ValueError("rescheduled event requires new_start_at")

    return replace(
        event,
        status=new_status,
        version=event.version + 1,
        start_at=new_start_at if new_start_at is not None else event.start_at,
        end_at=new_end_at if new_end_at is not None else event.end_at,
        updated_at=now,
    )


def sql_transition_predicate(
    event_id: str,
    expected_version: int,
) -> dict[str, object]:
    """生成 repository 层条件 UPDATE 所需参数。

    repository 须在 WHERE 子句包含：
    - event_id = ?
    - version = ?
    - status IN (scheduled, rescheduled)  # 非终止态

    然后要求 rowcount == 1，否则为乐观锁冲突或已终止。
    """
    return {
        "event_id": event_id,
        "expected_version": expected_version,
        "allowed_current_statuses": (
            EventStatus.SCHEDULED.value,
            EventStatus.RESCHEDULED.value,
        ),
    }
