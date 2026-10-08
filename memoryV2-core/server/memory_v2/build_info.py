"""BuildInfo：服务构建信息

批次 C2：BuildInfo 补充
- 服务加载时身份
- instance/start 时间
- 契约/schema
- 实际配置
"""

from __future__ import annotations

import os
import socket
import subprocess
from datetime import datetime


class BuildInfo:
    """服务构建信息"""

    @staticmethod
    def get_build_info() -> dict:
        """获取构建信息"""

        return {
            # Git 身份
            "git_commit": BuildInfo.get_git_commit(),
            "git_branch": BuildInfo.get_git_branch(),
            "git_dirty": BuildInfo.is_git_dirty(),

            # 服务身份
            "service_name": "memory_v2",
            "version": "2.0.0",
            "build_time": BuildInfo.get_build_timestamp(),

            # 实例信息
            "instance_id": os.getenv("INSTANCE_ID", socket.gethostname()),
            "started_at": datetime.utcnow().isoformat(),

            # 契约版本
            "api_version": "v2",
            "schema_version": "2.0",

            # 配置摘要（脱敏）
            "config_snapshot": BuildInfo.get_config_snapshot(),
        }

    @staticmethod
    def get_git_commit() -> str:
        """获取当前 Git commit"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    @staticmethod
    def get_git_branch() -> str:
        """获取当前 Git 分支"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    @staticmethod
    def is_git_dirty() -> bool:
        """检查 Git 工作目录是否有未提交的修改"""
        try:
            result = subprocess.run(
                ["git", "diff", "--quiet"],
                check=False,
                timeout=5,
            )
            # diff --quiet 返回 0 表示无修改，返回 1 表示有修改
            return result.returncode != 0
        except Exception:
            return False

    @staticmethod
    def get_build_timestamp() -> str:
        """获取构建时间戳"""
        # 尝试从环境变量获取（CI/CD 构建时设置）
        build_time = os.getenv("BUILD_TIMESTAMP")
        if build_time:
            return build_time

        # 否则使用当前时间
        return datetime.utcnow().isoformat()

    @staticmethod
    def get_config_snapshot() -> dict:
        """获取配置快照（脱敏）"""
        try:
            from server.memory_v2.startup_checks import ConfigValidator

            validator = ConfigValidator()
            snapshot = validator._generate_snapshot()

            return {
                "timestamp": snapshot.timestamp,
                "python_version": snapshot.python_version.split()[0],  # 只保留版本号
                "db_source": snapshot.db_config["source"],
                "qdrant_source": snapshot.qdrant_config["source"],
                "llm_provider": snapshot.llm_provider,
            }
        except Exception as e:
            return {
                "error": f"Failed to generate config snapshot: {e}",
            }


def get_build_info_summary() -> str:
    """获取构建信息摘要（单行）"""
    info = BuildInfo.get_build_info()
    return (
        f"memory_v2 v{info['version']} "
        f"(commit: {info['git_commit'][:8]}, "
        f"branch: {info['git_branch']}, "
        f"instance: {info['instance_id']})"
    )
