# Memory V2 本地依赖环境

此目录管理 MySQL、Qdrant 和独立 Python 环境，使用 `memoryV2-core` 进行连接与存储验证。Docker 项目名为 `memoryv2-local`，数据存入独立命名卷。

## 本机安装状态

2026-10-07 已实际完成本地安装与验证：

- 复用 Python 3.12.7，在本目录 `.venv` 安装核心依赖、异步 SQLAlchemy、MySQL RSA 认证支持和测试工具。
- 启动现有 Docker Desktop，下载并运行 MySQL 8.4.11 与 Qdrant 1.19.2。
- 生成本目录实际 `.env`，包含两组不同的随机数据库密码及应用连接参数；实际凭据未写入说明或输出。
- 创建 Memory V2 所需的 11 张表及 `bench_memory_v2_core` 向量集合（1536 维）。
- MySQL 同步/异步连接、Qdrant 健康检查、通过原 `IndexV2` 的向量写入与检索均通过；临时测试集合已移除。
- 新虚拟环境中的 5 项提取边界测试通过。

运行报告：`environment-verification.json`。模型 API 尚未调用；原核心已知缺失引用与旧测试失败详见 `../memoryV2-core/README.md`。

## 当前环境的常用命令

```powershell
Set-Location 'C:\Users\yilin\Desktop\Agent\memoryV2-local-env'
docker compose up -d
docker compose ps
& '.\.venv\Scripts\python.exe' -X utf8 verify_environment.py --initialize-memory-storage
```

依赖安装命令为 `& '.\.venv\Scripts\python.exe' -X utf8 -m pip install -r requirements-local.txt`。精确安装版本保存在 `requirements-lock.txt`。

验证脚本先加载本目录 `.env`，再导入提取代码，因此不需要向提取快照写入实际凭据。后续应用启动也应显式加载本目录环境，或者将对应参数注入进程环境。

| 服务 | 镜像 | 本机连接地址 | 用途 |
| --- | --- | --- | --- |
| MySQL | `mysql:8.4` | `127.0.0.1:3306` | 自动创建 `memory_v2` 数据库和 `memoryv2` 应用用户 |
| Qdrant | `qdrant/qdrant:v1.19.2` | `http://127.0.0.1:8701` | 向量存储，映射容器 HTTP 端口 `6333` |

端口只绑定 `127.0.0.1`。MySQL 使用官方 8.4 LTS 镜像标签，该标签会跟随 8.4 补丁更新；Qdrant 固定到官方稳定版本 [v1.19.2](https://github.com/qdrant/qdrant/releases/tag/v1.19.2)（2026-10-05 发布，已核实 Docker Hub 对应标签存在）。

## 启动

需要运行中的 Docker Desktop Linux 容器引擎。当前机器已有 Docker 29.8.1 客户端与 Python 3.12.7；客户端存在不代表引擎已经启动。先启动 Docker Desktop，再在 PowerShell 执行：

```powershell
Set-Location 'C:\Users\yilin\Desktop\Agent\memoryV2-local-env'
docker info
# 仅当 .env 尚不存在时复制，避免覆盖已经生成的凭据。
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
notepad .env
```

在 `.env` 中分别设置非空且不同的 `MYSQL_ROOT_PASSWORD` 与 `MYSQL_APP_PASSWORD`，建议使用至少 24 位随机字母数字。`.env` 已加入忽略规则。随后执行：

```powershell
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" -D "$MYSQL_DATABASE" -e "SELECT 1;"'
Invoke-RestMethod -Uri 'http://127.0.0.1:8701/healthz'
```

MySQL 初次初始化可能需要一分钟，等 `docker compose ps` 显示 `healthy` 后执行 SQL 验证。Compose 中的 MySQL 健康检查使用容器环境变量传递密码，不把真实密码写入检查命令。Qdrant 使用宿主机 HTTP 验证，未假设镜像内安装了 `curl`。

若端口已被占用，先确认本机现有服务，再调整 Compose 的宿主机端口与应用连接配置。本配置不发布 Qdrant gRPC 端口。

## 连接 Memory V2

在 `memoryV2-core` 的应用配置中使用以下连接参数（应用环境文件与本目录 `.env` 分开管理）：

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=memoryv2
DB_PASS=<本目录 MYSQL_APP_PASSWORD 的值>
DB_NAME=memory_v2
QDRANT_HOST=127.0.0.1
QDRANT_PORT=8701
MEMORY_V2_QDRANT_URL=http://127.0.0.1:8701
```

Compose 初始化数据库和用户；本机已通过 `verify_environment.py --initialize-memory-storage` 显式初始化 Memory V2 表及 Qdrant collection。应用编排、模型调用和科研业务的运行验证属于后续步骤。

LLM、embedding 与 rerank 仍需云 API 凭据：百炼/DashScope 的 `BAILIAN_API_KEY` 或 `DASHSCOPE_API_KEY`，以及 SiliconFlow 的 `RERANKER_SILICONFLOW_API_KEY`。模型名称、接口地址和 embedding 维度参见 `memoryV2-core/.env.example`。当前方案不下载本地模型，也不把 API 密钥写入 Compose。

## 停止与保留数据

```powershell
Set-Location 'C:\Users\yilin\Desktop\Agent\memoryV2-local-env'
docker compose down
```

`down` 删除本项目容器与网络，保留命名卷 `memoryv2-local_mysql_data` 和 `memoryv2-local_qdrant_data`；再次执行 `docker compose up -d` 会继续使用原数据。不要使用 `down -v`，它会删除这两份数据卷。

MySQL 的用户和密码环境变量只在数据卷首次初始化时生效。已有数据时，仅修改 `.env` 不会变更数据库中的密码；需要在 MySQL 内显式更新密码并同步应用配置。
