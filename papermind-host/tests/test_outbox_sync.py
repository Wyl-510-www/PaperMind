"""Outbox sync 模块测试。

测试覆盖：
1. 同步统计透传（UT-07）
2. 空批次处理（UT-07）
3. 部分失败返回 failed 状态（UT-07）
4. 批次异常处理（UT-07）
5. 输入验证（batch_size 非正数）
6. 数据库 session 释放（UT-08）
"""

import pytest
from unittest.mock import MagicMock, patch
from papermind.outbox_sync import sync_outbox_batch, SyncResult


class TestSyncStatistics:
    """测试同步统计处理。"""

    @pytest.mark.asyncio
    async def test_all_done_returns_completed(self):
        """UT-07: 全部成功返回 completed。"""
        with patch('papermind.outbox_sync._process_batch') as mock_process:
            mock_process.return_value = {"done": 5, "failed": 0, "dead": 0}

            result = await sync_outbox_batch(batch_size=10)

            assert result.status == "completed"
            assert result.done == 5
            assert result.failed == 0
            assert result.dead == 0
            assert "5 条" in result.message

    @pytest.mark.asyncio
    async def test_empty_batch_returns_completed(self):
        """UT-07: 空批次返回 completed，不宣称当前笔记已可检索。"""
        with patch('papermind.outbox_sync._process_batch') as mock_process:
            mock_process.return_value = {"done": 0, "failed": 0, "dead": 0}

            result = await sync_outbox_batch(batch_size=10)

            assert result.status == "completed"
            assert result.done == 0
            assert result.failed == 0
            assert result.dead == 0
            assert "为空" in result.message

    @pytest.mark.asyncio
    async def test_partial_failure_returns_failed(self):
        """UT-07: 部分失败返回 failed，保留 done 统计。"""
        with patch('papermind.outbox_sync._process_batch') as mock_process:
            mock_process.return_value = {"done": 3, "failed": 2, "dead": 0}

            result = await sync_outbox_batch(batch_size=10)

            assert result.status == "failed"
            assert result.done == 3
            assert result.failed == 2
            assert result.dead == 0
            assert "部分完成" in result.message
            assert "3 条成功" in result.message
            assert "2 条失败" in result.message

    @pytest.mark.asyncio
    async def test_all_failed_returns_failed(self):
        """UT-07: 全部失败返回 failed。"""
        with patch('papermind.outbox_sync._process_batch') as mock_process:
            mock_process.return_value = {"done": 0, "failed": 5, "dead": 0}

            result = await sync_outbox_batch(batch_size=10)

            assert result.status == "failed"
            assert result.done == 0
            assert result.failed == 5
            assert result.dead == 0
            assert "同步失败" in result.message

    @pytest.mark.asyncio
    async def test_dead_records_returns_failed(self):
        """UT-07: 存在 dead 记录返回 failed。"""
        with patch('papermind.outbox_sync._process_batch') as mock_process:
            mock_process.return_value = {"done": 2, "failed": 1, "dead": 2}

            result = await sync_outbox_batch(batch_size=10)

            assert result.status == "failed"
            assert result.done == 2
            assert result.failed == 1
            assert result.dead == 2
            assert "2 条 dead" in result.message


class TestExceptionHandling:
    """测试异常处理。"""

    @pytest.mark.asyncio
    async def test_batch_exception_returns_failed(self):
        """UT-07: 批次处理异常返回 failed。"""
        with patch('papermind.outbox_sync._process_batch') as mock_process:
            mock_process.side_effect = RuntimeError("Database connection error")

            result = await sync_outbox_batch(batch_size=10)

            assert result.status == "failed"
            assert result.done == 0
            assert result.failed == 0
            assert result.dead == 0
            assert "系统错误" in result.message


class TestInputValidation:
    """测试输入验证。"""

    @pytest.mark.asyncio
    async def test_zero_batch_size_returns_failed(self):
        """batch_size=0 返回 failed。"""
        result = await sync_outbox_batch(batch_size=0)

        assert result.status == "failed"
        assert "必须为正整数" in result.message

    @pytest.mark.asyncio
    async def test_negative_batch_size_returns_failed(self):
        """batch_size<0 返回 failed。"""
        result = await sync_outbox_batch(batch_size=-10)

        assert result.status == "failed"
        assert "必须为正整数" in result.message


class TestSessionManagement:
    """测试数据库 session 管理。"""

    @patch('server.memory_v2.store.outbox.OutboxWorker')
    @patch('server.memory_v2.retrieve.embedder.RealEmbedder')
    @patch('server.memory_v2.retrieve.index_v2.IndexV2')
    @patch('server.database.connection_pool.db_pool')
    def test_session_closed_on_success(self, mock_pool, mock_index_cls, mock_embedder_cls, mock_worker_cls):
        """UT-08: 成功路径关闭 session。"""
        from papermind.outbox_sync import _process_batch

        mock_session = MagicMock()
        mock_pool.sync_session_factory.return_value = mock_session

        mock_index = MagicMock()
        mock_index.embedding_dim = 1536
        mock_index_cls.return_value = mock_index

        mock_embedder = MagicMock()
        mock_embedder_cls.return_value = mock_embedder

        mock_worker = MagicMock()
        mock_worker.process_pending.return_value = {"done": 1, "failed": 0, "dead": 0}
        mock_worker_cls.return_value = mock_worker

        result = _process_batch(10)

        assert result["done"] == 1
        mock_session.close.assert_called_once()

    @patch('server.memory_v2.retrieve.index_v2.IndexV2')
    @patch('server.database.connection_pool.db_pool')
    def test_session_closed_on_error(self, mock_pool, mock_index_cls):
        """UT-08: 异常路径关闭 session。"""
        from papermind.outbox_sync import _process_batch

        mock_session = MagicMock()
        mock_pool.sync_session_factory.return_value = mock_session

        mock_index_cls.side_effect = RuntimeError("Index error")

        with pytest.raises(RuntimeError):
            _process_batch(10)

        mock_session.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
