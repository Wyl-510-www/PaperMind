"""Memory V2 检索链路封装模块。

此模块封装 Memory V2 的检索功能，提供统一的检索接口供 LLM 调用。
核心功能：
1. 封装 Memory V2 的检索调用
2. 实现租户和用户隔离
3. 格式化检索结果为 prompt 注入文本
4. 提供错误处理和降级策略
5. 提供结构化证据检索（返回 EvidenceItem 列表）
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from papermind.config import get_config

logger = logging.getLogger(__name__)


# 导入 app_service 中的 EvidenceItem（避免循环导入，使用 TYPE_CHECKING）
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from papermind.app_service import EvidenceItem


async def retrieve_structured_evidence(
    query: str,
    tenant_id: str,
    user_id: str,
    limit: int = 5,
) -> list[EvidenceItem]:
    """检索用户长期记忆并返回结构化证据列表。

    此函数提供结构化检索接口，返回 EvidenceItem 列表供业务层使用。
    与 retrieve_memory_context 不同，此函数不格式化为字符串，而是保留结构化数据。

    Args:
        query: 用户查询文本，用于语义检索
        tenant_id: 租户 ID，用于隔离不同租户的记忆
        user_id: 用户 ID，用于隔离同一租户下不同用户的记忆
        limit: 返回的最大证据数量，默认 5 条

    Returns:
        EvidenceItem 列表，每个 EvidenceItem 包含：
            - memory_id: 记忆 ID
            - content: 记忆内容文本
            - memory_type: 记忆类型（如 semantic）
            - confidence: 置信度分数
            - created_at: 创建时间（可能为 None）

        如果未检索到记忆，返回空列表。

    Raises:
        asyncio.TimeoutError: 检索超时
        RuntimeError: Memory V2 检索失败
        Exception: 其他检索错误

    Note:
        - 此函数抛出异常而不是返回降级提示，让调用者决定如何处理错误
        - 调用者应区分空列表（无证据）和异常（检索失败）

    Example:
        >>> evidence_list = await retrieve_structured_evidence(
        ...     query="我的研究方向是什么",
        ...     tenant_id="tenant_default",
        ...     user_id="alice",
        ...     limit=5
        ... )
        >>> if evidence_list:
        ...     print(f"找到 {len(evidence_list)} 条证据")
        ...     print(f"第一条：{evidence_list[0].content}")
    """
    # 延迟导入避免循环依赖
    from papermind.app_service import EvidenceItem

    config = get_config()

    # 设置超时控制（抛出异常，不捕获）
    evidence_pack = await asyncio.wait_for(
        _call_memory_v2_retrieval(
            query=query,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
        ),
        timeout=config.memory_retrieval_timeout,
    )

    # 转换为 EvidenceItem 列表
    if not evidence_pack or not evidence_pack.get("items"):
        return []

    evidence_items = []
    for item in evidence_pack["items"]:
        evidence_item = EvidenceItem(
            memory_id=item.get("memory_id", "unknown"),
            content=item.get("text", ""),  # 注意：evidence_pack 中字段名是 "text"
            memory_type=item.get("memory_type", "unknown"),
            confidence=item.get("confidence", 0.0),
            created_at=item.get("created_at"),
        )
        evidence_items.append(evidence_item)

    return evidence_items


async def retrieve_memory_context(
    query: str,
    tenant_id: str,
    user_id: str,
    limit: int = 5,
) -> str:
    """检索用户长期记忆并格式化为 prompt 注入文本。

    此函数是 papermind-host 层调用 Memory V2 检索的统一入口。
    实现租户和用户隔离，确保不同租户/用户的记忆相互隔离。

    Args:
        query: 用户查询文本，用于语义检索
        tenant_id: 租户 ID，用于隔离不同租户的记忆
        user_id: 用户 ID，用于隔离同一租户下不同用户的记忆
        limit: 返回的最大证据数量，默认 5 条

    Returns:
        格式化的证据文本，可直接注入到 LLM prompt 中。
        如果检索到记忆，返回结构化的证据列表（包含内容、来源、时间、置信度）。
        如果未检索到记忆，返回明确的"未找到相关记忆"提示。
        如果检索失败或超时，返回降级提示。

    Example:
        >>> memory_context = await retrieve_memory_context(
        ...     query="我的研究方向是什么",
        ...     tenant_id="tenant_default",
        ...     user_id="alice",
        ...     limit=5
        ... )
        >>> print(memory_context)
        [记忆检索结果]：找到以下相关记忆：

        1. 我的研究方向是计算机视觉
           来源：Memory ID abc123
           时间：2026-10-07 10:30
           置信度：0.95
    """
    config = get_config()

    try:
        # 设置超时控制
        evidence_pack = await asyncio.wait_for(
            _call_memory_v2_retrieval(
                query=query,
                tenant_id=tenant_id,
                user_id=user_id,
                limit=limit,
            ),
            timeout=config.memory_retrieval_timeout,
        )

        # 格式化证据包为 prompt 文本
        return format_evidence_pack(evidence_pack)

    except asyncio.TimeoutError:
        logger.warning(
            "Memory retrieval timeout: query=%s, tenant=%s, user=%s, timeout=%.2fs",
            query[:50],
            tenant_id,
            user_id,
            config.memory_retrieval_timeout,
        )
        return "[记忆检索超时，将基于当前对话回答]"

    except Exception as e:
        logger.error(
            "Memory retrieval failed: query=%s, tenant=%s, user=%s, error=%s",
            query[:50],
            tenant_id,
            user_id,
            str(e),
            exc_info=True,
        )
        return "[记忆检索失败，将基于当前对话回答]"


async def _call_memory_v2_retrieval(
    query: str,
    tenant_id: str,
    user_id: str,
    limit: int,
) -> Optional[dict]:
    """调用 Memory V2 检索接口。

    此函数封装与 Memory V2 的实际交互，包括：
    1. 初始化 Memory V2 依赖（IndexV2, Session, Reranker）
    2. 调用 EvidencePipeline.assemble() 执行检索
    3. 返回 EvidencePack 对象

    Args:
        query: 查询文本
        tenant_id: 租户 ID（用于 Hard Filter）
        user_id: 用户 ID（用于 Hard Filter）
        limit: 返回的最大证据数量

    Returns:
        EvidencePack 的字典表示，包含检索到的证据列表。
        如果检索失败或无结果，返回 None。

    Note:
        租户和用户隔离通过以下机制实现：
        1. tenant_id 和 user_id 作为参数传递给 EvidencePipeline
        2. HardFilter 会验证候选记忆的租户和用户是否匹配
        3. 只有匹配的记忆才会被返回
    """
    try:
        # 导入 Memory V2 核心模块
        from server.memory_v2.retrieve.evidence_pipeline import EvidencePipeline
        from server.memory_v2.retrieve.index_v2 import IndexV2
        from server.memory_v2.retrieve.embedder import RealEmbedder
        from server.database.database_bailian_config import Config as DBConfig
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from typing import Any

        # 创建一个带 embedder 的 IndexV2 包装器
        class IndexV2WithEmbedder:
            """IndexV2 包装器，自动处理 query embedding。"""
            def __init__(self, index: IndexV2, embedder: RealEmbedder):
                self.index = index
                self.embedder = embedder

            def search(
                self,
                memory_type: str,
                query: str,
                top_k: int,
                query_vector: list[float] | None = None,
                tenant_id: str | None = None,
                user_id: str | None = None,
            ) -> list[dict[str, Any]]:
                """自动生成 query_vector 然后调用 IndexV2.search。"""
                if query_vector is None:
                    query_vector = self.embedder.embed(query)
                return self.index.search(
                    memory_type=memory_type,
                    query=query,
                    top_k=top_k,
                    query_vector=query_vector,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )

        # 创建一个空操作的 Reranker（Phase 1.3 不需要 reranking）
        class NoopReranker:
            """空操作 Reranker，直接返回原始候选，不做重排。"""
            def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
                """不做任何重排，直接返回原始候选。"""
                # 为每个候选添加 rerank_score（使用原始 score）
                for cand in candidates:
                    if "rerank_score" not in cand:
                        cand["rerank_score"] = cand.get("score", 0.0)
                return candidates

        # 初始化数据库连接
        engine = create_engine(DBConfig.Database_url, pool_pre_ping=True)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        try:
            # 初始化 Memory V2 组件
            base_index = IndexV2(embedding_dim=1536)  # text-embedding-v4 维度
            embedder = RealEmbedder()  # 创建 embedder
            index = IndexV2WithEmbedder(base_index, embedder)  # 包装后的 index
            # Phase 1.3: 使用 NoopReranker（不做重排）
            reranker = NoopReranker()

            # 创建 EvidencePipeline
            pipeline = EvidencePipeline(
                index=index,
                session=session,
                reranker=reranker,
                token_budget=2000,  # 默认 token 预算
            )

            # 调用检索（同步方法，但包装在 async 函数中）
            evidence_pack = pipeline.assemble(
                query=query,
                tenant_id=tenant_id,
                user_id=user_id,
                now=datetime.now(),
            )

            # 转换为字典（便于格式化）
            return {
                "query": evidence_pack.query,
                "items": [
                    {
                        "memory_id": item.memory_id,
                        "text": item.content,  # EvidenceItem 字段是 content，不是 text_zh
                        "confidence": item.final_score,
                        "memory_type": item.memory_type,
                        "created_at": getattr(item, "created_at", None),
                    }
                    for item in evidence_pack.items
                ],
                "generated_at": evidence_pack.generated_at,
            }

        finally:
            session.close()
            engine.dispose()

    except ImportError as e:
        logger.error("Memory V2 模块导入失败: %s", str(e))
        raise RuntimeError("Memory V2 核心模块不可用") from e

    except Exception as e:
        logger.error("Memory V2 检索调用失败: %s", str(e), exc_info=True)
        raise


def format_evidence_pack(evidence_pack: Optional[dict]) -> str:
    """将 EvidencePack 格式化为 prompt 注入文本。

    将检索到的证据格式化为清晰易读的文本，供 LLM 理解和使用。
    格式包含：编号、内容、来源、时间戳和置信度。

    Args:
        evidence_pack: Memory V2 返回的证据包字典，可能为 None

    Returns:
        格式化的证据文本，适合注入到 LLM prompt 中。

    格式示例：
        有证据时：
        ```
        [记忆检索结果]：找到以下相关记忆：

        1. 我的研究方向是计算机视觉
           来源：Memory ID abc123
           类型：semantic
           时间：2026-10-07 10:30
           置信度：0.95

        2. 我对深度学习很感兴趣
           来源：Memory ID def456
           类型：semantic
           时间：2026-10-06 15:20
           置信度：0.88
        ```

        无证据时：
        ```
        [记忆检索结果]：未找到相关记忆，请基于当前对话回答。
        ```
    """
    if not evidence_pack or not evidence_pack.get("items"):
        return "[记忆检索结果]：未找到相关记忆，请基于当前对话回答。"

    lines = ["[记忆检索结果]：找到以下相关记忆：\n"]

    for idx, item in enumerate(evidence_pack["items"], start=1):
        # 提取证据字段
        text = item.get("text", "")
        memory_id = item.get("memory_id", "unknown")
        memory_type = item.get("memory_type", "unknown")
        confidence = item.get("confidence", 0.0)
        created_at = item.get("created_at")

        # 格式化时间戳
        time_str = "未知"
        if created_at:
            if isinstance(created_at, datetime):
                time_str = created_at.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = str(created_at)

        # 构造证据文本
        lines.append(f"{idx}. {text}")
        lines.append(f"   来源：Memory ID {memory_id}")
        lines.append(f"   类型：{memory_type}")
        lines.append(f"   时间：{time_str}")
        lines.append(f"   置信度：{confidence:.2f}\n")

    return "\n".join(lines)
