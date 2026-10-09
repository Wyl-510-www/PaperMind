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
    tags: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[EvidenceItem]:
    """检索用户长期记忆并返回结构化证据列表（支持标签和时间过滤）。

    此函数提供结构化检索接口，返回 EvidenceItem 列表供业务层使用。
    Phase 3: 支持两阶段检索——先硬过滤（标签+时间），再语义检索。

    Args:
        query: 用户查询文本，用于语义检索
        tenant_id: 租户 ID，用于隔离不同租户的记忆
        user_id: 用户 ID，用于隔离同一租户下不同用户的记忆
        limit: 返回的最大证据数量，默认 5 条
        tags: 标签列表（Phase 3 新增），使用 OR 逻辑（匹配任一标签）
        start_date: 起始日期（Phase 3 新增），过滤 read_date >= start_date 的笔记
        end_date: 结束日期（Phase 3 新增），过滤 read_date <= end_date 的笔记

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
        - Phase 3: 如果提供标签或时间范围，先进行硬过滤，再语义检索
        - 如果未提供标签和时间，直接全局语义检索（兼容 Phase 2 行为）
        - 调用者应区分空列表（无证据）和异常（检索失败）

    Example:
        >>> # Phase 2 全局检索
        >>> evidence_list = await retrieve_structured_evidence(
        ...     query="我的研究方向是什么",
        ...     tenant_id="tenant_default",
        ...     user_id="alice",
        ...     limit=5
        ... )

        >>> # Phase 3 标签过滤检索
        >>> evidence_list = await retrieve_structured_evidence(
        ...     query="Transformer 的注意力机制",
        ...     tenant_id="tenant_default",
        ...     user_id="alice",
        ...     tags=["Transformer", "注意力机制"],
        ...     start_date=date(2026, 1, 1),
        ...     end_date=date(2026, 1, 31),
        ...     limit=5
        ... )
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
            tags=tags,
            start_date=start_date,
            end_date=end_date,
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
    tags: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Optional[dict]:
    """调用 Memory V2 检索接口（Phase 3: 支持元数据过滤）。

    此函数封装与 Memory V2 的实际交互，包括：
    1. Phase 3: 如果提供标签或时间范围，先查询 MySQL 过滤 Memory IDs
    2. 初始化 Memory V2 依赖（IndexV2, Session, Reranker）
    3. 调用 EvidencePipeline.assemble() 执行检索（限制在过滤后的 Memory IDs）
    4. 返回 EvidencePack 对象

    Args:
        query: 查询文本
        tenant_id: 租户 ID（用于 Hard Filter）
        user_id: 用户 ID（用于 Hard Filter）
        limit: 返回的最大证据数量
        tags: 标签列表（Phase 3 新增），使用 OR 逻辑
        start_date: 起始日期（Phase 3 新增）
        end_date: 结束日期（Phase 3 新增）

    Returns:
        EvidencePack 的字典表示，包含检索到的证据列表。
        如果检索失败或无结果，返回 None。

    Note:
        Phase 3 两阶段检索：
        1. 如果提供标签或时间，先从 MySQL metadata 过滤 Memory IDs
        2. 将过滤后的 Memory IDs 传递给向量检索，缩小检索范围
        3. 如果未提供标签和时间，直接全局检索（兼容 Phase 2）
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
            # Phase 3: 如果提供标签或时间范围，先进行硬过滤
            filtered_memory_ids = None
            if tags or start_date or end_date:
                filtered_memory_ids = _filter_memory_ids_by_metadata(
                    session=session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tags=tags,
                    start_date=start_date,
                    end_date=end_date,
                )

                # 如果硬过滤后无结果，直接返回空
                if filtered_memory_ids is not None and len(filtered_memory_ids) == 0:
                    logger.info(
                        "Hard filter returned no results: tenant=%s, user=%s, tags=%s, date_range=%s-%s",
                        tenant_id,
                        user_id,
                        tags,
                        start_date,
                        end_date,
                    )
                    return {"query": query, "items": [], "generated_at": datetime.now()}

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

            # Phase 3: 如果有过滤后的 Memory IDs，传递给检索管道
            # TODO: 当前 EvidencePipeline.assemble 不支持 allowed_memory_ids 参数
            # 临时方案：先全局检索，然后在结果中过滤
            evidence_pack = pipeline.assemble(
                query=query,
                tenant_id=tenant_id,
                user_id=user_id,
                now=datetime.now(),
            )

            # Phase 3: 如果提供了过滤条件，在结果中过滤
            if filtered_memory_ids is not None:
                filtered_items = [
                    item for item in evidence_pack.items
                    if item.memory_id in filtered_memory_ids
                ]
                # 如果过滤后无结果，记录日志
                if not filtered_items:
                    logger.info(
                        "Semantic search returned results, but none matched metadata filter: "
                        "tenant=%s, user=%s, original_count=%d",
                        tenant_id,
                        user_id,
                        len(evidence_pack.items),
                    )
                evidence_pack.items = filtered_items

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


