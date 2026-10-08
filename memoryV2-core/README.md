# Memory V2 核心代码提取

来源：`C:/Users/yilin/Desktop/bailian-memoryV2-0912`，提取日期：2026-10-07。

本目录用于后续科研智能体的代码复用与数据库调研。保留原 `server.memory_v2` 包路径；源项目未修改。交付包括核心代码提取、最小导入解耦、依赖配置及验证记录。

后续本机环境配置已在相邻的 `../memoryV2-local-env/` 完成：MySQL、Qdrant、核心表及向量集合已初始化，同步/异步数据库连接与 IndexV2 向量读写已验证。提取目录保持快照形式；模型调用和完整端到端流程仍未验证。详情参见该目录 README 与环境验证报告。

## 提取内容

- `server/memory_v2/`：78 个核心 Python 文件，包括写入门控与抽取器、版本化存储、检索与证据组装、生成守卫、策略、高敏身份、偏好、迁移、Outbox 和接线工厂。
- `server/core/`：collection 管理、重排序适配器，以及独立模型/向量库配置桥接。
- `server/database/`：原连接池和独立数据库配置桥接。
- `server/memory_v2/tests/`：19 个精选原有离线测试文件，原样保留；其中部分测试与最新接口不一致，见下文。
- `tests/test_extraction_boundary.py`：独立导入、语法、导入不联网验证。
- `extraction-manifest.json`：源文件与提取文件 SHA-256、最小修正和生成文件清单。
- `known-upstream-import-issues.json`：原有内部缺失模块/导出静态检查结果。

排除了评测运行器、acceptance 集成环境、benchmark、debug HTTP 端点、历史结果、备份、模型权重，以及原应用和业务数据库表。原 `.env` 与包含非核心应用配置的共享 settings 未复制。

## 入口与调用边界

| 入口 | 用途 | 外部条件 |
|---|---|---|
| `store.fact_store.FactStore` | 核心事实写入、版本与查询 | SQLAlchemy Session；离线测试可用 SQLite |
| `write.writer.MemoryWriter` | 抽取、门控、分发 | 注入抽取器与 Store；真实抽取需要模型服务 |
| `retrieve.evidence_pipeline.EvidencePipeline` | 检索、过滤、证据组装 | 注入索引、重排器与 Session |
| `wiring.create_memory_writer` | 原默认完整写入接线 | MySQL 同步/异步连接池和模型客户端 |
| `production_entry.assemble_evidence_pack` | 原生产检索接线 | SQL 数据库、Qdrant、Embedding、重排服务 |
| `facade.MemoryCompatFacade` | 与旧 mem0 的兼容层 | 原接口依赖调用方传入 legacy_memory |
| `outbox_consumer` | SQL 记忆同步到向量索引 | 数据库、Embedding、Qdrant；需显式启动 |

完整默认接线仍具有旧业务的记忆语义，后续科研假设、文献来源、实验反馈和规划功能需要另外设计。

## 数据库结论

| 组件 | 作用 | 当前代码状态 |
|---|---|---|
| **MySQL 8.0+** | 记忆记录、当前版本、事件、实体、策略和 Outbox | 原默认接线使用 `pymysql` 与 `aiomysql`，改造最少 |
| **Qdrant** | 记忆向量索引与相似度检索 | `IndexV2` 已有适配；本地需部署服务 |
| SQLite | 核心 Store 的轻量离线验证 | 已有测试采用；完整接线不能只改 URL 就切换 |

提取的核心接线没有直接 Redis 依赖。原项目的 Redis 用于更外围的对话/会话业务；当前提取没有把这些业务一起带入。

`QDRANT_PORT=8701` 沿用原项目配置。Qdrant 标准 HTTP 端口是 6333；使用容器时可映射为 `8701:6333`。数据库安装、数据库创建、模型配置及真实服务验证留到后续步骤。

原核心有两套向量维度入口：Embedding 使用 `MODEL_EMBEDDING_QWEN_DIM`，QdrantManager 建 collection 使用 `EMBEDDING_DIM`。示例将两者均设为 1536；`IndexV2` 部分调用仍硬编码 1536，改变维度需要同时检查调用方与索引，不能仅改一个变量。

## 配置和本地检查

Python 建议 3.11+。当前验证使用已有 Python 环境，未安装或升级系统依赖。

```powershell
cd C:\Users\yilin\Desktop\Agent\memoryV2-core
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/verify_extraction.py
.\.venv\Scripts\python.exe -m pytest tests/test_extraction_boundary.py -q
```

`verify_extraction.py` 校验交付快照，不连接服务。复制 `.env.example` 为 `.env` 并配置凭据后，会改变快照的运行配置；快照验证应在此之前执行。共享配置桥接不在导入时创建任何表。

真实接线前需要先创建 MySQL 数据库，再显式初始化主模型、实体、身份与偏好等表；`create_all` 只建缺失表，不升级已有表结构。此提取没有添加数据库部署脚本或自动迁移工具。

## 相对源代码的修改

1. `write/extractors/__init__.py` 改为 `.base` 相对导入，修复独立包导入。
2. `guard/critical_guard.py` 修复一个 f-string 内未转义引号，仅改变字符串定界符。
3. 顶层 `server`、`core` 和 `database` 包使用轻量初始化，防止加载原应用；顶层包提前加载本目录 `.env`，使核心功能开关在初始化前生效。
4. `core/settings.py` 与 `database/database_bailian_config.py` 使用独立环境变量配置桥接；保持核心所需类名，移除原应用配置与导入时业务表建表操作。
5. 依赖清单明确声明 `SQLAlchemy[asyncio]` 与 `PyMySQL[rsa]`，覆盖新环境的异步连接和 MySQL 8.4 默认认证需求。

其余已复制核心与共享源文件保持字节一致，详见 manifest。

## 已知问题与测试状态

静态扫描发现原有扩展路径引用不存在的 `store.models`、`write.id_gen`、`store.active_fact`，以及模型导出 `Claim`、`EventRecord`、`OutboxEvent`、`EntityRecord`。这些引用已在来源项目确认，未通过名称猜测替换；对应功能调用仍可能失败。

最近运行全部交付测试的结果：**202 passed、41 failed、10 errors**，包含新增的 5 项提取边界测试。详细结果保存在 `validation/upstream-tests.xml`。失败主要是：

- Writer/Extractor 测试仍假定旧的 list/WriteTrace 契约，实际代码返回 LaneOutcome/V2WriteResult。
- 检索 FakeIndex 未接受最新租户参数；subject_id 断言与最新格式不一致。
- HardFilter 测试调用旧的 `apply` 方法。
- EntityStore 测试传入 URL，现构造器需要 Session 工厂。
- SpeechAct 的分类预期与现有实现不一致，需逐例确认需求。
- 文件型 SQLite 幂等测试在 Windows 清理阶段存在未释放连接，导致临时文件删除失败。

这些原有测试作为复用参考保留。没有为让旧测试通过而更改业务逻辑。当前全测试集不是通过状态。

提取边界新增测试 **5/5 通过**，覆盖全部核心语法、抽取器包导入、阻断网络连接时的配置/写入工厂导入、`.env` 功能开关加载顺序，以及示例向量维度的一致性。完整核验结果见 `VERIFICATION.md`。
