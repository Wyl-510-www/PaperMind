"""幂等键测试：数据库唯一约束 + 并发保护（P0-2）。

修复前：check_idempotency_key 逻辑几乎恒返回 False（candidate_id 不在 text_zh），
且"先查再写"无并发保护。修复后靠数据库 UNIQUE 约束兜底，第二次写返回既有 memory_id，
并发写只落一条。
"""

import os
import tempfile
import threading

import pytest
from sqlalchemy.exc import IntegrityError
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
from server.memory_v2.models import MemoryRecord, create_engine_and_tables


@pytest.fixture
def engine():
    """基于文件的 SQLite：支持多线程连接，可测唯一约束的并发行为。

    in-memory SQLite 不能跨线程共享，且并发语义与 MySQL 不同；file-based
    SQLite 支持多连接并能强制 UNIQUE 约束，足以验证"并发写只落一条"的契约。
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_engine_and_tables(f"sqlite:///{path}")
    yield eng
    eng.dispose()
    os.unlink(path)


@pytest.fixture
def session(engine):
    return sessionmaker(bind=engine)()


def make_decision_with_candidate_id(cand_id: str) -> WriteDecision:
    """构造一个带 candidate_id 的 WriteDecision。"""
    candidate = MemoryCandidate(
        candidate_id=cand_id,
        subject=SubjectRef(kind="user", canonical_name="user:self", is_current_user=True),
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
    return WriteDecision(
        candidate=candidate,
        accepted=True,
        route=MemoryType.SEMANTIC,
        reason_code="STABLE_SEMANTIC",
        fact_key="current_user:t1:u1:diet.dislike",
    )


def test_same_candidate_id_second_write_returns_existing(session):
    """相同 candidate_id 二次写入被 DB 唯一约束拦截，返回既有 memory_id。"""
    tenant_id, user_id = "t1", "u1"
    candidate_id = "cand_idempotency_001"

    # 第一次写入
    fact_store = FactStore(session)
    decision = make_decision_with_candidate_id(candidate_id)
    memory_id_1 = fact_store.write_fact(
        decision, tenant_id=tenant_id, user_id=user_id, source_turn_id="turn-1"
    )

    # 第二次写入相同 candidate_id（应返回既有 memory_id，不重复落库）
    decision_2 = make_decision_with_candidate_id(candidate_id)
    memory_id_2 = fact_store.write_fact(
        decision_2, tenant_id=tenant_id, user_id=user_id, source_turn_id="turn-1"
    )

    # 返回相同 memory_id
    assert memory_id_2 == memory_id_1

    # DB 只有一条
    count = session.query(MemoryRecord).filter_by(
        tenant_id=tenant_id, user_id=user_id, source_turn_id="turn-1"
    ).count()
    assert count == 1


def test_concurrent_writes_same_candidate_id_only_one_row(engine):
    """并发测试：两个 session 同时写相同 candidate_id，只产生一条 DB 记录。"""
    tenant_id, user_id = "t1", "u1"
    candidate_id = "cand_concurrent_001"

    results = []
    errors = []

    def write_fact():
        try:
            sess = sessionmaker(bind=engine)()
            fact_store = FactStore(sess)
            decision = make_decision_with_candidate_id(candidate_id)
            memory_id = fact_store.write_fact(
                decision, tenant_id=tenant_id, user_id=user_id, source_turn_id="turn-c"
            )
            results.append(memory_id)
        except IntegrityError as e:
            # 预期：一个线程成功，另一个捕获 IntegrityError 并返回既有
            errors.append(e)
        except Exception as e:
            errors.append(e)

    # 两个线程并发写
    t1 = threading.Thread(target=write_fact)
    t2 = threading.Thread(target=write_fact)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 验证：DB 只有一条记录
    sess = sessionmaker(bind=engine)()
    count = sess.query(MemoryRecord).filter_by(
        tenant_id=tenant_id, user_id=user_id, source_turn_id="turn-c"
    ).count()
    assert count == 1

    # 至少一个成功（results 非空）
    assert len(results) >= 1
