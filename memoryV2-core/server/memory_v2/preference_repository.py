"""Preference Repository：用户偏好的事实溯源与 confirmed/hypothesis 分离。

每个偏好事实记录来源（source_role, speech_act, source_turn_id, source_span）、
证据类型（explicit/confirmed/inferred）和状态（active/superseded/deleted）。
inferred 级别的偏好不进入 confirmed 查询。

对应方案：
- 高敏 Spec §3.3: UserPreferenceFact 数据模型
- 高敏 Spec §6: Preference Provenance（confirmed/hypothesis 分离）
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, String, Enum, Integer, Float, Boolean, Text,
    DateTime, UniqueConstraint, create_engine,
)
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

# 独立 Base，与 critical_identity.py 模式一致
Base = declarative_base()


# ---- 偏好强度枚举 ----

PREFERENCE_STRENGTHS = {"favorite", "strong", "normal", "weak"}

# 不应升级的弱表述 → 实际强度映射
WEAK_TO_STRENGTH: dict[str, str] = {
    "不讨厌": "weak",
    "可以吃": "weak",
    "还行": "weak",
    "不排斥": "weak",
    "能接受": "weak",
}


# ---- 数据模型 ----

class UserPreferenceFact(Base):
    """用户偏好事实（confirmed + hypothesis）—— Spec §3.3"""

    __tablename__ = "user_preference_fact"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    domain = Column(String(64), nullable=False)              # food / activity / music
    object_key = Column(String(256), nullable=False)          # 香菜 / 游泳 / 周杰伦
    polarity = Column(
        Enum("like", "dislike", "avoid", name="preference_polarity"),
        nullable=False,
    )
    strength = Column(
        Enum("favorite", "strong", "normal", "weak", name="preference_strength"),
        nullable=False,
    )
    evidence_type = Column(
        Enum("explicit", "confirmed", "inferred", name="preference_evidence_type"),
        nullable=False,
    )
    status = Column(
        Enum("active", "superseded", "deleted", name="preference_status"),
        nullable=False,
        default="active",
    )
    source_turn_id = Column(String(128), nullable=False)
    source_span = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "domain", "object_key", "version",
            name="uq_preference_version",
        ),
    )


class PreferenceActivePointer(Base):
    """Active Pointer：每个 domain+object_key 只有一个 active 偏好值"""

    __tablename__ = "user_preference_active"

    tenant_id = Column(String(64), primary_key=True)
    user_id = Column(String(128), primary_key=True)
    domain = Column(String(64), primary_key=True)
    object_key = Column(String(256), primary_key=True)
    fact_id = Column(String(36), nullable=False)
    lock_version = Column(Integer, nullable=False, default=0)


# ---- Repository ----

class PreferenceRepository:
    """偏好读写：confirmed/hypothesis 分离，inferred 不进入 confirmed 查询。"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_confirmed_preferences(
        self, tenant_id: str, user_id: str, domain: str | None = None,
    ) -> list[dict]:
        """只返回 evidence_type='confirmed' 或 'explicit' 的 active 偏好。

        inferred 级别不进入此查询——只能用于内部弱排序。
        """
        from sqlalchemy import select

        async with self.session_factory() as session:
            stmt = select(PreferenceActivePointer).where(
                PreferenceActivePointer.tenant_id == tenant_id,
                PreferenceActivePointer.user_id == user_id,
            )
            if domain:
                stmt = stmt.where(PreferenceActivePointer.domain == domain)

            result = await session.execute(stmt)
            pointers = {f"{p.domain}:{p.object_key}": p.fact_id
                        for p in result.scalars().all()}

            if not pointers:
                return []

            stmt2 = select(UserPreferenceFact).where(
                UserPreferenceFact.id.in_(pointers.values()),
                UserPreferenceFact.status == "active",
                UserPreferenceFact.evidence_type.in_(["explicit", "confirmed"]),
            )
            result2 = await session.execute(stmt2)
            return [
                {
                    "domain": f.domain,
                    "object_key": f.object_key,
                    "polarity": f.polarity,
                    "strength": f.strength,
                    "evidence_type": f.evidence_type,
                    "source_turn_id": f.source_turn_id,
                    "source_span": f.source_span,
                }
                for f in result2.scalars().all()
            ]

    async def get_hypotheses(
        self, tenant_id: str, user_id: str, domain: str | None = None,
    ) -> list[dict]:
        """返回 inferred 级别的偏好（仅供内部弱排序，不进入生成断言）。"""
        from sqlalchemy import select

        async with self.session_factory() as session:
            stmt = select(UserPreferenceFact).where(
                UserPreferenceFact.tenant_id == tenant_id,
                UserPreferenceFact.user_id == user_id,
                UserPreferenceFact.status == "active",
                UserPreferenceFact.evidence_type == "inferred",
            )
            if domain:
                stmt = stmt.where(UserPreferenceFact.domain == domain)

            result = await session.execute(stmt)
            return [
                {
                    "domain": f.domain,
                    "object_key": f.object_key,
                    "polarity": f.polarity,
                    "strength": f.strength,
                    "evidence_type": f.evidence_type,
                }
                for f in result.scalars().all()
            ]

    async def write_preference(
        self,
        tenant_id: str,
        user_id: str,
        domain: str,
        object_key: str,
        polarity: str,
        strength: str,
        evidence_type: str,
        source_turn_id: str,
        source_span: str,
        confidence: float = 1.0,
    ) -> str:
        """原子写入偏好事实：同一 domain+object_key 的新写入替代旧值。

        强度校验：'不讨厌'/'可以吃' 等弱表述不能升级为 'like'+'strong'。
        """
        from sqlalchemy import select, update

        # 强度校验
        if strength in ("strong", "favorite") and source_span.strip() in WEAK_TO_STRENGTH:
            actual_strength = WEAK_TO_STRENGTH[source_span.strip()]
            logger.warning(
                "Preference strength clamped: span='%s' strength %s→%s",
                source_span[:50], strength, actual_strength,
            )
            strength = actual_strength

        fact_id = str(uuid4())
        now = datetime.now(timezone.utc)

        async with self.session_factory() as session:
            async with session.begin():
                # 锁 active pointer
                stmt = select(PreferenceActivePointer).where(
                    PreferenceActivePointer.tenant_id == tenant_id,
                    PreferenceActivePointer.user_id == user_id,
                    PreferenceActivePointer.domain == domain,
                    PreferenceActivePointer.object_key == object_key,
                ).with_for_update()
                result = await session.execute(stmt)
                pointer = result.scalars().first()

                if pointer:
                    # 旧 fact → superseded
                    stmt_up = (
                        update(UserPreferenceFact)
                        .where(UserPreferenceFact.id == pointer.fact_id)
                        .values(status="superseded")
                    )
                    await session.execute(stmt_up)

                # 插新 fact
                new_fact = UserPreferenceFact(
                    id=fact_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    domain=domain,
                    object_key=object_key,
                    polarity=polarity,
                    strength=strength,
                    evidence_type=evidence_type,
                    status="active",
                    source_turn_id=source_turn_id,
                    source_span=source_span,
                    confidence=confidence,
                    version=(pointer.lock_version + 1) if pointer else 1,
                )
                session.add(new_fact)

                # 更新或插入 pointer
                if pointer:
                    pointer.fact_id = fact_id
                    pointer.lock_version += 1
                else:
                    session.add(PreferenceActivePointer(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        domain=domain,
                        object_key=object_key,
                        fact_id=fact_id,
                        lock_version=1,
                    ))

        logger.info(
            "Preference write: domain=%s key=%s polarity=%s strength=%s type=%s",
            domain, object_key, polarity, strength, evidence_type,
        )
        return fact_id


def create_engine_and_tables(database_url: str):
    """幂等建表（checkfirst=True），供 facade bootstrap 调用。"""
    engine = create_engine(database_url, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(engine, checkfirst=True)
    return engine
