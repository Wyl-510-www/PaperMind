"""PolicyCompiler: MySQL 直查编译 PolicyPack。

不经过 Qdrant 向量召回，直接查 MySQL 获取所有 active policy。
"""

from __future__ import annotations

import logging
from datetime import datetime

from .models import PolicyKind, PolicyPack, PolicyRule, PolicyStrength

logger = logging.getLogger(__name__)


class PolicyCompiler:
    """编译 PolicyPack：MySQL 直查，不依赖 Qdrant"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory

    async def compile(self, tenant_id: str, user_id: str, now: datetime | None = None) -> PolicyPack:
        """编译当前 scope 下的所有 active Behavior Policy。

        Returns:
            PolicyPack: 按 priority 降序排列的 active rules（hard rules 优先）
        """
        now = now or datetime.now().astimezone()

        if self._session_factory is None:
            return PolicyPack(scope=f"{tenant_id}:{user_id}")

        try:
            from server.memory_v2.models import MemoryRecord

            with self._session_factory() as session:
                rows = (
                    session.query(MemoryRecord)
                    .filter(
                        MemoryRecord.tenant_id == tenant_id,
                        MemoryRecord.user_id == user_id,
                        MemoryRecord.memory_type == "behavior_policy",
                        MemoryRecord.status == "active",
                    )
                    .order_by(MemoryRecord.created_at.desc())
                    .all()
                )

                rules = []
                for row in rows:
                    try:
                        rule = _record_to_rule(row)
                        if rule:
                            rules.append(rule)
                    except Exception:
                        logger.debug("Skip invalid policy record: %s", row.memory_id)
                        continue

                rules.sort(key=lambda r: r.priority, reverse=True)
                return PolicyPack(rules=rules, scope=f"{tenant_id}:{user_id}")
        except Exception:
            logger.warning("PolicyCompiler.compile 查询失败", exc_info=True)
            return PolicyPack(scope=f"{tenant_id}:{user_id}")

    def compile_sync(self, tenant_id: str, user_id: str) -> PolicyPack:
        """同步版本，用于测试"""
        return PolicyPack(scope=f"{tenant_id}:{user_id}")


def _record_to_rule(row) -> PolicyRule | None:
    """从 MemoryRecord 构建 PolicyRule"""
    try:
        value_data = row.value_json or {}
        policy_config = getattr(row, "policy_config", None) or {}

        return PolicyRule(
            policy_id=row.memory_id,
            kind=PolicyKind(policy_config.get("kind", "style")),
            strength=PolicyStrength(policy_config.get("strength", "soft")),
            priority=policy_config.get("priority", 0),
            instruction=row.text_zh or "",
            forbidden_terms=policy_config.get("forbidden_terms", []),
            required_terms_any=policy_config.get("required_terms_any", []),
            max_sentences=policy_config.get("max_sentences"),
            max_questions=policy_config.get("max_questions"),
            forbidden_question_patterns=policy_config.get("forbidden_question_patterns", []),
            source_memory_ids=[row.memory_id],
            valid_from=row.valid_from,
            valid_to=row.valid_to,
        )
    except Exception:
        return None