def _filter_memory_ids_by_metadata(
    session,
    tenant_id: str,
    user_id: str,
    tags: list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[str] | None:
    """根据元数据（标签、时间范围）过滤 Memory IDs（Phase 3）。

    查询 Memory V2 数据库，根据 metadata JSON 字段中的标签和阅读日期进行过滤。

    Args:
        session: SQLAlchemy session
        tenant_id: 租户 ID
        user_id: 用户 ID
        tags: 标签列表（OR 逻辑，匹配任一标签）
        start_date: 起始日期（过滤 read_date >= start_date）
        end_date: 结束日期（过滤 read_date <= end_date）

    Returns:
        符合条件的 Memory IDs 列表，如果无过滤条件返回 None（表示不过滤）
        如果有过滤条件但无结果，返回空列表

    Note:
        - 使用 MySQL JSON 函数查询 metadata 字段
        - 标签使用 OR 逻辑：JSON_OVERLAPS(metadata->'$.tags', JSON_ARRAY(...))
        - 时间使用范围查询：metadata->>'$.read_date' BETWEEN ... AND ...
    """
    from datetime import date as date_type

    # 如果没有任何过滤条件，返回 None（不过滤）
    if not tags and not start_date and not end_date:
        return None

    try:
        from sqlalchemy import text

        # 构建 SQL 查询
        # 注意：这里使用原生 SQL，因为 SQLAlchemy ORM 的 JSON 查询在不同数据库间差异较大
        query = text("""
            SELECT memory_id
            FROM memory_v2_record
            WHERE tenant_id = :tenant_id
              AND user_id = :user_id
              AND status = 'active'
              AND (:tags_filter OR JSON_OVERLAPS(
                  JSON_EXTRACT(metadata, '$.tags'),
                  :tags_json
              ))
              AND (:no_start_date OR JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.read_date')) >= :start_date)
              AND (:no_end_date OR JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.read_date')) <= :end_date)
        """)

        # 准备参数
        import json
        params = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "tags_filter": not tags,  # 如果没有标签过滤，跳过标签条件
            "tags_json": json.dumps(tags) if tags else "[]",
            "no_start_date": start_date is None,
            "start_date": start_date.isoformat() if start_date else "",
            "no_end_date": end_date is None,
            "end_date": end_date.isoformat() if end_date else "",
        }

        # 执行查询
        result = session.execute(query, params)
        memory_ids = [row[0] for row in result.fetchall()]

        logger.info(
            "Metadata filter returned %d memory IDs: tenant=%s, user=%s, tags=%s, date_range=%s-%s",
            len(memory_ids),
            tenant_id,
            user_id,
            tags,
            start_date,
            end_date,
        )

        return memory_ids

    except Exception as e:
        logger.error(
            "Metadata filtering failed: tenant=%s, user=%s, tags=%s, date_range=%s-%s, error=%s",
            tenant_id,
            user_id,
            tags,
            start_date,
            end_date,
            str(e),
            exc_info=True,
        )
        # 过滤失败时返回 None，让检索继续（降级到全局检索）
        return None


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
