"""Evidence Pipeline：检索与生成证据闭环的主编排（Seam 1）。

串起 4 步：
1. QueryRouter 判断本轮查什么类型
2. IndexV2 按 per_type_top_k 多路召回
3. HardFilter 排除不可用候选（读 MySQL 真值）
4. Scorer 打分裁剪产出 EvidenceItem
→ 组装 EvidencePack（items + active_events + generated_at）

全依赖注入：IndexV2 / session / reranker。
测试用 FakeIndex + 内存 SQLite + FakeReranker。
logger = logging.getLogger(__name__)

注意：DSM 当前状态与 Evidence Pack 是独立两路输入，不互相包含
（见 CONTEXT.md「Evidence Pack」词条）。本 pipeline 只组装 Evidence Pack，
DSM 状态由生成编排层单独获取，不经过此处。

这是 Phase 3 的主接缝，端到端可验证。
见 ADR 0005（模块命名）、ADR 0006（检索取向）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ..contracts import EvidencePack, Scope, SubjectRef
from .hard_filter import HardFilter
from ..identity import build_subject_id
from .query_router import QueryRouter
from .scorer import RerankerProtocol, Scorer
from server.memory_v2.tracing.context import get_or_create_retrieval_trace


# 默认检索参数（命名常量，可后续改为配置注入）
DEFAULT_TOKEN_BUDGET = 2000


class IndexProtocol(Protocol):
    """向量索引接口（Qdrant candidate_index）。"""

    def search(
        self,
        memory_type: str,
        query: str,
        top_k: int,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """按类型查询，返回候选 [{memory_id/event_id, score}, ...]

        Args:
            memory_type: 记忆类型
            query: 查询文本
            top_k: 返回候选数量
            tenant_id: 租户 ID（scope 过滤）
            user_id: 用户 ID（scope 过滤）
        """
        ...


class EvidencePipeline:
    """证据流水线（主接缝）。

    全依赖注入：index（Qdrant）、session（MySQL）、reranker。
    """

    def __init__(
        self,
        index: IndexProtocol,
        session: Session,
        reranker: RerankerProtocol,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ):
        self._index = index
        self._session = session
        self._reranker = reranker
        self._token_budget = token_budget

        self._query_router = QueryRouter()
        self._hard_filter = HardFilter(session)
        self._scorer = Scorer()

    def assemble(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        now: datetime,
    ) -> EvidencePack:
        """组装 EvidencePack：4 步编排 + 组装。"""
        user_id = str(user_id)  # 归一化：BigInteger 列存 int 但 Pydantic 模型要求 str
        
        # 获取追踪对象
        r_trace = get_or_create_retrieval_trace()
        
        # 1. QueryRouter 判断查什么
        plan = self._query_router.route(query)

        if plan.skip_retrieval:
            # 普通寒暄 → 返回空 pack
            return EvidencePack(query=query, items=[], generated_at=now)

        # 2. 临时绕过QueryRouter，搜索所有memory_type（待修复QueryRouter路由逻辑）
        # TODO: 恢复使用QueryRouter路由结果，当前为T7测试临时方案
        ALL_MEMORY_TYPES = ["semantic", "behavior_policy", "entity_relation"]
        all_candidates: list[dict[str, Any]] = []
        for memory_type in ALL_MEMORY_TYPES:
            top_k = 5  # 每种类型取5条候选
            # 传递 tenant_id 和 user_id 进行索引层预过滤
            candidates = self._index.search(
                memory_type,
                query,
                top_k,
                tenant_id=tenant_id,
                user_id=user_id
            )
            all_candidates.extend(candidates)

        # 记录检索候选 ID
        retrieval_candidate_ids = [
            c.get("memory_id") or c.get("event_id") for c in all_candidates
        ]
        r_trace.retrieval_candidate_ids = retrieval_candidate_ids

        # 3. HardFilter 排除不可用候选
        # 提取候选 ID 列表
        candidate_ids = [
            c.get("memory_id") or c.get("event_id")
            for c in all_candidates
            if c.get("memory_id") or c.get("event_id")
        ]

        # 调用 HardFilter 进行真值过滤（同步调用）
        filtered_records = self._hard_filter.filter_candidates(
            candidate_ids=candidate_ids,
            tenant_id=tenant_id,
            user_id=user_id,
            namespace="user_memory"
        )

        # 构建通过过滤的 ID 集合
        passed_ids = {r.memory_id for r in filtered_records}

        # 只保留通过过滤的候选
        surviving = [
            c for c in all_candidates
            if (c.get("memory_id") or c.get("event_id")) in passed_ids
        ]

        # 记录硬过滤接受的 ID
        hardfilter_accepted_ids = list(passed_ids)
        r_trace.hardfilter_accepted_ids = hardfilter_accepted_ids

        # 记录被拒绝的详细信息（使用 HardFilter.rejections）
        if self._hard_filter.rejections:
            r_trace.hardfilter_rejections = [
                {
                    "id": rej.candidate_id,
                    "reason": rej.reason,
                    "details": rej.details or {}
                }
                for rej in self._hard_filter.rejections
            ]

        # 4. 分流：事件候选单独成列（active_events），其余进 scorer
        event_candidates = [c for c in surviving if "event_id" in c]
        memory_candidates = [c for c in surviving if "event_id" not in c]

        items = self._scorer.score_and_trim(
            candidates=memory_candidates,
            query=query,
            token_budget=self._token_budget,
            reranker=self._reranker,
        )

        # 记录重排后的 ID
        reranked_ids = [item.memory_id for item in items]
        r_trace.reranked_ids = reranked_ids

        active_events = [self._to_active_event(c) for c in event_candidates]

        # 5. 组装 EvidencePack（不含 current_state，DSM 独立注入）
        pack = EvidencePack(
            query=query,
            items=items,
            active_events=active_events,
            generated_at=now,
        )
        
        # 记录最终注入的 Evidence ID
        evidence_memory_ids = [item.memory_id for item in pack.items]
        r_trace.evidence_memory_ids = evidence_memory_ids
        
        return pack

    @staticmethod
    def _to_active_event(cand: dict[str, Any]) -> dict[str, Any]:
        """把事件候选整理为 active_events 条目（hard_filter 已确保 scheduled/rescheduled）。"""
        return {
            "event_id": cand.get("event_id"),
            "event_type": cand.get("event_type"),
            "title": cand.get("title"),
            "status": cand.get("status"),
            "start_at": cand.get("start_at"),
            "end_at": cand.get("end_at"),
        }
