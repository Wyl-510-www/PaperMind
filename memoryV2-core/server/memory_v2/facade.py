"""MemoryCompatFacade：统一入口，兼容旧 memory_async 签名。

支持双写（mem0 + V2）、shadow read、灰度切换、bootstrap 幂等创建。
"""

from __future__ import annotations

import logging
import os

from server.memory_v2.config import config
from server.memory_v2.monitoring import metrics_collector
from server.memory_v2.policy.compiler import PolicyCompiler

logger = logging.getLogger(__name__)


class MemoryCompatFacade:
    """统一入口。add()/search()/bootstrap()，兼容旧 AsyncMemory 接口"""

    def __init__(self, legacy_memory, v2_writer=None, policy_compiler=None, v2_searcher=None):
        """
        Args:
            legacy_memory: 旧 mem0 AsyncMemory 实例
            v2_writer: MemoryWriter 实例
            policy_compiler: PolicyCompiler 实例
            v2_searcher: V2 检索入口（evidence_pipeline 或 production_entry）
        """
        self.legacy = legacy_memory
        self.writer = v2_writer
        self.policies = policy_compiler or PolicyCompiler()
        self.searcher = v2_searcher

        # 暴露 llm/embedding_model 属性给 token callback
        self.llm = getattr(legacy_memory, 'llm', None)
        self.embedding_model = getattr(legacy_memory, 'embedding_model', None)

    async def add(
        self,
        messages,
        *,
        user_id=None,
        metadata=None,
        tenant_id=None,
        turn_id=None,
        occurred_at=None,
        previous_user_text=None,
        skip_legacy_write=False,  # 新增：跳过legacy写入（快速trace模式）
        **kwargs,
    ):
        """双写：legacy + V2 writer。

        兼容旧 add_memory(messages, user_id=str(user_id)) 调用。
        P1-1: 透传 tenant_id/turn_id/occurred_at/previous_user_text 到 V2 writer。
        P1-2: Benchmark 模式下返回完整 V2 trace。
        B3: Speech Act 判断，QUERY_EXISTING/AMBIGUOUS 跳过双写。
        
        Args:
            skip_legacy_write: True时跳过legacy mem0写入，仅执行V2写入获取trace（用于快速测试）
        """
        # 提取用户文本
        user_text = _extract_user_text(messages)

        # B3: Speech Act 分类
        from server.memory_v2.speech_act import classify_speech_act, MemorySpeechAct

        speech_act = MemorySpeechAct.ASSERT  # 默认值
        if user_text:
            speech_act = classify_speech_act(user_text)
            logger.info("Facade Speech Act: %s (text=%.80s)", speech_act.value, user_text)

        # 查询或模糊输入，跳过双写（V2 和 legacy）
        if speech_act in (MemorySpeechAct.QUERY_EXISTING, MemorySpeechAct.AMBIGUOUS):
            logger.info("跳过写入 (V2 和 legacy): speech_act=%s", speech_act.value)

            # 返回空结果
            if os.getenv("BENCHMARK_MODE", "false").lower() == "true":
                return {
                    "messages": ["查询不写入记忆"],
                    "v2_write_success": False,
                    "speech_act": speech_act.value,
                    "skip_reason": "query_or_ambiguous",
                }
            else:
                return {"messages": ["查询不写入记忆"]}

        # 1. Legacy 写入（主路径，独立完成）
        # 快速trace模式下跳过legacy写入
        legacy_result = {}
        if skip_legacy_write:
            logger.info("跳过 legacy 写入 (skip_legacy_write=True)")
            legacy_result = {"messages": ["跳过legacy写入"], "results": [], "generated_memories": []}
        else:
            legacy_result = await self.legacy.add(messages, user_id=user_id, metadata=metadata, **kwargs)

        # 2. V2 写入（影子路径，失败不抛异常）
        v2_result = None
        v2_success = False
        if config.write_enabled and self.writer:
            try:
                if user_text:
                    v2_result = await self.writer.write_turn(
                        user_text=user_text,
                        user_id=str(user_id or ""),
                        turn_id=turn_id or (metadata.get("turn_id", "") if metadata else ""),
                        tenant_id=tenant_id or config.default_tenant_id,
                        occurred_at=occurred_at,
                        previous_user_text=previous_user_text,
                    )
                    v2_success = True
            except Exception:
                logger.exception("V2 写失败（不影响 legacy）")
                v2_success = False

        # P1-2: Benchmark 模式返回完整结果（legacy + V2 trace），生产模式返回 legacy 兼容
        if os.getenv("BENCHMARK_MODE", "false").lower() == "true":
            from server.memory_v2.build_info import BuildInfo

            return {
                "legacy_result": legacy_result,
                "results": legacy_result.get("results", []) if isinstance(legacy_result, dict) else [],
                "generated_memories": legacy_result.get("generated_memories", []) if isinstance(legacy_result, dict) else [],
                "v2_write": v2_result.model_dump() if v2_result else None,
                "v2_write_success": v2_success,
                "v2_enabled": config.write_enabled,
                "build_info": BuildInfo.get_build_info(),  # M0: 版本绑定
                "skip_legacy_write": skip_legacy_write,  # 标记是否跳过了legacy写入
            }
        return legacy_result

    async def search(self, query, *, user_id=None, limit=5, filters=None, threshold=None, **kwargs):
        """检索：根据灰度开关返回 legacy 或 V2。

        兼容旧 search_memory(query, user_id=user_id, limit=5) 调用。
        """
        # V2 读未开启：返回 legacy
        if not config.read_enabled:
            result = await self.legacy.search(
                query=query, user_id=user_id, limit=limit,
                filters=filters, threshold=threshold, **kwargs,
            )
            # Shadow read: 后台异步对比 V2
            if config.shadow_read and self.searcher:
                try:
                    _ = await self.searcher.search(query, str(user_id), limit)
                except Exception:
                    logger.debug("Shadow read failed", exc_info=True)
            return result

        # V2 读开启
        if self.searcher:
            return await self.searcher.search(query, str(user_id), limit)

        # Fallback
        return await self.legacy.search(
            query=query, user_id=user_id, limit=limit,
            filters=filters, threshold=threshold, **kwargs,
        )

    async def compile_policies(self, user_id: str):
        """编译当前用户的 PolicyPack"""
        return await self.policies.compile(config.default_tenant_id, str(user_id))

    async def bootstrap(self):
        """幂等创建 MySQL 表 + Qdrant collection（app lifespan 调用）"""
        from server.memory_v2.models import create_engine_and_tables
        from server.memory_v2.retrieve.index_v2 import IndexV2
        from server.database.database_bailian_config import Config as DBConfig

        # 1. MySQL 表（幂等，checkfirst=True）
        engine = create_engine_and_tables(DBConfig.Database_url)

        # EntityStore 使用独立的 Base，需单独建表
        from server.memory_v2.store.entity_store import Base as EntityBase
        EntityBase.metadata.create_all(engine, checkfirst=True)

        # CriticalIdentity 使用独立的 Base，需单独建表
        from server.memory_v2.critical_identity import Base as CriticalIdentityBase
        CriticalIdentityBase.metadata.create_all(engine, checkfirst=True)

        # PreferenceRepository 使用独立的 Base，需单独建表
        from server.memory_v2.preference_repository import Base as PrefBase
        PrefBase.metadata.create_all(engine, checkfirst=True)

        engine.dispose()
        logger.info("Facade bootstrap: MySQL tables OK")

        # 2. Qdrant collection（幂等，1536 维对齐 text-embedding-v4）
        try:
            index = IndexV2(embedding_dim=1536)
            index.create_collection_if_not_exists()
            logger.info("Facade bootstrap: Qdrant collection OK")
        except Exception:
            logger.warning("Facade bootstrap: Qdrant collection 创建失败（可能已存在或不可达）", exc_info=True)


def _extract_user_text(messages) -> str | None:
    """从 mem0 messages 列表提取用户文本"""
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                return msg.get("content", "")
    elif isinstance(messages, str):
        return messages
    return None
