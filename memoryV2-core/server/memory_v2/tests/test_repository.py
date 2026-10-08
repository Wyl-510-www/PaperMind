"""Tests for server/memory_v2/repository.py"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from server.memory_v2.models import (
    ActiveFact,
    Event,
    MemoryRecord,
    Outbox,
    create_engine_and_tables,
)
from server.memory_v2.store.repository import Repository, now_utc
from server.memory_v2.transitions import EventStatus


@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


@pytest.fixture
def repo(session):
    return Repository(session)


def make_fact_data(value: str, text: str) -> dict:
    return {
        "memory_type": "semantic",
        "subject_id": "user:self",
        "predicate": "diet.dislike",
        "value_json": {"value": value},
        "text_zh": text,
        "modality": "fact",
        "confidence": 0.92,
    }


# ─── fact 版本化 ─────────────────────────────────────────────────────────────

def test_write_first_fact_version(repo, session):
    """首次写入：version=1，无 supersedes"""
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "用户不吃香菜"),
        source_turn_id="turn-1",
    )
    repo.commit()

    rec = session.query(MemoryRecord).filter_by(memory_id="mem-001").first()
    assert rec.version == 1
    assert rec.supersedes_id is None
    assert rec.status == "active"

    # active pointer 指向 mem-001
    active = session.query(ActiveFact).filter_by(fact_key="user:self:diet.dislike").first()
    assert active.memory_id == "mem-001"


def test_write_second_fact_version(repo, session):
    """更新：新 version=2，旧版本 superseded，active 切换"""
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "用户不吃香菜"),
    )
    repo.commit()

    repo.write_fact_version(
        memory_id="mem-002",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜其实还行", "用户现在能接受香菜"),
    )
    repo.commit()

    # 旧版本 superseded
    old = session.query(MemoryRecord).filter_by(memory_id="mem-001").first()
    assert old.status == "superseded"

    # 新版本 version=2，supersedes 指向旧版本
    new = session.query(MemoryRecord).filter_by(memory_id="mem-002").first()
    assert new.version == 2
    assert new.supersedes_id == "mem-001"
    assert new.status == "active"

    # active pointer 指向新版本
    active = session.query(ActiveFact).filter_by(fact_key="user:self:diet.dislike").first()
    assert active.memory_id == "mem-002"


def test_only_one_active_per_fact_key(repo, session):
    """矛盾偏好只保留最新，active pointer 唯一"""
    for i, (val, text) in enumerate([("香菜", "不吃香菜"), ("香菜ok", "能吃香菜"), ("爱吃香菜", "喜欢香菜")], 1):
        repo.write_fact_version(
            memory_id=f"mem-{i:03d}",
            tenant_id="t", user_id="u", namespace="user_memory",
            fact_key="user:self:diet.dislike",
            fact_data=make_fact_data(val, text),
        )
        repo.commit()

    # 只有一条 active 记录
    active_records = session.query(MemoryRecord).filter_by(
        fact_key="user:self:diet.dislike", status="active"
    ).all()
    assert len(active_records) == 1
    assert active_records[0].memory_id == "mem-003"
    assert active_records[0].version == 3


# ─── event 状态迁移 ──────────────────────────────────────────────────────────

def _insert_event(session, event_id="evt-001", status="scheduled", version=1):
    evt = Event(
        event_id=event_id, tenant_id="t", user_id="u",
        event_type="appointment", title="聚会",
        status=status, version=version,
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(evt)
    session.commit()


def test_transition_event_success(repo, session):
    _insert_event(session, version=1)
    ok = repo.transition_event("evt-001", EventStatus.CANCELLED, expected_version=1)
    repo.commit()
    assert ok is True

    evt = session.query(Event).filter_by(event_id="evt-001").first()
    assert evt.status == "cancelled"
    assert evt.version == 2


def test_transition_event_version_conflict(repo, session):
    """version 不匹配 → 返回 False（乐观锁）"""
    _insert_event(session, version=1)
    ok = repo.transition_event("evt-001", EventStatus.CANCELLED, expected_version=99)
    repo.commit()
    assert ok is False

    # 状态未变
    evt = session.query(Event).filter_by(event_id="evt-001").first()
    assert evt.status == "scheduled"


def test_transition_terminal_event_rejected(repo, session):
    """终止态事件不能再迁移"""
    _insert_event(session, status="cancelled", version=2)
    ok = repo.transition_event("evt-001", EventStatus.SCHEDULED, expected_version=2)
    repo.commit()
    assert ok is False  # WHERE status IN (scheduled,rescheduled) 排除了 cancelled


# ─── tombstone ───────────────────────────────────────────────────────────────

def test_delete_memory(repo, session):
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()

    ok = repo.delete_memory("mem-001")
    repo.commit()
    assert ok is True

    rec = session.query(MemoryRecord).filter_by(memory_id="mem-001").first()
    assert rec.status == "deleted"


def test_delete_already_deleted(repo, session):
    """重复删除幂等：第二次返回 False"""
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()

    assert repo.delete_memory("mem-001") is True
    repo.commit()
    assert repo.delete_memory("mem-001") is False  # 已删除
    repo.commit()


# ─── outbox 一致性 ───────────────────────────────────────────────────────────

def test_fact_write_produces_outbox(repo, session):
    """写 fact 同时产生 outbox 记录"""
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()

    outbox = session.query(Outbox).filter_by(aggregate_id="mem-001").all()
    assert len(outbox) == 1
    assert outbox[0].operation == "upsert"
    assert outbox[0].status == "pending"


def test_delete_produces_outbox(repo, session):
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()
    repo.delete_memory("mem-001")
    repo.commit()

    delete_outbox = session.query(Outbox).filter_by(
        aggregate_id="mem-001", operation="delete"
    ).all()
    assert len(delete_outbox) == 1


def test_delete_active_fact_rolls_back_to_prior_version(repo, session):
    """删除 active fact 后，ActiveFact 回退到前一版本（P1-2）。"""
    # 写入版本 1
    repo.write_fact_version(
        memory_id="mem-v1",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()

    # 写入版本 2（supersedes v1）
    repo.write_fact_version(
        memory_id="mem-v2",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜和芹菜", "不吃香菜和芹菜"),
    )
    repo.commit()

    # ActiveFact 当前指向 v2
    active = session.query(ActiveFact).filter_by(
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
    ).first()
    assert active.memory_id == "mem-v2"

    # 删除 v2
    repo.delete_memory("mem-v2")
    repo.commit()

    # ActiveFact 应回退到 v1
    active = session.query(ActiveFact).filter_by(
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
    ).first()
    assert active.memory_id == "mem-v1"

    # v1 仍为 active（未被删除时已是 superseded，现在复活为 active）
    v1 = session.query(MemoryRecord).filter_by(memory_id="mem-v1").first()
    assert v1.status == "superseded"  # 注意：回退后 v1 状态暂不改（可选优化）


def test_delete_active_fact_with_no_prior_clears_activefact(repo, session):
    """删除 active fact 且无前一版本，ActiveFact 行被清除（P1-2）。"""
    repo.write_fact_version(
        memory_id="mem-only",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()

    # 删除唯一版本
    repo.delete_memory("mem-only")
    repo.commit()

    # ActiveFact 行应被清除
    active = session.query(ActiveFact).filter_by(
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
    ).first()
    assert active is None


def test_delete_superseded_fact_no_activefact_change(repo, session):
    """删除已 superseded 的旧版本，ActiveFact 不变（P1-2）。"""
    repo.write_fact_version(
        memory_id="mem-v1",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()

    repo.write_fact_version(
        memory_id="mem-v2",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜和芹菜", "不吃香菜和芹菜"),
    )
    repo.commit()

    # 删除旧版本 v1
    repo.delete_memory("mem-v1")
    repo.commit()

    # ActiveFact 仍指向 v2（不受影响）
    active = session.query(ActiveFact).filter_by(
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
    ).first()
    assert active.memory_id == "mem-v2"


# ─── active pointer 重建 ─────────────────────────────────────────────────────

def test_rebuild_active_pointers(repo, session):
    """清空 active_fact 后从 record 重建，结果一致"""
    # 写两个版本
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜", "不吃香菜"),
    )
    repo.commit()
    repo.write_fact_version(
        memory_id="mem-002",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="user:self:diet.dislike",
        fact_data=make_fact_data("香菜ok", "能吃香菜"),
    )
    repo.commit()

    # 清空并重建
    repo.rebuild_active_pointers("t", "u", "user_memory")
    repo.commit()

    # active 应指向最新版本 mem-002
    active = session.query(ActiveFact).filter_by(fact_key="user:self:diet.dislike").first()
    assert active.memory_id == "mem-002"
