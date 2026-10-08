"""Tests for server/memory_v2/fact_store.py"""

import pytest
from uuid import uuid4
from sqlalchemy.orm import sessionmaker

from server.memory_v2.contracts import (
    MemoryCandidate,
    MemoryType,
    Modality,
    SubjectRef,
    TimeCandidate,
    WriteDecision,
)
from server.memory_v2.store.fact_store import FactStore
from server.memory_v2.models import ActiveFact, MemoryRecord, create_engine_and_tables


@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


@pytest.fixture
def store(session):
    return FactStore(session)


def make_decision(fact_key: str, value: str, text: str, candidate_id: str | None = None) -> WriteDecision:
    """构造 WriteDecision。candidate_id 默认唯一，允许覆盖以测幂等。"""
    return WriteDecision(
        candidate=MemoryCandidate(
            candidate_id=candidate_id or f"cand-{uuid4().hex[:8]}",
            subject=SubjectRef(kind="user", canonical_name="用户", is_current_user=True),
            predicate="diet.dislike",
            value=value,
            normalized_text_zh=text,
            memory_type=MemoryType.SEMANTIC,
            modality=Modality.FACT,
            confidence=0.92,
            importance=0.8,
            durability="stable",
            source_span=text,
            time=TimeCandidate(),
        ),
        accepted=True,
        route=MemoryType.SEMANTIC,
        reason_code="STABLE_SEMANTIC",
        fact_key=fact_key,
    )


# ─── 基础写入 ────────────────────────────────────────────────────────────────

def test_write_first_fact(store, session):
    """首次写入 fact_key → version=1，active 指向它"""
    decision = make_decision("user:diet.dislike", "香菜", "用户不吃香菜")
    memory_id = store.write_fact(decision, "t", "u", source_turn_id="turn-1")

    rec = session.query(MemoryRecord).filter_by(memory_id=memory_id).first()
    assert rec.version == 1
    assert rec.status == "active"
    assert rec.supersedes_id is None
    assert rec.text_zh == "用户不吃香菜"

    active = store.get_active_fact("t", "u", "user:diet.dislike")
    assert active.memory_id == memory_id


def test_write_updates_existing_fact(store, session):
    """更新同一 fact_key → 新 v2，旧 v1 superseded"""
    d1 = make_decision("user:diet.dislike", "香菜", "用户不吃香菜")
    mem1 = store.write_fact(d1, "t", "u")

    d2 = make_decision("user:diet.dislike", "香菜ok", "用户现在能吃香菜")
    mem2 = store.write_fact(d2, "t", "u")

    # 旧版本 superseded
    old = session.query(MemoryRecord).filter_by(memory_id=mem1).first()
    assert old.status == "superseded"

    # 新版本 version=2
    new = session.query(MemoryRecord).filter_by(memory_id=mem2).first()
    assert new.version == 2
    assert new.supersedes_id == mem1

    # active 指向新版本
    active = store.get_active_fact("t", "u", "user:diet.dislike")
    assert active.memory_id == mem2


def test_contradictory_preferences_only_latest(store, session):
    """矛盾偏好：3 次更新，只有最新 active"""
    for val, text in [("香菜", "不吃香菜"), ("香菜ok", "能吃香菜"), ("爱香菜", "喜欢香菜")]:
        d = make_decision("user:diet.dislike", val, text)
        store.write_fact(d, "t", "u")

    # 只有一条 active
    active_records = session.query(MemoryRecord).filter_by(
        fact_key="user:diet.dislike", status="active"
    ).all()
    assert len(active_records) == 1
    assert active_records[0].text_zh == "喜欢香菜"
    assert active_records[0].version == 3


# ─── 查询 ────────────────────────────────────────────────────────────────────

def test_get_active_fact_returns_latest(store, session):
    """get_active_fact 返回最新版本"""
    d1 = make_decision("user:diet.dislike", "香菜", "不吃香菜")
    d2 = make_decision("user:diet.dislike", "香菜ok", "能吃香菜")
    store.write_fact(d1, "t", "u")
    mem2 = store.write_fact(d2, "t", "u")

    active = store.get_active_fact("t", "u", "user:diet.dislike")
    assert active.memory_id == mem2
    assert active.text_zh == "能吃香菜"


def test_get_active_fact_not_found(store):
    """不存在的 fact_key 返回 None"""
    active = store.get_active_fact("t", "u", "nonexistent")
    assert active is None


# ─── 错误处理 ────────────────────────────────────────────────────────────────

def test_wrong_route_raises(store):
    """route 不是 SEMANTIC 抛异常"""
    decision = make_decision("user:diet.dislike", "香菜", "不吃香菜")
    decision.route = MemoryType.EPISODIC
    with pytest.raises(ValueError, match="只处理 SEMANTIC"):
        store.write_fact(decision, "t", "u")


def test_missing_fact_key_raises(store):
    """缺 fact_key 抛异常"""
    decision = make_decision("user:diet.dislike", "香菜", "不吃香菜")
    decision.fact_key = None
    with pytest.raises(ValueError, match="必须带 fact_key"):
        store.write_fact(decision, "t", "u")


# ─── 租户隔离 ────────────────────────────────────────────────────────────────

def test_tenant_isolation(store, session):
    """不同租户的 fact_key 隔离"""
    d = make_decision("user:diet.dislike", "香菜", "不吃香菜")
    mem_a = store.write_fact(d, "tenant-A", "u")
    mem_b = store.write_fact(d, "tenant-B", "u")

    assert mem_a != mem_b
    active_a = store.get_active_fact("tenant-A", "u", "user:diet.dislike")
    active_b = store.get_active_fact("tenant-B", "u", "user:diet.dislike")
    assert active_a.memory_id == mem_a
    assert active_b.memory_id == mem_b
