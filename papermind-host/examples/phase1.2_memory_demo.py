"""Phase 1.2 Memory V2 检索链路快速验证脚本。

此脚本演示如何使用 Memory V2 检索链路：
1. 格式化证据包
2. 检索记忆（使用 Mock 数据）
3. 集成到 LLM 对话

运行方式：
    python examples/phase1.2_memory_demo.py
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from papermind.memory_retrieval import format_evidence_pack, retrieve_memory_context


def demo_format_evidence_pack():
    """演示证据格式化功能"""
    print("=" * 60)
    print("Demo 1: 证据格式化")
    print("=" * 60)

    # 模拟检索到的证据包
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
                "text": "我对深度学习和图像识别很感兴趣",
                "confidence": 0.88,
                "memory_type": "semantic",
                "created_at": datetime(2026, 10, 6, 15, 20),
            },
        ],
        "generated_at": datetime.now(),
    }

    formatted = format_evidence_pack(evidence_pack)
    print(formatted)
    print()


async def demo_retrieve_memory():
    """演示记忆检索功能（使用 Mock）"""
    print("=" * 60)
    print("Demo 2: 记忆检索（Mock）")
    print("=" * 60)

    # Mock Memory V2 返回值
    mock_evidence = {
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

    with patch("papermind.memory_retrieval.get_config") as mock_config, patch(
        "papermind.memory_retrieval._call_memory_v2_retrieval"
    ) as mock_retrieval:
        # Mock config
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=1.0,
        )

        # Mock retrieval
        mock_retrieval.return_value = mock_evidence

        # 调用检索
        result = await retrieve_memory_context(
            query="我的研究方向是什么",
            tenant_id="demo_tenant",
            user_id="alice",
            limit=5,
        )

        print(result)
        print()


async def demo_no_memory():
    """演示无记忆时的处理"""
    print("=" * 60)
    print("Demo 3: 无记忆处理")
    print("=" * 60)

    with patch("papermind.memory_retrieval.get_config") as mock_config, patch(
        "papermind.memory_retrieval._call_memory_v2_retrieval"
    ) as mock_retrieval:
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=1.0,
        )

        # Mock 返回空结果
        mock_retrieval.return_value = {
            "query": "我的研究方向是什么",
            "items": [],
            "generated_at": datetime.now(),
        }

        result = await retrieve_memory_context(
            query="我的研究方向是什么",
            tenant_id="demo_tenant",
            user_id="bob",  # 用户 Bob 没有记忆
        )

        print(result)
        print()


async def demo_timeout():
    """演示超时处理"""
    print("=" * 60)
    print("Demo 4: 超时处理")
    print("=" * 60)

    with patch("papermind.memory_retrieval.get_config") as mock_config, patch(
        "papermind.memory_retrieval._call_memory_v2_retrieval"
    ) as mock_retrieval:
        mock_config.return_value = MagicMock(
            memory_retrieval_limit=5,
            memory_retrieval_timeout=0.1,  # 短超时
        )

        # Mock 超时
        async def timeout_side_effect(*args, **kwargs):
            await asyncio.sleep(10)

        mock_retrieval.side_effect = timeout_side_effect

        result = await retrieve_memory_context(
            query="测试查询",
            tenant_id="demo_tenant",
            user_id="alice",
        )

        print(result)
        print()


async def main():
    """运行所有演示"""
    print("\n" + "=" * 60)
    print("Phase 1.2 Memory V2 检索链路功能演示")
    print("=" * 60)
    print()

    # Demo 1: 证据格式化
    demo_format_evidence_pack()

    # Demo 2: 记忆检索
    await demo_retrieve_memory()

    # Demo 3: 无记忆处理
    await demo_no_memory()

    # Demo 4: 超时处理
    await demo_timeout()

    print("=" * 60)
    print("演示完成！")
    print("=" * 60)
    print()
    print("下一步：")
    print("1. 查看 README.md 了解更多使用方法")
    print("2. 运行 pytest tests/test_memory_retrieval.py -v 查看测试")
    print("3. 阅读 specs/2026-10-07-phase1.2-memory-retrieval/ 了解实现细节")
    print()


if __name__ == "__main__":
    asyncio.run(main())
