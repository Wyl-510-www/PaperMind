#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简化的检索测试 - 诊断检索失败原因"""
import asyncio
import sys
from datetime import date
from pathlib import Path

# 确保 Windows 控制台正确显示 UTF-8
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 添加核心模块路径
core_path = Path(__file__).parent.parent / "memoryV2-core"
if core_path.exists():
    sys.path.insert(0, str(core_path))

from papermind.memory_retrieval import retrieve_structured_evidence

async def test_basic_retrieval():
    """测试基础检索"""
    print("\n" + "=" * 60)
    print("测试 1: 基础检索（无过滤）")
    print("=" * 60)

    try:
        results = await retrieve_structured_evidence(
            query="Transformer 注意力机制",
            tenant_id="tenant_phase3_e2e",
            user_id="user_test",
            limit=10,
        )

        print(f"\n[OK] 返回 {len(results)} 条结果")
        for i, item in enumerate(results[:3], 1):
            print(f"\n结果 {i}:")
            print(f"  Memory ID: {item.memory_id}")
            print(f"  Content: {item.content[:100]}...")
            print(f"  Confidence: {item.confidence}")

        return len(results) > 0

    except Exception as e:
        print(f"\n[ERROR] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_tag_filter():
    """测试标签过滤"""
    print("\n" + "=" * 60)
    print("测试 2: 标签过滤")
    print("=" * 60)

    try:
        results = await retrieve_structured_evidence(
            query="深度学习",
            tenant_id="tenant_phase3_e2e",
            user_id="user_test",
            limit=10,
            tags=["Transformer", "注意力机制"],
        )

        print(f"\n[OK] 返回 {len(results)} 条结果")
        for i, item in enumerate(results[:3], 1):
            print(f"\n结果 {i}:")
            print(f"  Memory ID: {item.memory_id}")
            print(f"  Content: {item.content[:100]}...")

        return len(results) > 0

    except Exception as e:
        print(f"\n[ERROR] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_date_filter():
    """测试日期过滤"""
    print("\n" + "=" * 60)
    print("测试 3: 日期过滤")
    print("=" * 60)

    try:
        results = await retrieve_structured_evidence(
            query="论文",
            tenant_id="tenant_phase3_e2e",
            user_id="user_test",
            limit=10,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 10, 31),
        )

        print(f"\n[OK] 返回 {len(results)} 条结果")
        for i, item in enumerate(results[:3], 1):
            print(f"\n结果 {i}:")
            print(f"  Memory ID: {item.memory_id}")
            print(f"  Content: {item.content[:100]}...")

        return len(results) > 0

    except Exception as e:
        print(f"\n[ERROR] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("\n" + "=" * 70)
    print(" 检索功能简化测试")
    print("=" * 70)

    test1 = await test_basic_retrieval()
    test2 = await test_tag_filter()
    test3 = await test_date_filter()

    print("\n" + "=" * 70)
    print(" 测试总结")
    print("=" * 70)
    print(f"基础检索: {'✓ PASS' if test1 else '✗ FAIL'}")
    print(f"标签过滤: {'✓ PASS' if test2 else '✗ FAIL'}")
    print(f"日期过滤: {'✓ PASS' if test3 else '✗ FAIL'}")

    return 0 if (test1 and test2 and test3) else 1

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
