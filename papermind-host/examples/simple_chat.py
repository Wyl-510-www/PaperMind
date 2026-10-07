"""Simple chat example using PaperMind Agent Host.

This script demonstrates basic LLM interaction with session management.
"""

import asyncio
import sys
from papermind.config import get_config
from papermind.llm_client import LLMClient, LLMClientError
from papermind.session import SessionManager


async def main() -> None:
    """Run a simple chat session."""
    print("=== PaperMind Simple Chat ===")
    print("Type 'quit' or 'exit' to end the conversation\n")

    try:
        # Initialize components
        config = get_config()
        client = LLMClient(config)
        manager = SessionManager()

        tenant_id = "default"
        user_id = "demo_user"

        # Initialize conversation with system message
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的 AI 研究助手，帮助用户理解和讨论学术论文。",
            }
        ]

        print(f"使用模型: {config.llm_model}\n")

        # Main chat loop
        while True:
            # Get user input
            user_input = input("You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["quit", "exit", "q"]:
                print("\n再见！")
                break

            # Add user message
            messages.append({"role": "user", "content": user_input})

            try:
                # Call LLM
                print("Assistant: ", end="", flush=True)
                reply = await client.chat(messages)
                print(reply)

                # Add assistant reply to history
                messages.append({"role": "assistant", "content": reply})

                # Increment turn counter
                turn = manager.increment_turn(tenant_id, user_id)
                print(f"\n[轮次 {turn}]\n")

            except LLMClientError as e:
                print(f"\n错误: {e}\n")
                # Remove the failed user message
                messages.pop()
                continue

    except KeyboardInterrupt:
        print("\n\n被用户中断。再见！")
        sys.exit(0)

    except Exception as e:
        print(f"\n致命错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
