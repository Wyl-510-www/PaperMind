"""Memory V2 运行时监控和 Metrics 收集模块

功能：
1. W层成功率统计
2. R层召回率统计
3. 性能监控（P99延迟）
4. 错误统计和告警
5. 实时 metrics 输出

使用方式：
    from server.memory_v2.monitoring import metrics_collector

    # 记录写入成功
    metrics_collector.record_write_success(elapsed_ms=100.5)

    # 记录写入失败
    metrics_collector.record_write_failure(error_type='extraction_failed')

    # 获取统计数据
    stats = metrics_collector.get_stats()
"""

from __future__ import annotations

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional
import statistics

logger = logging.getLogger(__name__)


@dataclass
class LatencyStats:
    """延迟统计"""
    samples: List[float] = field(default_factory=list)
    max_samples: int = 1000  # 保留最近1000个样本

    def add(self, latency_ms: float):
        """添加延迟样本"""
        self.samples.append(latency_ms)
        if len(self.samples) > self.max_samples:
            self.samples.pop(0)

    def get_percentile(self, p: float) -> float:
        """获取百分位延迟"""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        index = int(len(sorted_samples) * p / 100)
        return sorted_samples[min(index, len(sorted_samples) - 1)]

    def get_avg(self) -> float:
        """获取平均延迟"""
        if not self.samples:
            return 0.0
        return statistics.mean(self.samples)

    def get_stats(self) -> dict:
        """获取完整统计"""
        if not self.samples:
            return {
                "count": 0,
                "avg": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "max": 0.0,
            }
        return {
            "count": len(self.samples),
            "avg": self.get_avg(),
            "p50": self.get_percentile(50),
            "p95": self.get_percentile(95),
            "p99": self.get_percentile(99),
            "max": max(self.samples),
        }


@dataclass
class ErrorCounter:
    """错误计数器"""
    errors_by_type: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    recent_errors: List[dict] = field(default_factory=list)
    max_recent: int = 100

    def record(self, error_type: str, error_msg: str = "", context: dict = None):
        """记录错误"""
        self.errors_by_type[error_type] += 1

        error_record = {
            "type": error_type,
            "message": error_msg[:200],  # 限制长度
            "timestamp": datetime.utcnow().isoformat(),
            "context": context or {}
        }

        self.recent_errors.append(error_record)
        if len(self.recent_errors) > self.max_recent:
            self.recent_errors.pop(0)

    def get_stats(self) -> dict:
        """获取错误统计"""
        return {
            "errors_by_type": dict(self.errors_by_type),
            "total_errors": sum(self.errors_by_type.values()),
            "recent_errors": self.recent_errors[-10:],  # 最近10个
        }


