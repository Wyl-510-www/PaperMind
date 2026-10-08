"""全局数据库连接池管理器

解决问题：
1. 每次写入都新建引擎，导致连接池泄漏
2. 多套连接池互不共享，浪费资源
3. 生产环境持续写入会耗尽数据库连接数

修复方案：
- 全局单例模式，应用启动时初始化一次
- 同时管理同步和异步引擎
- 统一配置连接池参数
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from server.database.database_bailian_config import Config as DBConfig

logger = logging.getLogger(__name__)


class DatabaseConnectionPool:
    """全局数据库连接池管理器（单例）"""

    _instance: Optional[DatabaseConnectionPool] = None
    _sync_engine = None
    _async_engine = None
    _sync_session_factory = None
    _async_session_factory = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self):
        """初始化连接池（应用启动时调用一次）"""
        if self._sync_engine is not None:
            logger.info("数据库连接池已初始化，跳过")
            return

        # 同步引擎（配置连接池参数）
        self._sync_engine = create_engine(
            DBConfig.Database_url,
            pool_size=20,           # 连接池大小
            max_overflow=10,        # 溢出连接数
            pool_recycle=3600,      # 连接回收时间（秒）
            pool_pre_ping=True,     # 连接前检查可用性
            echo=False,
        )
        self._sync_session_factory = sessionmaker(
            bind=self._sync_engine,
            expire_on_commit=False,
        )

        # 异步引擎
        async_db_url = DBConfig.Database_url.replace(
            'mysql+pymysql://',
            'mysql+aiomysql://'
        )
        self._async_engine = create_async_engine(
            async_db_url,
            pool_size=20,
            max_overflow=10,
            pool_recycle=3600,
            pool_pre_ping=True,
            echo=False,
        )
        self._async_session_factory = async_sessionmaker(
            self._async_engine,
            expire_on_commit=False,
        )

        logger.info("数据库连接池初始化完成")

    @property
    def sync_session_factory(self):
        """获取同步 Session 工厂"""
        if self._sync_session_factory is None:
            self.initialize()
        return self._sync_session_factory

    @property
    def async_session_factory(self):
        """获取异步 Session 工厂"""
        if self._async_session_factory is None:
            self.initialize()
        return self._async_session_factory

    def dispose(self):
        """释放连接池（应用关闭时调用）"""
        if self._sync_engine:
            self._sync_engine.dispose()
            logger.info("同步引擎已释放")
        if self._async_engine:
            # 异步引擎需要在事件循环中关闭
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._async_engine.dispose())
            except RuntimeError:
                # 如果没有运行中的事件循环，同步关闭
                asyncio.run(self._async_engine.dispose())
            logger.info("异步引擎已释放")


# 全局单例
db_pool = DatabaseConnectionPool()
