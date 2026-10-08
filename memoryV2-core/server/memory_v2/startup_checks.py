"""启动校验：统一配置校验器

批次 C1：启动校验统一配置
- 读取生产真正使用的配置对象
- 统一 DB_*、V2 数据库 URL、Qdrant 入口和模型角色
- 配置快照脱敏处理
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ConfigSnapshot:
    """配置快照（脱敏）"""
    timestamp: str
    python_version: str
    db_config: dict
    qdrant_config: dict
    llm_provider: str


class ConfigValidator:
    """统一配置校验器"""

    def __init__(self):
        # 读取实际配置
        self.db_config = self._load_db_config()
        self.qdrant_config = self._load_qdrant_config()
        self.llm_config = self._load_llm_config()

    def _load_db_config(self) -> dict:
        """加载数据库配置 - 统一多种入口"""

        # 优先 V2 URL
        db_url = os.getenv("MEMORY_V2_DB_URL")
        if db_url:
            return {"source": "MEMORY_V2_DB_URL", "url": db_url}

        # 其次 DB_* 变量
        host = os.getenv("DB_HOST")
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASS")
        db_name = os.getenv("DB_NAME", "memory_v2")
        port = os.getenv("DB_PORT", "3306")

        if all([host, user, password]):
            return {
                "source": "DB_*",
                "host": host,
                "user": user,
                "db": db_name,
                "port": port,
                "password": password,  # 内部使用，不在快照中暴露
            }

        raise ValueError("No valid database configuration found")

    def _load_qdrant_config(self) -> dict:
        """加载 Qdrant 配置"""

        # URL 模式
        qdrant_url = os.getenv("QDRANT_URL")
        if qdrant_url:
            return {"source": "QDRANT_URL", "url": qdrant_url}

        # Host/Port 模式
        host = os.getenv("QDRANT_HOST", "localhost")
        port = os.getenv("QDRANT_PORT", "6333")

        return {"source": "QDRANT_HOST_PORT", "host": host, "port": port}

    def _load_llm_config(self) -> dict:
        """加载 LLM 配置"""

        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY not found")

        return {
            "provider": "DashScope",
            "api_key": api_key,  # 内部使用，不在快照中暴露
        }

    def validate_all(self) -> ConfigSnapshot:
        """验证所有配置"""

        errors = []

        # 数据库连接测试
        try:
            self._test_db_connection()
        except Exception as e:
            errors.append(f"Database: {e}")

        # Qdrant 连接测试
        try:
            self._test_qdrant_connection()
        except Exception as e:
            errors.append(f"Qdrant: {e}")

        # LLM 凭据检查
        try:
            self._validate_llm_credentials()
        except Exception as e:
            errors.append(f"LLM: {e}")

        if errors:
            raise ValueError(f"Configuration validation failed: {errors}")

        # 生成快照（脱敏）
        return self._generate_snapshot()

    def _test_db_connection(self):
        """测试数据库连接"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # 尝试建立数据库连接
            if self.db_config.get("source") == "MEMORY_V2_DB_URL":
                # URL 模式
                from sqlalchemy import create_engine
                engine = create_engine(self.db_config["url"])
                with engine.connect() as conn:
                    conn.execute("SELECT 1")
                logger.info("Database connection test passed (URL mode)")
            else:
                # DB_* 模式
                import pymysql
                connection = pymysql.connect(
                    host=self.db_config["host"],
                    user=self.db_config["user"],
                    password=self.db_config["password"],
                    database=self.db_config["db"],
                    port=int(self.db_config["port"]),
                )
                connection.close()
                logger.info("Database connection test passed (DB_* mode)")
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            raise

    def _test_qdrant_connection(self):
        """测试 Qdrant 连接"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            from qdrant_client import QdrantClient

            if self.qdrant_config.get("source") == "QDRANT_URL":
                client = QdrantClient(url=self.qdrant_config["url"])
            else:
                client = QdrantClient(
                    host=self.qdrant_config["host"],
                    port=int(self.qdrant_config["port"]),
                )

            # 尝试获取集合列表
            client.get_collections()
            logger.info("Qdrant connection test passed")
        except Exception as e:
            logger.error(f"Qdrant connection test failed: {e}")
            raise

    def _validate_llm_credentials(self):
        """验证 LLM 凭据"""
        import logging
        logger = logging.getLogger(__name__)

        # 简单检查 API Key 格式
        api_key = self.llm_config["api_key"]
        if not api_key or len(api_key) < 10:
            raise ValueError("Invalid DASHSCOPE_API_KEY format")

        logger.info("LLM credentials validation passed")

    def _generate_snapshot(self) -> ConfigSnapshot:
        """生成配置快照（脱敏）"""

        return ConfigSnapshot(
            timestamp=datetime.utcnow().isoformat(),
            python_version=sys.version,
            db_config={
                "source": self.db_config["source"],
                "host": self.db_config.get("host", "***"),  # 脱敏
                "db": self.db_config.get("db", "***"),
                # 不包含密码、用户名
            },
            qdrant_config={
                "source": self.qdrant_config["source"],
                "host": self.qdrant_config.get("host", "***"),
                "port": self.qdrant_config.get("port", "***"),
            },
            llm_provider="DashScope",  # 不包含 API Key
        )


def run_startup_checks() -> ConfigSnapshot:
    """运行启动检查"""
    import logging
    logger = logging.getLogger(__name__)

    logger.info("Starting configuration validation...")

    validator = ConfigValidator()
    snapshot = validator.validate_all()

    logger.info("Configuration validation passed")
    logger.info(f"Snapshot: {snapshot}")

    return snapshot
