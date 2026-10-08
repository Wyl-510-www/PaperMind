# Requirements — Phase 1.2: Memory V2 检索链路

## 功能范围

Phase 1.2 专注于将 Memory V2 的检索能力集成到智能体宿主层，使 AI 回复能够基于用户的长期记忆。

**包含**：
- 封装 `assemble_evidence_pack` 调用
- 将检索到的证据注入到 LLM prompt 中
- 实现"无证据时明确说明未知"的提示词模板
- 租户和用户隔离的检索逻辑

**不包含**：
- Memory V2 写入链路（留给 Phase 1.3）
- CLI 命令行界面（留给 Phase 1.4）
- 复杂的 Reranking 或多轮对话上下文（MVP 使用基础检索）

## 技术选型决策

### 检索策略
- **选择**：完整检索链路（Hard Filter + Top-K + 基础 Reranker）
- **理由**：
  - 需要 Hard Filter 确保租户隔离（P0 需求）
  - Top-K 向量检索是核心功能
  - 基础 Reranker 提升检索质量，符合 Memory V2 设计
  - 不实现多轮对话上下文（简化 MVP）

### 证据注入格式
- **选择**：结构化证据包
- **理由**：
  - 按置信度排序，提供清晰的信息层次
  - 标注来源和时间戳，增强可解释性
  - 便于后续 UI 展示证据来源
  - 比简单文本拼接更易于调试和维护

### 无证据处理
- **选择**：Prompt 提示（明确告知无相关记忆）
- **理由**：
  - 让 LLM 根据上下文决定如何回复（更灵活）
  - 避免前置拦截导致的体验割裂
  - 简单直接，符合 MVP 原则

### 项目结构
```text
papermind-host/
├── papermind/
│   ├── __init__.py
│   ├── config.py
│   ├── llm_client.py
│   ├── session.py
│   └── memory_retrieval.py    # 新增：Memory V2 检索封装
├── tests/
│   ├── test_config.py
│   ├── test_llm_client.py
│   ├── test_session.py
│   └── test_memory_retrieval.py  # 新增：检索链路测试
└── ...
```

## 核心模块职责

### memory_retrieval.py
- 封装 `assemble_evidence_pack` 调用
- 实现租户/用户隔离的检索逻辑
- 将检索结果格式化为结构化证据包
- 提供统一的检索接口供 LLM 调用

**核心接口**：
```python
async def retrieve_memory_context(
    query: str,
    tenant_id: str,
    user_id: str,
    limit: int = 5
) -> str:
    """
    检索用户长期记忆并格式化为 prompt 注入文本
    
    Args:
        query: 用户查询文本
        tenant_id: 租户 ID（用于隔离）
        user_id: 用户 ID（用于隔离）
        limit: 返回的最大证据数量
    
    Returns:
        格式化的证据文本，包含来源、时间戳和置信度
        如果无相关记忆，返回明确的"无记忆"提示
    """
    pass
```

## 验收标准

### P0 验收标准（必需）
1. **检索功能可用**：
   - 可以成功调用 `assemble_evidence_pack` 并获得检索结果
   - 检索结果正确过滤租户和用户（Hard Filter）
   - 返回的证据按置信度排序

2. **证据注入正确**：
   - 检索到的证据正确格式化并注入到 prompt
   - 证据包含来源、时间戳和置信度信息
   - prompt 格式清晰易读

3. **无证据处理**：
   - 检索不到记忆时，prompt 中明确说明"无相关记忆"
   - LLM 能够根据 prompt 提示给出合理回复

### P1 验收标准（可选）
4. **错误处理**：
   - Memory V2 服务不可用时有明确的降级策略
   - 检索超时或失败不阻断 LLM 回复

5. **性能要求**：
   - 检索延迟在合理范围内（< 500ms）
   - 支持并发检索请求

## 验证场景

### 场景 1：有相关记忆
**前置条件**：
- 用户 Alice 在 tenant_default 下已有记忆："我的研究方向是计算机视觉"