class MetricsCollector:
    """Memory V2 Metrics 收集器"""

    def __init__(self):
        self._lock = Lock()
        self._start_time = time.time()

        # W层统计
        self.write_total = 0
        self.write_success = 0
        self.write_latency = LatencyStats()
        self.write_errors = ErrorCounter()

        # R层统计
        self.read_total = 0
        self.read_success = 0  # 召回到记忆的次数
        self.read_empty = 0    # 未召回到记忆的次数
        self.read_latency = LatencyStats()
        self.read_errors = ErrorCounter()

        # 各 lane 统计
        self.lane_stats = defaultdict(lambda: {"total": 0, "success": 0})

        # Speech Act 统计
        self.speech_act_stats = defaultdict(int)

        # 告警阈值
        self.alert_thresholds = {
            "write_error_rate": 0.1,      # 写入错误率 > 10%
            "read_error_rate": 0.1,       # 读取错误率 > 10%
            "write_latency_p99": 5000.0,  # P99延迟 > 5秒
            "read_latency_p99": 3000.0,   # P99延迟 > 3秒
        }

        # 告警记录
        self.alerts = []
        self.max_alerts = 50

    def record_write_start(self) -> float:
        """记录写入开始，返回开始时间戳"""
        return time.time()

    def record_write_success(
        self,
        elapsed_ms: float,
        lane: Optional[str] = None,
        speech_act: Optional[str] = None,
        candidates_total: int = 0,
        candidates_accepted: int = 0,
    ):
        """记录写入成功"""
        with self._lock:
            self.write_total += 1
            self.write_success += 1
            self.write_latency.add(elapsed_ms)

            if lane:
                self.lane_stats[lane]["total"] += 1
                self.lane_stats[lane]["success"] += 1

            if speech_act:
                self.speech_act_stats[speech_act] += 1

            # 检查延迟告警
            self._check_write_latency_alert(elapsed_ms)

            logger.info(
                f"V2_METRICS_WRITE: success=true elapsed_ms={elapsed_ms:.1f} "
                f"lane={lane} candidates={candidates_accepted}/{candidates_total}"
            )

    def record_write_failure(
        self,
        elapsed_ms: float = 0.0,
        error_type: str = "unknown",
        error_msg: str = "",
        lane: Optional[str] = None,
        context: dict = None,
    ):
        """记录写入失败"""
        with self._lock:
            self.write_total += 1
            self.write_errors.record(error_type, error_msg, context)

            if elapsed_ms > 0:
                self.write_latency.add(elapsed_ms)

            if lane:
                self.lane_stats[lane]["total"] += 1

            # 检查错误率告警
            self._check_write_error_rate_alert()

            logger.error(
                f"V2_METRICS_WRITE: success=false error_type={error_type} "
                f"error_msg={error_msg[:100]} lane={lane}"
            )

    def record_read_start(self) -> float:
        """记录读取开始，返回开始时间戳"""
        return time.time()

    def record_read_success(
        self,
        elapsed_ms: float,
        memories_count: int = 0,
        query: str = "",
    ):
        """记录读取成功（正常完成，无异常）"""
        with self._lock:
            self.read_total += 1
            self.read_success += 1  # 只要正常完成就算成功
            if memories_count > 0:
                pass  # 有召回到记忆
            else:
                self.read_empty += 1  # 没召回到记忆（但仍然是成功的调用）

            self.read_latency.add(elapsed_ms)

            # 检查延迟告警
            self._check_read_latency_alert(elapsed_ms)

            logger.info(
                f"V2_METRICS_READ: success=true elapsed_ms={elapsed_ms:.1f} "
                f"memories_count={memories_count} query={query[:50]}"
            )

    def record_read_failure(
        self,
        elapsed_ms: float = 0.0,
        error_type: str = "unknown",
        error_msg: str = "",
        context: dict = None,
    ):
        """记录读取失败"""
        with self._lock:
            self.read_total += 1
            self.read_errors.record(error_type, error_msg, context)

            if elapsed_ms > 0:
                self.read_latency.add(elapsed_ms)

            # 检查错误率告警
            self._check_read_error_rate_alert()

            logger.error(
                f"V2_METRICS_READ: success=false error_type={error_type} "
                f"error_msg={error_msg[:100]}"
            )

    def _check_write_error_rate_alert(self):
        """检查写入错误率告警"""
        if self.write_total < 10:  # 样本量太小不告警
            return

        error_rate = (self.write_total - self.write_success) / self.write_total
        threshold = self.alert_thresholds["write_error_rate"]

        if error_rate > threshold:
            self._add_alert(
                level="ERROR",
                message=f"写入错误率过高: {error_rate:.1%} > {threshold:.1%}",
                metric="write_error_rate",
                value=error_rate,
            )

    def _check_read_error_rate_alert(self):
        """检查读取错误率告警"""
        if self.read_total < 10:
            return

        error_count = self.read_errors.errors_by_type
        total_errors = sum(error_count.values())
        error_rate = total_errors / self.read_total if self.read_total > 0 else 0
        threshold = self.alert_thresholds["read_error_rate"]

        if error_rate > threshold:
            self._add_alert(
                level="ERROR",
                message=f"读取错误率过高: {error_rate:.1%} > {threshold:.1%}",
                metric="read_error_rate",
                value=error_rate,
            )

    def _check_write_latency_alert(self, latency_ms: float):
        """检查写入延迟告警"""
        p99 = self.write_latency.get_percentile(99)
        threshold = self.alert_thresholds["write_latency_p99"]

        if p99 > threshold:
            self._add_alert(
                level="WARNING",
                message=f"写入P99延迟过高: {p99:.1f}ms > {threshold:.1f}ms",
                metric="write_latency_p99",
                value=p99,
            )

    def _check_read_latency_alert(self, latency_ms: float):
        """检查读取延迟告警"""
        p99 = self.read_latency.get_percentile(99)
        threshold = self.alert_thresholds["read_latency_p99"]

        if p99 > threshold:
            self._add_alert(
                level="WARNING",
                message=f"读取P99延迟过高: {p99:.1f}ms > {threshold:.1f}ms",
                metric="read_latency_p99",
                value=p99,
            )

    def _add_alert(self, level: str, message: str, metric: str, value: float):
        """添加告警"""
        alert = {
            "level": level,
            "message": message,
            "metric": metric,
            "value": value,
            "timestamp": datetime.utcnow().isoformat(),
        }

        self.alerts.append(alert)
        if len(self.alerts) > self.max_alerts:
            self.alerts.pop(0)

        logger.warning(f"V2_ALERT: {level} {message} metric={metric} value={value:.3f}")

    def get_stats(self) -> dict:
        """获取完整统计数据"""
        with self._lock:
            uptime_seconds = time.time() - self._start_time

            # 计算成功率
            write_success_rate = (
                self.write_success / self.write_total if self.write_total > 0 else 0.0
            )
            read_recall_rate = (
                self.read_success / self.read_total if self.read_total > 0 else 0.0
            )

            return {
                "uptime_seconds": uptime_seconds,
                "timestamp": datetime.utcnow().isoformat(),

                # W层统计
                "write": {
                    "total": self.write_total,
                    "success": self.write_success,
                    "success_rate": write_success_rate,
                    "latency": self.write_latency.get_stats(),
                    "errors": self.write_errors.get_stats(),
                },

                # R层统计
                "read": {
                    "total": self.read_total,
                    "success": self.read_success,
                    "empty": self.read_empty,
                    "recall_rate": read_recall_rate,
                    "latency": self.read_latency.get_stats(),
                    "errors": self.read_errors.get_stats(),
                },

                # Lane 统计
                "lanes": dict(self.lane_stats),

                # Speech Act 统计
                "speech_acts": dict(self.speech_act_stats),

                # 告警
                "alerts": {
                    "total": len(self.alerts),
                    "recent": self.alerts[-5:],  # 最近5个
                },
            }

    def get_summary(self) -> str:
        """获取简短摘要（用于日志）"""
        stats = self.get_stats()
        return (
            f"W: {stats['write']['success']}/{stats['write']['total']} "
            f"({stats['write']['success_rate']:.1%}) "
            f"P99={stats['write']['latency']['p99']:.0f}ms | "
            f"R: {stats['read']['success']}/{stats['read']['total']} "
            f"({stats['read']['recall_rate']:.1%}) "
            f"P99={stats['read']['latency']['p99']:.0f}ms"
        )

    def reset(self):
        """重置所有统计（用于测试）"""
        with self._lock:
            self._start_time = time.time()
            self.write_total = 0
            self.write_success = 0
            self.write_latency = LatencyStats()
            self.write_errors = ErrorCounter()
            self.read_total = 0
            self.read_success = 0
            self.read_empty = 0
            self.read_latency = LatencyStats()
            self.read_errors = ErrorCounter()
            self.lane_stats.clear()
            self.speech_act_stats.clear()
            self.alerts.clear()


# 全局单例
metrics_collector = MetricsCollector()


def get_metrics() -> dict:
    """获取当前 metrics（便捷函数）"""
    return metrics_collector.get_stats()


def get_metrics_summary() -> str:
    """获取 metrics 摘要（便捷函数）"""
    return metrics_collector.get_summary()
