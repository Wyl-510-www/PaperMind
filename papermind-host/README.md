# PaperMind Agent Host

智能体宿主层模块，提供 LLM 调用、配置管理和会话管理能力。

## 功能特性

- **配置管理**：基于 Pydantic Settings 的类型安全配置加载
- **LLM 客户端**：封装 DashScope API（OpenAI 兼容接口）
- **会话管理**：多租户、多用户会话状态管理
- **记忆检索**：集成 Memory V2 长期记忆检索能力（Phase 1.2）
- **完整测试**：单元测试覆盖核心功能

## 安装

### 前置要求

- Python 3.11+
- DashScope API Key（百炼）

### 安装步骤

```bash
# 1. 进入项目目录
cd papermind-host

# 2. 安装依赖（开发模式）
pip install -e .

# 或安装开发依赖（包含测试工具）
pip install -e ".[dev]"

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的 BAILIAN_API_KEY
```

### 获取 API Key

访问 [DashScope 控制台](https://dashscope.console.aliyun.com/apiKey) 获取 API Key。

## 快速开始

### 基础示例

```python
import asyncio
from papermind.config import get_config
from papermind.llm_client import LLMClient


async def main():
    # 加载配置
    config = get_config()
    
    # 创建 LLM 客户端
    client = LLMClient(config)
    
    # 调用 LLM
    messages = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "介绍一下 Transformer 架构"}
    ]
    
    reply = await client.chat(messages)
    print(reply)


if __name__ == "__main__":
    asyncio.run(main())
```

### 会话管理示例

```python
from papermind.session import SessionManager

# 创建会话管理器
manager = SessionManager()

# 获取或创建会话
session = manager.get_or_create_session(
    tenant_id="default",
    user_id="alice"
)

print(f"当前轮次: {session.turn_id}")

# 递增轮次
new_turn = manager.increment_turn("default", "alice")
print(f"新轮次: {new_turn}")

# 列出所有会话
sessions = manager.list_sessions()
print(f"活跃会话: {sessions}")

# 清除会话
manager.clear_session("default", "alice")
```

### 完整对话示例

```python
import asyncio
from papermind.config import get_config
from papermind.llm_client import LLMClient
from papermind.session import SessionManager


async def chat_example():
    config = get_config()
    client = LLMClient(config)
    manager = SessionManager()
    
    tenant_id = "default"
    user_id = "alice"
    
    # 对话历史
    messages = []
    
    while True:
        # 获取用户输入
        user_input = input("You: ")
        if user_input.lower() in ["quit", "exit"]:
            break
        
        # 添加用户消息
        messages.append({"role": "user", "content": user_input})
        
        # 调用 LLM
        reply = await client.chat(messages)
        print(f"Assistant: {reply}")
        
        # 添加助手回复到历史
        messages.append({"role": "assistant", "content": reply})
        
        # 递增轮次
        turn = manager.increment_turn(tenant_id, user_id)
        print(f"[Turn {turn}]\n")


if __name__ == "__main__":
    asyncio.run(chat_example())
```

### 使用记忆检索的对话示例

**新功能（Phase 1.2）**：LLM 可以检索用户的长期记忆，使回复更加个性化。

```python
import asyncio
from papermind.config import get_config
from papermind.llm_client import LLMClient
from papermind.memory_retrieval import retrieve_memory_context


async def chat_with_memory_example():
    """使用记忆检索的对话示例"""
    config = get_config()
    client = LLMClient(config)
    
    tenant_id = "default"
    user_id = "alice"
    
    # 用户提问
    user_message = "我的研究方向是什么"
    
    # 方式 1：使用 chat_with_memory 方法（推荐）
    reply = await client.chat_with_memory(
        user_message=user_message,
        tenant_id=tenant_id,
        user_id=user_id,
        system_prompt="你是一个有帮助的助手。"
    )
    print(f"Assistant: {reply}")
    
    # 方式 2：手动检索记忆并构造 prompt
    memory_context = await retrieve_memory_context(
        query=user_message,
        tenant_id=tenant_id,
        user_id=user_id,
        limit=5  # 返回最多 5 条相关记忆
    )
    
    print(f"\n[检索到的记忆]:\n{memory_context}\n")
    
    # 构造包含记忆的 messages
    messages = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "system", "content": memory_context},
        {"role": "user", "content": user_message}
    ]
    
    reply = await client.chat(messages)
    print(f"Assistant: {reply}")


if __name__ == "__main__":
    asyncio.run(chat_with_memory_example())
```

**记忆检索说明**：
- 检索结果会自动格式化为易读的文本，包含内容、来源、时间和置信度
- 如果未检索到相关记忆，会返回明确的"未找到相关记忆"提示
- 检索失败或超时不会阻断 LLM 回复，会使用降级策略
- 租户和用户隔离确保不同租户/用户的记忆相互隔离



在 `.env` 文件中配置：

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `BAILIAN_API_KEY` | 是 | - | DashScope API Key |
| `LLM_MODEL` | 否 | `qwen-max` | 模型名称 |
| `LLM_BASE_URL` | 否 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | API 端点 |
| `LOG_LEVEL` | 否 | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL） |

## 开发

### 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_config.py -v

# 查看测试覆盖率
pytest --cov=papermind tests/ --cov-report=term-missing
```

### 代码格式化

```bash
# 检查格式
black --check papermind/ tests/

# 自动格式化
black papermind/ tests/
```

### 类型检查

```bash
mypy papermind/ --strict
```

## API 文档

### Config

类型安全的配置管理。

```python
from papermind.config import get_config

config = get_config()
print(config.llm_model)  # 'qwen-max'
```

### LLMClient

LLM 调用客户端。

```python
from papermind.llm_client import LLMClient

client = LLMClient(config)

# 异步调用
reply = await client.chat(messages, temperature=0.7, max_tokens=1000)

# 同步调用（不推荐）
reply = client.chat_sync(messages)
```

**支持记忆检索的对话**：

```python
# 使用记忆检索的对话
reply = await client.chat_with_memory(
    user_message="我的研究方向是什么",
    tenant_id="default",
    user_id="alice",
    system_prompt="你是一个有帮助的助手。"
)
```

**异常**：
- `LLMRateLimitError`：超出速率限制
- `LLMConnectionError`：连接失败
- `LLMAPIError`：API 错误

### SessionManager

会话状态管理。

```python
from papermind.session import SessionManager

manager = SessionManager()

# 获取或创建会话
session = manager.get_or_create_session(tenant_id, user_id)

# 递增轮次
turn = manager.increment_turn(tenant_id, user_id)

# 列出会话
sessions = manager.list_sessions()

# 清除会话
manager.clear_session(tenant_id, user_id)
```

### 记忆检索

Memory V2 检索模块提供长期记忆检索能力。

```python
from papermind.memory_retrieval import retrieve_memory_context

# 检索用户长期记忆
memory_context = await retrieve_memory_context(
    query="我的研究方向是什么",
    tenant_id="default",
    user_id="alice",
    limit=5  # 返回最多 5 条相关记忆
)

print(memory_context)
# 输出示例：
# [记忆检索结果]：找到以下相关记忆：
#
# 1. 我的研究方向是计算机视觉
#    来源：Memory ID mem_001
#    类型：semantic
#    时间：2026-10-07 10:30
#    置信度：0.95
```

**格式化证据包**：

```python
from papermind.memory_retrieval import format_evidence_pack

# 手动格式化证据包（通常不需要，retrieve_memory_context 已自动格式化）
evidence_pack = {
    "items": [...],
    "generated_at": datetime.now()
}
formatted_text = format_evidence_pack(evidence_pack)
```



```
papermind-host/
├── papermind/              # 源代码
│   ├── __init__.py
│   ├── config.py          # 配置管理
│   ├── llm_client.py      # LLM 客户端
│   └── session.py         # 会话管理
├── tests/                 # 测试代码
│   ├── test_config.py
│   ├── test_llm_client.py
│   └── test_session.py
├── examples/              # 示例代码
│   └── simple_chat.py
├── .env.example           # 环境变量示例
├── pyproject.toml         # 项目配置
└── README.md
```

## 常见问题

### Q: 如何切换模型？

在 `.env` 文件中设置 `LLM_MODEL`：

```bash
LLM_MODEL=qwen-turbo
```

支持的模型：`qwen-max`, `qwen-plus`, `qwen-turbo` 等。

### Q: 如何处理 API 错误？

使用 try-except 捕获异常：

```python
from papermind.llm_client import LLMAPIError, LLMRateLimitError

try:
    reply = await client.chat(messages)
except LLMRateLimitError:
    print("速率限制，请稍后重试")
except LLMAPIError as e:
    print(f"API 错误: {e}")
```

### Q: 会话数据会持久化吗？

当前版本会话数据仅存储在内存中，重启后丢失。后续版本将支持持久化。

### Q: Memory V2 检索需要什么前置条件？

需要以下服务运行：
1. MySQL 8.0+（存储记忆真值）
2. Qdrant（存储向量索引）
3. Memory V2 核心模块已安装

详见 [Memory V2 文档](../memoryV2-core/README.md)。

### Q: 如何调试记忆检索问题？

设置日志级别为 DEBUG：

```bash
LOG_LEVEL=DEBUG
```

查看检索日志：

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 许可证

MIT License

## 下一步

- ~~集成 Memory V2（长期记忆能力）~~ ✅ 已完成（Phase 1.2）
- 实现 Memory V2 写入链路（Phase 1.3）
- 实现 CLI 交互界面（Phase 1.4）
- 添加 Web UI
- 支持文档上传和解析

---

**相关文档**：
- [项目使命](../specs/mission.md)
- [技术栈](../specs/tech-stack.md)
- [实施路线图](../specs/roadmap.md)
