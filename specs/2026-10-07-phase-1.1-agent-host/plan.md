# Plan — Phase 1.1: 智能体宿主模块

## 任务组概览

本计划将 Phase 1.1 拆解为 4 个任务组，每组聚焦一个独立的交付物。

## 任务组 1：项目结构和依赖管理

**目标**：创建 `papermind-host/` 项目骨架，配置依赖和开发环境

**任务清单**：
1. 创建项目目录结构
   ```bash
   mkdir -p papermind-host/papermind
   mkdir -p papermind-host/tests
   ```

2. 编写 `pyproject.toml`
   - 项目元数据（名称、版本、描述）
   - 依赖声明：
     - `openai` (>= 1.0)：调用 DashScope
     - `pydantic` (>= 2.0)：配置管理
     - `pydantic-settings`：环境变量加载
     - `python-dotenv`：.env 文件支持
   - 开发依赖：`pytest`, `pytest-asyncio`, `black`, `mypy`

3. 创建 `.env.example`
   ```bash
   # DashScope API Key（百炼）
   BAILIAN_API_KEY=sk-xxx
   
   # 模型配置
   LLM_MODEL=qwen-max
   LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
   
   # 可选：日志级别
   LOG_LEVEL=INFO
   ```

4. 创建占位 `__init__.py` 文件

**产出**：
- 项目结构完整，可以被其他模块导入
- 依赖清单明确，可通过 `pip install -e .` 安装

**验收**：
- `pip install -e papermind-host/` 成功
- 无依赖冲突或版本错误

---

## 任务组 2：配置模块（config.py）

**目标**：实现类型安全的配置加载和验证

**任务清单**：
1. 定义 `Config` 类（继承 `pydantic_settings.BaseSettings`）
   - 字段：
     - `bailian_api_key: str`（必需）
     - `llm_model: str = "qwen-max"`
     - `llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"`
     - `log_level: str = "INFO"`
   - 配置来源：环境变量优先，.env 文件兜底

2. 实现配置加载函数
   ```python
   def get_config() -> Config:
       """加载并验证配置，缺失必需字段时抛出异常"""
   ```

3. 添加配置验证逻辑
   - API Key 不能为空
   - 模型名称在支持列表中（可选验证）

4. 编写单元测试
   - 测试从环境变量加载
   - 测试缺失 API Key 时抛出异常
   - 测试默认值生效

**产出**：
- `papermind/config.py` 完整实现
- 单元测试覆盖核心逻辑

**验收**：
- `pytest tests/test_config.py` 通过
- 缺失 API Key 时有清晰的错误提示

---

## 任务组 3：LLM 客户端封装（llm_client.py）

**目标**：封装 OpenAI SDK，提供统一的 LLM 调用接口

**任务清单**：
1. 实现 `LLMClient` 类
   - 初始化：接收 `Config` 对象，创建 OpenAI 客户端
   - 方法：
     - `async def chat(messages: list[dict], **kwargs) -> str`：异步调用，返回回复文本
     - （可选）`def chat_sync(messages: list[dict], **kwargs) -> str`：同步版本

2. 配置 OpenAI SDK
   ```python
   from openai import AsyncOpenAI
   
   client = AsyncOpenAI(
       api_key=config.bailian_api_key,
       base_url=config.llm_base_url
   )
   ```

3. 处理 API 调用
   - 构造 `messages` 参数
   - 调用 `client.chat.completions.create()`
   - 提取回复内容：`response.choices[0].message.content`

4. 错误处理
   - 捕获 `openai.APIError`、`openai.RateLimitError` 等异常
   - 包装为自定义异常或记录日志

5. 编写集成测试
   - 测试真实 API 调用（需要有效的 API Key）
   - 测试错误处理（可使用 mock）

**产出**：
- `papermind/llm_client.py` 完整实现
- 至少有一个成功的 API 调用测试

**验收**：
- 运行测试时能成功调用 Qwen 模型并获得回复
- 错误场景有基本的异常处理

---

## 任务组 4：会话管理（session.py，可选）

**目标**：维护会话状态，支持多用户隔离

