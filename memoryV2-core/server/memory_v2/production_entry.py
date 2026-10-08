"""生产入口适配：把 Memory V2 evidence_pipeline 接到真实服务，供 build_context 调用。

解决两个接缝问题：
1. IndexProtocol.search(memory_type, query, top_k) 不传向量，但 IndexV2.search 需要
   query_vector → EmbeddingIndexAdapter 先 embed query 再查 Qdrant。
2. build_context 期望字符串格式的 user_info → assemble_user_memory 把 EvidencePack
   转成"- 内容"的多行字符串（与旧 mem0 输出格式对齐）。

依赖注入：所有真实服务（IndexV2/RealEmbedder/RealReranker/MySQL session）在
build_memory_v2_pipeline 里一次性组装，缓存复用。
"""

from __future__ import annotations

import time
from .monitoring import metrics_collector

from functools import wraps
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.core.settings import Config_Bailian
from server.memory_v2.retrieve.embedder import RealEmbedder
from server.memory_v2.retrieve.evidence_pipeline import EvidencePipeline
from server.memory_v2.retrieve.index_v2 import IndexV2
from server.memory_v2.retrieve.reranker import RealReranker

logger = logging.getLogger(__name__)


# ─── R 层监控装饰器 ────────────────────────────────────────────────────
def monitor_read_operation(func):
    """R 层监控装饰器：保证监控一定被调用"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        _start = metrics_collector.record_read_start()
        logger.info(f"[R_MONITOR] {func.__name__} called")
        try:
            result = func(*args, **kwargs)
            elapsed_ms = (time.time() - _start) * 1000
            
            # 计算 memories_count
            if isinstance(result, str):
                count = len([line for line in result.split("\n") if line.strip()]) if result else 0
            elif isinstance(result, dict) and result is not None:
                count = len(result.get("items", []))
            else:
                count = 0
            
            logger.info(f"[R_MONITOR] {func.__name__} success: elapsed={elapsed_ms:.1f}ms, count={count}")
            metrics_collector.record_read_success(elapsed_ms=elapsed_ms, memories_count=count)
            return result
        except Exception as e:
            elapsed_ms = (time.time() - _start) * 1000
            logger.error(f"[R_MONITOR] {func.__name__} failed: {e}")
            metrics_collector.record_read_failure(elapsed_ms=elapsed_ms, error_type=type(e).__name__, error_msg=str(e))
            raise
    return wrapper




class EmbeddingIndexAdapter:
    """把 IndexV2 适配成 evidence_pipeline.IndexProtocol。

    evidence_pipeline 调用 search(memory_type, query, top_k) 不含向量，
    这里先用 embedder 把 query 转向量，再调用 IndexV2.search。
    """

    def __init__(self, index: IndexV2, embedder: RealEmbedder):
        self._index = index
        self._embedder = embedder
        self._vector_cache: dict[str, list[float]] = {}

    def search(
        self,
        memory_type: str,
        query: str,
        top_k: int,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """embed query（按 query 缓存，多路召回复用）后调用 IndexV2.search。

        Args:
            memory_type: 记忆类型
            query: 查询文本
            top_k: 返回候选数量
            tenant_id: 租户 ID（scope 过滤）
            user_id: 用户 ID（scope 过滤）
        """
        if query not in self._vector_cache:
            self._vector_cache[query] = self._embedder.embed(query)
        query_vector = self._vector_cache[query]

        return self._index.search(
            memory_type=memory_type,
            query=query,
            top_k=top_k,
            query_vector=query_vector,
            tenant_id=tenant_id,
            user_id=user_id,
        )


# ─── 单例缓存（只缓存重量级、线程安全的组件；session 每次调用新建）──────────
# Qdrant client / embedder / reranker 是无状态或线程安全的，可复用；
# SQLAlchemy Session 非线程安全且有事务快照，必须每次请求新建，否则并发下会：
#   1. 多线程共享 Session 崩溃；2. 事务隔离导致读到陈旧数据（看不到其他连接的提交）。
_index_adapter: EmbeddingIndexAdapter | None = None
_reranker: RealReranker | None = None
_session_factory: sessionmaker | None = None


def _get_db_url() -> str:
    """MySQL 连接串。优先用 MEMORY_V2_DB_URL 环境变量，否则用项目 Config.Database_url。"""
    url = os.getenv("MEMORY_V2_DB_URL", "")
    if url:
        return url
    # 复用项目既有 database_bailian_config（避免硬编码，已支持 DB_HOST/USER/PASS 环境变量）
    from server.database.database_bailian_config import Config as DBConfig
    return DBConfig.Database_url


def _build_shared_components() -> tuple[EmbeddingIndexAdapter, RealReranker, sessionmaker]:
    """懒初始化并缓存重量级组件（index_adapter / reranker / session_factory）。"""
    global _index_adapter, _reranker, _session_factory

    if _index_adapter is not None and _reranker is not None and _session_factory is not None:
        return _index_adapter, _reranker, _session_factory

    logger.info("Building Memory V2 shared components...")

    # MySQL session factory（engine 缓存连接池，session 每次请求从工厂新建）
    engine = create_engine(_get_db_url(), pool_pre_ping=True, pool_recycle=3600)
    _session_factory = sessionmaker(bind=engine)

    # IndexV2 + embedder（Qdrant client 线程安全，可复用）
    from server.memory_v2.retrieve.index_v2 import get_collection_name
    index = IndexV2(
        host=Config_Bailian.DB_VECTOR_QDRANT_HOST,
        port=Config_Bailian.DB_VECTOR_QDRANT_PORT,
        collection_name=get_collection_name(),  # 使用环境变量配置的 collection
    )
    index.create_collection_if_not_exists()
    embedder = RealEmbedder()
    _index_adapter = EmbeddingIndexAdapter(index, embedder)

    # RealReranker（SiliconFlow，无状态 HTTP client）
    _reranker = RealReranker()

    logger.info("Memory V2 shared components ready.")
    return _index_adapter, _reranker, _session_factory


def build_memory_v2_pipeline(session: Session) -> EvidencePipeline:
    """用传入的 session 组装一个 EvidencePipeline（index/reranker 复用缓存组件）。

    Args:
        session: 本次请求专用的 MySQL session（调用方负责关闭）
    """
    index_adapter, reranker, _ = _build_shared_components()
    return EvidencePipeline(
        index=index_adapter,
        session=session,
        reranker=reranker,
    )


@monitor_read_operation
def assemble_evidence_pack(
    query: str,
    tenant_id: str,
    user_id: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """用 Memory V2 evidence_pipeline 检索，返回 EvidencePack dict（含 usage 标注）。

    返回 dict 可直接注入 biz_params 或用作 JSON 序列化。
    每次调用新建 session，用完即关。

    P0-3 修复：使用 pack.model_dump() 完整序列化 EvidenceItem，
    保留 memory_type、predicate 等 ClaimGuard 必需的契约字段，
    不再手工裁剪字段（原实现丢失 memory_type/predicate 导致 Guard 校验失败）。
    
    T8 召回修复：初始化 ChainTrace 上下文并注入检索元数据到返回结果，
    使 retrieval_trace 中的 candidate_ids/filtered/reranked 字段有数据。
    """
    now = now or datetime.now(timezone.utc)
    user_id = str(user_id)  # 归一化：BigInteger 列存 int 但 Pydantic 模型要求 str
    
    # T8 修复：初始化 ChainTrace 上下文，确保 EvidencePipeline 能记录检索元数据
    from server.memory_v2.tracing.context import init_chain_trace
    chain_trace = init_chain_trace()
    
    _, _, session_factory = _build_shared_components()

    session = session_factory()
    try:
        pipeline = build_memory_v2_pipeline(session)
        pack = pipeline.assemble(
            query=query,
            tenant_id=tenant_id,
            user_id=user_id,
            now=now,
        )
        
        # T8 修复：获取 EvidencePipeline 填充的 RetrievalTrace 数据
        r_trace = chain_trace.retrieval if chain_trace and chain_trace.retrieval else None
    finally:
        session.close()

    if not pack.items:
        return {
            "query": query,
            "items": [],
            "usage_rules": "无可用证据，禁止编造用户偏好、经历或关系。",
            "candidate_ids": [],  # T8 修复：返回空列表而非缺失字段
            "filtered": [],
            "reranked": [],
        }

    # P0-3 修复：使用 model_dump(mode="json") 完整序列化，保留所有契约字段
    # （memory_type/predicate/importance/source_turn_ids 等），供 ClaimGuard 消费。
    result = pack.model_dump(mode="json")
    # 兼容下游：保留 usage_rules 提示字段（有证据时给出使用约束）
    result.setdefault(
        "usage_rules",
        "仅可依据以下证据回答，不得编造证据之外的用户偏好、经历或关系。",
    )
    
    # T8 修复：注入 RetrievalTrace 元数据到返回结果
    # 这些字段将被 context.py 用于构造 retrieval_trace["retrieval"]
    if r_trace:
        result["candidate_ids"] = r_trace.retrieval_candidate_ids or []
        result["filtered"] = r_trace.hardfilter_accepted_ids or []
        result["reranked"] = r_trace.reranked_ids or []
    else:
        # 降级处理：如果 trace 未正确初始化，从 items 中提取 memory_id
        result["candidate_ids"] = [item.get("memory_id", "") for item in result.get("items", [])]
        result["filtered"] = []
        result["reranked"] = []
    
    return result

@monitor_read_operation
def assemble_user_memory(
    query: str,
    tenant_id: str,
    user_id: str,
    now: datetime | None = None,
) -> str:
    """用 Memory V2 evidence_pipeline 检索用户记忆，返回字符串格式（与旧 mem0 对齐）。

    每次调用新建 session（线程安全 + 避免事务快照读到陈旧数据），用完即关。

    Args:
        query: 用户查询
        tenant_id: 租户 ID
        user_id: 用户 ID
        now: 当前时间，默认 now(UTC)

    Returns:
        "- 记忆1\n- 记忆2" 格式的字符串，无记忆时返回空字符串
    """
    now = now or datetime.now(timezone.utc)
    user_id = str(user_id)  # 归一化
    _, _, session_factory = _build_shared_components()

    session = session_factory()
    try:
        pipeline = build_memory_v2_pipeline(session)
        pack = pipeline.assemble(
            query=query,
            tenant_id=tenant_id,
            user_id=user_id,
            now=now,
        )
    finally:
        session.close()

    if not pack.items:
        return ""

    # 问题 2 修复：为 behavior_policy 类型的记忆增加时序和指令标记
    lines = []
    for item in pack.items:
        from server.memory_v2.contracts import MemoryType
        if item.memory_type == MemoryType.BEHAVIOR_POLICY:
            # 行为准则需要明确的时序和指令强度
            lines.append(f"【行为准则 - 必须遵守】{item.content}")
        else:
            # 其他类型保持原格式
            lines.append(f"- {item.content}")

    return "\n".join(lines)
