# Requirements — Phase 1.1: 智能体宿主模块

## 功能范围

Phase 1.1 专注于构建智能体宿主层的基础设施，为后续 Memory V2 集成打下基础。

**包含**：
- 模型客户端封装（DashScope OpenAI 兼容接口）
- 会话状态管理（内存 dict，维护 tenant_id, user_id, turn_id）
- 环境变量配置加载（python-dotenv）
- 基础项目结构和依赖管理（pyproject.toml）

**不包含**：
- Memory V2 检索和写入链路（留给 Phase 1.2 和 1.3）
- CLI 命令行界面（留给 Phase 1.4）
- 会话持久化（MVP 阶段使用内存，后续按需迁移 Redis）

## 技术选型决策

### LLM API
- **选择**：百炼 DashScope（OpenAI 兼容接口）
- **模型**：qwen-max（主力）、qwen-plus、qwen-turbo
- **理由**：
  - 符合 tech-stack.md 既定方案
  - OpenAI 兼容接口易于后续切换其他模型
  - 国内访问稳定，适合课程作业展示

### 会话管理
- **选择**：内存 dict
- **理由**：
  - MVP 阶段无需多进程共享会话
  - 简化初期实现，减少外部依赖
  - 后续可无缝迁移到 Redis

### 配置管理
- **选择**：python-dotenv + Pydantic Settings
- **理由**：
  - 与 Memory V2 核心保持一致
  - 类型安全的配置验证
  - 支持 .env 文件和环境变量

### 项目结构
```text
papermind-host/
├── papermind/
│   ├── __init__.py
│   ├── config.py          # 环境变量和配置（Pydantic BaseSettings）
│   ├── llm_client.py      # 模型客户端封装
│   └── session.py         # 会话状态管理
├── tests/
│   ├── __init__.py
│   ├── test_llm_client.py
│   └── test_session.py
├── pyproject.toml         # 项目元数据和依赖
├── .env.example           # 环境变量模板
└── README.md              # 快速开始指南
```

## 核心模块职责

### config.py
- 加载环境变量（BAILIAN_API_KEY, LLM_MODEL 等）
- 使用 Pydantic BaseSettings 进行类型验证
- 提供默认配置和配置覆盖机制

### llm_client.py
- 封装 OpenAI SDK 调用 DashScope 接口
- 支持同步和异步调用（优先异步）
- 处理 API 错误和重试逻辑
- 支持流式和非流式回复

### session.py
- 维护会话状态（tenant_id, user_id, turn_id）
- turn_id 自动递增
- 会话隔离（按 tenant_id + user_id 分组）
- 提供获取/创建/清除会话的接口

## 验收标准（已放宽）

### 最低验收标准
1. **LLM 调用成功**：
   - 可以成功调用 Qwen 模型并获得回复
   - 能够处理简单的对话请求
   - API 错误有基本的异常处理

### 扩展验收标准（可选）
2. **会话状态维护**（如时间允许）：
   - 会话状态正确维护 tenant_id, user_id, turn_id
   - turn_id 在同一会话内单调递增
   - 不同用户的会话相互隔离

3. **配置加载**（如时间允许）：
   - 从 .env 文件正确加载 API Key
   - 配置缺失时有清晰的错误提示

## 非功能需求

### 代码质量
- 类型注解覆盖所有公共接口
- 核心模块有基础单元测试
- 代码符合 PEP 8 规范（使用 black 格式化）

### 文档
- README.md 包含快速开始指南
- .env.example 说明所有必需的环境变量
- 核心函数有 docstring

### 依赖管理
- 使用 pyproject.toml（Poetry 或 setuptools 风格）
- 依赖版本明确锁定（避免版本冲突）
- 最小化依赖数量（仅包含必需库）

## 时间规划

**原计划**：1 天  
**调整后**：可灵活分配，建议拆分为：
- 项目结构和配置模块：0.3 天
- LLM 客户端封装：0.4 天
- 会话管理（可选）：0.3 天

## 风险和依赖

### 技术风险
- **DashScope API 配额**：可能遇到速率限制或配额不足
  - 缓解：实现重试机制，提示用户配额不足
- **OpenAI SDK 兼容性**：DashScope 的 OpenAI 兼容接口可能有细微差异
  - 缓解：参考 DashScope 官方文档，测试常见调用场景

### 外部依赖
- 需要有效的百炼 API Key（BAILIAN_API_KEY）
- 需要网络连接访问 DashScope 服务

## 成功标志

当以下条件满足时，Phase 1.1 可以合并到主分支：
1. 可以成功调用 Qwen 模型生成回复
2. 代码通过基础测试（至少有 LLM 调用的集成测试）
3. README.md 提供清晰的使用说明
4. 无已知的阻塞性 bug

## 参考资料

- [DashScope OpenAI 兼容接口文档](https://help.aliyun.com/zh/model-studio/developer-reference/compatibility-of-openai-with-dashscope/)
- [OpenAI Python SDK](https://github.com/openai/openai-python)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
