"""SQLAlchemy models for Memory V2 truth store.

Phase 2 的 5 张真值表 + Phase 1 的 entity tables（未来迁移进来）。
使用独立的 declarative_base，不依赖项目现有 Base，保持模块边界清晰。
测试用 SQLite in-memory，生产用 MySQL（db_url 注入）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class MemoryRecord(Base):
    """真值主表：存储所有类型的记忆（semantic/episodic/task/relationship）"""

    __tablename__ = "memory_v2_record"

    memory_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(128), nullable=False)
    namespace = Column(String(64), nullable=False, default="user_memory")
    memory_type = Column(String(32), nullable=False)  # semantic/episodic/task/relationship

    # semantic 专用
    fact_key = Column(String(255), nullable=True)
    subject_id = Column(String(255), nullable=True)
    predicate = Column(String(128), nullable=True)
    value_json = Column(JSON, nullable=True)

    # 通用字段
    text_zh = Column(Text, nullable=False)
    modality = Column(String(32), nullable=False)  # fact/plan/wish/hypothesis/joke/...
    evidence_type = Column(String(16), nullable=True)  # explicit/confirmed/inferred（Ticket 10: Preference Provenance）
    status = Column(String(32), nullable=False, default="active")  # active/superseded/deleted
    confidence = Column(Float, nullable=False, default=0.5)
    importance = Column(Float, nullable=False, default=0.5)

    # Ticket 04: 偏好结构化字段（全部 nullable，非偏好记录留空）
    domain = Column(String(32), nullable=True)  # 偏好领域：food/music/activity/…
    object_key = Column(String(128), nullable=True)  # 偏好对象：香菜/辣味/摇滚/…
    polarity = Column(String(8), nullable=True)  # 极性：like/dislike/avoid
    preference_strength = Column(  # 偏好强度：favorite/strong/normal/weak
        String(16), nullable=True,
    )
    provenance = Column(String(16), nullable=True)  # 来源：confirmed/hypothesis/inferred

    # 时间
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # 版本化
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String(36), nullable=True)

    # 索引状态
    index_status = Column(String(16), nullable=False, default="pending")  # pending/indexed/failed

    # 幂等键（P0-2）：来自 MemoryCandidate.candidate_id，配合唯一约束做去重
    candidate_id = Column(String(64), nullable=True)

    # Phase 3: 笔记元数据（标签、阅读日期、作者等）
    # 注意：使用 note_metadata 而非 metadata，因为 metadata 是 SQLAlchemy 保留名
    note_metadata = Column('metadata', JSON, nullable=True)

    # 审计
    source_turn_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "idx_memv2_scope_status_type",
            "tenant_id",
            "user_id",
            "namespace",
            "status",
            "memory_type",
        ),
        Index(
            "idx_memv2_fact_key",
            "tenant_id",
            "user_id",
            "namespace",
            "fact_key",
        ),
        Index("idx_memv2_expires", "expires_at"),
        # P0-2：幂等唯一约束——同一 (scope, turn, candidate) 只允许一条
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "namespace",
            "source_turn_id",
            "candidate_id",
            name="uq_idempotency",
        ),
    )


class ActiveFact(Base):
    """Active pointer：O(1) 定位某 fact_key 的当前有效版本"""

    __tablename__ = "memory_v2_active_fact"

    tenant_id = Column(String(64), primary_key=True)
    user_id = Column(String(128), primary_key=True)
    namespace = Column(String(64), primary_key=True)
    fact_key = Column(String(255), primary_key=True)

    memory_id = Column(String(36), nullable=False)  # 指向 MemoryRecord.memory_id
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "namespace", "fact_key", name="uq_active_fact"),
    )


class Event(Base):
    """事件表：episodic memory / task"""

    __tablename__ = "memory_v2_event"

    event_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(128), nullable=False)
    namespace = Column(String(64), nullable=False, default="user_memory")

    event_type = Column(String(32), nullable=False)  # meeting/appointment/task/...
    title = Column(String(255), nullable=False)
    participants_json = Column(JSON, nullable=True)
    location_json = Column(JSON, nullable=True)

    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)
    timezone_name = Column(String(64), nullable=False, default="Asia/Shanghai")

    status = Column(String(32), nullable=False, default="scheduled")  # scheduled/rescheduled/cancelled/completed
    version = Column(Integer, nullable=False, default=1)

    source_turn_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "idx_memv2_event_scope_status",
            "tenant_id",
            "user_id",
            "status",
            "start_at",
        ),
    )


class Nickname(Base):
    """昵称版本表：独立管理昵称真值，修复 DSM 重启续期 bug"""

    __tablename__ = "memory_v2_nickname"

    nickname_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(128), nullable=False)

    value = Column(String(128), nullable=False)
    type = Column(String(16), nullable=False)  # temporary/permanent

    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)  # None for permanent

    status = Column(String(16), nullable=False, default="active")  # active/superseded/deleted
    version = Column(Integer, nullable=False, default=1)

    source_turn_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_memv2_nickname_user", "tenant_id", "user_id", "status"),
    )


class Outbox(Base):
    """Outbox 队列：真值变更异步同步到 Qdrant candidate_index"""

    __tablename__ = "memory_v2_outbox"

    # SQLite autoincrement 只认 INTEGER PRIMARY KEY，MySQL 用 BIGINT
    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        nullable=False,
    )
    aggregate_id = Column(String(36), nullable=False)  # memory_id / event_id / nickname_id
    operation = Column(String(16), nullable=False)  # upsert/delete
    payload_json = Column(JSON, nullable=False)

    status = Column(String(16), nullable=False, default="pending")  # pending/processing/done/dead
    retry_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # P1-4：并发 claim 语义。claimed_until 为软租约到期时间，过期后可被其他 worker 重新 claim
    claimed_by = Column(String(64), nullable=True)
    claimed_until = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_memv2_outbox_pending", "status", "next_retry_at", "id"),
    )


def create_engine_and_tables(db_url: str):
    """创建引擎和所有表（测试/生产初始化用）"""
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(db_url: str):
    """创建 session factory（测试/生产用）"""
    engine = create_engine(db_url)
    return sessionmaker(bind=engine)
