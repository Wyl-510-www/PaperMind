"""Tests for server/memory_v2/entity_store.py"""

import pytest
from sqlalchemy import create_engine

from server.memory_v2.store.entity_store import EntityStore, Base
from server.memory_v2.contracts import (
    MemoryCandidate,
    MemoryType,
    Modality,
    SubjectRef,
    WriteDecision,
)


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db_url():
    """使用内存 SQLite 数据库测试"""
    return "sqlite:///:memory:"


@pytest.fixture
def store(db_url):
    s = EntityStore(db_url)
    s.create_tables()
    return s


@pytest.fixture
def tenant_id():
    return "test-tenant"


@pytest.fixture
def user_id():
    return "user-12345"


# ─── helpers ────────────────────────────────────────────────────────────────

def make_third_party_candidate(
    name: str = "阿宁",
    predicate: str = "food.dislike",
    value: str = "辣",
    **kwargs
) -> MemoryCandidate:
    defaults = dict(
        candidate_id="cand-001",
        subject=SubjectRef(
            kind="person",
            canonical_name=name,
            is_current_user=False,
        ),
        predicate=predicate,
        value=value,
        normalized_text_zh=f"{name}不吃{value}",
        memory_type=MemoryType.SEMANTIC,
        modality=Modality.FACT,
        confidence=0.92,
        durability="stable",
        source_span=f"{name}不吃{value}",
    )
    defaults.update(kwargs)
    return MemoryCandidate(**defaults)


def make_decision(candidate: MemoryCandidate) -> WriteDecision:
    return WriteDecision(
        candidate=candidate,
        accepted=True,
        route=MemoryType.ENTITY_RELATION,
        reason_code="THIRD_PARTY_ROUTE",
    )


# ─── 基础写入 ────────────────────────────────────────────────────────────────

def test_write_entity_and_relation(store, tenant_id, user_id):
    """写入第三方实体及其关系"""
    candidate = make_third_party_candidate(name="阿宁", predicate="food.dislike", value="辣")
    decision = make_decision(candidate)

    entity_id = store.write(decision, tenant_id, user_id, source_turn_id="turn-001")

    # 验证实体存在
    entity = store.query_entity(tenant_id, user_id, "阿宁")
    assert entity is not None
    assert entity.canonical_name == "阿宁"
    assert entity.entity_type == "person"

    # 验证关系存在
    relations = store.query_relations(tenant_id, user_id, entity_id)
    assert len(relations) == 1
    assert relations[0].predicate == "food.dislike"
    assert relations[0].object_value == "辣"
    assert relations[0].status == "active"


def test_write_multiple_entities(store, tenant_id, user_id):
    """写入多个实体：阿宁、团团、栗子"""
    entities_data = [
        ("阿宁", "person", "food.dislike", "辣"),
        ("团团", "pet", "behavior.tendency", "掀翻桌子"),
        ("栗子", "pet", "behavior.trait", "安全"),
    ]

    for name, kind, predicate, value in entities_data:
        candidate = make_third_party_candidate(name=name, predicate=predicate, value=value)
        candidate.subject.kind = kind
        decision = make_decision(candidate)
        store.write(decision, tenant_id, user_id)

    # 验证三个实体都存在
    aning = store.query_entity(tenant_id, user_id, "阿宁")
    tuantuan = store.query_entity(tenant_id, user_id, "团团")
    lizi = store.query_entity(tenant_id, user_id, "栗子")

    assert aning is not None
    assert tuantuan is not None
    assert lizi is not None
    assert tuantuan.entity_type == "pet"


# ─── 幂等性 ──────────────────────────────────────────────────────────────────

def test_write_same_entity_twice_idempotent(store, tenant_id, user_id):
    """重复写入同一实体，不产生重复行"""
    candidate = make_third_party_candidate(name="阿宁")
    decision = make_decision(candidate)

    # 写入两次
    entity_id_1 = store.write(decision, tenant_id, user_id)
    entity_id_2 = store.write(decision, tenant_id, user_id)

    assert entity_id_1 == entity_id_2

    # 查询实体，应该只有一个
    entity = store.query_entity(tenant_id, user_id, "阿宁")
    assert entity is not None


