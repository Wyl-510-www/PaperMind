"""Phase 1.3 验收脚本 - 自动化端到端测试。

验收测试覆盖：
1. 保存论文笔记到 MySQL（UT-03）
2. 同步 Outbox 到 Qdrant（UT-07）
3. 跨进程检索回忆（UT-10）
4. 租户隔离验证（UT-11）
5. 失败处理（UT-05, UT-06）

使用真实的 MySQL + Qdrant 环境，验证完整的写入-同步-检索链路。
"""

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# 添加核心模块路径
core_path = Path(__file__).parent.parent.parent / "memoryV2-core"
if core_path.exists():
    sys.path.insert(0, str(core_path))

from papermind.memory_writer import save_turn_to_memory
from papermind.memory_retrieval import retrieve_memory_context
from papermind.outbox_sync import sync_outbox_batch


class TestResult:
    """测试结果。"""
    def __init__(self, name: str, passed: bool, message: str):
        self.name = name
        self.passed = passed
        self.message = message

    def __str__(self):
        status = "[PASS]" if self.passed else "[FAIL]"
        return f"{status} | {self.name}\n      {self.message}"


async def test_write_and_retrieve():
    """测试用例 1：写入-同步-检索闭环（UT-03, UT-07, UT-10）。"""
    tenant_id = "tenant_verify_phase13"
    user_id = "user_alice"
    turn_id = uuid4().hex

    # Step 1: 保存论文笔记
    note = "我的论文《Transformer架构研究》的阅读结论是：多头注意力机制显著提升了模型的表达能力。"

    write_result = await save_turn_to_memory(
        user_text=note,
        tenant_id=tenant_id,
        user_id=user_id,
        turn_id=turn_id,
        confirmed=True,
    )

    if write_result.status != "saved":
        return TestResult(
            name="写入-同步-检索闭环",
            passed=False,
            message=f"写入失败: {write_result.message}",
        )

    memory_ids = write_result.memory_ids
    if not memory_ids:
        return TestResult(
            name="写入-同步-检索闭环",
            passed=False,
            message="写入成功但未返回 memory_ids",
        )

    # Step 2: 同步 Outbox
    sync_result = await sync_outbox_batch(batch_size=100)

    if sync_result.status != "completed":
        return TestResult(
            name="写入-同步-检索闭环",
            passed=False,
            message=f"同步失败: {sync_result.message}",
        )

    if sync_result.done == 0:
        return TestResult(
            name="写入-同步-检索闭环",
            passed=False,
            message="同步完成但 done=0（批次为空或未处理当前记录）",
        )

    # Step 3: 检索回忆
    query = "多头注意力有什么作用？"
    memory_context = await retrieve_memory_context(
        query=query,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=5,
    )

    if "多头注意力" not in memory_context and "表达能力" not in memory_context:
        return TestResult(
            name="写入-同步-检索闭环",
            passed=False,
            message=f"检索未找到相关记忆。上下文: {memory_context[:200]}",
        )

    return TestResult(
        name="写入-同步-检索闭环",
        passed=True,
        message=f"写入 {len(memory_ids)} 条 -> 同步 {sync_result.done} 条 -> 检索成功",
    )


async def test_tenant_isolation():
    """测试用例 2：租户隔离（UT-11）。"""
    tenant_a = "tenant_verify_a"
    tenant_b = "tenant_verify_b"
    user_id = "user_test"

    # Tenant A 保存笔记
    turn_id_a = uuid4().hex
    note_a = "租户A的论文笔记：BERT模型使用掩码语言模型进行预训练。"

    write_a = await save_turn_to_memory(
        user_text=note_a,
        tenant_id=tenant_a,
        user_id=user_id,
        turn_id=turn_id_a,
        confirmed=True,
    )

    if write_a.status != "saved":
        return TestResult(
            name="租户隔离",
            passed=False,
            message=f"租户A写入失败: {write_a.message}",
        )

    # 同步
    await sync_outbox_batch(batch_size=100)

    # Tenant B 不应检索到 Tenant A 的记忆
    query = "BERT模型的预训练方法"
    memory_b = await retrieve_memory_context(
        query=query,
        tenant_id=tenant_b,
        user_id=user_id,
        limit=5,
    )

    if "BERT" in memory_b or "掩码语言模型" in memory_b:
        return TestResult(
            name="租户隔离",
            passed=False,
            message=f"租户B检索到了租户A的记忆！隔离失败。上下文: {memory_b[:200]}",
        )

    # Tenant A 应该能检索到自己的记忆
    memory_a = await retrieve_memory_context(
        query=query,
        tenant_id=tenant_a,
        user_id=user_id,
        limit=5,
    )

    if "BERT" not in memory_a and "掩码语言模型" not in memory_a:
        return TestResult(
            name="租户隔离",
            passed=False,
            message=f"租户A无法检索自己的记忆。上下文: {memory_a[:200]}",
        )

    return TestResult(
        name="租户隔离",
        passed=True,
        message="租户A可检索自己的记忆，租户B无法检索租户A的记忆",
    )


