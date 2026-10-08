"""Qdrant V2 adapter for bench_memory_v2_runtime collection.

bench_memory_v2_runtime 是 Memory V2 真值的向量索引，可从 MySQL 重建。
与生产 mem0 collection 隔离。
"""

from __future__ import annotations

import os
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams, Filter, FieldCondition, MatchValue

from server.core.settings import Config_Bailian


def get_collection_name() -> str:
    """从 CollectionManager 获取collection名称（P2统一配置）"""
    from server.core.collection_manager import collection_manager
    return collection_manager.collection_name


class IndexV2:
    """Qdrant V2 索引适配器"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection_name: str | None = None,
        embedding_dim: int = 1536,
        validate_dimension: bool = True,
    ):
        """
        Args:
            host: Qdrant host，默认从 Config_Bailian 读取
            port: Qdrant port，默认从 Config_Bailian 读取
            collection_name: collection 名称，默认 bench_memory_v2_runtime
            embedding_dim: 向量维度，默认 1536（Qwen embedding）
            validate_dimension: 是否校验向量维度（upsert 时检查），默认 True
        """
        self.host = host or Config_Bailian.DB_VECTOR_QDRANT_HOST
        self.port = port or Config_Bailian.DB_VECTOR_QDRANT_PORT
        self.collection_name = collection_name or get_collection_name()
        self.embedding_dim = embedding_dim
        self.validate_dimension = validate_dimension

        self.client = QdrantClient(host=self.host, port=self.port)

    def create_collection_if_not_exists(self):
        """创建 collection（幂等）"""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
            )

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]):
        """插入或更新向量点"""
        if self.validate_dimension and len(vector) != self.embedding_dim:
            raise ValueError(
                f"Vector dimension mismatch: expected {self.embedding_dim}, got {len(vector)}"
            )
        point = PointStruct(id=point_id, vector=vector, payload=payload)
        self.client.upsert(collection_name=self.collection_name, points=[point])

    def delete(self, point_id: str):
        """删除向量点"""
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=[point_id],
        )

    def search(
        self,
        memory_type: str,
        query: str,
        top_k: int,
        query_vector: list[float] | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """语义检索（IndexProtocol 接口）。

        Args:
            memory_type: 记忆类型过滤（修复：现在使用 payload filter）
            query: 查询文本（当前未用，需 query_vector）
            top_k: 返回 top N
            query_vector: 查询向量（必须提供，因为 IndexV2 不含 embedder）
            tenant_id: 租户 ID（scope 过滤）
            user_id: 用户 ID（scope 过滤）

        Returns:
            [{memory_id, score, ...payload}, ...]，按相似度降序
        """
        if query_vector is None:
            raise ValueError("IndexV2.search requires query_vector (no built-in embedder)")

        if self.validate_dimension and len(query_vector) != self.embedding_dim:
            raise ValueError(
                f"Query vector dimension mismatch: expected {self.embedding_dim}, got {len(query_vector)}"
            )

        must_conditions = [
            FieldCondition(
                key="memory_type",
                match=MatchValue(value=memory_type)
            )
        ]

        # 添加租户和用户过滤（如果提供）
        if tenant_id:
            must_conditions.append(
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=tenant_id)
                )
            )

        if user_id:
            must_conditions.append(
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=str(user_id))  # 确保字符串匹配
                )
            )

        query_filter = Filter(must=must_conditions)

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,  # 修复：使用过滤条件
            limit=top_k,
        )
        results = response.points

        candidates = []
        for hit in results:
            payload = hit.payload or {}
            candidates.append({
                "memory_id": payload.get("memory_id", str(hit.id)),
                "score": hit.score,
                "user_id": payload.get("user_id"),
                "subject_id": payload.get("subject_id"),
                "text_zh": payload.get("text_zh", ""),
                "content": payload.get("content", payload.get("text_zh", "")),
                "fact_key": payload.get("fact_key"),
                "status": payload.get("status"),
                "memory_type": payload.get("memory_type"),  # 修复：返回 memory_type
            })
        return candidates

    def rebuild_from_records(self, records: list[dict[str, Any]]):
        """从 MySQL records 全量重建索引。

        Args:
            records: 每条记录包含 memory_id, text_zh, vector（已 embed 的向量）
        """
        # 清空现有索引
        self.client.delete_collection(collection_name=self.collection_name)
        self.create_collection_if_not_exists()

        # 批量写入
        points = [
            PointStruct(
                id=rec["memory_id"],
                vector=rec["vector"],
                payload={"text_zh": rec["text_zh"], "memory_id": rec["memory_id"]},
            )
            for rec in records
        ]
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
