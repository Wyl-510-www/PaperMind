"""
Truth Snapshot 独立获取 - M3 批次

功能：
1. Evidence 和 truth_snapshot 独立获取
2. Evidence 来自检索结果，truth_snapshot 独立查询 MySQL
3. 交叉验证：Evidence 的 ID 必须在 truth 中存在

问题：
- 01 报告 context.py:558-569：把 Evidence 当 truth_snapshot 并用其 ID 补 candidate_ids
- Evidence 和 truth 混淆导致 ID 链断裂

解决方案：
- 分离 Evidence 和 truth_snapshot 的获取逻辑
- MySQL 查询作为 truth 的唯一来源
"""

from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class EvidencePack(BaseModel):
    """证据包：Evidence + truth_snapshot 独立"""

    # Evidence（来自检索结果）
    evidence: list  # SearchResult 列表

    # Truth snapshot（来自 MySQL，真值的快照）
    truth_snapshot: dict[str, any]  # {memory_id: MemoryRecord}

    # Candidate IDs（来自 truth，不是 Evidence）
    candidate_ids: list[str]

    # 过滤信息
    filtered_ids: list[str]  # 被过滤掉的 ID
    filter_reasons: dict[str, str]  # {memory_id: reason}

    # Rerank 信息
    reranked_ids: list[str]

    # 统计信息
    evidence_count: int
    truth_count: int
    mismatch_count: int  # Evidence 有但 truth 没有的数量

    # Trace
    retrieval_trace: Optional[any] = None


class EvidenceAssembler:
    """M3 批次：Evidence 组装器"""

    def __init__(self, db_session):
        self.db = db_session

    async def assemble_evidence_pack(
        self,
        tenant_id: str,
        user_id: str,
        namespace: str,
        query: str,
        retrieval_results: list,  # SearchResult 列表
    ) -> EvidencePack:
        """组装证据包：Evidence 和 truth_snapshot 独立获取

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            query: 查询文本
            retrieval_results: 检索结果（SearchResult 列表）

        Returns:
            EvidencePack 对象

        核心逻辑：
        1. Evidence 直接来自检索结果
        2. Truth snapshot 独立查询 MySQL（唯一真值来源）
        3. 交叉验证：Evidence 的 ID 必须在 truth 中存在
        4. candidate_ids 来自 truth，不是 Evidence
        """
        from server.memory_v2.store.models import MemoryRecord
        import logging

        logger = logging.getLogger(__name__)

        # 1. Evidence 列表（来自检索）
        evidence_list = retrieval_results
        evidence_ids = [r.memory_id for r in evidence_list]

        # 2. Truth snapshot（独立查询 MySQL）
        # 这是真值的唯一来源
        truth_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.memory_id.in_(evidence_ids),
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.namespace == namespace,
            MemoryRecord.active == True,  # 只查询 active 记录
        ).all()

        truth_snapshot = {r.memory_id: r for r in truth_records}
        truth_ids = list(truth_snapshot.keys())

        # 3. 交叉验证：Evidence 的 ID 必须在 truth 中存在
        validated_evidence = []
        filtered_ids = []
        filter_reasons = {}

        for ev in evidence_list:
            if ev.memory_id in truth_snapshot:
                validated_evidence.append(ev)
            else:
                # Evidence 有但 truth 没有（索引延迟或脏数据）
                filtered_ids.append(ev.memory_id)
                filter_reasons[ev.memory_id] = "no_truth_record"
                logger.warning(
                    f"Evidence {ev.memory_id} 无对应 truth，已过滤 "
                    f"(tenant={tenant_id}, user={user_id}, namespace={namespace})"
                )

        # 4. 统计信息
        evidence_count = len(validated_evidence)
        truth_count = len(truth_snapshot)
        mismatch_count = len(filtered_ids)

        if mismatch_count > 0:
            logger.warning(
                f"Evidence 和 truth 不匹配：{mismatch_count} 条 Evidence 无对应 truth "
                f"(query={query[:50]}, tenant={tenant_id}, user={user_id})"
            )

        # 5. candidate_ids 来自 truth，不是 Evidence
        # 这是关键修复：context.py 之前用 Evidence ID 补 candidate_ids
        candidate_ids = truth_ids

        return EvidencePack(
            evidence=validated_evidence,
            truth_snapshot=truth_snapshot,
            candidate_ids=candidate_ids,
            filtered_ids=filtered_ids,
            filter_reasons=filter_reasons,
            reranked_ids=[],  # 待 rerank 模块填充
            evidence_count=evidence_count,
            truth_count=truth_count,
            mismatch_count=mismatch_count,
        )

    async def validate_truth_existence(
        self,
        memory_ids: list[str],
        tenant_id: str,
        user_id: str,
    ) -> dict[str, bool]:
        """验证一批 memory_id 在 truth 中是否存在

        Args:
            memory_ids: 要验证的 memory_id 列表
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            {memory_id: exists}
        """
        from server.memory_v2.store.models import MemoryRecord

        if not memory_ids:
            return {}

        truth_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.memory_id.in_(memory_ids),
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.active == True,
        ).all()

        existing_ids = {r.memory_id for r in truth_records}

        return {
            memory_id: (memory_id in existing_ids)
            for memory_id in memory_ids
        }

    async def get_truth_snapshot_by_ids(
        self,
        memory_ids: list[str],
        tenant_id: str,
        user_id: str,
    ) -> dict[str, any]:
        """根据 memory_ids 获取 truth snapshot

        Args:
            memory_ids: memory_id 列表
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            {memory_id: MemoryRecord}
        """
        from server.memory_v2.store.models import MemoryRecord

        if not memory_ids:
            return {}

        truth_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.memory_id.in_(memory_ids),
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.active == True,
        ).all()

        return {r.memory_id: r for r in truth_records}


class TruthSnapshotValidator:
    """Truth snapshot 验证器"""

    @staticmethod
    def validate_evidence_truth_consistency(
        evidence_pack: EvidencePack,
    ) -> dict:
        """验证 Evidence 和 truth 的一致性

        Returns:
            验证报告
        """
        report = {
            "consistent": True,
            "issues": [],
            "statistics": {
                "evidence_count": evidence_pack.evidence_count,
                "truth_count": evidence_pack.truth_count,
                "mismatch_count": evidence_pack.mismatch_count,
            },
        }

        # 检查不匹配
        if evidence_pack.mismatch_count > 0:
            report["consistent"] = False
            report["issues"].append({
                "type": "evidence_without_truth",
                "count": evidence_pack.mismatch_count,
                "memory_ids": evidence_pack.filtered_ids,
                "severity": "warning",
                "message": f"{evidence_pack.mismatch_count} 条 Evidence 无对应 truth 记录",
            })

        # 检查 candidate_ids 来源
        evidence_ids = {ev.memory_id for ev in evidence_pack.evidence}
        candidate_ids_set = set(evidence_pack.candidate_ids)

        if not candidate_ids_set.issubset(evidence_pack.truth_snapshot.keys()):
            report["consistent"] = False
            report["issues"].append({
                "type": "candidate_not_in_truth",
                "severity": "error",
                "message": "candidate_ids 包含不在 truth_snapshot 中的 ID",
            })

        # 检查是否所有 evidence 都有 truth
        for ev in evidence_pack.evidence:
            if ev.memory_id not in evidence_pack.truth_snapshot:
                report["consistent"] = False
                report["issues"].append({
                    "type": "evidence_missing_truth",
                    "memory_id": ev.memory_id,
                    "severity": "error",
                    "message": f"Evidence {ev.memory_id} 缺少 truth 记录",
                })

        return report
