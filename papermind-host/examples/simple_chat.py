"""Simple chat 示例 - Phase 1.3 写入与检索联调。

提供命令行交互界面，支持：
- save: 确认保存论文笔记
- sync: 显式同步 Outbox
- ask: 提问并检索历史记忆
- quit: 退出

每次保存使用独立的 UUID turn_id。
"""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

# 添加核心模块路径
core_path = Path(__file__).parent.parent.parent / "memoryV2-core"
if core_path.exists():
    sys.path.insert(0, str(core_path))

from papermind.config import get_config
from papermind.llm_client import LLMClient
from papermind.memory_writer import save_turn_to_memory
from papermind.memory_retrieval import retrieve_memory_context
from papermind.outbox_sync import sync_outbox_batch


async def save_note(tenant_id: str, user_id: str):
    """保存论文笔记。"""
    print("\n=== 保存论文笔记 ===")
    print("请输入论文笔记（例如：我的论文《注意力机制》的阅读结论是：自注意力有效提升了模型性能）")
    user_text = input("笔记内容: ").strip()

    if not user_text:
        print("❌ 输入为空，已取消")
        return

    print(f"\n确认保存以下内容？")
    print(f"  {user_text}")
    confirm = input("确认 (y/n): ").strip().lower()

    if confirm != 'y':
        print("❌ 已取消保存")
        return

    # 生成独立的 turn_id
    turn_id = uuid4().hex
    print(f"\n正在保存... (turn_id: {turn_id[:8]}...)")

    result = await save_turn_to_memory(
        user_text=user_text,
        tenant_id=tenant_id,
        user_id=user_id,
        turn_id=turn_id,
        confirmed=True,
    )

    print(f"\n状态: {result.status}")
    print(f"消息: {result.message}")
    if result.speech_act:
        print(f"分类: {result.speech_act}")
    if result.memory_ids:
        print(f"Memory IDs: {result.memory_ids}")
    if result.error_code:
        print(f"错误代码: {result.error_code}")


async def sync_batch():
    """显式同步 Outbox。"""
    print("\n=== 同步 Outbox ===")
    batch_size = input("批次大小 (默认 100): ").strip()
    batch_size = int(batch_size) if batch_size else 100

    print(f"\n正在同步... (batch_size: {batch_size})")

    result = await sync_outbox_batch(batch_size=batch_size)

    print(f"\n状态: {result.status}")
    print(f"消息: {result.message}")
    print(f"统计: done={result.done}, failed={result.failed}, dead={result.dead}")


async def ask_question(tenant_id: str, user_id: str, llm_client: LLMClient):
    """提问并检索历史记忆。"""
    print("\n=== 提问 ===")
    query = input("请输入问题: ").strip()

    if not query:
        print("❌ 输入为空，已取消")
        return

    print("\n正在检索记忆...")

    # 检索历史记忆
    memory_context = await retrieve_memory_context(
        query=query,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=5,
    )

    print(f"\n{memory_context}")

    # 使用 LLM 回答
    print("\n正在生成答案...")
    messages = [
        {"role": "system", "content": "你是一个有记忆的助手，可以回忆用户的历史信息。"},
        {"role": "user", "content": f"{memory_context}\n\n用户问题：{query}"},
    ]

    response = await llm_client.chat(messages)
    print(f"\n回答: {response}")


async def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="Simple chat - Phase 1.3 示例")
    parser.add_argument("--tenant", required=True, help="租户 ID")
    parser.add_argument("--user", required=True, help="用户 ID")
    args = parser.parse_args()

    tenant_id = args.tenant
    user_id = args.user

    print("=" * 60)
    print("Simple Chat - Phase 1.3 写入与检索联调示例")
    print("=" * 60)
    print(f"租户: {tenant_id}")
    print(f"用户: {user_id}")
    print("\n可用命令:")
    print("  save - 保存论文笔记")
    print("  sync - 同步 Outbox")
    print("  ask  - 提问并检索")
    print("  quit - 退出")
    print("=" * 60)

    # 初始化 LLM 客户端
    config = get_config()
    llm_client = LLMClient(
        api_key=config.bailian_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )

    while True:
        try:
            print("\n")
            command = input("请输入命令 (save/sync/ask/quit): ").strip().lower()

            if command == "quit":
                print("\n再见！")
                break
            elif command == "save":
                await save_note(tenant_id, user_id)
            elif command == "sync":
                await sync_batch()
            elif command == "ask":
                await ask_question(tenant_id, user_id, llm_client)
            else:
                print("❌ 未知命令，请使用 save/sync/ask/quit")

        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            print(f"\n❌ 错误: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main())
