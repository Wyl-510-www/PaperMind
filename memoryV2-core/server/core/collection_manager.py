"""
CollectionManager - 统一的Collection配置管理器

功能：
1. 统一管理collection名称配置
2. 支持显式配置和动态生成
3. 提供测试collection判断和安全检查
4. 向后兼容legacy配置

使用示例：
    from server.core.collection_manager import collection_manager

    # 获取当前collection名称
    name = collection_manager.collection_name

    # 判断是否为测试collection
    if collection_manager.is_test_collection():
        print("当前使用测试collection")

    # 安全检查（清理前）
    if collection_manager.is_safe_for_cleanup(some_name):
        # 执行清理操作
        pass

配置优先级：
    COLLECTION_NAME > MEMORY_V2_COLLECTION_NAME > MEM0_COLLECTION_NAME > 动态生成

环境变量：
    COLLECTION_NAME: 推荐使用的统一配置
    MEMORY_V2_COLLECTION_NAME: 已废弃，保留兼容
    MEM0_COLLECTION_NAME: 已废弃，保留兼容
"""

from datetime import datetime
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CollectionManager:
    """
    Collection配置管理器（单例模式）

    负责：
    - 从环境变量读取或动态生成collection名称
    - 写入环境变量供子模块使用
    - 提供测试collection判断逻辑
    - 提供安全清理检查
    """

    _instance: Optional['CollectionManager'] = None

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化CollectionManager（仅执行一次）"""
        if self._initialized:
            return

        self._collection_name = self._resolve_collection_name()

        # 写入环境变量供子模块读取
        os.environ["COLLECTION_NAME"] = self._collection_name

        self._initialized = True

        logger.info(
            f"CollectionManager initialized: {self._collection_name} "
            f"(test={self.is_test_collection()})"
        )

    def _resolve_collection_name(self) -> str:
        """
        解析collection名称

        优先级：
        1. COLLECTION_NAME（推荐）
        2. MEMORY_V2_COLLECTION_NAME（废弃，保留兼容）
        3. MEM0_COLLECTION_NAME（废弃，保留兼容）
        4. 动态生成 collection_test_{YYYYMMDDHHMM}

        Returns:
            str: 解析后的collection名称
        """
        # 优先级1: COLLECTION_NAME
        collection_name = os.getenv("COLLECTION_NAME")
        if collection_name:
            logger.info(f"使用显式配置: COLLECTION_NAME={collection_name}")
            return collection_name

        # 优先级2: MEMORY_V2_COLLECTION_NAME（废弃）
        v2_name = os.getenv("MEMORY_V2_COLLECTION_NAME")
        if v2_name:
            logger.warning(
                f"使用废弃配置: MEMORY_V2_COLLECTION_NAME={v2_name}. "
                "请迁移到 COLLECTION_NAME"
            )
            return v2_name

        # 优先级3: MEM0_COLLECTION_NAME（废弃）
        mem0_name = os.getenv("MEM0_COLLECTION_NAME")
        if mem0_name:
            logger.warning(
                f"使用废弃配置: MEM0_COLLECTION_NAME={mem0_name}. "
                "请迁移到 COLLECTION_NAME"
            )
            return mem0_name

        # 优先级4: 动态生成
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M")
        generated_name = f"collection_test_{timestamp}"
        logger.info(f"动态生成collection名称: {generated_name}")
        return generated_name

    @property
    def collection_name(self) -> str:
        """
        获取当前collection名称（只读）

        Returns:
            str: collection名称
        """
        return self._collection_name

    def is_test_collection(self, name: Optional[str] = None) -> bool:
        """
        判断是否为测试collection

        规则：
        - 以 'bench_' 开头 → 测试collection
        - 以 'collection_test_' 开头 → 测试collection
        - 等于 'mem0' → 生产collection
        - 其他 → 生产collection

        Args:
            name: collection名称，默认使用当前collection

        Returns:
            bool: True表示测试collection，False表示生产collection
        """
        target_name = name if name is not None else self._collection_name

        # 测试collection前缀
        test_prefixes = ('bench_', 'collection_test_')

        return target_name.startswith(test_prefixes)

    def is_safe_for_cleanup(self, name: Optional[str] = None) -> bool:
        """
        判断是否可安全清理

        规则：
        - 必须是测试collection
        - 生产collection 'mem0' 禁止清理

        Args:
            name: collection名称，默认使用当前collection

        Returns:
            bool: True表示可安全清理

        Raises:
            ValueError: 尝试清理生产collection时抛出异常
        """
        target_name = name if name is not None else self._collection_name

        # 硬保护：禁止清理生产collection
        if target_name == 'mem0':
            raise ValueError(
                f"禁止清理生产collection: {target_name}. "
                "这是安全保护机制。"
            )

        # 只允许清理测试collection
        is_safe = self.is_test_collection(target_name)

        if not is_safe:
            logger.warning(
                f"Collection '{target_name}' 不是测试collection，清理风险较高"
            )

        return is_safe

    def reset(self):
        """
        重置单例实例（仅供测试使用）

        警告：此方法会清空单例状态，仅应在测试环境中使用
        """
        self._initialized = False
        CollectionManager._instance = None
        logger.debug("CollectionManager已重置（测试模式）")


# 全局单例实例
collection_manager = CollectionManager()
