"""Tests for server/memory_v2/evidence_pipeline.py"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import sessionmaker
from typing import Any
from uuid import uuid4

from server.memory_v2.contracts import MemoryType
from server.memory_v2.retrieve.evidence_pipeline import EvidencePipeline
from server.memory_v2.models import MemoryRecord, Event, create_engine_and_tables


# ─── Fakes ────────────────────────────────────────────────────────────────

class FakeIndex:
    """假 Qdrant index，返回预设候选，不执行真实向量检索。

    ✅ 可验证：pipeline 按 memory_type 多路召回、候选进入 hard_filter/scorer。
    ❌ 不可验证（真实 Qdrant 集成测试才能覆盖）：语义召回准确性、向量距离方向、
       collection schema、filter 性能、最终一致性。真实适配器契约测试见票 12。
    """

    def __init__(self, candidates: dict[str, list[dict[str, Any]]]):
        """candidates: {memory_type.value: [{memory_id/event_id, score}]}"""
        self._candidates = candidates

    def search(self, memory_type: str, query: str, top_k: int) -> list[dict]:
        return self._candidates.get(memory_type, [])[:top_k]


class FakeReranker:
    """假 reranker，返回预设分数，不执行真实跨语言重排。

    ✅ 可验证：scorer 调用 rerank、分数进入 final_score、按分数排序。
    ❌ 不可验证（真实 reranker 冒烟测试才能覆盖）：跨语言理解、细粒度 query-passage
       匹配、真实分数分布、推理延迟。真实适配器契约测试见票 14。
    """

    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        for cand in candidates:
            memory_id = cand.get("memory_id", cand.get("event_id"))
            cand["rerank_score"] = self._scores.get(memory_id, 0.5)
        return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)


class FakeDSMReader:
    """假 DSM reader（已弃用，Evidence Pack 不再包含 current_state）"""

    def __init__(self, state: dict[str, Any]):
        self._state = state

    def get_current_state(self, user_id: str, now: datetime) -> dict[str, Any]:
        return self._state


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


@pytest.fixture
def now():
    return datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)


# ─── Pipeline 端到端测试 ──────────────────────────────────────────────────

def test_assemble_basic_flow(session, now):
    """基本流程：QueryRouter → Index 召回 → HardFilter → Scorer → EvidencePack"""
    # 1. MySQL 真值：一条 semantic 记忆
    memory_id = str(uuid4())
    session.add(
        MemoryRecord(
            memory_id=memory_id,
            tenant_id="tenant1",
            user_id="user123",
            namespace="user_memory",
            memory_type="semantic",
            text_zh="用户不吃香菜",
            modality="fact",
            status="active",
            confidence=0.9,
            importance=0.8,
            subject_id="current_user:tenant1:user123",
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    # 2. FakeIndex 召回这条记忆
    fake_index = FakeIndex({"semantic": [{"memory_id": memory_id, "score": 0.95}]})
    fake_reranker = FakeReranker({memory_id: 0.9})

    # 3. Pipeline 组装（不再需要 dsm_reader）
    pipeline = EvidencePipeline(
        index=fake_index,
        session=session,
        reranker=fake_reranker,
    )

    pack = pipeline.assemble(
        query="你知道我喜欢吃什么吗",
        tenant_id="tenant1",
        user_id="user123",
        now=now,
    )

    # 4. 验证 EvidencePack
    assert pack.query == "你知道我喜欢吃什么吗"
    assert len(pack.items) == 1
    assert pack.items[0].memory_id == memory_id
    assert pack.items[0].content == "用户不吃香菜"
    # current_state 已从 EvidencePack 移除（DSM 独立注入）
    assert not hasattr(pack, "current_state")


def test_skip_retrieval_returns_empty_pack(session, now):
    """普通寒暄 skip_retrieval=True 时返回空 pack"""
    fake_index = FakeIndex({})
    fake_reranker = FakeReranker({})

    pipeline = EvidencePipeline(fake_index, session, fake_reranker)
    pack = pipeline.assemble("你好呀", "tenant1", "user123", now)

    # QueryRouter 判断为寒暄，skip_retrieval
    assert len(pack.items) == 0


def test_cross_account_filtered(session, now):
    """跨账号候选被 HardFilter 排除（集成回归）"""
    memory_id = str(uuid4())
    session.add(
        MemoryRecord(
            memory_id=memory_id,
            tenant_id="other_tenant",  # 不同租户
            user_id="user123",
            namespace="user_memory",
            memory_type="semantic",
            text_zh="用户不吃香菜",
            modality="fact",
            status="active",
            confidence=0.9,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    fake_index = FakeIndex({"semantic": [{"memory_id": memory_id, "score": 0.95}]})
    fake_reranker = FakeReranker({memory_id: 0.9})

    pipeline = EvidencePipeline(fake_index, session, fake_reranker)
    pack = pipeline.assemble("我不吃什么", "current_tenant", "user123", now)

    # 跨账号候选被 HardFilter 排除
    assert len(pack.items) == 0


def test_expired_memory_filtered(session, now):
    """过期状态被 HardFilter 排除（集成回归）"""
    memory_id = str(uuid4())
    session.add(
        MemoryRecord(
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
            valid_to=now - timedelta(days=1),  # 已过期
            created_at=now - timedelta(days=7),
            updated_at=now - timedelta(days=7),
        )
    )
    session.commit()

    fake_index = FakeIndex({"semantic": [{"memory_id": memory_id, "score": 0.95}]})
    fake_reranker = FakeReranker({memory_id: 0.9})

    pipeline = EvidencePipeline(fake_index, session, fake_reranker)
    pack = pipeline.assemble("最近怎么样", "tenant1", "user123", now)

    # 过期状态被排除
    assert len(pack.items) == 0


def test_cancelled_event_filtered(session, now):
    """cancelled 事件被 HardFilter 排除（集成回归）"""
    event_id = str(uuid4())
    session.add(
        Event(
            event_id=event_id,
            tenant_id="tenant1",
            user_id="user123",
            namespace="user_memory",
            event_type="meeting",
            title="团队聚会",
            status="cancelled",  # 已取消
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    fake_index = FakeIndex({"episodic": [{"event_id": event_id, "score": 0.95}]})
    fake_reranker = FakeReranker({event_id: 0.9})

    pipeline = EvidencePipeline(fake_index, session, fake_reranker)
    pack = pipeline.assemble("那个聚会还去吗", "tenant1", "user123", now)

    # cancelled 事件被排除
    assert len(pack.items) == 0


def test_usage_rules_present(session, now):
    """EvidencePack 基本结构完整（items/active_events/generated_at）"""
    fake_index = FakeIndex({})
    fake_reranker = FakeReranker({})

    pipeline = EvidencePipeline(fake_index, session, fake_reranker)
    pack = pipeline.assemble("test", "tenant1", "user123", now)

    # EvidencePack 基本字段非空
    assert pack is not None
    assert pack.generated_at is not None
    assert isinstance(pack.items, list)
    assert isinstance(pack.active_events, list)
