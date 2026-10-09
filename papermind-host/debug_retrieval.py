#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调试检索失败的问题"""
import asyncio
import sys
from datetime import date
from pathlib import Path
import json

# 确保 Windows 控制台正确显示 UTF-8
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 添加核心模块路径
core_path = Path(__file__).parent.parent / "memoryV2-core"
if core_path.exists():
    sys.path.insert(0, str(core_path))

import pymysql
from dotenv import load_dotenv
import os

# 加载环境变量
parent_dir = Path(__file__).parent.parent
env_path = parent_dir / 'memoryV2-core' / '.env'
load_dotenv(env_path)

from papermind.app_service import Identity
from papermind.memory_retrieval import retrieve_structured_evidence

def connect_db():
    """连接数据库"""
    return pymysql.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER', 'memoryv2'),
        password=os.getenv('DB_PASS', ''),
        database=os.getenv('DB_NAME', 'memory_v2'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def check_database_records():
    """检查数据库中的记录"""
    print("\n" + "=" * 60)
    print("1. 检查数据库中的记录")
    print("=" * 60)

    conn = connect_db()
    cursor = conn.cursor()

    # 查询 Phase3 测试用户的所有记录
    cursor.execute("""
        SELECT memory_id, tenant_id, user_id,
               LEFT(text_zh, 50) as text_preview,
               metadata, status, index_status,
               created_at
        FROM memory_v2_record
        WHERE tenant_id = 'tenant_phase3_e2e'
        ORDER BY created_at DESC
        LIMIT 10
    """)

    records = cursor.fetchall()
    print(f"\n找到 {len(records)} 条记录:\n")

    for i, rec in enumerate(records, 1):
        print(f"[{i}] Memory ID: {rec['memory_id']}")
        print(f"    Text: {rec['text_preview']}...")
        print(f"    Status: {rec['status']}")
        print(f"    Index Status: {rec['index_status']}")
        print(f"    Metadata: {rec['metadata']}")
        print(f"    Created: {rec['created_at']}")
        print()

    cursor.close()
    conn.close()

    return len(records)

async def test_retrieval_basic():
    """测试基础检索（无过滤）"""
    print("\n" + "=" * 60)
    print("2. 测试基础检索（无过滤条件）")
    print("=" * 60)

    identity = Identity(
        tenant_id="tenant_phase3_e2e",
        user_id="user_test",
        label="调试测试"
    )

    query = "Transformer 注意力机制"

    print(f"\n查询: {query}")
    print(f"租户: {identity.tenant_id}")
    print(f"用户: {identity.user_id}\n")

    try:
        results = await retrieve_structured_evidence(
            identity=identity,
            query_text=query,
            limit=10,
            # 不传任何过滤条件
        )

        print(f"[OK] 返回 {len(results)} 条结果\n")

        if results:
            for i, result in enumerate(results[:3], 1):
                print(f"结果 {i}:")
                print(f"  Memory ID: {result.memory_id}")
                print(f"  Text: {result.text[:100]}...")
                print(f"  Score: {result.score}")
                print(f"  Metadata: {result.metadata}")
                print()
        else:
            print("[WARN] 无结果返回")

        return len(results)

    except Exception as e:
        print(f"[ERROR] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return 0

async def test_retrieval_with_tags():
    """测试标签过滤"""
    print("\n" + "=" * 60)
    print("3. 测试标签过滤")
    print("=" * 60)

    identity = Identity(
        tenant_id="tenant_phase3_e2e",
        user_id="user_test",
        label="调试测试"
    )

    query = "深度学习"
    tags = ["Transformer", "注意力机制"]

    print(f"\n查询: {query}")
    print(f"标签: {tags}\n")

    try:
        results = await retrieve_structured_evidence(
            identity=identity,
            query_text=query,
            limit=10,
            filter_tags=tags,
        )

        print(f"[OK] 返回 {len(results)} 条结果\n")

        if results:
            for i, result in enumerate(results[:3], 1):
                print(f"结果 {i}:")
                print(f"  Memory ID: {result.memory_id}")
                print(f"  Text: {result.text[:100]}...")
                print(f"  Metadata: {result.metadata}")
                print()
        else:
            print("[WARN] 无结果返回")

        return len(results)

    except Exception as e:
        print(f"[ERROR] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return 0

async def test_retrieval_with_date():
    """测试日期过滤"""
    print("\n" + "=" * 60)
    print("4. 测试日期过滤")
    print("=" * 60)

    identity = Identity(
        tenant_id="tenant_phase3_e2e",
        user_id="user_test",
        label="调试测试"
    )

    query = "深度学习"
    date_start = date(2020, 1, 1)
    date_end = date(2030, 12, 31)

    print(f"\n查询: {query}")
    print(f"日期范围: {date_start} ~ {date_end}\n")

    try:
        results = await retrieve_structured_evidence(
            identity=identity,
            query_text=query,
            limit=10,
            filter_date_start=date_start,
            filter_date_end=date_end,
        )

        print(f"[OK] 返回 {len(results)} 条结果\n")

        if results:
            for i, result in enumerate(results[:3], 1):
                print(f"结果 {i}:")
                print(f"  Memory ID: {result.memory_id}")
                print(f"  Text: {result.text[:100]}...")
                print(f"  Metadata: {result.metadata}")
                print()
        else:
            print("[WARN] 无结果返回")

        return len(results)

    except Exception as e:
        print(f"[ERROR] 检索失败: {e}")
        import traceback
        traceback.print_exc()
        return 0

async def main():
    """主函数"""
    print("\n" + "=" * 70)
    print(" Phase 3 检索失败诊断工具")
    print("=" * 70)

    # 1. 检查数据库记录
    record_count = check_database_records()

    if record_count == 0:
        print("\n[ERROR] 数据库中没有测试记录！")
        return 1

    # 等待索引
    print("\n等待 5 秒让向量索引生效...")
    await asyncio.sleep(5)

    # 2. 测试基础检索
    basic_count = await test_retrieval_basic()

    # 3. 测试标签过滤
    tag_count = await test_retrieval_with_tags()

    # 4. 测试日期过滤
    date_count = await test_retrieval_with_date()

    # 总结
    print("\n" + "=" * 70)
    print(" 诊断总结")
    print("=" * 70)
    print(f"数据库记录数: {record_count}")
    print(f"基础检索结果: {basic_count}")
    print(f"标签过滤结果: {tag_count}")
    print(f"日期过滤结果: {date_count}")

    if basic_count == 0:
        print("\n[问题] 基础检索无结果 → 向量索引可能未生效或查询逻辑有问题")
    elif tag_count == 0:
        print("\n[问题] 标签过滤无结果 → 标签过滤逻辑可能有问题")
    elif date_count == 0:
        print("\n[问题] 日期过滤无结果 → 日期过滤逻辑可能有问题")
    else:
        print("\n[OK] 所有检索测试通过！")

    return 0 if (basic_count > 0 and tag_count > 0 and date_count > 0) else 1

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
