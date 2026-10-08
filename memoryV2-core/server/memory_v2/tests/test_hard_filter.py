"""Tests for server/memory_v2/hard_filter.py"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import sessionmaker
from uuid import uuid4

from server.memory_v2.retrieve.hard_filter import HardFilter
from server.memory_v2.models import (
    MemoryRecord,
    Event,
    create_engine_and_tables,
)


@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


@pytest.fixture
def hard_filter(session):
    return HardFilter(session)


@pytest.fixture
def now():
    return datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)


# ─── 跨账号过滤 ─────────────────────────────────────────────────────────────

def test_filter_cross_tenant(session, hard_filter, now):
    """跨租户候选被排除"""
    # 写入一条 tenant_id=other 的记忆
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="other_tenant",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户不吃香菜",
        modality="fact",
        status="active",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    # 召回候选包含这条记忆
    candidates = [{"memory_id": memory_id, "score": 0.95}]

    # hard_filter 用 current_tenant 过滤
    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="current_tenant",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    # 跨租户候选被排除
    assert len(surviving) == 0


def test_filter_cross_user(session, hard_filter, now):
    """跨用户候选被排除"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="other_user",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户不吃香菜",
        modality="fact",
        status="active",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="current_user",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


# ─── 状态过滤 ──────────────────────────────────────────────────────────────

def test_filter_deleted_status(session, hard_filter, now):
    """status=deleted 的候选被排除（tombstone）"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户不吃香菜",
        modality="fact",
        status="deleted",  # tombstone
        confidence=0.9,
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


def test_filter_superseded_status(session, hard_filter, now):
    """status=superseded 的候选被排除"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户不吃香菜",
        modality="fact",
        status="superseded",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


# ─── 有效期过滤 ────────────────────────────────────────────────────────────

def test_filter_expired_valid_to(session, hard_filter, now):
    """valid_to < now 的候选被排除（已过期）"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户最近在减肥",
        modality="fact",
        status="active",
        confidence=0.9,
        valid_from=now - timedelta(days=7),
        valid_to=now - timedelta(days=1),  # 昨天过期
        created_at=now - timedelta(days=7),
        updated_at=now - timedelta(days=7),
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


def test_filter_not_yet_valid(session, hard_filter, now):
    """valid_from > now 的候选被排除（尚未生效）"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户明天开始减肥",
        modality="plan",
        status="active",
        confidence=0.9,
        valid_from=now + timedelta(days=1),  # 明天才生效
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


# ─── 事件状态过滤 ──────────────────────────────────────────────────────────

def test_filter_cancelled_event(session, hard_filter, now):
    """status=cancelled 的事件被排除"""
    event_id = str(uuid4())
    session.add(Event(
        event_id=event_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        event_type="meeting",
        title="团队聚会",
        status="cancelled",
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"event_id": event_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


def test_filter_completed_event(session, hard_filter, now):
    """status=completed 的事件被排除"""
    event_id = str(uuid4())
    session.add(Event(
        event_id=event_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        event_type="meeting",
        title="团队聚会",
        status="completed",
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"event_id": event_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


# ─── 模态过滤 ──────────────────────────────────────────────────────────────

def test_filter_joke_modality(session, hard_filter, now):
    """modality=joke 的候选被排除（不可用于断言）"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户开玩笑说自己是外星人",
        modality="joke",
        status="active",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


def test_filter_quote_modality(session, hard_filter, now):
    """modality=quote 的候选被排除"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="引用：活着就是为了改变世界",
        modality="quote",
        status="active",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 0


# ─── 存活场景 ──────────────────────────────────────────────────────────────

def test_active_valid_memory_survives(session, hard_filter, now):
    """status=active、有效期内、modality=fact 的候选存活"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="用户不吃香菜",
        modality="fact",
        status="active",
        confidence=0.9,
        subject_id="current_user:tenant1:user123",
        valid_from=now - timedelta(days=7),
        valid_to=now + timedelta(days=30),  # 未来过期
        created_at=now - timedelta(days=7),
        updated_at=now - timedelta(days=7),
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="current_user:tenant1:user123",
    )

    assert len(surviving) == 1
    assert surviving[0]["memory_id"] == memory_id


# ─── 票 07：加固过滤 ──────────────────────────────────────────────────────────

def test_filter_expires_at_past(session, hard_filter, now):
    """expires_at 已过期的记忆被排除（P2-1）。"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="临时状态已过期",
        modality="fact",
        status="active",
        confidence=0.9,
        expires_at=now - timedelta(hours=1),  # 1 小时前过期
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]
    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    # 已过期，应被排除
    assert len(surviving) == 0


def test_filter_namespace_mismatch(session, hard_filter, now):
    """namespace 不匹配的记忆被排除（P2-2）。"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="agent_memory",  # 不同命名空间
        memory_type="semantic",
        text_zh="agent 专属记忆",
        modality="fact",
        status="active",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]
    # apply 默认查 user_memory，agent_memory 应被排除
    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
        namespace="user_memory",  # 显式传命名空间
    )

    assert len(surviving) == 0


def test_filter_subject_id_none_rejected(session, hard_filter, now):
    """subject_id=None 的记忆被排除（P2-3 数据质量防护）。"""
    memory_id = str(uuid4())
    session.add(MemoryRecord(
        memory_id=memory_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        memory_type="semantic",
        text_zh="subject_id 缺失的脏数据",
        modality="fact",
        status="active",
        confidence=0.9,
        subject_id=None,  # 脏数据
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"memory_id": memory_id, "score": 0.95}]
    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    # subject_id=None 应被拒绝
    assert len(surviving) == 0



def test_scheduled_event_survives(session, hard_filter, now):
    """status=scheduled 的事件存活"""
    event_id = str(uuid4())
    session.add(Event(
        event_id=event_id,
        tenant_id="tenant1",
        user_id="user123",
        namespace="user_memory",
        event_type="meeting",
        title="团队聚会",
        status="scheduled",
        created_at=now,
        updated_at=now,
    ))
    session.commit()

    candidates = [{"event_id": event_id, "score": 0.95}]

    surviving = hard_filter.apply(
        candidates=candidates,
        tenant_id="tenant1",
        user_id="user123",
        now=now,
        query_subject="user",
    )

    assert len(surviving) == 1
    assert surviving[0]["event_id"] == event_id
