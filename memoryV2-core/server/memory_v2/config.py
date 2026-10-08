"""Memory V2 集中配置管理。

环境变量 → dataclass。gate 的 TTL 和置信度阈值由 gate 模块自己管理，不在此重复。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.lower() == "true"


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw is not None else default


@dataclass(frozen=True)
class MemoryV2Config:
    """Memory V2 全局配置 —— 仅管理灰度开关和环境可控参数"""

    # 一键灰度开关：MEMORY_V2_ENABLE=true 同时启用所有 V2 功能
    # 各独立开关优先级高于一键开关（可单独关闭子功能）
    enable_all: bool = _bool("MEMORY_V2_ENABLE", False)

    # 灰度开关（enable_all 为 true 时默认全部开启，仍可通过独立 env var 覆盖）
    write_enabled: bool = _bool(
        "MEMORY_V2_WRITE_ENABLED",
        _bool("MEMORY_V2_ENABLE", False),  # enable_all 时默认 true
    )
    read_enabled: bool = _bool(
        "MEMORY_V2_READ_ENABLED",
        _bool("MEMORY_V2_ENABLE", False),
    )
    shadow_read: bool = _bool("MEMORY_V2_SHADOW_READ", True)
    policy_enabled: bool = _bool(
        "MEMORY_V2_POLICY_ENABLED",
        _bool("MEMORY_V2_ENABLE", False),
    )

    # B4: 新增 Guard 开关
    claim_guard_enabled: bool = _bool(
        "MEMORY_V2_CLAIM_GUARD",
        _bool("MEMORY_V2_ENABLE", False),
    )
    policy_guard_enabled: bool = _bool(
        "MEMORY_V2_POLICY_GUARD",
        _bool("MEMORY_V2_ENABLE", False),
    )

    # B6: 新增 Benchmark 开关
    benchmark_mode: bool = _bool("BENCHMARK_MODE", False)
    benchmark_sync_memory: bool = _bool("BENCHMARK_SYNC_MEMORY", False)

    # Debug Trace 开关（仅测试环境）
    enable_debug_trace: bool = _bool("ENABLE_DEBUG_TRACE", False)
    debug_token: str = os.getenv("DEBUG_TOKEN", "")

    # 租户和时区
    default_tenant_id: str = os.getenv(
        "MEMORY_V2_TENANT_ID",
        "benchmark" if _bool("BENCHMARK_MODE", False) else "default"
    )
    timezone_name: str = os.getenv("MEMORY_TIMEZONE", "Asia/Shanghai")

    # 检索阈值（可通过环境变量覆盖）
    retrieval_min_score: float = _float("RETRIEVAL_MIN_SCORE", 0.45)
    rerank_min_score: float = _float("RERANK_MIN_SCORE", 0.15)
    candidate_limit: int = int(os.getenv("MEMORY_CANDIDATE_LIMIT", "30"))
    final_limit: int = int(os.getenv("MEMORY_FINAL_LIMIT", "5"))
    context_budget_tokens: int = int(os.getenv("MEMORY_CONTEXT_BUDGET_TOKENS", "600"))

    # B4: Qdrant 配置
    qdrant_url: str = os.getenv("MEMORY_V2_QDRANT_URL", "http://localhost:8701")

    # P1: 向量维度配置
    @property
    def embedding_dimension(self) -> int:
        """向量维度配置，默认1024（text-embedding-v4）"""
        return int(os.getenv("EMBEDDING_DIM", "1024"))

    @property
    def qdrant_collection_name(self) -> str:
        """从 CollectionManager 动态读取collection名称"""
        from server.core.collection_manager import collection_manager
        return collection_manager.collection_name

    def validate_embedding_dim(self) -> None:
        """验证向量维度配置是否在合法范围内"""
        dim = self.embedding_dimension
        if not (128 <= dim <= 4096):
            raise ValueError(
                f"EMBEDDING_DIM必须在[128, 4096]范围内，当前值: {dim}"
            )


config = MemoryV2Config()
