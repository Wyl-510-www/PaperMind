"""测试 Memory V2 检索链路。

此测试模块验证 memory_retrieval 模块的核心功能：
1. 检索功能是否可用
2. 租户隔离是否生效
3. 证据格式化是否正确
4. 无证据处理是否合理
5. 错误处理和降级策略
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from papermind.memory_retrieval import (
    format_evidence_pack,
    retrieve_memory_context,
)


class TestFormatEvidencePack:
    """测试证据格式化函数。"""

    def test_format_with_results(self):
        """测试：有相关记忆时返回格式化证据。"""
        evidence_pack = {
            "query": "我的研究方向是什么",
            "items": [
                {
                    "memory_id": "mem_001",
                    "text": "我的研究方向是计算机视觉",
                    "confidence": 0.95,
                    "memory_type": "semantic",
                    "created_at": datetime(2026, 10, 7, 10, 30),
                },
                {
                    "memory_id": "mem_002",
                    "text": "我对深度学习很感兴趣",
                    "confidence": 0.88,
                    "memory_type": "semantic",
                    "created_at": datetime(2026, 10, 6, 15, 20),
                },
            ],
            "generated_at": datetime.now(),
        }

        result = format_evidence_pack(evidence_pack)

        # 验证格式
        assert "[记忆检索结果]：找到以下相关记忆" in result
        assert "我的研究方向是计算机视觉" in result
        assert "我对深度学习很感兴趣" in result
        assert "置信度：0.95" in result
        assert "置信度：0.88" in result
        assert "来源：Memory ID mem_001" in result
        assert "来源：Memory ID mem_002" in result
        assert "类型：semantic" in result
        assert "2026-10-07 10:30" in result
        assert "2026-10-06 15:20" in result

    def test_format_no_results(self):
        """测试：无相关记忆时返回明确提示。"""
        evidence_pack = {
            "query": "我的研究方向是什么",
            "items": [],
            "generated_at": datetime.now(),
        }

        result = format_evidence_pack(evidence_pack)

        assert "[记忆检索结果]：未找到相关记忆" in result
        assert "请基于当前对话回答" in result

    def test_format_none_input(self):
        """测试：输入 None 时返回未找到提示。"""
        result = format_evidence_pack(None)

        assert "[记忆检索结果]：未找到相关记忆" in result
        assert "请基于当前对话回答" in result

    def test_format_single_result(self):
        """测试：只有一条证据时格式正确。"""
        evidence_pack = {
            "query": "测试查询",
            "items": [
                {
                    "memory_id": "mem_001",
                    "text": "单条测试记忆",
                    "confidence": 0.92,
                    "memory_type": "semantic",
                    "created_at": datetime(2026, 10, 7, 12, 0),
                }
            ],
            "generated_at": datetime.now(),
        }

        result = format_evidence_pack(evidence_pack)

        assert "1. 单条测试记忆" in result
        assert "置信度：0.92" in result
        # 不应该有编号 2
        assert "2." not in result


@pytest.mark.asyncio
class TestRetrieveMemoryContext:
    """测试记忆检索主函数。"""

    @patch("papermind.memory_retrieval.get_config")
    @patch("papermind.memory_retrieval._call_memory_v2_retrieval")
    async def test_retrieve_with_results(self, mock_retrieval, mock_config):
        """测试：成功检索到记忆。"""
        # Mock config
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=1.0,
        )

        # Mock Memory V2 返回值
        mock_retrieval.return_value = {
            "query": "我的研究方向是什么",
            "items": [
                {
                    "memory_id": "mem_001",
                    "text": "我的研究方向是计算机视觉",
                    "confidence": 0.95,
                    "memory_type": "semantic",
                    "created_at": datetime(2026, 10, 7, 10, 30),
                }
            ],
            "generated_at": datetime.now(),
        }

        result = await retrieve_memory_context(
            query="我的研究方向是什么",
            tenant_id="tenant_1",
            user_id="alice",
            limit=5,
        )

        # 验证调用参数
        mock_retrieval.assert_called_once_with(
            query="我的研究方向是什么",
            tenant_id="tenant_1",
            user_id="alice",
            limit=5,
        )

        # 验证返回结果
        assert "我的研究方向是计算机视觉" in result
        assert "置信度" in result

    @patch("papermind.memory_retrieval.get_config")
    @patch("papermind.memory_retrieval._call_memory_v2_retrieval")
    async def test_retrieve_no_results(self, mock_retrieval, mock_config):
        """测试：检索不到记忆时返回明确提示。"""
        # Mock config
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=1.0,
        )
        mock_retrieval.return_value = {
            "query": "我的研究方向是什么",
            "items": [],
            "generated_at": datetime.now(),
        }

        result = await retrieve_memory_context(
            query="我的研究方向是什么",
            tenant_id="tenant_1",
            user_id="bob",
        )

        assert "未找到相关记忆" in result
        assert "请基于当前对话回答" in result

    @patch("papermind.memory_retrieval.get_config")
    @patch("papermind.memory_retrieval._call_memory_v2_retrieval")
    async def test_retrieve_timeout(self, mock_retrieval, mock_config):
        """测试：检索超时时返回降级提示。"""
        # Mock config with short timeout
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=0.1,  # 短超时用于测试
        )

        # Mock 超时异常
        async def timeout_side_effect(*args, **kwargs):
            await asyncio.sleep(10)  # 模拟长时间等待

        mock_retrieval.side_effect = timeout_side_effect

        result = await retrieve_memory_context(
            query="测试查询",
            tenant_id="tenant_1",
            user_id="alice",
        )

        assert "超时" in result or "失败" in result

    @patch("papermind.memory_retrieval.get_config")
    @patch("papermind.memory_retrieval._call_memory_v2_retrieval")
    async def test_retrieve_exception(self, mock_retrieval, mock_config):
        """测试：检索异常时返回降级提示。"""
        # Mock config
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=1.0,
        )
        mock_retrieval.side_effect = Exception("模拟检索失败")

        result = await retrieve_memory_context(
            query="测试查询",
            tenant_id="tenant_1",
            user_id="alice",
        )

        assert "失败" in result or "基于当前对话回答" in result


@pytest.mark.integration
@pytest.mark.asyncio
class TestMemoryRetrievalIntegration:
    """集成测试（需要真实的 Memory V2 环境）。

    这些测试需要：
    1. MySQL 数据库运行
    2. Qdrant 向量数据库运行
    3. Memory V2 核心模块可导入
    4. 测试数据已准备

    运行方式：
        pytest tests/test_memory_retrieval.py -m integration -v
    """

    async def test_end_to_end_retrieval(self):
        """端到端测试：真实调用 Memory V2 检索。

        前置条件：
        1. 在 MySQL 中插入测试记忆
        2. 运行 Outbox 同步，确保 Qdrant 有向量

        验证：
        1. 检索调用成功
        2. 返回格式正确
        3. 租户隔离生效
        """
        pytest.skip("需要真实 Memory V2 环境")

    async def test_tenant_isolation(self):
        """测试：租户隔离生效。

        前置条件：
        1. 用户 Alice 在 tenant_A 下有记忆："我喜欢深度学习"
        2. 用户 Alice 在 tenant_B 下无记忆

        验证：
        1. tenant_A 的检索返回"深度学习"
        2. tenant_B 的检索返回"未找到相关记忆"
        """
        pytest.skip("需要真实 Memory V2 环境和测试数据")


@pytest.mark.benchmark
@pytest.mark.asyncio
class TestMemoryRetrievalPerformance:
    """性能测试（可选）。"""

    @patch("papermind.memory_retrieval.get_config")
    @patch("papermind.memory_retrieval._call_memory_v2_retrieval")
    async def test_retrieval_latency(self, mock_retrieval, mock_config):
        """测试：检索延迟在合理范围内。"""
        import time

        # Mock config
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=1.0,
        )

        mock_retrieval.return_value = {
            "query": "测试查询",
            "items": [],
            "generated_at": datetime.now(),
        }

        start = time.time()
        await retrieve_memory_context(
            query="测试查询",
            tenant_id="tenant_1",
            user_id="alice",
        )
        elapsed = time.time() - start

        # 验证延迟小于 2 秒（包含超时控制）
        assert elapsed < 2.0, f"检索延迟过高: {elapsed:.3f} 秒"
