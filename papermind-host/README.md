# PaperMind Agent Host

PaperMind Phase 2 Streamlit UI - 三身份论文笔记记忆系统

## 项目简介

PaperMind Phase 2 提供基于 Streamlit 的单页 UI，支持论文阅读笔记的保存、同步和查询。系统实现了完整的 Memory V2 闭环：笔记写入 → Outbox 同步 → 语义检索 → LLM 回答。

**P0 功能范围：**
- 三个固定身份组合（tenant_A/user_A、tenant_A/user_B、tenant_B/user_A）
- 论文笔记保存（标题 + 阅读结论）
- 二次确认门控
- Outbox 显式同步
- 基于历史记忆的问答
- 新建会话重置

## 功能特性

- **三身份隔离**：租户和用户级别的记忆隔离
- **笔记保存**：论文标题 + 阅读结论写入 Memory V2
- **PDF 上传**：自动提取 PDF 文本和标题（Phase 2.2 新增）
- **同步机制**：Outbox 队列批量同步到 Qdrant 索引
- **记忆问答**：基于历史笔记的语义检索 + LLM 回答
- **完整测试**：单元测试 + 集成测试 + 真实服务验收

## 安装依赖

### 前置要求

- Python 3.11+
- MySQL 8.0+
- Qdrant（向量数据库）
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
# 编辑 .env 文件，填入你的 DASHSCOPE_API_KEY
```

### 获取 API Key

访问 [DashScope 控制台](https://dashscope.console.aliyun.com/apiKey) 获取 API Key。

## 服务启动

在运行 Streamlit UI 之前，需要启动以下服务：

### 1. 启动 MySQL

```bash
# Windows (如已安装为服务)
net start MySQL80

# macOS
brew services start mysql

# Linux
sudo systemctl start mysql

# 或直接启动
mysqld --console
```

**初始化数据库（首次运行）：**

确保 Memory V2 数据库已初始化。如需手动初始化：

```bash
# 连接 MySQL
mysql -u root -p

# 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS memory_v2 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

数据表会在首次运行 Memory V2 写入时自动创建（通过 SQLAlchemy ORM）。

### 2. 启动 Qdrant

使用 Docker 启动 Qdrant：

```bash
docker run -d -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

验证 Qdrant 运行：

```bash
curl http://localhost:6333
```

### 3. 配置环境变量

确保以下环境变量已配置（在 `.env` 文件或系统环境变量中）：

```bash
# DashScope API Key（必需）
DASHSCOPE_API_KEY=sk-xxx

# MySQL 连接（Memory V2 会读取这些配置）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=memory_v2

# Qdrant 连接
QDRANT_HOST=localhost
QDRANT_PORT=6333

# LLM 配置（可选）
LLM_MODEL=qwen-max
LOG_LEVEL=INFO
```

**注意：** Memory V2 的数据库配置在 `memoryV2-core/server/database/database_bailian_config.py` 中定义。确保该配置文件指向正确的 MySQL 实例。

## 运行 Streamlit UI

启动所有服务后，运行 Streamlit 应用：

```bash
cd papermind-host
streamlit run streamlit_app.py
```

Streamlit 会自动打开浏览器（默认 http://localhost:8501）。

## 使用流程

### 1. 选择身份

在侧边栏选择一个身份：
- **租户A-用户A** (tenant_A/user_A)
- **租户A-用户B** (tenant_A/user_B)
- **租户B-用户A** (tenant_B/user_A)

每个身份的记忆是隔离的，不同身份不能看到彼此的笔记。

### 2. 保存笔记

**方式 1: 上传 PDF 论文（Phase 2.2 新增）**

- 点击"选择 PDF 文件"上传按钮
- 选择本地 PDF 文件（<10MB）
- 系统自动提取文本和标题
- 查看预览（前 500 字符）
- 可编辑提取的内容后保存

**支持的 PDF 类型：**
- ✅ 可复制文本的 PDF
- ❌ 扫描版 PDF（暂不支持 OCR）
- ❌ 加密 PDF

**方式 2: 手动输入**

- **论文标题**：论文的标题或主题
- **阅读结论**：你对论文的总结、理解或笔记

**保存流程：**
- 点击"💾 保存笔记"按钮
- 点击"✅ 确认保存"进行二次确认

**查看结果：**
- 显示保存状态（saved/skipped/failed）
- 显示 Memory ID 和 turn_id
- 显示保存的事实数量

### 3. 同步笔记

保存笔记后，需要显式同步到索引：

- 点击"同步笔记到索引"按钮
- 系统会批量处理 Outbox 队列
- 查看同步统计（done/failed/dead）

**注意：** 只有同步成功后，笔记才能被检索到。

### 4. 查询记忆

**输入问题：**
在"问题"输入框中输入你的问题，例如：
- "我读过哪些关于 Transformer 的论文？"
- "我对注意力机制有什么理解？"

**查看回答：**
- 系统会检索相关历史笔记
- LLM 基于检索到的证据生成回答
- 查看回答状态和证据列表

### 5. 查看证据

展开"检索到的证据"区域，查看：
- Memory ID
- 笔记内容
- 记忆类型
- 置信度分数
- 创建时间

### 6. 新建会话

点击"新建会话"按钮重置当前会话状态：
- 清空所有输入框
- 重置保存和查询状态
- 但不删除已保存的笔记（笔记持久化在数据库中）

## 验收脚本

运行完整的三身份隔离验收脚本：

```bash
cd papermind-host
python scripts/verify_phase2_ui.py
```

**验收内容：**

1. **Stage 1: Write** - 写入笔记到 MySQL（MemoryRecord + Outbox）
2. **Stage 2: Sync** - 同步 Outbox 到 Qdrant 索引
3. **Stage 3: Recall** - 使用相同身份召回笔记
4. **Stage 4: Isolation** - 验证不同身份不能看到未授权的记忆
   - tenant_A/user_B 查询 → 不返回 tenant_A/user_A 的笔记
   - tenant_B/user_A 查询 → 不返回 tenant_A/user_A 的笔记
   - 查询未保存的标记 → 返回 no_evidence
5. **Stage 5: Query Does Not Write** - 验证查询不会新增事实

**验收原则：**
- 直接调用 app_service 层（不通过 Streamlit UI）
- 使用真实服务（MySQL、Qdrant、Memory V2）
- 生成脱敏报告（只记录标识符，不记录全文/密钥/连接串）
- 任何阶段失败返回非零退出码

**成功输出示例：**

```
[Stage 1] 写入阶段 - 身份: 租户A-用户A
✅ Stage 1 通过 - Memory ID: mem_xyz123...