async def test_unconfirmed_skip():
    """测试用例 3：未确认输入跳过（UT-01）。"""
    tenant_id = "tenant_verify_phase13"
    user_id = "user_test"
    turn_id = uuid4().hex

    result = await save_turn_to_memory(
        user_text="这是一条未确认的笔记",
        tenant_id=tenant_id,
        user_id=user_id,
        turn_id=turn_id,
        confirmed=False,
    )

    if result.status != "skipped":
        return TestResult(
            name="未确认输入跳过",
            passed=False,
            message=f"预期 skipped，实际 {result.status}",
        )

    if result.memory_ids:
        return TestResult(
            name="未确认输入跳过",
            passed=False,
            message="未确认输入不应生成 memory_ids",
        )

    return TestResult(
        name="未确认输入跳过",
        passed=True,
        message=result.message,
    )


async def test_query_skip():
    """测试用例 4：查询请求跳过（UT-02）。"""
    tenant_id = "tenant_verify_phase13"
    user_id = "user_test"
    turn_id = uuid4().hex

    # 查询不应写入记忆
    query_text = "我之前读过哪些论文？"

    result = await save_turn_to_memory(
        user_text=query_text,
        tenant_id=tenant_id,
        user_id=user_id,
        turn_id=turn_id,
        confirmed=True,
    )

    if result.status != "skipped":
        return TestResult(
            name="查询请求跳过",
            passed=False,
            message=f"预期 skipped，实际 {result.status}",
        )

    if result.speech_act != "query_existing":
        return TestResult(
            name="查询请求跳过",
            passed=False,
            message=f"预期 speech_act=query_existing，实际 {result.speech_act}",
        )

    return TestResult(
        name="查询请求跳过",
        passed=True,
        message=result.message,
    )


async def test_empty_input_failure():
    """测试用例 5：空输入失败处理（UT-05）。"""
    tenant_id = "tenant_verify_phase13"
    user_id = "user_test"
    turn_id = uuid4().hex

    result = await save_turn_to_memory(
        user_text="",
        tenant_id=tenant_id,
        user_id=user_id,
        turn_id=turn_id,
        confirmed=True,
    )

    if result.status != "failed":
        return TestResult(
            name="空输入失败处理",
            passed=False,
            message=f"预期 failed，实际 {result.status}",
        )

    if result.error_code != "EMPTY_INPUT":
        return TestResult(
            name="空输入失败处理",
            passed=False,
            message=f"预期 error_code=EMPTY_INPUT，实际 {result.error_code}",
        )

    return TestResult(
        name="空输入失败处理",
        passed=True,
        message=result.message,
    )


async def main():
    """运行所有验收测试。"""
    print("=" * 70)
    print("Phase 1.3 验收测试")
    print("=" * 70)
    print("环境: 真实 MySQL + Qdrant")
    print("范围: 写入 -> 同步 -> 检索闭环 + 租户隔离 + 失败处理")
    print("=" * 70)
    print()

    # 运行测试
    tests = [
        ("核心闭环", test_write_and_retrieve()),
        ("租户隔离", test_tenant_isolation()),
        ("未确认跳过", test_unconfirmed_skip()),
        ("查询跳过", test_query_skip()),
        ("空输入失败", test_empty_input_failure()),
    ]

    results = []
    for name, test_coro in tests:
        print(f"运行: {name}...")
        try:
            result = await test_coro
            results.append(result)
            print(f"  {result}\n")
        except Exception as e:
            result = TestResult(name, False, f"异常: {str(e)}")
            results.append(result)
            print(f"  {result}\n")

    # 统计结果
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    print("=" * 70)
    print(f"测试完成: {passed}/{total} 通过")
    print("=" * 70)

    if passed == total:
        print("[PASS] 所有测试通过！Phase 1.3 验收成功。")
        sys.exit(0)
    else:
        print("[FAIL] 部分测试失败，请检查上述错误。")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
