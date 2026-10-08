"""Outbox 消费者：定期消费 outbox 表的 pending 记录，同步到 Qdrant candidate_index。

背景：每次写入 MemoryRecord 时，同一 MySQL 事务里还会写一条 outbox 记录（status=pending），
相当于留了一张"待办便签"——"请把这条数据同步到 Qdrant"。本模块就是处理这些待办便签的后台任务。

⚠️ 当前仍使用 APScheduler BlockingScheduler（独立进程），AD R 0016 已决策改为 asyncio 后台任务
内嵌到 FastAPI lifespan。实施时本文件将重构为纯函数模块（process_outbox_batch），
调度循环移到 app.py lifespan。过渡期间保持现状不变。

依赖（必须配置）：
- MySQL（阿里云 RDS，见 CLAUDE.md）
- Qdrant（0.0.0.0:8701）
- BAILIAN_API_KEY（embedding 服务）

健康检查：
- 日志输出每批处理统计（done/failed/dead 计数）
- backlog 监控：若 pending 记录持续积压，需调大 batch_size 或增加 worker 实例
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.memory_v2.retrieve.embedder import RealEmbedder
from server.memory_v2.retrieve.index_v2 import IndexV2
from server.memory_v2.store.outbox import OutboxWorker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 调度参数
POLL_INTERVAL_SECONDS = 30  # 每 30 秒消费一批 outbox
BATCH_SIZE = 100  # 单批处理数量
WORKER_ID = None  # None = auto-generate (worker-{uuid})

# 数据库配置（从 server.database.database_bailian_config 读取，避免硬编码）
from server.database.database_bailian_config import Config

DB_URL = Config.Database_url

# Qdrant 配置（从 settings 读取）
from server.core.settings import Config_Bailian

QDRANT_HOST = Config_Bailian.DB_VECTOR_QDRANT_HOST
QDRANT_PORT = Config_Bailian.DB_VECTOR_QDRANT_PORT

# 全局状态
scheduler: BlockingScheduler | None = None
worker: OutboxWorker | None = None
session_factory: sessionmaker | None = None


async def run_outbox_async(interval_seconds: float = 30):
    """Phase 5B: asyncio 后台循环消费 outbox，可嵌入 FastAPI lifespan。

    每 interval_seconds 秒调用一次 OutboxWorker.process_pending()（通过 asyncio.to_thread）。
    """
    import asyncio

    logger.info("Outbox async worker started (interval=%ss)", interval_seconds)
    try:
        init_worker()
    except Exception:
        logger.exception("Outbox worker 初始化失败")
        return

    while True:
        try:
            processed = await asyncio.to_thread(worker.process_pending, BATCH_SIZE)
            if processed:
                logger.info("Outbox processed: done=%d failed=%d dead=%d",
                            processed.get("done", 0), processed.get("failed", 0), processed.get("dead", 0))
        except Exception:
            logger.exception("Outbox 消费异常（下一轮重试）")
        await asyncio.sleep(interval_seconds)


def init_worker():
    """初始化 worker 依赖（MySQL session、IndexV2、RealEmbedder）"""
    global worker, session_factory

    logger.info("Initializing OutboxWorker...")
    logger.info(f"  DB: {DB_URL[:30]}...")
    logger.info(f"  Qdrant: {QDRANT_HOST}:{QDRANT_PORT}")
    logger.info(f"  Batch size: {BATCH_SIZE}, Poll interval: {POLL_INTERVAL_SECONDS}s")

    # MySQL session
    engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=3600)
    session_factory = sessionmaker(bind=engine)

    # IndexV2（真实 Qdrant）
    index = IndexV2(host=QDRANT_HOST, port=QDRANT_PORT)
    index.create_collection_if_not_exists()
    logger.info(f"  Qdrant collection: {index.collection_name}")

    # RealEmbedder（真实 embedding 服务）
    embedder = RealEmbedder()
    embedder.validate_dimension(index.embedding_dim)
    logger.info(f"  Embedder model: {embedder.model}, dim: {embedder.dimensions}")

    # OutboxWorker
    session = session_factory()
    worker = OutboxWorker(
        session=session,
        index=index,
        embedder=embedder,
        worker_id=WORKER_ID,
    )
    logger.info(f"  Worker ID: {worker.worker_id}")
    logger.info("OutboxWorker initialized.")


def process_batch():
    """调度器每次触发时执行：消费一批 outbox 记录"""
    if worker is None:
        logger.error("Worker not initialized!")
        return

    try:
        start = time.time()
        stats = worker.process_pending(batch_size=BATCH_SIZE)
        elapsed = time.time() - start

        logger.info(
            f"Processed batch: done={stats['done']}, failed={stats['failed']}, "
            f"dead={stats['dead']}, elapsed={elapsed:.2f}s"
        )

        # 如果有 dead 记录，警告（需人工介入）
        if stats["dead"] > 0:
            logger.warning(f"Dead-letter detected: {stats['dead']} records reached max retries")

    except Exception as e:
        logger.exception(f"Batch processing failed: {e}")


def shutdown_handler(signum, frame):
    """优雅关闭：停止调度器"""
    logger.info(f"Received signal {signum}, shutting down...")
    if scheduler:
        scheduler.shutdown(wait=True)
    sys.exit(0)


def main():
    """启动 APScheduler，定期消费 outbox"""
    global scheduler

    # 注册信号处理器（SIGTERM/SIGINT）
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # 初始化 worker
    init_worker()

    # 启动调度器
    scheduler = BlockingScheduler()
    scheduler.add_job(
        process_batch,
        "interval",
        seconds=POLL_INTERVAL_SECONDS,
        id="outbox_worker",
        max_instances=1,  # 同时只运行一个实例（防止批次重叠）
    )

    logger.info("Starting APScheduler...")
    logger.info("Press Ctrl+C to stop.")
    scheduler.start()


if __name__ == "__main__":
    main()
