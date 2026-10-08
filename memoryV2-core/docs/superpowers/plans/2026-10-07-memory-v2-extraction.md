# Memory V2 核心代码提取 Implementation Plan

> **For agentic workers:** 使用当前会话顺序执行；独立代理只读审查依赖和最终交付，禁止改动来源项目。

**Goal:** 从 `C:/Users/yilin/Desktop/bailian-memoryV2-0912` 提取 Memory V2 核心代码到独立目录，提供依赖、配置、来源清单和离线验证。

**Architecture:** 保留 `server.memory_v2` 包结构，复制核心写入、存储、检索、守卫、迁移和编排模块。共享依赖限于配置、连接池、collection 管理和重排序；配置桥接使用环境变量，包初始化不加载原应用。

**Tech Stack:** Python、SQLAlchemy、MySQL 驱动、Qdrant client、OpenAI compatible SDK、pytest。

**Spec:** 本轮用户请求“先帮我提取出里面的 memoryV2 核心代码”。交付边界：核心提取，不实现科研业务，不部署数据库，不承诺在线端到端可用。

## Global Constraints

- 来源目录只读；复制文件记录源 SHA-256。
- 不复制 `.env`、密钥、历史测试结果、模型权重、缓存、备份或评测运行器。
- 原有核心文件仅允许修复确认的字符串语法错误和抽取器包导入路径，逐项记录。
- 独立配置桥接不在导入时建表或连接数据库。
- 运行既有离线测试及提取验证脚本；真实数据库、模型和检索服务的验证单独注明。

## Task 1: 确定边界

- [x] AST 检查核心导入，定位共享依赖。
- [x] 复现 `guard/critical_guard.py` 语法错误，定位到 f-string 内的未转义双引号。
- [x] 确认数据库接线默认为 MySQL，向量索引为 Qdrant，核心接线没有直接 Redis 依赖。

## Task 2: 提取与最小解耦

- [x] 创建提取边界验证测试，在修正之前运行，确认原有语法和导入缺陷。
- [x] 复制核心 `.py` 与精选原有离线测试；保留来源校验清单。
- [x] 添加轻量包初始化和环境配置桥接；配置参数在 `.env.example` 中列明。
- [x] 只在副本中修复已定位的 f-string 引号和抽取器包相对导入。
- [x] 添加中文 README、依赖清单、重复运行的验证脚本。

## Task 3: 验证与审查

- [x] 核验文件清单、源文件未变、复制文件一致、允许修改可追溯。
- [x] 对全部交付 Python 文件执行语法检查与内部 import 扫描，记录 18 处原有未闭合引用。
- [x] 运行提取验证测试和既有离线 Store/Writer/EvidencePipeline 测试；最终记录 202 passed、41 failed、10 errors，未扩大范围修复旧业务。
- [x] 代理只读审查配置、依赖、遗漏及说明是否准确；修正配置加载顺序与示例向量维度后，5 项边界测试全部通过，原失败数量未变。
- [x] 在 README 中区分离线验证和未执行的真实数据库、模型服务验证。
