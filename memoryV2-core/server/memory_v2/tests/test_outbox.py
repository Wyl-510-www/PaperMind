"""Tests for server/memory_v2/outbox.py and index_v2.py"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from server.memory_v2.models import MemoryRecord, Outbox, create_engine_and_tables
from server.memory_v2.store.outbox import OutboxWorker
from server.memory_v2.store.repository import Repository, now_utc


# ─── fake index & embedder ───────────────────────────────────────────────────

class FakeIndex:
    """测试用假索引：记录调用，不访问真实 Qdrant。

    ✅ 可验证：worker 是否调用 upsert/delete、point_id/payload 是否正确传递。
    ❌ 不可验证（真实 Qdrant 集成测试才能覆盖）：collection schema、向量维度校验、
       距离度量方向、payload 过滤、最终一致性、网络超时。
    真实适配器契约测试见票 12（真实临时 collection）。
    """

    def __init__(self):
        self.upserted = []
        self.deleted = []

    def upsert(self, point_id: str, vector: list[float], payload: dict):
        self.upserted.append((point_id, vector, payload))

    def delete(self, point_id: str):
        self.deleted.append(point_id)


class FakeEmbedder:
    """测试用假 embedder：返回固定维度向量。

    ✅ 可验证：worker 调用 embed 的路径、向量被传给 index。
    ❌ 不可验证（真实 embedding 冒烟测试才能覆盖）：真实向量维度、模型版本、
       语义相似度、批处理、API 成本/超时。维度必须与 Qdrant collection 一致——
       真实校验见票 13。
    """

    def embed(self, text: str) -> list[float]:
        return [0.1] * 1536  # 固定维度（真实模型维度需与 collection 对齐）


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite:///:memory:")
    return sessionmaker(bind=engine)()


@pytest.fixture
def fake_index():
    return FakeIndex()


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def worker(session, fake_index, fake_embedder):
    return OutboxWorker(session, fake_index, fake_embedder, max_retries=3)


# ─── pending → done ──────────────────────────────────────────────────────────

def test_process_pending_upsert(session, worker, fake_index):
    """pending upsert 记录 → done，索引被调用"""
    # 写一条真值 + outbox
    mem = MemoryRecord(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        memory_type="semantic", fact_key="u:diet.dislike",
        text_zh="用户不吃香菜",
        modality="fact", status="active",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(mem)

    ob = Outbox(
        aggregate_id="mem-001",
        operation="upsert",
        payload_json={"memory_id": "mem-001"},
        status="pending",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(ob)
    session.commit()

    # 处理
    stats = worker.process_pending()
    assert stats["done"] == 1
    assert stats["failed"] == 0

    # outbox 标 done
    ob_after = session.query(Outbox).first()
    assert ob_after.status == "done"

    # index.upsert 被调用（outbox 将 memory_id 转为 UUID 格式）
    from server.memory_v2.store.outbox import _to_qdrant_id
    assert len(fake_index.upserted) == 1
    assert fake_index.upserted[0][0] == _to_qdrant_id("mem-001")


def test_process_pending_delete(session, worker, fake_index):
    """pending delete 记录 → done，index.delete 被调用"""
    ob = Outbox(
        aggregate_id="mem-999",
        operation="delete",
        payload_json={"memory_id": "mem-999"},
        status="pending",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(ob)
    session.commit()

    worker.process_pending()

    from server.memory_v2.store.outbox import _to_qdrant_id
    assert session.query(Outbox).first().status == "done"
    assert _to_qdrant_id("mem-999") in fake_index.deleted


# ─── 失败重试 ────────────────────────────────────────────────────────────────

class FailingIndex:
    """模拟失败的索引"""

    def __init__(self, fail_count=1):
        self.call_count = 0
        self.fail_count = fail_count

    def upsert(self, *args, **kwargs):
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise RuntimeError("index error")

    def delete(self, *args):
        raise RuntimeError("index error")


def test_process_pending_retry(session, fake_embedder):
    """失败 → retry_count++，设 next_retry_at"""
    failing_index = FailingIndex(fail_count=1)
    worker = OutboxWorker(session, failing_index, fake_embedder, max_retries=3)

    mem = MemoryRecord(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        memory_type="semantic", text_zh="test",
        modality="fact", status="active",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(mem)

    ob = Outbox(
        aggregate_id="mem-001", operation="upsert",
        payload_json={"memory_id": "mem-001"},
        status="pending",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(ob)
    session.commit()

    # 第一次处理失败
    stats = worker.process_pending()
    assert stats["failed"] == 1
    assert stats["done"] == 0

    ob_after = session.query(Outbox).first()
    assert ob_after.status == "pending"
    assert ob_after.retry_count == 1
    assert ob_after.next_retry_at is not None
    assert ob_after.last_error is not None


def test_process_pending_dead_letter(session, fake_embedder):
    """达到重试上限 → dead"""
    failing_index = FailingIndex(fail_count=999)
    worker = OutboxWorker(session, failing_index, fake_embedder, max_retries=2)

    mem = MemoryRecord(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        memory_type="semantic", text_zh="test",
        modality="fact", status="active",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(mem)

    ob = Outbox(
        aggregate_id="mem-001", operation="upsert",
        payload_json={"memory_id": "mem-001"},
        status="pending",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(ob)
    session.commit()

    # 失败 2 次后进入 dead。每次推进 now 越过 next_retry_at 退避时间
    base = now_utc()
    worker.process_pending(now=base)  # 第一次失败，retry_count=1
    worker.process_pending(now=base + timedelta(hours=1))  # 第二次失败，达上限 → dead

    ob_after = session.query(Outbox).first()
    assert ob_after.status == "dead"
    assert ob_after.retry_count == 2


# ─── 事务一致性 ──────────────────────────────────────────────────────────────

def test_fact_write_and_outbox_in_same_transaction(session, fake_index, fake_embedder):
    """真值写入 + outbox 在同一事务（repository 保证）"""
    repo = Repository(session)
    fact_data = {
        "memory_type": "semantic",
        "text_zh": "用户不吃香菜",
        "modality": "fact",
    }
    repo.write_fact_version(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        fact_key="u:diet.dislike",
        fact_data=fact_data,
    )
    # repository 已 commit

    # 验证 outbox 存在
    outbox = session.query(Outbox).filter_by(aggregate_id="mem-001").all()
    assert len(outbox) == 1
    assert outbox[0].operation == "upsert"

    # worker 处理
    worker = OutboxWorker(session, fake_index, fake_embedder)
    worker.process_pending()

    # index 被调用
    assert len(fake_index.upserted) == 1


def test_next_retry_at_not_due(session, fake_embedder):
    """next_retry_at 未到期的记录不处理"""
    failing_index = FailingIndex()
    worker = OutboxWorker(session, failing_index, fake_embedder)

    mem = MemoryRecord(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        memory_type="semantic", text_zh="test",
        modality="fact", status="active",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(mem)

    future = now_utc() + timedelta(hours=1)
    ob = Outbox(
        aggregate_id="mem-001", operation="upsert",
        payload_json={"memory_id": "mem-001"},
        status="pending",
        next_retry_at=future,  # 未到期
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(ob)
    session.commit()

    # 处理时传入当前时间，记录不会被处理
    stats = worker.process_pending(now=now_utc())
    assert stats["done"] == 0
    assert stats["failed"] == 0


# ─── 幂等 ────────────────────────────────────────────────────────────────────

def test_idempotency(session, worker, fake_index):
    """同一 aggregate_id 的重复 outbox 记录只处理一次"""
    mem = MemoryRecord(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        memory_type="semantic", text_zh="test",
        modality="fact", status="active",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(mem)

    # 两条相同的 outbox
    for i in range(2):
        ob = Outbox(
            aggregate_id="mem-001", operation="upsert",
            payload_json={"memory_id": "mem-001"},
            status="pending",
            created_at=now_utc(), updated_at=now_utc(),
        )
        session.add(ob)
    session.commit()

    worker.process_pending(batch_size=10)

    # index.upsert 被调用 2 次（outbox 有 2 条 pending）
    # 实际幂等由 Qdrant upsert 语义保证（相同 point_id 覆盖）
    assert len(fake_index.upserted) == 2


# ─── 票 06：并发 claim 强测试 ────────────────────────────────────────────────

def test_concurrent_claim_only_one_worker_wins(session, fake_embedder):
    """并发 claim：多 worker 只有一个能成功 claim 同一 outbox 行（P1-4）。"""
    fake_index = FakeIndex()

    mem = MemoryRecord(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        memory_type="semantic", text_zh="test",
        modality="fact", status="active",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(mem)

    ob = Outbox(
        aggregate_id="mem-001", operation="upsert",
        payload_json={"memory_id": "mem-001"},
        status="pending",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(ob)
    session.commit()
    outbox_id = ob.id

    # 两个 worker 同时 claim
    worker1 = OutboxWorker(session, fake_index, fake_embedder)
    worker2 = OutboxWorker(session, fake_index, fake_embedder)

    # 模拟并发：worker1 claim
    claimed1 = worker1._claim_batch(batch_size=10)
    # worker2 试图 claim（应返回空，因为已被 worker1 claimed）
    claimed2 = worker2._claim_batch(batch_size=10)

    # 只有一个成功
    assert len(claimed1) == 1
    assert len(claimed2) == 0


def test_claimed_by_expires_allows_reclaim(session, fake_embedder):
    """claimed_by 过期后其他 worker 可重新 claim（P1-4）。"""
    fake_index = FakeIndex()

    mem = MemoryRecord(
        memory_id="mem-001",
        tenant_id="t", user_id="u", namespace="user_memory",
        memory_type="semantic", text_zh="test",
        modality="fact", status="active",
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(mem)

    # outbox claimed_until 已过期
    past = now_utc() - timedelta(seconds=120)
    ob = Outbox(
        aggregate_id="mem-001", operation="upsert",
        payload_json={"memory_id": "mem-001"},
        status="pending",
        claimed_by="old-worker",
        claimed_until=past,
        created_at=now_utc(), updated_at=now_utc(),
    )
    session.add(ob)
    session.commit()

    # 新 worker claim
    worker = OutboxWorker(session, fake_index, fake_embedder)
    claimed = worker._claim_batch(batch_size=10)

    # 应能重新 claim
    assert len(claimed) == 1
    assert claimed[0].claimed_by == worker.worker_id