[Stage 2] 同步阶段
✅ Stage 2 通过

[Stage 3] 召回阶段 - 身份: 租户A-用户A
✅ Stage 3 通过

[Stage 4] 隔离验证...
✅ Stage 4.1 - tenant_A/user_B
✅ Stage 4.2 - tenant_B/user_A
✅ Stage 4.3 - Unsaved Marker

[Stage 5] 查询不误写验证
✅ Stage 5 - Query Does Not Write

✅ 验收通过
```

## Phase 2.2 新增功能

**PDF 文本提取** ✅
- 支持上传 PDF 论文并自动提取文本
- 自动识别论文标题（从元数据或首页）
- 提取内容预览（前 500 字符）
- 错误检测（加密、扫描版、损坏文件）
- 复用现有保存和检索流程

**限制：**
- 仅支持可复制文本的 PDF（不支持扫描版 OCR）
- 文件大小限制 10MB
- 不保存原始 PDF 文件
- 不实现文档级 RAG（全文不作为独立向量存储）

## 当前不支持的功能

以下功能不在 Phase 2 范围内：

- ❌ **OCR 识别** - 扫描版 PDF 需要手动输入
- ❌ **批量 PDF 上传** - 一次只能上传一份 PDF
- ❌ **论文库管理** - 没有论文列表、分类、标签等功能
- ❌ **文档级 RAG** - PDF 全文不作为独立向量存储
- ❌ **REST API** - 只有 Streamlit UI，没有 HTTP API
- ❌ **自动后台 worker** - 需要手动点击同步按钮
- ❌ **正式鉴权系统** - 使用固定的三个身份，没有登录/注册

这些功能计划在后续 Phase 中实现。

## 快速开始（编程接口）

虽然 Phase 2 主要是 Streamlit UI，但也可以直接使用编程接口：

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
│   ├── session.py         # 会话管理
│   ├── memory_writer.py   # Memory V2 写入模块
│   ├── memory_retrieval.py # Memory V2 检索模块
│   ├── outbox_sync.py     # Outbox 同步模块
│   ├── app_service.py     # Streamlit 业务层
│   └── pdf_extractor.py   # PDF 文本提取（Phase 2.2）
├── tests/                 # 测试代码
│   ├── test_config.py
│   ├── test_llm_client.py
│   ├── test_session.py
│   ├── test_memory_writer.py
│   ├── test_memory_retrieval.py
│   └── test_pdf_extractor.py  # PDF 提取测试
├── scripts/               # 验收脚本
│   └── verify_phase2_ui.py
├── examples/              # 示例代码
│   └── simple_chat.py
├── streamlit_app.py       # Streamlit UI 主入口
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

### Q: PDF 上传失败怎么办？

**常见问题：**
- **加密 PDF**：使用解密工具移除密码后重试
- **扫描版 PDF**：当前不支持 OCR，请手动输入内容
- **文件过大**：压缩 PDF 或手动输入关键内容
- **损坏文件**：重新下载 PDF 或使用 PDF 修复工具

**技术细节：**
- PDF 提取使用 PyMuPDF (fitz) 库
- 仅支持可复制文本的 PDF
- 提取后自动清理临时文件

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
