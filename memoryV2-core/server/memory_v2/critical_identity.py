"""Critical Identity Store：高敏身份字段的结构化真值，不参与向量检索。

每个 predicate 同一时刻只有一个 active 值（通过 Active Pointer 保证）。
旧值进入 superseded/blocked 状态，已删除值永不复活。

Predicate 枚举（先上4个，后续按需扩展）：
- nickname.current: 当前昵称
- pronoun.preferred: 代词偏好
- gender.self_reported: 性别
- relationship_boundary.spousal_address: 关系称谓边界
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    JSON,
    Integer,
    Float,
    Boolean,
    DateTime,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

# 独立 Base，类同 entity_store 模式
Base = declarative_base()

# ---- 预置 predicate ----

CRITICAL_PREDICATES: set[str] = {
    "nickname.current",
    "pronoun.preferred",
    "gender.self_reported",
    "relationship_boundary.spousal_address",
}

def is_critical_predicate(predicate: str) -> bool:
    """判断是否属于高敏 predicate（后续可扩展为查表）。"""
    return predicate in CRITICAL_PREDICATES


# ---- 数据模型 ----

class UserCriticalFact(Base):
    __tablename__ = "user_critical_fact"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(128), nullable=False)
    predicate = Column(String(128), nullable=False)
    value_json = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="active")  # active | superseded | deleted | blocked
    version = Column(Integer, nullable=False, default=1)
    confidence = Column(Float, nullable=False, default=1.0)
    explicit = Column(Boolean, nullable=False, default=True)
    source_turn_id = Column(String(128), nullable=False)
    source_span = Column(String(1024), nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "predicate", "version", name="uq_critical_fact_version"),
    )


class UserCriticalFactActive(Base):
    """Active Pointer：原子指向每个 predicate 的当前生效值。"""
    __tablename__ = "user_critical_fact_active"

    tenant_id = Column(String(64), primary_key=True)
    user_id = Column(String(128), primary_key=True)
    predicate = Column(String(128), primary_key=True)
    fact_id = Column(String(36), nullable=False)
    lock_version = Column(Integer, nullable=False, default=0)


# ---- Repository ----

class CriticalIdentityRepo:
    """Critical Identity 读写（确定性直查 MySQL，不走 Qdrant）。

    使用同步 session_factory（sessionmaker），调用方负责在 async 上下文中用
    asyncio.to_thread 包裹，或直接同步调用。
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def get_active_profile(
        self, tenant_id: str, user_id: str, predicates: list[str] | None = None,
    ) -> dict[str, dict]:
        """加载当前 active 的身份快照。

        Returns:
            {predicate: {value: ..., fact_id: ..., blocked_values: [...]}}
        """
        from sqlalchemy import select

        preds = predicates or list(CRITICAL_PREDICATES)
        session = self.session_factory()
        try:
            # 查 active pointer
            stmt = select(UserCriticalFactActive).where(
                UserCriticalFactActive.tenant_id == tenant_id,
                UserCriticalFactActive.user_id == user_id,
                UserCriticalFactActive.predicate.in_(preds),
            )
            result = session.execute(stmt)
            pointers = {row.predicate: row.fact_id for row in result.scalars().all()}

            if not pointers:
                return {}

            # 查对应的 fact
            stmt2 = select(UserCriticalFact).where(
                UserCriticalFact.id.in_(pointers.values()),
            )
            result2 = session.execute(stmt2)
            facts = {f.id: f for f in result2.scalars().all()}

            # 查 blocked values
            stmt3 = select(UserCriticalFact).where(
                UserCriticalFact.tenant_id == tenant_id,
                UserCriticalFact.user_id == user_id,
                UserCriticalFact.predicate.in_(preds),
                UserCriticalFact.status == "blocked",
            )
            result3 = session.execute(stmt3)
            blocked_by_pred: dict[str, list[str]] = {}
            for f in result3.scalars().all():
                blocked_by_pred.setdefault(f.predicate, []).extend(
                    f.value_json.get("value", []) if isinstance(f.value_json.get("value"), list)
                    else [f.value_json.get("value", "")]
                )

            profile = {}
            for predicate, fact_id in pointers.items():
                fact = facts.get(fact_id)
                if fact:
                    profile[predicate] = {
                        "value": fact.value_json.get("value"),
                        "fact_id": fact.id,
                        "blocked_values": blocked_by_pred.get(predicate, []),
                    }
            return profile
        finally:
            session.close()

    def write_fact(
        self,
        tenant_id: str,
        user_id: str,
        predicate: str,
        value: str,
        source_turn_id: str,
        source_span: str,
        confidence: float = 1.0,
        explicit: bool = True,
    ) -> str:
        """原子写入：锁 pointer → 旧 fact 标 superseded → 插新 fact → 更新 pointer。

        Returns:
            新 fact 的 ID。
        """
        from sqlalchemy import select, update

        fact_id = str(uuid4())
        now = datetime.now(timezone.utc)

        session = self.session_factory()
        try:
            with session.begin():
                # 锁 pointer
                stmt = select(UserCriticalFactActive).where(
                    UserCriticalFactActive.tenant_id == tenant_id,
                    UserCriticalFactActive.user_id == user_id,
                    UserCriticalFactActive.predicate == predicate,
                ).with_for_update()
                result = session.execute(stmt)
                pointer = result.scalars().first()

                if pointer:
                    # 旧 fact → superseded
                    old_fact_id = pointer.fact_id
                    stmt_up = (
                        update(UserCriticalFact)
                        .where(UserCriticalFact.id == old_fact_id)
                        .values(status="superseded")
                    )
                    session.execute(stmt_up)

                # 插入新 fact
                new_fact = UserCriticalFact(
                    id=fact_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    predicate=predicate,
                    value_json={"value": value},
                    status="active",
                    version=(pointer.lock_version + 1) if pointer else 1,
                    confidence=confidence,
                    explicit=explicit,
                    source_turn_id=source_turn_id,
                    source_span=source_span,
                    valid_from=now,
                )
                session.add(new_fact)

                # 更新或插入 pointer
                if pointer:
                    pointer.fact_id = fact_id
                    pointer.lock_version += 1
                else:
                    session.add(UserCriticalFactActive(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        predicate=predicate,
                        fact_id=fact_id,
                        lock_version=1,
                    ))

            logger.info(
                "CriticalIdentity write: predicate=%s value=%s user=%s turn=%s",
                predicate, value, user_id, source_turn_id,
            )
            return fact_id
        finally:
            session.close()

    def block_value(
        self, tenant_id: str, user_id: str, predicate: str, value: str | None = None,
    ) -> bool:
        """将指定值标记为 blocked（不再作为 active 候选）。

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            predicate: 高敏字段谓词
            value: 要 block 的具体值。如果为 None，block 该 predicate 的所有 superseded 值

        Returns:
            bool: 是否成功
        """
        from sqlalchemy import update, text

        session = self.session_factory()
        try:
            with session.begin():
                # P0-4: 构建 WHERE 条件，如果指定了 value，只 block 这个值
                where_conditions = [
                    UserCriticalFact.tenant_id == tenant_id,
                    UserCriticalFact.user_id == user_id,
                    UserCriticalFact.predicate == predicate,
                    UserCriticalFact.status == "superseded",
                ]

                # 如果指定了 value，只 block 这个值
                if value is not None:
                    # 使用 JSON 查询匹配 value_json.value
                    where_conditions.append(
                        text("JSON_EXTRACT(value_json, '$.value') = :value_param")
                    )
                    stmt = (
                        update(UserCriticalFact)
                        .where(*where_conditions)
                        .values(status="blocked")
                    )
                    result = session.execute(stmt, {"value_param": value})
                else:
                    stmt = (
                        update(UserCriticalFact)
                        .where(*where_conditions)
                        .values(status="blocked")
                    )
                    result = session.execute(stmt)

            logger.info(
                "CriticalIdentity blocked: predicate=%s value=%s user=%s affected_rows=%d",
                predicate, value or "all", user_id, result.rowcount,
            )
            return True
        except Exception:
            logger.exception("block_value 失败")
            session.rollback()
            return False
        finally:
            session.close()


def create_engine_and_tables(database_url: str):
    """幂等建表（checkfirst=True），供 facade bootstrap 调用。"""
    engine = create_engine(database_url, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(engine, checkfirst=True)
    return engine
