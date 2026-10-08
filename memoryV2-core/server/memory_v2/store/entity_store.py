"""Entity store for third-party entities (person/pet/place).

第三方实体（朋友、宠物、地点等）独立存储，不进用户画像。
当 subject.is_current_user=False 时，候选路由到此模块。

表结构：
- entities: 实体本体（阿宁、团团、栗子）
- entity_relations: 实体属性和关系（阿宁不吃辣、团团可能掀翻桌子）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Index, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from ..contracts import MemoryCandidate, WriteDecision, Scope, SubjectRef
from ..identity import build_subject_id

Base = declarative_base()


class Entity(Base):
    """实体表：存储第三方人物/宠物/地点"""

    __tablename__ = "entities"

    entity_id = Column(String(128), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)  # 哪个用户提到的这个实体
    entity_type = Column(String(32), nullable=False)  # person / pet / place
    canonical_name = Column(String(128), nullable=False)
    aliases = Column(JSON, nullable=False, default=list)  # ["阿宁", "小宁"]
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_tenant_user_name", "tenant_id", "user_id", "canonical_name"),
    )


class EntityRelation(Base):
    """实体关系表：存储实体的属性和关系"""

    __tablename__ = "entity_relations"

    relation_id = Column(String(128), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    subject_id = Column(String(128), nullable=False, index=True)  # entity_id
    predicate = Column(String(128), nullable=False)  # food.dislike / behavior.tendency
    object_value = Column(Text, nullable=False)  # "辣" / "掀翻桌子"
    status = Column(String(32), nullable=False, default="active")  # active / deleted
    source_turn_id = Column(String(128), nullable=True)
    extra_metadata = Column(JSON, nullable=False, default=dict)  # metadata 是 SQLAlchemy 保留字段
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_subject_predicate", "subject_id", "predicate"),
        Index("idx_tenant_user_status", "tenant_id", "user_id", "status"),
    )


class EntityStore:
    """第三方实体存储，处理 route=ENTITY_RELATION 的候选"""

    def __init__(self, session_factory):
        """
        Args:
            session_factory: SQLAlchemy sessionmaker（不再接收 db_url）
        """
        self.session_factory = session_factory

    def create_tables(self):
        """创建表结构（仅用于测试或首次初始化）"""
        # 从 session_factory 获取 engine
        session = self.session_factory()
        try:
            Base.metadata.create_all(session.bind)
        finally:
            session.close()

    def write(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        source_turn_id: str | None = None,
    ):
        """写入第三方实体及其属性/关系。

        幂等：重复写入同一条关系不产生重复行。

        Args:
            decision: 门控决策（route=ENTITY_RELATION）
            tenant_id: 租户 ID
            user_id: 用户 ID（谁提到的这个实体）
            source_turn_id: 来源轮次 ID

        Returns:
            EntityWriteReceipt: 完整的写入回执，包含entity_id、relation_id、memory_id、outbox_id

        Raises:
            ValueError: decision.route != ENTITY_RELATION 时抛出
        """
        from ..contracts import MemoryType, EntityWriteReceipt

        if decision.route != MemoryType.ENTITY_RELATION:
            raise ValueError(f"EntityStore 只处理 ENTITY_RELATION 路由，收到 {decision.route}")

        candidate = decision.candidate
        session = self.session_factory()

        try:
            # 1. 确保实体存在（幂等）
            entity_id = self._ensure_entity(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                candidate=candidate,
            )

            # 2. 写入关系（幂等）
            relation_id = self._write_relation(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                entity_id=entity_id,
                candidate=candidate,
                source_turn_id=source_turn_id,
            )

            # 3. 同时写入 memory_v2_record 用于向量检索（修复 entity_relation 召回）
            memory_id = self._write_to_memory_record(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                entity_id=entity_id,
                relation_id=relation_id,
                candidate=candidate,
                source_turn_id=source_turn_id,
            )

            # 4. 写入 outbox 触发索引
            outbox_id = self._write_to_outbox(
                session,
                memory_id=memory_id,
            )

            session.commit()

            # P0-2修复：返回完整的EntityWriteReceipt
            return EntityWriteReceipt(
                entity_id=entity_id,
                relation_id=relation_id,
                memory_id=memory_id,
                outbox_id=outbox_id,
            )

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _ensure_entity(
        self,
        session: Session,
        tenant_id: str,
        user_id: str,
        candidate: MemoryCandidate,
    ) -> str:
        """确保实体存在，不存在则创建（幂等）"""
        canonical_name = candidate.subject.canonical_name
        entity_type = candidate.subject.kind  # person / pet / place

        # 如果候选已经带 entity_id，优先使用
        if candidate.subject.entity_id:
            entity_id = candidate.subject.entity_id
        else:
            # 生成 entity_id：包含租户/用户命名空间，避免跨用户主键冲突
            # 格式：{tenant_id}:{user_id}:{entity_type}:{canonical_name}
            entity_id = f"{tenant_id}:{user_id}:{entity_type}:{canonical_name}"

        # 检查是否已存在
        existing = session.query(Entity).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            entity_id=entity_id,
        ).first()

        if existing:
            return entity_id

        # 创建新实体
        entity = Entity(
            entity_id=entity_id,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            aliases=[],
        )
        session.add(entity)
        return entity_id

    def _write_relation(
        self,
        session: Session,
        tenant_id: str,
        user_id: str,
        entity_id: str,
        candidate: MemoryCandidate,
        source_turn_id: str | None,
    ) -> str:
        """写入实体关系（幂等）
        
        Returns:
            relation_id
        """
        predicate = candidate.predicate
        object_value = str(candidate.value)

        # 检查是否已存在相同的关系
        existing = session.query(EntityRelation).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            subject_id=entity_id,
            predicate=predicate,
            object_value=object_value,
            status="active",
        ).first()

        if existing:
            # 已存在，更新 updated_at（SQLAlchemy 自动处理）
            existing.updated_at = datetime.now(timezone.utc)
            return existing.relation_id

        # 创建新关系
        relation = EntityRelation(
            relation_id=f"rel-{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            user_id=user_id,
            subject_id=entity_id,
            predicate=predicate,
            object_value=object_value,
            status="active",
            source_turn_id=source_turn_id,
            extra_metadata={
                "confidence": candidate.confidence,
                "modality": candidate.modality.value,
                "normalized_text": candidate.normalized_text_zh,
            },
        )
        session.add(relation)
        return relation.relation_id

    def query_entity(
        self,
        tenant_id: str,
        user_id: str,
        canonical_name: str,
    ) -> Entity | None:
        """查询实体"""
        session = self.session_factory()
        try:
            return session.query(Entity).filter_by(
                tenant_id=tenant_id,
                user_id=user_id,
                canonical_name=canonical_name,
            ).first()
        finally:
            session.close()

    def query_relations(
        self,
        tenant_id: str,
        user_id: str,
        entity_id: str,
    ) -> list[EntityRelation]:
        """查询实体的所有活跃关系"""
        session = self.session_factory()
        try:
            return session.query(EntityRelation).filter_by(
                tenant_id=tenant_id,
                user_id=user_id,
                subject_id=entity_id,
                status="active",
            ).all()
        finally:
            session.close()

    def _write_to_memory_record(
        self,
        session,
        tenant_id: str,
        user_id: str,
        entity_id: str,
        relation_id: str,
        candidate,
        source_turn_id: str | None,
    ) -> str:
        """将 entity_relation 写入 memory_v2_record 用于向量检索

        修复：让 entity_relation 也能被索引到 Qdrant

        Returns:
            memory_id
        """
        from server.memory_v2.models import MemoryRecord

        memory_id = f"mem-{uuid.uuid4().hex[:16]}"

        # 构建记忆文本
        text_zh = candidate.normalized_text_zh

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        # 构造正确的 subject_id（与召回时的 query_subject 格式一致）
        scope = Scope(tenant_id=tenant_id, user_id=user_id, namespace="user_memory")
        current_user_subject = SubjectRef(
            kind="user",
            canonical_name="user:self",
            is_current_user=True,
        )
        subject_id = build_subject_id(scope, current_user_subject)
        
        mem_record = MemoryRecord(
            memory_id=memory_id,
            tenant_id=tenant_id,
            user_id=user_id,
            subject_id=subject_id,
            namespace="user_memory",
            memory_type="entity_relation",
            text_zh=text_zh,
            modality="fact",
            fact_key=candidate.predicate,
            status="active",
            source_turn_id=source_turn_id,
            created_at=now,
            updated_at=now,
            value_json={
                "entity_id": entity_id,
                "relation_id": relation_id,
                "subject": candidate.subject.canonical_name,
                "predicate": candidate.predicate,
                "object": str(candidate.value),
                "confidence": candidate.confidence,
            },
        )
        session.add(mem_record)
        return memory_id

    def _write_to_outbox(
        self,
        session,
        memory_id: str,
    ) -> int:
        """写入 outbox 触发异步索引

        Returns:
            outbox_id (自增主键id)
        """
        from server.memory_v2.models import Outbox

        outbox = Outbox(
            aggregate_id=memory_id,
            operation="upsert",
            payload_json={"memory_id": memory_id},
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(outbox)
        session.flush()  # 刷新以获取自增id
        return outbox.id
