"""Tests for server/memory_v2/transitions.py"""

from datetime import datetime, timezone, timedelta

import pytest

from server.memory_v2.transitions import (
    ALLOWED_TRANSITIONS,
    EventSnapshot,
    EventStatus,
    InvalidTransition,
    OptimisticLockConflict,
    TERMINAL_STATES,
    sql_transition_predicate,
    transition_event,
    validate_transition,
)

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 31, 15, 30, 0, tzinfo=TZ)


def make_event(status=EventStatus.SCHEDULED, version=1) -> EventSnapshot:
    return EventSnapshot(
        event_id="evt-001",
        status=status,
        version=version,
        start_at=datetime(2026, 8, 2, 10, 0, 0, tzinfo=TZ),
        end_at=None,
        updated_at=NOW,
    )


# ─── 合法迁移 ────────────────────────────────────────────────────────────────

def test_scheduled_to_cancelled():
    evt = make_event(EventStatus.SCHEDULED, version=1)
    new = transition_event(evt, EventStatus.CANCELLED, expected_version=1, now=NOW)
    assert new.status == EventStatus.CANCELLED
    assert new.version == 2


def test_scheduled_to_completed():
    evt = make_event(EventStatus.SCHEDULED, version=1)
    new = transition_event(evt, EventStatus.COMPLETED, expected_version=1, now=NOW)
    assert new.status == EventStatus.COMPLETED


def test_scheduled_to_rescheduled():
    evt = make_event(EventStatus.SCHEDULED, version=1)
    new_start = datetime(2026, 8, 3, 10, 0, 0, tzinfo=TZ)
    new = transition_event(
        evt, EventStatus.RESCHEDULED, expected_version=1, now=NOW, new_start_at=new_start
    )
    assert new.status == EventStatus.RESCHEDULED
    assert new.start_at == new_start


def test_rescheduled_to_rescheduled():
    """可多次改期"""
    evt = make_event(EventStatus.RESCHEDULED, version=2)
    new_start = datetime(2026, 8, 4, 10, 0, 0, tzinfo=TZ)
    new = transition_event(
        evt, EventStatus.RESCHEDULED, expected_version=2, now=NOW, new_start_at=new_start
    )
    assert new.status == EventStatus.RESCHEDULED
    assert new.version == 3


def test_rescheduled_to_completed():
    evt = make_event(EventStatus.RESCHEDULED, version=2)
    new = transition_event(evt, EventStatus.COMPLETED, expected_version=2, now=NOW)
    assert new.status == EventStatus.COMPLETED


# ─── 终止态不可逆 ────────────────────────────────────────────────────────────

def test_cancelled_to_scheduled_rejected():
    """取消的事件不能复活"""
    evt = make_event(EventStatus.CANCELLED, version=2)
    with pytest.raises(InvalidTransition):
        transition_event(evt, EventStatus.SCHEDULED, expected_version=2, now=NOW)


def test_cancelled_to_rescheduled_rejected():
    evt = make_event(EventStatus.CANCELLED, version=2)
    with pytest.raises(InvalidTransition):
        transition_event(
            evt, EventStatus.RESCHEDULED, expected_version=2, now=NOW,
            new_start_at=datetime(2026, 8, 5, tzinfo=TZ),
        )


def test_completed_to_scheduled_rejected():
    evt = make_event(EventStatus.COMPLETED, version=2)
    with pytest.raises(InvalidTransition):
        transition_event(evt, EventStatus.SCHEDULED, expected_version=2, now=NOW)


def test_completed_to_cancelled_rejected():
    evt = make_event(EventStatus.COMPLETED, version=2)
    with pytest.raises(InvalidTransition):
        transition_event(evt, EventStatus.CANCELLED, expected_version=2, now=NOW)


def test_terminal_states_defined():
    assert TERMINAL_STATES == {EventStatus.CANCELLED, EventStatus.COMPLETED}
    assert ALLOWED_TRANSITIONS[EventStatus.CANCELLED] == set()
    assert ALLOWED_TRANSITIONS[EventStatus.COMPLETED] == set()


# ─── 乐观锁 ──────────────────────────────────────────────────────────────────

def test_version_mismatch_raises():
    evt = make_event(EventStatus.SCHEDULED, version=3)
    with pytest.raises(OptimisticLockConflict):
        transition_event(evt, EventStatus.CANCELLED, expected_version=1, now=NOW)


def test_version_increments():
    evt = make_event(EventStatus.SCHEDULED, version=5)
    new = transition_event(evt, EventStatus.CANCELLED, expected_version=5, now=NOW)
    assert new.version == 6


# ─── 参数校验 ────────────────────────────────────────────────────────────────

def test_rescheduled_without_new_start_raises():
    evt = make_event(EventStatus.SCHEDULED, version=1)
    with pytest.raises(ValueError, match="new_start_at"):
        transition_event(evt, EventStatus.RESCHEDULED, expected_version=1, now=NOW)


def test_naive_now_raises():
    evt = make_event(EventStatus.SCHEDULED, version=1)
    naive = datetime(2026, 7, 31, 15, 30, 0)  # 无时区
    with pytest.raises(ValueError, match="时区"):
        transition_event(evt, EventStatus.CANCELLED, expected_version=1, now=naive)


# ─── validate_transition ─────────────────────────────────────────────────────

def test_validate_transition_valid():
    validate_transition(EventStatus.SCHEDULED, EventStatus.CANCELLED)  # 不抛异常


def test_validate_transition_invalid():
    with pytest.raises(InvalidTransition):
        validate_transition(EventStatus.CANCELLED, EventStatus.SCHEDULED)


# ─── sql_transition_predicate ────────────────────────────────────────────────

def test_sql_predicate():
    p = sql_transition_predicate("evt-001", 3)
    assert p["event_id"] == "evt-001"
    assert p["expected_version"] == 3
    assert "scheduled" in p["allowed_current_statuses"]
    assert "rescheduled" in p["allowed_current_statuses"]
    assert "cancelled" not in p["allowed_current_statuses"]
