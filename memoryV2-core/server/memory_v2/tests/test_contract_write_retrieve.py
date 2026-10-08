"""跨模块契约测试：写入 → 检索闭环。

修复 P0-1（subject_id 写入/检索契约不一致）后，验证写入侧产生的 subject_id
能被检索侧的 query_subject 精确匹配到。这类测试用真实的 gate / fact_store /
build_subject_id / evidence_pipeline，禁止为迁就实现而改测试数据——这正是审查
报告指出"测试迁就实现"问题的补救。

Seam（公共边界）：
- 写入：MemoryGate.decide → FactStore.write_fact（真实 build_subject_id）
- 检索：EvidencePipeline.assemble（真实构造 query_subject）→ HardFilter
"""

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from server.memory_v2.contracts import (
    DeterministicSignals,
    MemoryCandidate,
    MemoryType,
    Modality,
    SubjectRef,
    TimeCandidate,
)
from server.memory_v2.retrieve.evidence_pipeline import EvidencePipeline
from server.memory_v2.store.fact_store import FactStore
from server.memory_v2.write.gate import MemoryGate
from server.memory_v2.models import create_engine_and_tables


# ─── Fakes（仅隔离向量库/重排，真值走真实 MySQL 语义）────────────────────────

class FakeIndex:
    """假 Qdrant index，返回预设候选（只模拟召回，真值判定回 MySQL）。"""

    def __init__(self, candidates: dict[str, list[dict[str, Any]]]):
        self._candidates = candidates

    def search(self, memory_type: str, query: str, top_k: int) -> list[dict]:
        return self._candidates.get(memory_type, [])[:top_k]


class FakeReranker:
    """假 reranker，原样返回并附中性分数（不模拟真实语义重排）。"""

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        for cand in candidates:
            cand["rerank_score"] = 0.9
        return candidates


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


@pytest.fixture
def now():
    return datetime(2026, 8, 2, 10, 0, 0, tzinfo=timezone.utc)


def make_user_candidate() -> MemoryCandidate:
    """构造一条当前用户的稳定 semantic 候选（会被门控接受）。"""
    return MemoryCandidate(
        candidate_id="cand-roundtrip-1",
        subject=SubjectRef(
            kind="user",
            canonical_name="user:self",
            is_current_user=True,
        ),
        predicate="diet.dislike",
        value="香菜",
        normalized_text_zh="用户不吃香菜",
        memory_type=MemoryType.SEMANTIC,
        modality=Modality.FACT,
        confidence=0.92,
        importance=0.8,
        durability="stable",
        time=TimeCandidate(),
        source_span="我从来不吃香菜",
    )


# ─── 闭环契约测试 ───────────────────────────────────────────────────────────

def test_user_fact_written_can_be_retrieved(session, now):
    """写入的用户 subject_id 格式，检索侧必须能匹配召回（P0-1 核心回归）。

    修复前：写入 subject_id="user:self"，检索 query_subject="user"，
    "user:self" != "user" → 全部过滤，len(items)==0。
    修复后：两侧都走 build_subject_id → "current_user:tenant1:user123"，能召回。
    """
    tenant_id, user_id = "tenant1", "user123"

    # 1. 门控裁决（真实 gate）
    gate = MemoryGate()
    candidate = make_user_candidate()
    decision = gate.decide(candidate, DeterministicSignals())
    assert decision.accepted
    assert decision.route == MemoryType.SEMANTIC

    # 2. 写入真值（真实 fact_store + build_subject_id）
    fact_store = FactStore(session)
    memory_id = fact_store.write_fact(
        decision, tenant_id=tenant_id, user_id=user_id, source_turn_id="turn-1"
    )

    # 3. 检索（真实 evidence_pipeline 构造 query_subject）
    fake_index = FakeIndex({"semantic": [{"memory_id": memory_id, "score": 0.95}]})
    pipeline = EvidencePipeline(fake_index, session, FakeReranker())
    pack = pipeline.assemble(
        query="你知道我不吃什么吗",
        tenant_id=tenant_id,
        user_id=user_id,
        now=now,
    )

    # 4. 必须召回——subject_id 全程一致
    assert len(pack.items) == 1
    assert pack.items[0].memory_id == memory_id
    assert pack.items[0].content == "用户不吃香菜"
    assert pack.items[0].subject_id == "current_user:tenant1:user123"


def test_written_subject_id_matches_query_subject_format(session):
    """写库的 subject_id 与检索构造的 query_subject 采用同一格式。"""
    tenant_id, user_id = "tenant_x", "user_999"

    gate = MemoryGate()
    decision = gate.decide(make_user_candidate(), DeterministicSignals())
    fact_store = FactStore(session)
    memory_id = fact_store.write_fact(decision, tenant_id=tenant_id, user_id=user_id)

    rec = fact_store.get_active_fact(
        tenant_id, user_id, fact_key=decision.fact_key
    )
    assert rec is not None
    assert rec.subject_id == "current_user:tenant_x:user_999"
