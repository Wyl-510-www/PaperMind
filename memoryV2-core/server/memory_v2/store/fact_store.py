"""Semantic 事实写入。

router 的 SEMANTIC 路由调用 fact_store。把 WriteDecision 转成 fact_data，
通过 repository 做版本化写入。同一 fact_key 的新版本使旧版本 superseded。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..contracts import MemoryType, Scope, WriteDecision
from ..identity import build_subject_id_v2 as build_subject_id
from ..models import ActiveFact, MemoryRecord
from .repository import Repository


@dataclass
class _FactRow:
    """list_facts 返回的轻量行对象。"""
    object_id: str
    subject: str
    predicate: str
    object_value: object
    status: str
    created_at: object


class FactStore:
    """semantic 事实的版本化写入"""

    def __init__(self, session: Session):
        self.session = session
        self.repo = Repository(session)

    def list_facts(
        self,
        tenant_id: str,
        user_id: str,
        status: str = "active",
        namespace: str = "user_memory",
    ) -> list[_FactRow]:
        """列出用户当前活跃的事实快照（Bug #2 修复）。"""
        from ..models import ActiveFact, MemoryRecord

        rows = (
            self.session.query(MemoryRecord)
            .join(ActiveFact, ActiveFact.memory_id == MemoryRecord.memory_id)
            .filter(
                ActiveFact.tenant_id == tenant_id,
                ActiveFact.user_id == user_id,
                ActiveFact.namespace == namespace,
                MemoryRecord.status == status,
            )
            .all()
        )

        results = []
        for mem in rows:
            value_obj = None
            if isinstance(mem.value_json, dict):
                value_obj = mem.value_json.get("value")
            subject = mem.subject_id
            if isinstance(subject, str) and ":" in subject:
                subject = subject.split(":")[0]
            results.append(
                _FactRow(
                    object_id=mem.memory_id,
                    subject=subject or "user",
                    predicate=mem.predicate,
                    object_value=value_obj if value_obj else mem.text_zh,
                    status=mem.status,
                    created_at=mem.created_at,
                )
            )
        return results

    def write_fact(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        namespace: str = "user_memory",
        source_turn_id: str | None = None,
        occurred_at: datetime | None = None,
        is_update: bool = False,  # 新增：是否为更新操作
    ) -> str:
        """写入 semantic 事实。

        Args:
            decision: 门控决策，route 必须是 SEMANTIC，带 fact_key
            tenant_id/user_id/namespace: 隔离范围
            source_turn_id: 来源轮次
            occurred_at: 事件发生时间
            is_update: 是否为更新操作（由 Extractor 检测更新语义后传入）

        Returns:
            memory_id

        Raises:
            ValueError: route 不是 SEMANTIC 或缺 fact_key
        """
        import logging
        logger = logging.getLogger(__name__)

        if decision.route not in (MemoryType.SEMANTIC, MemoryType.BEHAVIOR_POLICY):
            raise ValueError(f"FactStore 只处理 SEMANTIC/BEHAVIOR_POLICY 路由，收到 {decision.route}")
        if not decision.fact_key:
            raise ValueError(f"{decision.route.value} 决策必须带 fact_key")

        candidate = decision.candidate
        memory_id = f"mem-{uuid.uuid4().hex[:16]}"
        is_policy = decision.route == MemoryType.BEHAVIOR_POLICY

        # P0-1 修复：使用统一的 build_subject_id 构造，不再各自拼接
        scope = Scope(tenant_id=tenant_id, user_id=user_id, namespace=namespace)
        subject_id = build_subject_id(
            canonical_name=candidate.subject.canonical_name,
            is_current_user=candidate.subject.is_current_user,
            entity_type=candidate.subject.kind if not candidate.subject.is_current_user else None,
            owner_user_id=user_id,
            tenant_id=tenant_id,
        )

        fact_data = {
            "memory_type": "behavior_policy" if is_policy else "semantic",
            "subject_id": subject_id,
            "predicate": candidate.predicate,
            "value_json": {"value": candidate.value},
            "text_zh": candidate.normalized_text_zh,
            "modality": candidate.modality.value,
            "confidence": candidate.confidence,
            "importance": candidate.importance,
            "valid_from": candidate.time.absolute_start,
            "valid_to": candidate.time.absolute_end,
            # Ticket 04: 偏好结构化字段
            "domain": getattr(candidate, "domain", None),
            "object_key": getattr(candidate, "object_key", None),
            "polarity": getattr(candidate, "polarity", None),
            "preference_strength": getattr(candidate, "preference_strength", None),
            "provenance": getattr(candidate, "provenance", None) or getattr(candidate, "evidence_type", None),
            # Fix2: observed_at — 消息发生的 UTC 时间（用于 scorer 的 recency 和冲突裁决）
            "occurred_at": occurred_at,
        }

        # === UPDATE 语义检查（B5 修复）===
        # 如果 Extractor 标记为 UPDATE，基于 fact_key 查找冲突记忆
        # B5 修复：改用 fact_key 进行冲突检测，自动支持 SET 型谓词的多值存储
        # - SET 型谓词（如 diet.like）：fact_key 包含 value hash，不同对象不冲突
        # - SINGLE 型谓词（如 nickname.current）：fact_key 仅含 subject+predicate，新值覆盖旧值
        if is_update:
            conflict = self.find_conflicting_memory_by_fact_key(
                tenant_id=tenant_id,
                user_id=user_id,
                fact_key=decision.fact_key,
                namespace=namespace,
            )

            if conflict:
                logger.info(
                    "检测到 UPDATE 操作: 旧记忆=%s (%s), 新值=%s, fact_key=%s",
                    conflict.memory_id,
                    conflict.value_json.get("value") if conflict.value_json else conflict.text_zh,
                    candidate.value,
                    decision.fact_key,
                )
                # 执行 UPDATE 逻辑（软删除旧记忆 + 创建新记忆）
                return self.update_memory(
                    old_memory_id=conflict.memory_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    namespace=namespace,
                    new_fact_data=fact_data,
                    new_fact_key=decision.fact_key,
                    source_turn_id=source_turn_id,
                    candidate_id=candidate.candidate_id,
                )
            else:
                logger.info(
                    "标记为 UPDATE 但未找到冲突记忆，降级为 ADD: fact_key=%s",
                    decision.fact_key,
                )

        # === 原有 ADD 逻辑 ===
        # 修复：behavior_policy 也需要写入 outbox，否则无法索引到 Qdrant
        returned_id = self.repo.write_fact_version(
            memory_id=memory_id,
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            fact_key=decision.fact_key,
            fact_data=fact_data,
            source_turn_id=source_turn_id,
            candidate_id=candidate.candidate_id,
            skip_outbox=False,  # 修复：改为 False，让 behavior_policy 也能索引
        )
        # 幂等预检命中：返回既有 memory_id，无需再写
        if returned_id != memory_id:
            return returned_id

        try:
            self.repo.commit()
        except IntegrityError:
            # P0-2 并发：另一事务已抢先写入相同幂等键 → 回滚，查既有返回
            self.repo.rollback()
            existing = self.session.query(MemoryRecord).filter_by(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
                source_turn_id=source_turn_id,
                candidate_id=candidate.candidate_id,
            ).first()
            if existing is not None:
                return existing.memory_id
            raise
        return memory_id

    def get_active_fact(
        self,
        tenant_id: str,
        user_id: str,
        fact_key: str,
        namespace: str = "user_memory",
    ) -> MemoryRecord | None:
        """查询某 fact_key 的当前有效版本"""
        active = self.session.query(ActiveFact).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            fact_key=fact_key,
        ).first()
        if not active:
            return None
        return self.session.query(MemoryRecord).filter_by(
            memory_id=active.memory_id
        ).first()

    def find_conflicting_memory_by_fact_key(
        self,
        tenant_id: str,
        user_id: str,
        fact_key: str,
        namespace: str = "user_memory",
    ) -> MemoryRecord | None:
        """基于 fact_key 查找冲突记忆（B5 修复）

        B5 修复：使用 fact_key 进行冲突检测，自动支持 SET 型谓词的多值存储
        - SET 型谓词（如 diet.like）：fact_key 包含 value hash (如 "用户:diet.like:3a7bd3e2")
          不同对象有不同 hash，不会误判为冲突，实现多值共存
        - SINGLE 型谓词（如 nickname.current）：fact_key 仅含 subject+predicate (如 "用户:nickname.current")
          相同 fact_key 触发 UPDATE，新值覆盖旧值

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            fact_key: 事实键（由 build_fact_key() 生成）
            namespace: 命名空间

        Returns:
            冲突的记忆对象，如果没有冲突返回 None

        Example:
            # SET 型谓词：不同对象不冲突
            conflict1 = store.find_conflicting_memory_by_fact_key(
                tenant_id="benchmark",
                user_id="user_001",
                fact_key="用户:diet.like:abc123",  # "苹果" 的 hash
            )  # 返回 "苹果" 的旧版本（如有）

            conflict2 = store.find_conflicting_memory_by_fact_key(
                tenant_id="benchmark",
                user_id="user_001",
                fact_key="用户:diet.like:def456",  # "橙子" 的 hash
            )  # 返回 "橙子" 的旧版本（如有），与 "苹果" 无关

            # SINGLE 型谓词：新值覆盖旧值
            conflict3 = store.find_conflicting_memory_by_fact_key(
                tenant_id="benchmark",
                user_id="user_001",
                fact_key="用户:nickname.current",
            )  # 返回当前昵称，将被新昵称替换
        """
        import logging
        logger = logging.getLogger(__name__)

        # 通过 ActiveFact 查找当前活跃的记忆
        active = self.session.query(ActiveFact).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            fact_key=fact_key,
        ).first()

        if not active:
            return None

        # 获取完整的 MemoryRecord
        memory = self.session.query(MemoryRecord).filter_by(
            memory_id=active.memory_id,
            status="active",
        ).first()

        if memory:
            logger.info(
                "发现冲突记忆（基于 fact_key）: memory_id=%s, fact_key=%s, value=%s",
                memory.memory_id,
                fact_key,
                memory.value_json.get("value") if memory.value_json else memory.text_zh,
            )

        return memory

    def find_conflicting_memory(
        self,
        tenant_id: str,
        user_id: str,
        subject_id: str,
        predicate: str,
        namespace: str = "user_memory",
    ) -> MemoryRecord | None:
        """查找冲突记忆：相同 user + subject + predicate 的活跃记忆

        ⚠️ DEPRECATED: B5 修复后，推荐使用 find_conflicting_memory_by_fact_key()

        该方法基于 subject_id + predicate 进行冲突检测，对 SET 型谓词会误判冲突。
        例如："喜欢吃苹果" 和 "喜欢吃橙子" 会被误判为冲突，导致后者覆盖前者。

        保留该方法仅用于向后兼容，新代码应使用 find_conflicting_memory_by_fact_key()。

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            subject_id: 主语 ID（如 "benchmark:user_001:我"）
            predicate: 谓语（如 "喜欢吃"）
            namespace: 命名空间

        Returns:
            冲突的记忆对象，如果没有冲突返回 None

        Example:
            # ⚠️ 错误用法：会导致 SET 型谓词的多值被覆盖
            conflict = store.find_conflicting_memory(
                tenant_id="benchmark",
                user_id="user_001",
                subject_id="benchmark:user_001:我",
                predicate="diet.like"  # SET 型谓词
            )
            # 如果找到 "苹果"，写入 "橙子" 会覆盖 "苹果"（错误行为）
        """
        import logging
        logger = logging.getLogger(__name__)

        conflict = (
            self.session.query(MemoryRecord)
            .join(ActiveFact, ActiveFact.memory_id == MemoryRecord.memory_id)
            .filter(
                ActiveFact.tenant_id == tenant_id,
                ActiveFact.user_id == user_id,
                ActiveFact.namespace == namespace,
                MemoryRecord.subject_id == subject_id,
                MemoryRecord.predicate == predicate,
                MemoryRecord.status == "active",
            )
            .first()
        )

        if conflict:
            logger.info(
                "发现冲突记忆: memory_id=%s, subject=%s, predicate=%s, object=%s",
                conflict.memory_id,
                subject_id,
                predicate,
                conflict.value_json.get("value") if conflict.value_json else conflict.text_zh,
            )

        return conflict

    def update_memory(
        self,
        old_memory_id: str,
        tenant_id: str,
        user_id: str,
        namespace: str,
        new_fact_data: dict,
        new_fact_key: str,
        source_turn_id: str | None = None,
        candidate_id: str | None = None,
    ) -> str:
        """更新记忆：软删除旧记忆 + 创建新记忆

        UPDATE 操作的核心实现。遵循 P0-2 修复的 Outbox 模式：
        1. 软删除旧记忆（标记 status=superseded）
        2. 删除 ActiveFact 指针
        3. 写入 Outbox delete 事件（触发 Qdrant 删除）
        4. 创建新记忆
        5. 写入 Outbox create 事件（触发 Qdrant 添加）
        6. 事务提交

        Args:
            old_memory_id: 要被替换的旧记忆 ID
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            new_fact_data: 新记忆的数据（包含 subject_id, predicate, value_json 等）
            new_fact_key: 新记忆的 fact_key
            source_turn_id: 来源轮次
            candidate_id: 候选 ID（幂等键）

        Returns:
            新记忆的 memory_id

        Raises:
            Exception: 数据库操作失败时抛出

        Example:
            # 更新"喜欢吃苹果"为"喜欢吃橙子"
            new_id = store.update_memory(
                old_memory_id="mem-abc123",
                tenant_id="benchmark",
                user_id="user_001",
                namespace="user_memory",
                new_fact_data={
                    "memory_type": "semantic",
                    "subject_id": "benchmark:user_001:我",
                    "predicate": "喜欢吃",
                    "value_json": {"value": "橙子"},
                    "text_zh": "我喜欢吃橙子",
                    ...
                },
                new_fact_key="user:我|喜欢吃",
                source_turn_id="turn_456"
            )
        """
        import logging
        from datetime import datetime, timezone
        from sqlalchemy import update, delete as sql_delete

        logger = logging.getLogger(__name__)

        try:
            new_memory_id = f"mem-{uuid.uuid4().hex[:16]}"

            # === 阶段 1：软删除旧记忆（参考 P0-2 delete_memory） ===
            logger.info("开始 UPDATE 操作: 旧记忆=%s, 新记忆=%s", old_memory_id, new_memory_id)

            # 1.1 更新旧记忆状态为 superseded
            stmt = (
                update(MemoryRecord)
                .where(
                    MemoryRecord.memory_id == old_memory_id,
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.user_id == user_id,
                    MemoryRecord.status == "active",
                )
                .values(
                    status="superseded",
                    supersedes_id=new_memory_id,  # 记录被哪条新记忆替代
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = self.session.execute(stmt)

            if result.rowcount == 0:
                logger.warning("未找到需要更新的旧记忆: memory_id=%s", old_memory_id)
                # 旧记忆不存在，降级为普通创建
                return self._create_new_memory(
                    new_memory_id, tenant_id, user_id, namespace,
                    new_fact_data, new_fact_key, source_turn_id, candidate_id
                )

            # 1.2 删除 ActiveFact 指针
            delete_stmt = sql_delete(ActiveFact).where(
                ActiveFact.memory_id == old_memory_id,
                ActiveFact.tenant_id == tenant_id,
                ActiveFact.user_id == user_id,
            )
            self.session.execute(delete_stmt)

            # 1.3 写入 Outbox delete 事件（触发 Qdrant 删除旧向量）
            self.repo._write_outbox(
                aggregate_id=old_memory_id,
                operation="delete",
                payload={
                    "memory_id": old_memory_id,
                    "reason": "superseded",
                    "superseded_by": new_memory_id,
                },
            )

            # === 阶段 2：创建新记忆 ===
            # 添加 supersedes_id 到新记忆数据中（记录替代了哪条旧记忆）
            new_fact_data["supersedes_id"] = old_memory_id

            # 调用内部方法创建新记忆
            self._create_new_memory(
                new_memory_id, tenant_id, user_id, namespace,
                new_fact_data, new_fact_key, source_turn_id, candidate_id
            )

            # === 阶段 3：事务提交 ===
            self.repo.commit()
            logger.info(
                "UPDATE 操作成功: 旧记忆=%s (superseded), 新记忆=%s (active)",
                old_memory_id,
                new_memory_id,
            )
            return new_memory_id

        except Exception:
            logger.exception("update_memory 失败: old_memory_id=%s", old_memory_id)
            self.repo.rollback()
            raise

    def _create_new_memory(
        self,
        memory_id: str,
        tenant_id: str,
        user_id: str,
        namespace: str,
        fact_data: dict,
        fact_key: str,
        source_turn_id: str | None,
        candidate_id: str | None,
    ) -> str:
        """内部方法：创建新记忆（复用 repository 的 write_fact_version）

        从 update_memory 和 write_fact 中提取的公共逻辑。
        """
        # 使用 repository 的版本化写入逻辑
        returned_id = self.repo.write_fact_version(
            memory_id=memory_id,
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            fact_key=fact_key,
            fact_data=fact_data,
            source_turn_id=source_turn_id,
            candidate_id=candidate_id,
            skip_outbox=False,
        )
        return returned_id

    def delete_memory(
        self,
        tenant_id: str,
        user_id: str,
        memory_id: str,
    ) -> bool:
        """删除指定记忆（软删除 MemoryRecord + 清理 ActiveFact + 写 Outbox）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            memory_id: 记忆 ID

        Returns:
            True 删除成功，False 记录不存在或已删除

        Raises:
            Exception: 数据库操作失败时抛出
        """
        import logging
        from datetime import datetime, timezone
        from sqlalchemy import update, delete as sql_delete
        from ..models import ActiveFact, MemoryRecord

        logger = logging.getLogger(__name__)

        try:
            # 1. 软删除 MemoryRecord（带行锁，防并发重复删除）
            stmt = (
                update(MemoryRecord)
                .where(
                    MemoryRecord.memory_id == memory_id,
                    MemoryRecord.tenant_id == tenant_id,
                    MemoryRecord.user_id == user_id,
                    MemoryRecord.status == "active",
                )
                .values(
                    status="deleted",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            result = self.session.execute(stmt)

            if result.rowcount == 0:
                logger.warning("未找到需要删除的记忆: memory_id=%s", memory_id)
                return False

            # 2. 删除 ActiveFact 指针
            delete_stmt = sql_delete(ActiveFact).where(
                ActiveFact.memory_id == memory_id,
                ActiveFact.tenant_id == tenant_id,
                ActiveFact.user_id == user_id,
            )
            self.session.execute(delete_stmt)

            # 3. 写入 Outbox（触发索引删除）- 复用 Repository 标准方法
            # P0-2 修复：使用正确的 aggregate_id/payload_json 字段
            self.repo._write_outbox(
                aggregate_id=memory_id,
                operation="delete",
                payload={"memory_id": memory_id},
            )

            # 4. 提交事务
            self.repo.commit()
            logger.info("删除成功: memory_id=%s", memory_id)
            return True

        except Exception:
            logger.exception("delete_memory 失败: memory_id=%s", memory_id)
            self.repo.rollback()
            raise
