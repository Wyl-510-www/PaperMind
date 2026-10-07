# Tech Stack — PaperMind

## 架构原则

- **保持轻量**：复用现有 Memory V2 核心，避免过度设计
- **渐进演进**：从 CLI Demo 开始，逐步增加 Web UI 和文档处理能力
- **技术深度优先**：展示 Memory V2 架构创新，而非堆砌流行框架
- **课程作业友好**：清晰的技术选型说明，便于评审理解

## 核心技术栈

### 1. 智能体层（待构建）

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 对话编排 | Python 3.11+ | 异步应用，复用 Memory V2 的 asyncio 架构 |
| HTTP 服务 | FastAPI | 轻量级，原生支持异步，自动生成 OpenAPI 文档 |
| CLI 工具 | Click / Rich | Click 处理命令行参数，Rich 提供美观输出 |
| 会话管理 | 内存 dict / Redis（可选）| MVP 使用内存，后续可接 Redis |

### 2. Memory V2 核心（已有）

| 组件 | 技术选型 | 版本 |
|------|---------|------|
| 编程语言 | Python | 3.11+ （当前环境 3.12）|
| 异步框架 | asyncio | 标准库 |
| 数据模型 | Pydantic | 2.x |
| ORM | SQLAlchemy | 2.x，异步引擎 |
| 测试框架 | pytest + pytest-asyncio | - |

### 3. 大语言模型

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| LLM API | 百炼 DashScope | OpenAI 兼容接口 |
| 主力模型 | Qwen 系列 | qwen-max, qwen-plus, qwen-turbo |
| Embedding | text-embedding-v4 | 维度 1536 |
| Reranker | SiliconFlow Qwen Reranker | 检索结果重排序 |

### 4. 数据存储

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| 事实存储 | MySQL 8.0+ | 记忆真值、版本化事实/事件/实体/策略 |
| 向量索引 | Qdrant | 语义相似度检索 |
| 文档存储 | 本地文件系统 | PDF/Markdown 原始文件（MVP 阶段）|

### 5. 前端界面（Phase 2）

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 框架 | React 18+ | 生态成熟，组件丰富 |
| UI 库 | Ant Design / Shadcn UI | Ant Design 适合后台，Shadcn UI 更现代 |
| 状态管理 | React Query / Zustand | React Query 管理服务端状态 |
| 构建工具 | Vite | 快速开发体验 |

## Memory V2 技术亮点

### 写入链路

```text
Speech Act 分类
    ↓
多 lane 并行抽取（事实/事件/实体/策略）
    ↓
Memory Gate 门控（过滤查询型消息）
    ↓
Dispatcher 路由
    ↓
版本化 Store（MySQL 真值存储）
    ↓
Outbox 事件队列
    ↓
异步同步到 Qdrant 向量索引
```

**创新点**：
- Speech Act 分类避免将查询误写为记忆
- 多 lane 并行抽取提升写入效率
- 版本化存储支持记忆追溯和回滚
- Outbox 模式确保最终一致性

### 检索链路

```text
Query Router（意图识别）
    ↓
Embedding（向量化）
    ↓
Qdrant 相似度检索（Top-K）
    ↓
Hard Filter（租户隔离、状态过滤）
    ↓
Scorer / Reranker（精排）
    ↓
EvidencePack（证据包，附带置信度和来源）
```

**创新点**：
- 多级过滤确保租户隔离
- Reranker 二次精排提升准确率
- 证据包包含来源、置信度和使用规则
- 智能体只能基于证据回答，无证据时明确说明

## 部署架构

### MVP 阶段（本地开发）

```text
┌─────────────────┐
│  CLI / FastAPI  │ ← 智能体宿主层
└────────┬────────┘
         │
    ┌────▼────┐
    │ Memory  │
    │   V2    │
    └─┬────┬──┘
      │    │
  ┌───▼┐ ┌─▼────┐
  │MySQL│ │Qdrant│
  └─────┘ └──────┘
  
全部运行在 localhost
Docker Compose 管理数据库
```

### Phase 2（可选云部署）

```text
前端（静态托管）
    ↓
后端 API（云服务器 / Serverless）
    ↓
Memory V2
    ↓
云数据库（MySQL + Qdrant Cloud）
```

## 环境配置

### 必需的环境变量

```bash
# 数据库
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=memoryv2
DB_PASS=<MYSQL_APP_PASSWORD>
DB_NAME=memory_v2

# Qdrant
QDRANT_HOST=127.0.0.1
QDRANT_PORT=8701
MEMORY_V2_QDRANT_URL=http://127.0.0.1:8701

# 模型 API
BAILIAN_API_KEY=<your-dashscope-key>
RERANKER_SILICONFLOW_API_KEY=<your-siliconflow-key>

# 可选：应用配置
LOG_LEVEL=INFO
ENABLE_SPEECH_ACT_GATE=true
```

### 本地启动流程

```bash
# 1. 启动数据库
cd memoryV2-local-env
docker compose up -d

# 2. 初始化数据库表和 Qdrant collection
python verify_environment.py --initialize-memory-storage

# 3. 启动智能体服务（待构建）
cd ../papermind-host
python -m papermind.cli chat  # CLI 模式
# 或
uvicorn papermind.api:app --reload  # API 模式
```

## 技术债务和已知限制

- **Outbox 同步任务**：需要单独启动后台 worker，当前未自动化
- **文献解析**：PDF 提取、分块和文档级 RAG 尚未接入
- **前端界面**：MVP 阶段无 UI，仅命令行
- **兼容层**：`create_facade` 仍需要传入 mem0 兼容对象，纯 V2 应用需自行适配
- **测试覆盖**：核心模块有单元测试，但缺少端到端集成测试

## 后续技术演进

### Phase 2：增强功能
- 接入 PDF 解析（PyMuPDF / pdfplumber）
- 文档分块和向量化（LangChain Text Splitters）
- Web UI 开发（React + FastAPI）

### Phase 3：生产优化
- Redis 会话管理
- 云数据库迁移
- Prometheus + Grafana 监控
- CI/CD 自动化部署
