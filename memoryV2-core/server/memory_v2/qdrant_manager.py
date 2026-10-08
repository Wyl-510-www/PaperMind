"""Qdrant 客户端全局单例管理器

解决问题：
1. Qdrant 客户端在多处各自创建实例（检索侧、Outbox侧、建表时）
2. 配置可能不一致
3. 资源浪费

修复方案：
- 全局单例模式，应用启动时初始化一次
- 统一配置管理
- P1: 服务启动时自动检测并创建collection
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

logger = logging.getLogger(__name__)


class QdrantManager:
    """Qdrant 客户端全局单例"""

    _instance: Optional[QdrantManager] = None
    _client = None
    _collection_name: str = "memory_v2"
    _qdrant_url: str = "http://localhost:6333"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self):
        """初始化 Qdrant 客户端（应用启动时调用）"""
        if self._client is not None:
            logger.info("Qdrant 客户端已初始化，跳过")
            return

        # 从环境变量读取配置
        # 优先使用 MEMORY_V2_QDRANT_URL，兼容 QDRANT_URL
        self._qdrant_url = os.getenv("MEMORY_V2_QDRANT_URL") or os.getenv("QDRANT_URL", "http://localhost:6333")

        # P1: 从 CollectionManager 读取 collection 名称
        from server.core.collection_manager import collection_manager
        self._collection_name = collection_manager.collection_name

        # 初始化客户端
        self._client = QdrantClient(
            url=self._qdrant_url,
            timeout=30,
        )
        logger.info(
            "Qdrant 客户端初始化完成: url=%s collection=%s",
            self._qdrant_url,
            self._collection_name,
        )

    async def ensure_collection_exists(self) -> None:
        """
        P1: 确保collection存在，如不存在则自动创建

        功能：
        - 检查collection是否存在
        - 如已存在，记录INFO日志并返回（幂等性）
        - 如不存在，使用配置的向量维度创建collection
        - 连接失败时抛出RuntimeError，导致服务启动失败

        Raises:
            RuntimeError: Qdrant连接失败或创建collection失败
            ValueError: 向量维度配置错误
        """
        if self._client is None:
            self.initialize()

        # 读取向量维度配置并验证
        from server.memory_v2.config import config as memory_config
        try:
            memory_config.validate_embedding_dim()
            embedding_dim = memory_config.embedding_dimension
        except ValueError as e:
            logger.error(f"向量维度配置错误: {e}")
            raise

        try:
            # 检查collection是否存在
            collections = self._client.get_collections()
            existing_names = [c.name for c in collections.collections]

            if self._collection_name in existing_names:
                logger.info(f"Collection '{self._collection_name}' 已存在，跳过创建")
                return

            # 创建collection
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=embedding_dim,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                f"成功创建 collection: {self._collection_name} (vector_size={embedding_dim})"
            )

        except Exception as e:
            error_msg = f"无法连接或初始化Qdrant collection '{self._collection_name}': {e}"
            logger.error(f"Qdrant初始化失败: {e}")
            raise RuntimeError(error_msg) from e

    @property
    def client(self):
        """获取 Qdrant 客户端"""
        if self._client is None:
            self.initialize()
        return self._client

    @property
    def collection_name(self) -> str:
        """获取集合名称"""
        return self._collection_name


# 全局单例
qdrant_manager = QdrantManager()