**任务清单**：
1. 定义 `Session` 数据类
   ```python
   @dataclass
   class Session:
       tenant_id: str
       user_id: str
       turn_id: int = 0
       created_at: datetime = field(default_factory=datetime.now)
   ```

2. 实现 `SessionManager` 类
   - 内部存储：`dict[tuple[str, str], Session]`（key 为 (tenant_id, user_id)）
   - 方法：
     - `get_or_create_session(tenant_id: str, user_id: str) -> Session`
     - `increment_turn(tenant_id: str, user_id: str) -> int`：返回新 turn_id
     - `clear_session(tenant_id: str, user_id: str)`

3. 线程安全考虑（可选）
   - 如果支持多线程，使用 `threading.Lock`

4. 编写单元测试
   - 测试会话创建和获取
   - 测试 turn_id 递增
   - 测试多用户隔离

**产出**：
- `papermind/session.py` 完整实现
- 单元测试覆盖核心逻辑

**验收**：
- `pytest tests/test_session.py` 通过
- 不同用户的会话状态相互隔离

---

## 任务组 5：文档和示例

**目标**：提供清晰的使用说明和快速开始示例

**任务清单**：
1. 编写 `README.md`
   - 项目介绍
   - 安装步骤：
     ```bash
     cd papermind-host
     pip install -e .
     cp .env.example .env
     # 编辑 .env，填入 BAILIAN_API_KEY
     ```
   - 快速开始代码示例：
     ```python
     import asyncio
     from papermind.config import get_config
     from papermind.llm_client import LLMClient
     
     async def main():
         config = get_config()
         client = LLMClient(config)
         
         messages = [{"role": "user", "content": "你好"}]
         reply = await client.chat(messages)
         print(reply)
     
     asyncio.run(main())
     ```

2. 检查 `.env.example` 注释是否清晰

3. （可选）创建 `examples/simple_chat.py` 演示脚本

**产出**：
- `README.md` 完整且易于理解
- 外部开发者可以根据 README 快速上手

**验收**：
- 按照 README 步骤操作，能成功运行示例代码

---

## 任务执行顺序

建议按以下顺序执行：
1. **任务组 1**（项目结构）→ **任务组 2**（配置）→ **任务组 3**（LLM 客户端）
2. **任务组 4**（会话管理）和 **任务组 5**（文档）可并行或根据时间决定优先级

## 关键路径

**最小可交付路径**（满足放宽后的验收标准）：
- 任务组 1 + 任务组 2 + 任务组 3 + 任务组 5

**完整交付路径**（满足原始验收标准）：
- 任务组 1 + 任务组 2 + 任务组 3 + 任务组 4 + 任务组 5

## 时间分配建议

| 任务组 | 预估时间 | 优先级 |
|--------|---------|--------|
| 任务组 1：项目结构 | 0.5h | P0 |
| 任务组 2：配置模块 | 1h | P0 |
| 任务组 3：LLM 客户端 | 2h | P0 |
| 任务组 4：会话管理 | 1.5h | P1 |
| 任务组 5：文档和示例 | 1h | P0 |
| **总计** | **6h** | - |

**说明**：
- P0 任务必须完成才能验收
- P1 任务可根据实际进度决定是否包含

## 技术决策记录

| 决策点 | 选项 | 最终选择 | 理由 |
|--------|------|---------|------|
| 依赖管理工具 | Poetry / setuptools | setuptools (pyproject.toml) | 与 Memory V2 保持一致，避免引入新工具 |
| 异步框架 | asyncio / trio | asyncio | 标准库，与 Memory V2 一致 |
| 测试框架 | pytest / unittest | pytest | 社区标准，支持异步测试 |
| 类型检查 | mypy / pyright | mypy | Memory V2 使用 mypy |

## 风险缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| DashScope API 配额不足 | 测试无法运行 | 提供 mock 测试选项，文档说明配额要求 |
| OpenAI SDK 兼容性问题 | API 调用失败 | 参考 DashScope 官方示例，测试常见场景 |
| 时间不足 | 部分功能未完成 | 优先完成任务组 1-3-5（最小可交付路径）|