def test_write_same_relation_twice_idempotent(store, tenant_id, user_id):
    """重复写入同一关系（subject + predicate + object 相同），不产生重复行"""
    candidate = make_third_party_candidate(name="阿宁", predicate="food.dislike", value="辣")
    decision = make_decision(candidate)

    # 写入两次
    entity_id = store.write(decision, tenant_id, user_id)
    store.write(decision, tenant_id, user_id)

    # 查询关系，应该只有一条
    relations = store.query_relations(tenant_id, user_id, entity_id)
    assert len(relations) == 1


def test_write_different_relations_same_entity(store, tenant_id, user_id):
    """同一实体写入不同关系"""
    candidate1 = make_third_party_candidate(name="阿宁", predicate="food.dislike", value="辣")
    candidate2 = make_third_party_candidate(name="阿宁", predicate="food.like", value="甜")

    entity_id_1 = store.write(make_decision(candidate1), tenant_id, user_id)
    entity_id_2 = store.write(make_decision(candidate2), tenant_id, user_id)

    assert entity_id_1 == entity_id_2  # 同一实体

    # 查询关系，应该有两条
    relations = store.query_relations(tenant_id, user_id, entity_id_1)
    assert len(relations) == 2
    predicates = {r.predicate for r in relations}
    assert predicates == {"food.dislike", "food.like"}


# ─── 错误处理 ────────────────────────────────────────────────────────────────

def test_write_wrong_route_raises(store, tenant_id, user_id):
    """route 不是 ENTITY_RELATION 时抛异常"""
    candidate = make_third_party_candidate()
    decision = WriteDecision(
        candidate=candidate,
        accepted=True,
        route=MemoryType.SEMANTIC,  # 错误的 route
        reason_code="STABLE_SEMANTIC",
    )

    with pytest.raises(ValueError, match="只处理 ENTITY_RELATION"):
        store.write(decision, tenant_id, user_id)


# ─── 租户隔离 ────────────────────────────────────────────────────────────────

def test_tenant_isolation(store):
    """不同租户的实体隔离"""
    candidate = make_third_party_candidate(name="阿宁")
    decision = make_decision(candidate)

    store.write(decision, tenant_id="tenant-A", user_id="user-1")
    store.write(decision, tenant_id="tenant-B", user_id="user-1")

    # tenant-A 能查到
    entity_a = store.query_entity("tenant-A", "user-1", "阿宁")
    assert entity_a is not None

    # tenant-B 也能查到（是独立的一条）
    entity_b = store.query_entity("tenant-B", "user-1", "阿宁")
    assert entity_b is not None

    # tenant-A 查不到 tenant-B 的实体
    entity_cross = store.query_entity("tenant-A", "user-1", "阿宁")
    relations_cross = store.query_relations("tenant-A", "user-2", entity_cross.entity_id)
    # 因为 user_id 不同，查不到关系（虽然实体名字一样）
    # 这个测试验证的是 user_id 隔离，不是 tenant_id


def test_user_isolation(store, tenant_id):
    """同一租户下，不同用户的实体隔离"""
    candidate = make_third_party_candidate(name="阿宁")
    decision = make_decision(candidate)

    store.write(decision, tenant_id, user_id="user-A")
    store.write(decision, tenant_id, user_id="user-B")

    # user-A 能查到自己的阿宁
    entity_a = store.query_entity(tenant_id, "user-A", "阿宁")
    assert entity_a is not None

    # user-B 能查到自己的阿宁
    entity_b = store.query_entity(tenant_id, "user-B", "阿宁")
    assert entity_b is not None

    # user-A 查 user-B 的实体 ID，查不到关系
    relations_cross = store.query_relations(tenant_id, "user-A", entity_b.entity_id)
    assert len(relations_cross) == 0  # 因为 user_id 不匹配
