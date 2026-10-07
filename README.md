# PaperMind

**AI Research Paper Reading & Memory Assistant**

一个面向硕博研究生的 AI 论文阅读与记忆助手，具有可追溯的长期记忆能力。

## 项目定位

PaperMind 帮助硕博研究生持续管理：
- 论文阅读过程中的关键发现和理解
- 研究方向、术语偏好和文献引用关系
- 研究任务计划、待办事项和时间线
- 个人工作习惯和偏好设置

## 核心特性

- ✅ **可追溯记忆**：每条记忆有版本、来源和时间戳
- ✅ **多租户隔离**：不同用户和租户的记忆严格隔离
- ✅ **证据驱动**：智能体只基于检索到的证据回答，无证据时明确说明未知
- ✅ **门控写入**：查询型或含义不明确的消息不会被误写成长期记忆
- ✅ **科研友好**：针对论文阅读、实验记录、任务规划等场景优化

## 技术架构

```text
用户消息
   │
   ▼
智能体宿主层 (Phase 1 开发中)
   ├─ 对话编排
   ├─ 文献/资料检索 (Phase 2)
   ├─ 提示词构建
   └─ 模型调用
        │
        ├─ 生成前：Memory V2 检索 EvidencePack
        └─ 生成后：Memory V2 写入用户陈述
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
          MySQL 真值存储          Qdrant 向量索引
          事实/事件/实体/策略      相似记忆检索
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 智能体编排 | Python 3.11+, FastAPI (Phase 2) |
| LLM | 百炼 DashScope (Qwen 系列) |
| Embedding | text-embedding-v4 (1536 维) |
| Reranker | SiliconFlow Qwen Reranker |
| 记忆核心 | Memory V2 (Pydantic, SQLAlchemy, asyncio) |
| 事实存储 | MySQL 8.0+ |
| 向量存储 | Qdrant |
| 前端 | React 18 + Ant Design (Phase 2) |

## 项目结构

```text
.
├── specs/                      # 项目规范文档
│   ├── mission.md              # 项目使命和定位
│   ├── tech-stack.md           # 技术栈详解
│   └── roadmap.md              # 实施路线图
├── memoryV2-core/              # Memory V2 核心模块
│   ├── server/memory_v2/write/ # 抽取、门控、写入编排
│   ├── server/memory_v2/store/ # MySQL 真值存储与 Outbox
│   ├── server/memory_v2/retrieve/ # 检索、过滤、重排、证据组装
│   └── server/memory_v2/guard/ # 声明、策略和敏感信息守卫
├── memoryV2-local-env/         # MySQL、Qdrant 本地环境
├── papermind-host/             # 智能体宿主层 (待构建)
└── README.md
```

## 快速开始

### 前置要求

- Python 3.11+
- Docker 和 Docker Compose
- 百炼 DashScope API Key
- SiliconFlow API Key (可选，用于 Reranker)

### 1. 启动本地环境

```bash
# 启动 MySQL 和 Qdrant
cd memoryV2-local-env
docker compose up -d

# 验证环境并初始化数据库
python verify_environment.py --initialize-memory-storage
```

### 2. 配置环境变量

```bash
# 复制示例配置
cp memoryV2-core/.env.example memoryV2-core/.env

# 编辑 .env 文件，填入真实 API Key
# BAILIAN_API_KEY=sk-xxx
# RERANKER_SILICONFLOW_API_KEY=sk-xxx
```

### 3. 运行 CLI Demo (Phase 1 开发中)

```bash
cd papermind-host
python -m papermind.cli chat --user alice --tenant default
```

## 开发路线

| Phase | 状态 | 说明 |
|-------|------|------|
| Phase 0 | ✅ 完成 | Memory V2 环境验证 |
| Phase 1 | 🚧 进行中 | CLI Demo，核心功能验证 (3-5天) |
| Phase 2 | 📅 计划中 | Web UI + 文档上传 (2-3周) |
| Phase 3 | 💡 可选 | 功能增强（实验记录、任务规划、知识图谱） |

详细路线图请查看 [specs/roadmap.md](specs/roadmap.md)

## 文档

- [Mission — 项目使命](specs/mission.md)
- [Tech Stack — 技术栈](specs/tech-stack.md)
- [Roadmap — 实施路线图](specs/roadmap.md)

## License

MIT

## 致谢

本项目基于 Memory V2 长期记忆核心模块构建。
