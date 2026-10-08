"""Tests for server/memory_v2/event_store.py"""

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from server.memory_v2.contracts import (
    MemoryCandidate,
    MemoryType,
    Modality,
    SubjectRef,
    TimeCandidate,
    WriteDecision,
)
from server.memory_v2.store.event_store import EventStore
from server.memory_v2.models import Event, create_engine_and_tables
from server.memory_v2.transitions import EventStatus

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 31, 15, 30, 0, tzinfo=TZ)


@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


@pytest.fixture
def store(session):
    return EventStore(session)


def make_event_decision(text: str, route=MemoryType.EPISODIC, start_at=None) -> WriteDecision:
    return WriteDecision(
        candidate=MemoryCandidate(
            candidate_id="cand-001",
            subject=SubjectRef(kind="user", canonical_name="用户", is_current_user=True),
            predicate="event.attend",
            value="聚会",
            normalized_text_zh=text,
            memory_type=route,
            modality=Modality.PLAN,
            confidence=0.85,
            durability="episodic",
            source_span=text,
            time=TimeCandidate(
                absolute_start=start_at,
                precision="day" if start_at else "unknown",
            ),
        ),
        accepted=True,
        route=route,
        reason_code="ACCEPTED",
    )


# ─── 创建事件 ────────────────────────────────────────────────────────────────

def test_create_event(store, session):
    d = make_event_decision("周六去聚会", start_at=datetime(2026, 8, 2, 10, 0, tzinfo=TZ))
    event_id = store.create_event(d, "t", "u", source_turn_id="turn-1")

    evt = store.get_event(event_id)
    assert evt.status == "scheduled"
    assert evt.version == 1
    assert evt.title == "周六去聚会"
    assert evt.event_type == "event"


def test_create_task(store, session):
    d = make_event_decision("交论文", route=MemoryType.TASK)
    event_id = store.create_event(d, "t", "u")

    evt = store.get_event(event_id)
    assert evt.event_type == "task"


def test_create_wrong_route_raises(store):
    d = make_event_decision("不吃香菜", route=MemoryType.SEMANTIC)
    with pytest.raises(ValueError, match="只处理 EPISODIC/TASK"):
        store.create_event(d, "t", "u")


# ─── 状态迁移 ────────────────────────────────────────────────────────────────

def test_transition_cancel(store, session):
    """创建后取消"""
    d = make_event_decision("周六聚会", start_at=datetime(2026, 8, 2, 10, 0, tzinfo=TZ))
    event_id = store.create_event(d, "t", "u")

    ok = store.transition(event_id, EventStatus.CANCELLED, expected_version=1, now=NOW)
    assert ok is True

    evt = store.get_event(event_id)
    assert evt.status == "cancelled"
    assert evt.version == 2


def test_transition_reschedule(store, session):
    """改期"""
    d = make_event_decision("周六聚会", start_at=datetime(2026, 8, 2, 10, 0, tzinfo=TZ))
    event_id = store.create_event(d, "t", "u")

    new_start = datetime(2026, 8, 3, 14, 0, tzinfo=TZ)
    ok = store.transition(
        event_id, EventStatus.RESCHEDULED, expected_version=1, now=NOW, new_start_at=new_start
    )
    assert ok is True

    evt = store.get_event(event_id)
    assert evt.status == "rescheduled"


def test_transition_complete(store, session):
    d = make_event_decision("交论文", route=MemoryType.TASK)
    event_id = store.create_event(d, "t", "u")

    ok = store.transition(event_id, EventStatus.COMPLETED, expected_version=1, now=NOW)
    assert ok is True
    assert store.get_event(event_id).status == "completed"


def test_cancelled_event_cannot_revive(store, session):
    """取消的事件不能复活（transitions 校验）"""
    d = make_event_decision("周六聚会", start_at=datetime(2026, 8, 2, 10, 0, tzinfo=TZ))
    event_id = store.create_event(d, "t", "u")
    store.transition(event_id, EventStatus.CANCELLED, expected_version=1, now=NOW)

    # 尝试复活 → transitions 抛 InvalidTransition
    from server.memory_v2.transitions import InvalidTransition
    with pytest.raises(InvalidTransition):
        store.transition(event_id, EventStatus.SCHEDULED, expected_version=2, now=NOW)


def test_transition_status_only_preserves_times(store, session):
    """只改状态（不传时间）→ start_at/end_at 保持原值（P1-3）。"""
    original_start = datetime(2026, 8, 2, 10, 0, tzinfo=TZ)
    original_end = datetime(2026, 8, 2, 12, 0, tzinfo=TZ)
    d = make_event_decision("周六聚会", start_at=original_start)
    event_id = store.create_event(d, "t", "u")

    # 手动补一个 end_at（模拟已有结束时间）
    evt = store.get_event(event_id)
    evt.end_at = original_end
    session.commit()

    # 只改状态为 completed（不传 new_start_at/new_end_at）
    ok = store.transition(event_id, EventStatus.COMPLETED, expected_version=1, now=NOW)
    assert ok is True

    # 时间应保持不变（非 None 即证明未被清空；SQLite 会剥离 tzinfo，比较日期部分）
    evt_after = store.get_event(event_id)
    assert evt_after.start_at is not None
    assert evt_after.end_at is not None
    assert evt_after.start_at.replace(tzinfo=None) == original_start.replace(tzinfo=None)
    assert evt_after.end_at.replace(tzinfo=None) == original_end.replace(tzinfo=None)


def test_transition_reschedule_updates_times(store, session):
    """改期（传时间）→ start_at 更新（P1-3）。"""
    original_start = datetime(2026, 8, 2, 10, 0, tzinfo=TZ)
    d = make_event_decision("周六聚会", start_at=original_start)
    event_id = store.create_event(d, "t", "u")

    new_start = datetime(2026, 8, 3, 14, 0, tzinfo=TZ)
    ok = store.transition(
        event_id, EventStatus.RESCHEDULED, expected_version=1, now=NOW, new_start_at=new_start
    )
    assert ok is True

    evt = store.get_event(event_id)
    assert evt.start_at is not None
    assert evt.start_at.replace(tzinfo=None) == new_start.replace(tzinfo=None)


def test_transition_version_conflict(store, session):
    """版本冲突 → 乐观锁"""
    d = make_event_decision("周六聚会", start_at=datetime(2026, 8, 2, 10, 0, tzinfo=TZ))
    event_id = store.create_event(d, "t", "u")

    from server.memory_v2.transitions import OptimisticLockConflict
    with pytest.raises(OptimisticLockConflict):
        store.transition(event_id, EventStatus.CANCELLED, expected_version=99, now=NOW)


def test_transition_nonexistent_event(store):
    ok = store.transition("evt-nonexistent", EventStatus.CANCELLED, expected_version=1, now=NOW)
    assert ok is False
