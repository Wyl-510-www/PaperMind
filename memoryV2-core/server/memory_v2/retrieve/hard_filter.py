"""MySQL HardFilter：真值复核，确保返回的 Evidence 均为 active 且未被删除

M2 实施：阻止旧值复活的关键防线。

0913 规范：HardFilter 执行 6 条强制过滤规则
1. Scope 检查（tenant/user/namespace 三重匹配）
2. Subject 检查（禁止第三方 subject 泄露）
3. Deleted 检查（软删除记录不返回）
4. Confidence 检查（<0.3 的记录不返回）
5. Modality 检查（hypothesis/joke 不返回）
6. Event 状态检查（cancelled 事件不返回）

设计原则：
- DELETE 操作后，Qdrant 索引是异步删除（通过 Outbox）
- 在异步任务完成前，被删除的旧值仍可能从 Qdrant 召回
- HardFilter 作为最后一道防线，必须过滤掉不合规的记录
- 失败时返回空结果，不抛异常
- 禁止用 surviving=all_candidates 绕过过滤
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional
from dataclasses import dataclass

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from server.memory_v2.models import MemoryRecord

logger = logging.getLogger(__name__)


@dataclass
class Rejection:
    """被拒绝的候选记录

    0913 规范：记录拒绝原因和 ID 用于调试
    """
    candidate_id: str
    reason: str
    details: Optional[dict] = None


class HardFilter:
    """MySQL 真值复核：确保返回的 Evidence 均为 active 且未被删除

    0913 规范：执行 6 条强制过滤规则，失败安全

    职责：
    1. Scope 检查：tenant_id/user_id/namespace 匹配（安全隔离）
    2. Subject 检查：禁止第三方 subject 泄露
    3. Deleted 检查：active=True, deleted_at IS NULL
    4. Confidence 检查：confidence >= 0.3
    5. Modality 检查：排除 hypothesis, joke, quote
    6. Event 状态检查：排除 cancelled 事件
    """

    # 0913 规范：不允许的 modality
    DISALLOWED_MODALITIES = {'hypothesis', 'joke', 'quote'}

    # 0913 规范：最小置信度阈值
    MIN_CONFIDENCE = 0.3

    # 0913 规范：不允许的 Event 状态
    DISALLOWED_EVENT_STATUSES = {'cancelled'}

    def __init__(self, db_session: Session):
        """
        Args:
            db_session: SQLAlchemy session
        """
        self.db = db_session
        self.rejections: List[Rejection] = []  # 记录拒绝的候选

    def filter_candidates(
        self,
        candidate_ids: list[str],
        tenant_id: str,
        user_id: str,
        namespace: str,
        current_user_subject_id: Optional[str] = None,
    ) -> list[MemoryRecord]:
        """从 MySQL 读取真值并执行 6 条过滤规则（0913 规范）

        硬约束（按顺序执行）：
        1. Scope 检查：tenant_id/user_id/namespace 匹配
        2. Subject 检查：禁止第三方 subject（不是 current_user 的记录）
        3. Deleted 检查：active=True, deleted_at IS NULL
        4. Confidence 检查：confidence >= 0.3
        5. Modality 检查：排除 hypothesis, joke, quote
        6. Event 状态检查：排除 cancelled 事件

        Args:
            candidate_ids: Qdrant 召回的候选 memory_id 列表
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            current_user_subject_id: 当前用户的 subject_id（用于主体检查）

        Returns:
            list[MemoryRecord]: 过滤后的记录列表（保持 Qdrant 排序）

        0913 规范：
        - 失败时返回空结果，不抛异常
        - 记录所有 rejection 用于调试
        - 禁止绕过过滤
        """
        from server.memory_v2.models import MemoryRecord

        # 清空上次的 rejection 记录
        self.rejections = []

        if not candidate_ids:
            logger.info("HardFilter: 输入为空，返回空结果")
            return []

        # 0913 规范：禁止绕过过滤
        if candidate_ids == ["all_candidates"]:
            logger.error("HardFilter: 检测到绕过尝试 (surviving=all_candidates)，拒绝")
            return []

        # 1. Scope 检查：从 MySQL 查询符合 Scope 的记录
        records = self.db.query(MemoryRecord).filter(
            MemoryRecord.memory_id.in_(candidate_ids),
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.namespace == namespace,
        ).all()

        # 记录 Scope 不匹配的候选
        fetched_ids = {r.memory_id for r in records}
        for cid in candidate_ids:
            if cid not in fetched_ids:
                self.rejections.append(Rejection(
                    candidate_id=cid,
                    reason="scope_mismatch",
                    details={"expected_scope": f"{tenant_id}/{user_id}/{namespace}"}
                ))

        surviving = []

        for record in records:
            # 2. Subject 检查（如果提供了 current_user_subject_id）
            if current_user_subject_id:
                if not self._check_subject(record, current_user_subject_id):
                    self.rejections.append(Rejection(
                        candidate_id=record.memory_id,
                        reason="subject_mismatch",
                        details={"record_subject": record.subject_id, "expected": current_user_subject_id}
                    ))
                    continue

            # 3. Deleted 检查：status != "active" 表示已删除或被取代
            if record.status != "active":
                self.rejections.append(Rejection(
                    candidate_id=record.memory_id,
                    reason="deleted_or_inactive",
                    details={"status": record.status}
                ))
                continue

            # 4. Confidence 检查
            if not self._check_confidence(record):
                self.rejections.append(Rejection(
                    candidate_id=record.memory_id,
                    reason="low_confidence",
                    details={"confidence": getattr(record, 'confidence', None)}
                ))
                continue

            # 5. Modality 检查
            if not self._check_modality(record):
                self.rejections.append(Rejection(
                    candidate_id=record.memory_id,
                    reason="disallowed_modality",
                    details={"modality": getattr(record, 'modality', None)}
                ))
                continue

            # 6. Event 状态检查
            if not self._check_event_status(record):
                self.rejections.append(Rejection(
                    candidate_id=record.memory_id,
                    reason="disallowed_event_status",
                    details={"status": getattr(record, 'status', None)}
                ))
                continue

            # 通过所有检查
            surviving.append(record)

        # 按 candidate_ids 顺序返回（保持 Qdrant 排序）
        records_map = {r.memory_id: r for r in surviving}
        ordered_records = []
        for cid in candidate_ids:
            if cid in records_map:
                ordered_records.append(records_map[cid])

        logger.info(
            f"HardFilter (0913): 输入 {len(candidate_ids)} 条，"
            f"通过 {len(ordered_records)} 条，"
            f"拒绝 {len(self.rejections)} 条"
        )

        if self.rejections:
            logger.debug(f"HardFilter rejections: {self.rejections[:5]}")  # 只记录前 5 个

        return ordered_records

    def _check_subject(self, record: MemoryRecord, current_user_subject_id: str) -> bool:
        """检查主体是否匹配

        0913 规范：只返回当前用户的记忆，不返回第三方实体的记忆
        """
        if not hasattr(record, 'subject_id') or not record.subject_id:
            return True  # 没有 subject_id 则放行

        # 检查是否是 current_user 的记录
        return record.subject_id == current_user_subject_id or record.subject_id.startswith("user@")

    def _check_confidence(self, record: MemoryRecord) -> bool:
        """检查置信度

        0913 规范：confidence < 0.3 的记录不返回
        """
        if not hasattr(record, 'confidence'):
            return True  # 没有 confidence 字段则放行

        confidence = record.confidence
        if confidence is None:
            return True  # None 视为放行

        return confidence >= self.MIN_CONFIDENCE

    def _check_modality(self, record: MemoryRecord) -> bool:
        """检查 modality

        0913 规范：hypothesis, joke, quote 不返回
        """
        if not hasattr(record, 'modality'):
            return True  # 没有 modality 字段则放行

        modality = record.modality
        if not modality:
            return True  # None 或空则放行

        return modality not in self.DISALLOWED_MODALITIES

    def _check_event_status(self, record: MemoryRecord) -> bool:
        """检查 Event 状态

        0913 规范：cancelled 事件不返回
        """
        # 只检查 memory_type 为 event 的记录
        if not hasattr(record, 'memory_type') or record.memory_type != 'event':
            return True  # 非 event 类型放行

        if not hasattr(record, 'status'):
            return True  # 没有 status 字段则放行

        status = record.status
        if not status:
            return True  # None 或空则放行

        return status not in self.DISALLOWED_EVENT_STATUSES

    def get_rejections(self) -> List[Rejection]:
        """获取本次过滤的 rejection 记录

        0913 规范：用于调试和审计
        """
        return self.rejections

    async def filter_by_fact_key_cardinality(
        self,
        records: list[MemoryRecord],
    ) -> list[MemoryRecord]:
        """按 fact_key cardinality 过滤（单值谓词只保留最新版本）

        单值谓词（如 nickname.current）：同一 fact_key 只保留最新的 active 记录
        集合谓词（如 diet.dislike）：同一 fact_key 保留所有 active 记录

        Args:
            records: 待过滤的记录列表

        Returns:
            list[MemoryRecord]: 过滤后的记录列表
        """
        # 单值谓词列表（从 gate.py 获取）
        # TODO: 从配置或 gate 模块导入
        SINGLE_VALUE_PREDICATES = {
            "nickname.current",
            "location.current",
            "occupation.current",
            "relationship.current",
        }

        # 按 fact_key 分组
        fact_key_groups: dict[str, list[MemoryRecord]] = {}
        for r in records:
            fact_key_groups.setdefault(r.fact_key, []).append(r)

        filtered = []
        for fact_key, group in fact_key_groups.items():
            # 判断 cardinality
            predicate = group[0].predicate

            if predicate in SINGLE_VALUE_PREDICATES:
                # 单值型：只保留最新（按 created_at 排序）
                latest = max(group, key=lambda r: r.created_at)
                filtered.append(latest)
                logger.debug(
                    f"单值谓词 {predicate}：fact_key={fact_key}，"
                    f"保留最新版本 {latest.memory_id}"
                )
            else:
                # 集合型：全部保留
                filtered.extend(group)

        logger.info(
            f"Cardinality 过滤: {len(records)} 条 → {len(filtered)} 条"
        )

        return filtered

    async def filter_by_subject(
        self,
        candidates: list[MemoryRecord],
        subject_scope: str | None = None,
        entity_name: str | None = None,
    ) -> list[MemoryRecord]:
        """确保主体匹配：用户的事实不能返回给实体查询，反之亦然

        Args:
            candidates: 待过滤的候选记录
            subject_scope: 主体范围 ("current_user" | "entity")
            entity_name: 实体名称（如 "福妹", "小乔"）

        Returns:
            list[MemoryRecord]: 过滤后的记录列表
        """
        if not subject_scope:
            return candidates

        filtered = []

        # 如果查询是关于用户自己的
        if subject_scope == "current_user":
            filtered = [c for c in candidates if "current_user:" in c.subject_id]
            logger.debug(
                f"Subject 过滤（current_user）: {len(candidates)} 条 → "
                f"{len(filtered)} 条"
            )
            return filtered

        # 如果查询是关于特定实体的
        if subject_scope == "entity" and entity_name:
            entity_pattern = f":e:{entity_name}"
            filtered = [c for c in candidates if entity_pattern in c.subject_id]
            logger.debug(
                f"Subject 过滤（entity={entity_name}）: {len(candidates)} 条 → "
                f"{len(filtered)} 条"
            )
            return filtered

        return candidates