**执行步骤**：
1. 调用 `retrieve_memory_context("我的研究方向是什么", "tenant_default", "alice")`
2. 检查返回的证据文本

**预期结果**：
- 返回格式化的证据，包含"我的研究方向是计算机视觉"
- 证据包含来源（fact_id）、时间戳和置信度
- 格式清晰，可直接注入 prompt

### 场景 2：无相关记忆
**前置条件**：
- 用户 Bob 在 tenant_default 下无任何记忆

**执行步骤**：
1. 调用 `retrieve_memory_context("我的研究方向是什么", "tenant_default", "bob")`
2. 检查返回的证据文本

**预期结果**：
- 返回明确的"无相关记忆"提示
- prompt 格式为："[记忆检索结果]：未找到相关记忆"

### 场景 3：租户隔离
**前置条件**：
- 用户 Alice 在 tenant_A 下有记忆："我喜欢深度学习"
- 用户 Alice 在 tenant_B 下无记忆

**执行步骤**：
1. 调用 `retrieve_memory_context("我喜欢什么", "tenant_A", "alice")`
2. 调用 `retrieve_memory_context("我喜欢什么", "tenant_B", "alice")`

**预期结果**：
- tenant_A 的检索返回"我喜欢深度学习"
- tenant_B 的检索返回"无相关记忆"
- 证明租户隔离生效

## 非功能需求

### 代码质量
- 类型注解覆盖所有公共接口
- 核心函数有完整的 docstring
- 代码符合 PEP 8 规范（使用 black 格式化）
- 通过 mypy 类型检查（--strict）

### 测试覆盖
- Mock 测试：验证检索逻辑和格式化逻辑
- 集成测试：验证与 Memory V2 的实际交互（可选）
- 租户隔离测试：验证 Hard Filter 生效

### 依赖管理
- 确保 Memory V2 核心模块可正确导入
- 添加必要的依赖到 `pyproject.toml`

## 技术决策记录

| 决策点 | 选项 | 最终选择 | 理由 |
|--------|------|---------|------|
| 检索深度 | 基础 Top-K / 完整链路 / 高级检索 | 完整链路（Hard Filter + Reranker） | 租户隔离是 P0 需求，Reranker 提升质量 |
| 证据格式 | 简单拼接 / 结构化 / 多格式 | 结构化证据包 | 可读性高，便于调试和后续 UI 展示 |
| 无证据处理 | Prompt 提示 / 前置拦截 / 智能路由 | Prompt 提示 | 简单灵活，让 LLM 决定如何回复 |
| 测试策略 | Mock / 集成 / 隔离测试 | Mock + 租户隔离测试 | Mock 快速验证，隔离测试确保核心功能 |

## 风险和依赖

### 技术风险
- **Memory V2 服务依赖**：检索依赖 MySQL 和 Qdrant 正常运行
  - 缓解：实现降级策略，服务不可用时跳过检索
- **检索质量**：可能检索到不相关的记忆
  - 缓解：使用 Reranker 提升精度，后续可调整 top_k 参数

### 外部依赖
- Memory V2 核心模块（`memoryV2-core/`）
- MySQL 和 Qdrant 服务正常运行
- Phase 1.1 的智能体宿主模块已完成

## 成功标志

当以下条件满足时，Phase 1.2 可以合并到主分支：
1. 可以成功检索用户长期记忆并注入 prompt
2. 租户和用户隔离生效（Hard Filter 正常工作）
3. 无证据时有明确的 prompt 提示
4. 代码通过单元测试和类型检查
5. 无已知的阻塞性 bug

## 时间规划

**预估时间**：1 天

**任务分解**：
- 实现 `memory_retrieval.py` 核心逻辑：0.4 天
- 证据格式化和 prompt 注入：0.2 天
- 单元测试和集成测试：0.3 天
- 文档和代码审查：0.1 天

## 参考资料

- Memory V2 设计文档（`memoryV2-core/docs/`）
- `assemble_evidence_pack` API 文档
- Phase 1.1 智能体宿主模块实现
