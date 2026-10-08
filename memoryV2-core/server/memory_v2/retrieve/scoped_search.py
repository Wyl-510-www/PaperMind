"""
Scoped Retrieval - M3 批次

功能：
1. 按 tenant_id/user_id/namespace 过滤的检索
2. 防止其他用户的相似候选占满 Top-K
3. 支持 active=True 过滤

问题：
- 01 报告：48 个 Anchor 有提交，仅 36 个 Probe 有 Evidence
- 其他用户相似候选可能占满全局 Top-K

解决方案：
- Qdrant filter 先按 scope 过滤，再取 Top-K
"""

from typing import Optional
from pydantic import BaseModel


class SearchResult(BaseModel):
    """检索结果"""
    memory_id: str
    score: float
    payload: dict


class ScopedSearchConfig(BaseModel):
    """Scoped 检索配置"""
    tenant_id: str
    user_id: str
    namespace: str
    top_k: int = 10
    score_threshold: Optional[float] = None  # 可选的分数阈值
    include_inactive: bool = False  # 是否包含 active=False 的记录


class IndexV2:
    """M3 增强：Scoped 检索"""

    def __init__(self, qdrant_client, collection_name: str):
        self.qdrant_client = qdrant_client
        self.collection_name = collection_name

    async def search(
        self,
        query_vector: list[float],
        config: ScopedSearchConfig,
    ) -> list[SearchResult]:
        """Scoped 检索：先按 tenant/user/namespace 过滤，再 Top-K

        Args:
            query_vector: 查询向量
            config: Scoped 检索配置

        Returns:
            检索结果列表（已按 score 排序）

        核心逻辑：
        1. 构建 Qdrant filter（tenant/user/namespace/active）
        2. Qdrant 内部先过滤，再取 Top-K
        3. 返回本用户的 Top-K，不被其他用户占满
        """

        # 1. 构建 Qdrant filter
        must_conditions = [
            {"key": "tenant_id", "match": {"value": config.tenant_id}},
            {"key": "user_id", "match": {"value": config.user_id}},
            {"key": "namespace", "match": {"value": config.namespace}},
        ]

        # active 过滤（默认只返回 active=True）
        if not config.include_inactive:
            must_conditions.append(
                {"key": "active", "match": {"value": True}}
            )

        filter_condition = {"must": must_conditions}

        # 2. Qdrant 检索
        try:
            results = await self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=filter_condition,
                limit=config.top_k,
                score_threshold=config.score_threshold,
            )
        except Exception as e:
            # 检索失败时返回空列表
            import logging
            logging.exception(f"Qdrant search failed: {e}")
            return []

        # 3. 转换为 SearchResult
        search_results = [
            SearchResult(
                memory_id=r.payload["memory_id"],
                score=r.score,
                payload=r.payload,
            )
            for r in results
        ]

        return search_results

    async def search_multi_namespace(
        self,
        query_vector: list[float],
        tenant_id: str,
        user_id: str,
        namespaces: list[str],
        top_k: int = 10,
    ) -> dict[str, list[SearchResult]]:
        """跨多个 namespace 检索

        用于同时检索 user.profile、user.preference 等多个 namespace
        """
        results_by_namespace = {}

        for namespace in namespaces:
            config = ScopedSearchConfig(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
                top_k=top_k,
            )

            namespace_results = await self.search(query_vector, config)
            results_by_namespace[namespace] = namespace_results

        return results_by_namespace

    async def upsert_point(
        self,
        memory_id: str,
        vector: list[float],
        payload: dict,
    ) -> bool:
        """Upsert 单个 point 到 Qdrant

        用于 Benchmark 模式同步索引
        """
        try:
            await self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=[{
                    "id": memory_id,
                    "vector": vector,
                    "payload": payload,
                }],
            )
            return True
        except Exception as e:
            import logging
            logging.exception(f"Qdrant upsert failed for {memory_id}: {e}")
            return False

    async def delete_by_memory_ids(
        self,
        memory_ids: list[str],
    ) -> bool:
        """删除指定 memory_ids 的 points

        用于 DELETE 操作的索引同步
        """
        try:
            await self.qdrant_client.delete(
                collection_name=self.collection_name,
                points_selector={"ids": memory_ids},
            )
            return True
        except Exception as e:
            import logging
            logging.exception(f"Qdrant delete failed for {memory_ids}: {e}")
            return False


class ScopedRetriever:
    """M3 批次：完整的 Scoped 检索流程"""

    def __init__(
        self,
        index: IndexV2,
        embedding_service,
    ):
        self.index = index
        self.embedding_service = embedding_service

    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        user_id: str,
        namespace: str,
        top_k: int = 10,
    ) -> list[SearchResult]:
        """完整检索流程

        1. 生成 query embedding
        2. Scoped 检索
        3. 返回结果
        """

        # 1. 生成 embedding
        query_vector = await self.embedding_service.embed(query)

        # 2. Scoped 检索
        config = ScopedSearchConfig(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            top_k=top_k,
        )

        results = await self.index.search(query_vector, config)

        return results
