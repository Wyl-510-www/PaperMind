# 验证记录

日期：2026-10-07。来源目录保持只读，测试在提取目录执行。未连接真实 MySQL、Qdrant 或模型服务。

## 提取测试 RED → GREEN

首次缺少提取文件时，三个边界测试失败；复制原核心后，复现字符串语法错误、裸 memory_v2 导入错误和缺少独立数据库配置桥接。最小修正后，`python -m pytest tests/test_extraction_boundary.py -q` 输出 `3 passed`。

审查发现 `.env` 功能开关加载过晚以及两套向量维度入口默认不一致。新增回归测试先输出 `2 failed, 3 passed`，提前加载 settings 并补齐 `.env.example` 后输出 **`5 passed`**。

## 原有测试检查

首次 `python -m pytest tests server/memory_v2/tests -q --tb=short`：`41 failed, 200 passed, 10 errors`。修正审查问题后执行 `python -m pytest tests server/memory_v2/tests -q --tb=no --junitxml=validation/upstream-tests.xml`：**`41 failed, 202 passed, 10 errors`**；增加的两项回归测试通过，原有失败/错误数量未变。原因分类见 README。原测试逐字节保留，避免将提取工作混入业务修复。未宣称原核心整体运行正常。

## 提取完整性与语法

`python scripts/verify_extraction.py` 已通过：100 个复制来源文件的 SHA-256 未变，100 个提取文件的 SHA-256 与清单一致，107 个交付 Python 文件通过 AST 语法检查。18 处已知内部导入问题对应 7 个缺失模块/导出目标，详情见 `known-upstream-import-issues.json`；核验通过表示提取清单完整且问题已记录，不代表这些运行路径可用。

额外静态扫描未发现交付运行模块含 `sk-` 形式的长密钥字符串；独立共享配置均从环境变量取凭据，实际 `.env` 没有复制。

## 尚待执行的运行验证

- MySQL 建库、主模型与独立 Base 的建表。
- Qdrant collection、向量维度和 Embedding 一致性。
- Outbox 写入、后台同步与真实长期召回。
- 实体、事件、策略检索的类型覆盖与更新/删除行为。
- 多用户/多课题隔离以及科研场景任务规划。

## 环境提示

现有 Python 环境加载 requests 时报告字符编码依赖兼容性警告，原实体 Store 使用 SQLAlchemy 已弃用的 declarative_base 导入。没有为消除这些提示而升级全局环境。
