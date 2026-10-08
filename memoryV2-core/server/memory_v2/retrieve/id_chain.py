"""
ID 漏斗追踪 - M3 批次

功能：
1. 追踪完整的 ID 链：aggregate_id → truth_id → outbox_id → qdrant_point_id → evidence_id
2. 明确写入成功但无 Evidence 时，停在哪一层（outbox pending / index lag / retrieval miss）
3. 为 Benchmark 测试提供清晰的可观测性

问题：
- 01 报告：48 个 Anchor 有提交，仅 36 个 Probe 有 Evidence
- ID 链断裂，无法追踪哪一环出问题

解决方案：
- 记录每个阶段的 ID 转换
- 提供完整的 Trace 信息
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from enum import Enum


class IDChainStatus(str, Enum):
    """ID 链状态"""
    FULL_CHAIN = "full_chain"  # 完整链路：写入 → 索引 → 检索成功
    MISSING_OUTBOX = "missing_outbox"  # 写入成功，但未写 Outbox
    MISSING_INDEX = "missing_index"  # Outbox 写入，但未同步到 Qdrant
    MISSING_EVIDENCE = "missing_evidence"  # Qdrant 有，但检索未召回
    TRUTH_NOT_FOUND = "truth_not_found"  # Truth 记录丢失（严重错误）


class IDChain(BaseModel):
    """单个 memory 的完整 ID 链"""

    # 各阶段 ID
    aggregate_id: str  # 写入时的 aggregate ID（通常等于 truth_id）
    truth_id: str  # MemoryRecord.memory_id
    outbox_id: Optional[str] = None  # OutboxEvent.outbox_id
    qdrant_point_id: Optional[str] = None  # Qdrant point ID（通常等于 truth_id）
    evidence_id: Optional[str] = None  # Evidence 中的 memory_id

    # 状态
    status: IDChainStatus

    # 时间戳
    truth_created_at: Optional[datetime] = None
    outbox_created_at: Optional[datetime] = None
    indexed_at: Optional[datetime] = None
    retrieved_at: Optional[datetime] = None

    # 错误信息（如果有）
    error_message: Optional[str] = None


class RetrievalTrace(BaseModel):
    """检索漏斗 Trace"""

    # 查询信息
    query: str
    tenant_id: str
    user_id: str
    namespace: str

    # 漏斗各阶段
    qdrant_candidates: int  # Qdrant 返回数量
    qdrant_ids: list[str]  # memory_id 列表

    hard_filter_accepted: int  # HardFilter 过滤后剩余
    hard_filter_ids: list[str]

    reranked: int  # Rerank 后数量
    reranked_ids: list[str]

    final_evidence_count: int  # 最终 Evidence 数量
    final_evidence_ids: list[str]

    # 每个 memory_id 的完整链
    id_chains: dict[str, IDChain]

    # 统计信息
    full_chain_count: int = 0  # 完整链路数量
    missing_outbox_count: int = 0
    missing_index_count: int = 0
    missing_evidence_count: int = 0

    # 时间信息
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None


class IDChainBuilder:
    """构建 ID 链的工具类"""

    def __init__(self, db_session):
        self.db = db_session

    async def build_chain(
        self,
        memory_id: str,
        tenant_id: str,
        user_id: str,
        check_index: bool = True,
        check_evidence: bool = False,
        evidence_ids: Optional[list[str]] = None,
    ) -> IDChain:
        """构建单个 memory 的 ID 链

        Args:
            memory_id: 要追踪的 memory_id
            tenant_id: 租户 ID
            user_id: 用户 ID
            check_index: 是否检查 Qdrant 索引
            check_evidence: 是否检查是否在 Evidence 中
            evidence_ids: Evidence 的 memory_id 列表（用于检查）

        Returns:
            IDChain 对象
        """
        from server.memory_v2.store.models import MemoryRecord, OutboxEvent

        # 1. 查询 Truth
        truth = self.db.query(MemoryRecord).filter(
            MemoryRecord.memory_id == memory_id,
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
        ).first()

        if not truth:
            return IDChain(
                aggregate_id=memory_id,
                truth_id=memory_id,
                status=IDChainStatus.TRUTH_NOT_FOUND,
                error_message=f"Truth record not found for {memory_id}",
            )

        # 2. 查询 Outbox
        outbox = self.db.query(OutboxEvent).filter(
            OutboxEvent.aggregate_id == memory_id,
        ).order_by(OutboxEvent.created_at.desc()).first()

        outbox_id = outbox.outbox_id if outbox else None
        outbox_created_at = outbox.created_at if outbox else None

        # 3. 检查 Qdrant（如果需要）
        qdrant_point_id = None
        indexed_at = None
        if check_index and outbox:
            # TODO: 实际检查 Qdrant
            # 这里简化处理，假设 outbox 存在就代表已索引
            qdrant_point_id = memory_id
            indexed_at = outbox_created_at

        # 4. 检查 Evidence（如果需要）
        evidence_id = None
        retrieved_at = None
        if check_evidence and evidence_ids:
            if memory_id in evidence_ids:
                evidence_id = memory_id
                retrieved_at = datetime.utcnow()

        # 5. 判断状态
        status = self._determine_status(
            truth_id=truth.memory_id,
            outbox_id=outbox_id,
            qdrant_point_id=qdrant_point_id,
            evidence_id=evidence_id,
        )

        return IDChain(
            aggregate_id=truth.memory_id,
            truth_id=truth.memory_id,
            outbox_id=outbox_id,
            qdrant_point_id=qdrant_point_id,
            evidence_id=evidence_id,
            status=status,
            truth_created_at=truth.created_at,
            outbox_created_at=outbox_created_at,
            indexed_at=indexed_at,
            retrieved_at=retrieved_at,
        )

    def _determine_status(
        self,
        truth_id: str,
        outbox_id: Optional[str],
        qdrant_point_id: Optional[str],
        evidence_id: Optional[str],
    ) -> IDChainStatus:
        """判断 ID 链状态"""

        if not outbox_id:
            return IDChainStatus.MISSING_OUTBOX

        if not qdrant_point_id:
            return IDChainStatus.MISSING_INDEX

        if not evidence_id:
            return IDChainStatus.MISSING_EVIDENCE

        return IDChainStatus.FULL_CHAIN


class RetrievalTracer:
    """检索 Trace 构建器"""

    def __init__(self, db_session):
        self.db = db_session
        self.chain_builder = IDChainBuilder(db_session)

    async def trace_retrieval(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        namespace: str,
        qdrant_results: list,
        hard_filter_results: list,
        reranked_results: list,
        final_evidence: list,
    ) -> RetrievalTrace:
        """追踪完整的检索流程

        Args:
            query: 查询文本
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: 命名空间
            qdrant_results: Qdrant 检索结果（SearchResult 列表）
            hard_filter_results: HardFilter 过滤后结果（MemoryRecord 列表）
            reranked_results: Rerank 后结果
            final_evidence: 最终 Evidence

        Returns:
            RetrievalTrace 对象
        """
        started_at = datetime.utcnow()

        # 提取各阶段 ID
        qdrant_ids = [r.memory_id for r in qdrant_results]
        hard_filter_ids = [r.memory_id for r in hard_filter_results]
        reranked_ids = [r.memory_id for r in reranked_results]
        final_evidence_ids = [e.memory_id for e in final_evidence]

        # 构建 ID 链（针对 Qdrant 候选）
        id_chains = {}
        for memory_id in qdrant_ids:
            chain = await self.chain_builder.build_chain(
                memory_id=memory_id,
                tenant_id=tenant_id,
                user_id=user_id,
                check_index=True,
                check_evidence=True,
                evidence_ids=final_evidence_ids,
            )
            id_chains[memory_id] = chain

        # 统计各状态数量
        full_chain_count = sum(
            1 for c in id_chains.values()
            if c.status == IDChainStatus.FULL_CHAIN
        )
        missing_outbox_count = sum(
            1 for c in id_chains.values()
            if c.status == IDChainStatus.MISSING_OUTBOX
        )
        missing_index_count = sum(
            1 for c in id_chains.values()
            if c.status == IDChainStatus.MISSING_INDEX
        )
        missing_evidence_count = sum(
            1 for c in id_chains.values()
            if c.status == IDChainStatus.MISSING_EVIDENCE
        )

        completed_at = datetime.utcnow()
        duration_ms = (completed_at - started_at).total_seconds() * 1000

        return RetrievalTrace(
            query=query,
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            qdrant_candidates=len(qdrant_ids),
            qdrant_ids=qdrant_ids,
            hard_filter_accepted=len(hard_filter_ids),
            hard_filter_ids=hard_filter_ids,
            reranked=len(reranked_ids),
            reranked_ids=reranked_ids,
            final_evidence_count=len(final_evidence_ids),
            final_evidence_ids=final_evidence_ids,
            id_chains=id_chains,
            full_chain_count=full_chain_count,
            missing_outbox_count=missing_outbox_count,
            missing_index_count=missing_index_count,
            missing_evidence_count=missing_evidence_count,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
