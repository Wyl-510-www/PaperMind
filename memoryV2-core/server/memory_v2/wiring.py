"""Phase 5C: 工厂函数 — 创建完整 MemoryWriter 和 MemoryCompatFacade。

所有的"接线"集中在此文件，外部只需调用 create_facade() 即可。
"""

from __future__ import annotations

from server.memory_v2.write.gate import MemoryGate
from server.memory_v2.write.router import MemoryDispatcher
from server.memory_v2.write.writer import MemoryWriter
from server.memory_v2.store.fact_store import FactStore
from server.memory_v2.store.event_store import EventStore
from server.memory_v2.store.entity_store import EntityStore
from server.memory_v2.policy.compiler import PolicyCompiler
from server.memory_v2.critical_identity import CriticalIdentityRepo
from server.memory_v2.preference_repository import PreferenceRepository
from server.memory_v2.facade import MemoryCompatFacade
from server.database.database_bailian_config import Config as DBConfig


def _create_default_extractors(llm_client, fact_store=None, tenant_id="default"):
    """创建 6 lane extractors 字典

    Args:
        llm_client: LLM客户端
        fact_store: FactStore实例，用于UpdateDeleteExtractor查询existing truths（P0-1）
        tenant_id: 租户ID，用于查询truths时过滤（P0-1）
    """
    from server.memory_v2.write.extractors.semantic import SemanticExtractor
    from server.memory_v2.write.extractors.event_task import EventTaskExtractor
    from server.memory_v2.write.extractors.entity_relation import EntityRelationExtractor
    from server.memory_v2.write.extractors.behavior_policy import BehaviorPolicyExtractor
    from server.memory_v2.write.extractors.update_delete import UpdateDeleteExtractor

    return {
        "semantic": SemanticExtractor(llm_client),
        "event_task": EventTaskExtractor(llm_client),
        "entity_relation": EntityRelationExtractor(llm_client),
        "behavior_policy": BehaviorPolicyExtractor(llm_client),
        # P0-1修复：UpdateDeleteExtractor需要fact_store和tenant_id查询existing truths
        "update_delete": UpdateDeleteExtractor(llm_client, fact_store=fact_store, tenant_id=tenant_id),
    }


def create_memory_writer(llm_client, tenant_id="default") -> MemoryWriter:
    """创建完整写入链路：extractors → gate → dispatcher → stores

    Args:
        llm_client: LLM客户端
        tenant_id: 租户ID，用于P0-1查询existing truths
    """
    from server.database.connection_pool import db_pool

    # 使用全局连接池（修复 P0-6 连接池泄漏）
    SessionLocal = db_pool.sync_session_factory
    AsyncSessionLocal = db_pool.async_session_factory
    session = SessionLocal()

    # 创建fact_store用于P0-1查询existing truths
    fact_store = FactStore(session)

    # P0-1: 传递fact_store和tenant_id给extractors
    extractors = _create_default_extractors(llm_client, fact_store=fact_store, tenant_id=tenant_id)
    gate = MemoryGate()

    # P0-1: PreferenceRepository 使用异步工厂
    critical_identity_repo = CriticalIdentityRepo(SessionLocal)
    preference_repo = PreferenceRepository(AsyncSessionLocal)

    dispatcher = MemoryDispatcher(
        entity_store=EntityStore(SessionLocal),
        fact_store=fact_store,  # 复用同一个fact_store实例
        event_store=EventStore(session),
        critical_identity_repo=critical_identity_repo,
        preference_repo=preference_repo,
    )
    return MemoryWriter(extractors=extractors, gate=gate, dispatcher=dispatcher, llm_client=llm_client)


def create_facade(
    legacy_memory,
    llm_client=None,
) -> MemoryCompatFacade:
    """创建完整 Facade：legacy + V2 writer + policy compiler + V2 searcher。

    Args:
        legacy_memory: 旧 mem0 AsyncMemory 实例
        llm_client: DashScopeClient 实例（None 时 writer 不可用）

    Returns:
        MemoryCompatFacade（可立即调用 add/search/bootstrap）
    """
    from server.memory_v2.models import make_session_factory as sf  # Fix: 实际函数名是 make_session_factory

    policy_compiler = PolicyCompiler(sf(DBConfig.Database_url))

    v2_writer = None
    if llm_client is not None:
        v2_writer = _SessionBoundWriter(llm_client)

    # V2 searcher: 轻量适配器，把 production_entry 的 assemble_evidence_pack
    # 适配为 facade.search() 期望的接口
    v2_searcher = _V2SearcherAdapter()

    return MemoryCompatFacade(
        legacy_memory=legacy_memory,
        v2_writer=v2_writer,
        policy_compiler=policy_compiler,
        v2_searcher=v2_searcher,
    )


class _SessionBoundWriter:
    """每次 write_turn 创建新的 MemoryWriter + session，用完关闭"""

    def __init__(self, llm_client):
        self._llm = llm_client

    async def write_turn(self, **kwargs):
        # P0-1: 从kwargs中提取tenant_id，传递给create_memory_writer
        tenant_id = kwargs.get("tenant_id", "default")
        writer = create_memory_writer(self._llm, tenant_id=tenant_id)
        trace = await writer.write_turn(**kwargs)
        # 关闭 dispatcher 中的 session
        if writer.dispatcher and writer.dispatcher.fact_store:
            try:
                writer.dispatcher.fact_store.session.close()
            except Exception:
                pass
        return trace


class _V2SearcherAdapter:
    """Ticket 08: 把 production_entry 的 assemble_evidence_pack 适配为 facade.search() 接口。

    facade.search() 期望 searcher 有 async def search(query, user_id, limit) → legacy 格式 dict。
    """

    async def search(self, query: str, user_id: str, limit: int = 5) -> dict:
        """V2 检索，返回兼容 mem0 search() 格式的 dict。"""
        import asyncio
        from server.memory_v2.config import config
        from server.memory_v2.production_entry import assemble_evidence_pack

        evidence = await asyncio.to_thread(
            assemble_evidence_pack,
            query=query,
            tenant_id=config.default_tenant_id,
            user_id=str(user_id),  # 归一化
        )

        if not evidence or not evidence.get("items"):
            return {"results": []}

        results = []
        for item in evidence["items"][:limit]:
            results.append({
                "id": item.get("memory_id", ""),
                "memory": item.get("content", ""),
                "hash": "",
                "score": item.get("confidence", 0.5),
                "created_at": "",
                "updated_at": "",
                "metadata": {
                    "memory_type": item.get("memory_type", "semantic"),
                    "modality": item.get("modality", "fact"),
                    "status": item.get("status", "active"),
                    "confidence": item.get("confidence", 0.5),
                },
            })

        return {"results": results}
