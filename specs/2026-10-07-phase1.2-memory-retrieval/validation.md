# Validation — Phase 1.2: Memory V2 检索链路

## 验证目标

确认 Phase 1.2 的交付物符合 requirements.md 中定义的验收标准，Memory V2 检索链路正确集成到智能体宿主层。

## 验证层级

### 第一层：功能验证（必需）

验证核心检索功能是否可用。

#### 1.1 检索功能验证（P0）

**目标**：确认可以成功检索用户长期记忆

**验证步骤**：
```bash
# 1. 确保 Memory V2 环境运行
cd memoryV2-core
docker compose ps  # 确认 MySQL 和 Qdrant 运行

# 2. 安装依赖
cd papermind-host
pip install -e .

# 3. 运行检索测试
pytest tests/test_memory_retrieval.py::test_retrieve_with_results -v

# 4. 运行集成测试（可选，需要真实数据）
pytest tests/test_memory_retrieval.py -m integration -v
```

**预期结果**：
- 检索调用成功，无 API 错误
- 返回的证据格式正确（包含 fact_text, confidence, 时间戳）
- 证据按置信度排序

**失败条件**：
- `assemble_evidence_pack` 调用失败
- 返回的证据格式异常或缺失字段
- 检索超时或连接失败

---

#### 1.2 租户隔离验证（P0）

**目标**：确认不同租户/用户的记忆相互隔离

**验证步骤**：
```bash
# 运行租户隔离测试
pytest tests/test_memory_retrieval.py::test_tenant_isolation -v
```

**预期结果**：
- 用户 A 在 tenant_1 的检索不会返回 tenant_2 的记忆
- 同一租户下不同用户的记忆相互隔离
- Hard Filter 参数正确传递到 Memory V2

**失败条件**：
- 跨租户数据泄露
- Hard Filter 未生效

---

#### 1.3 证据注入验证（P0）

**目标**：确认检索到的证据正确注入到 LLM prompt

**验证步骤**：
```python
# 手动验证脚本
from papermind.memory_retrieval import retrieve_memory_context

async def test_evidence_injection():
    # 检索记忆
    memory_context = await retrieve_memory_context(
        query="我的研究方向是什么",
        tenant_id="test_tenant",
        user_id="alice",
        limit=5
    )
    
    print(memory_context)
    
    # 验证格式
    assert "[记忆检索结果]" in memory_context
    assert "来源" in memory_context or "未找到相关记忆" in memory_context

# 运行
import asyncio
asyncio.run(test_evidence_injection())
```

**预期结果**：
- 证据文本格式清晰，包含编号、内容、来源、时间戳、置信度
- 无证据时返回明确的"未找到相关记忆"提示
- 证据文本可直接注入 prompt，无需二次处理

**失败条件**：
- 证据格式混乱或缺失关键信息
- 无证据时返回空字符串或异常

---

#### 1.4 无证据处理验证（P1，可选）

**目标**：确认检索不到记忆时有合理的降级处理

**验证步骤**：
```bash
pytest tests/test_memory_retrieval.py::test_retrieve_no_results -v
```

**预期结果**：
- 返回明确的"未找到相关记忆"提示
- 不抛出异常，不阻断 LLM 回复
- prompt 中明确说明"请基于当前对话回答"

---

### 第二层：代码质量验证（必需）

验证代码符合项目标准。

#### 2.1 类型检查

**验证步骤**：
```bash
cd papermind-host
mypy papermind/ --strict
```

**预期结果**：
- 无类型错误
- `memory_retrieval.py` 所有公共接口有类型注解

**允许的例外**：
- 第三方库（Memory V2）的类型存根缺失（可忽略或添加 type: ignore）

---

#### 2.2 代码格式

**验证步骤**：
```bash
black --check papermind/ tests/
```

**预期结果**：
- 代码符合 black 格式规范

**修复方法**：
```bash
black papermind/ tests/
```

---

#### 2.3 单元测试覆盖率

**验证步骤**：
```bash
pytest --cov=papermind.memory_retrieval tests/test_memory_retrieval.py --cov-report=term-missing
```

**目标覆盖率**：
- `memory_retrieval.py` > 80%
- 整体覆盖率 > 70%

**说明**：覆盖率仅作参考，核心逻辑必须有测试

---

### 第三层：集成验证（必需）

验证与 Phase 1.1 的集成是否正常。

#### 3.1 LLM 客户端集成验证

**目标**：确认 LLM 客户端可以正确使用检索链路

**验证步骤**：
```python
# 测试脚本：chat_with_memory_demo.py
import asyncio
from papermind.config import get_config
from papermind.llm_client import LLMClient
from papermind.memory_retrieval import retrieve_memory_context

async def main():
    config = get_config()
    client = LLMClient(config)
    
    # 1. 检索记忆
    memory_context = await retrieve_memory_context(
        query="我的研究方向是什么",
        tenant_id="demo_tenant",
        user_id="alice"
    )
    
    print(f"[检索到的记忆]:\n{memory_context}\n")
    
    # 2. 构造包含记忆的 prompt
    messages = [
        {"role": "system", "content": memory_context},
        {"role": "user", "content": "我的研究方向是什么"}
    ]
    
    # 3. 调用 LLM
    reply = await client.chat(messages)
    print(f"[AI 回复]:\n{reply}")

asyncio.run(main())
```

**预期结果**：
- 脚本运行无报错
- LLM 回复基于检索到的记忆（如果有）
- 无记忆时 LLM 明确说明"未找到相关记忆"

---

#### 3.2 端到端场景验证

**场景 1：有相关记忆**

**前置条件**：
1. 在 MySQL 中插入测试记忆
   ```sql
   INSERT INTO facts (tenant_id, user_id, fact_text, created_at)
   VALUES ('test_tenant', 'alice', '我的研究方向是计算机视觉', NOW());
   ```

2. 运行 Outbox 同步（确保 Qdrant 有向量）
   ```bash
   cd memoryV2-core
   python -m memoryV2_core.sync_outbox
   ```

**执行步骤**：
1. 运行检索测试
   ```python
   result = await retrieve_memory_context(
       query="我的研究方向是什么",
       tenant_id="test_tenant",
       user_id="alice"
   )
   ```

2. 验证结果
   ```python
   assert "计算机视觉" in result
   assert "置信度" in result
   ```

**预期结果**：
- 检索到包含"计算机视觉"的记忆
- 证据格式完整

---

**场景 2：无相关记忆**

**前置条件**：
- 用户 Bob 在数据库中无任何记忆

**执行步骤**：
```python
result = await retrieve_memory_context(
    query="我的研究方向是什么",
    tenant_id="test_tenant",
    user_id="bob"
)
```

**预期结果**：
- 返回"未找到相关记忆"提示

---

**场景 3：租户隔离**

**前置条件**：
1. 用户 Alice 在 tenant_A 下有记忆："我喜欢深度学习"
2. 用户 Alice 在 tenant_B 下无记忆

**执行步骤**：
```python
# 检索 tenant_A
result_a = await retrieve_memory_context(
    query="我喜欢什么",
    tenant_id="tenant_A",
    user_id="alice"
)

# 检索 tenant_B
result_b = await retrieve_memory_context(
    query="我喜欢什么",
    tenant_id="tenant_B",
    user_id="alice"
)
```

**预期结果**：
- `result_a` 包含"深度学习"
- `result_b` 返回"未找到相关记忆"

---

## 性能和资源验证（可选）

### 检索延迟

**目标**：确认检索在合理时间内完成

**验证方法**：
```python
import time

start = time.time()
result = await retrieve_memory_context(
    query="测试查询",
    tenant_id="test_tenant",
    user_id="alice"
)
elapsed = time.time() - start

assert elapsed < 1.0  # 1 秒内完成
print(f"检索延迟：{elapsed:.3f} 秒")
```

**说明**：延迟受网络和数据库负载影响，仅作参考

---

### 错误处理

**目标**：确认 Memory V2 不可用时有降级策略

**验证方法**：
1. 停止 Qdrant 服务
   ```bash
   docker compose stop qdrant
   ```

2. 运行检索测试
   ```bash
   pytest tests/test_memory_retrieval.py::test_retrieve_timeout -v
   ```

**预期结果**：
- 检索超时或失败后返回降级提示
- 不抛出未捕获的异常

---

## 文档完整性验证（必需）

### README.md 更新验证

**验证清单**：
- [ ] README 包含 Memory V2 检索链路的使用说明
- [ ] 包含代码示例：如何调用 `retrieve_memory_context`
- [ ] 说明检索参数（query, tenant_id, user_id, limit）

**验证方法**：
按照 README 步骤操作，确认能成功运行示例代码。

---

### Docstring 验证

**验证清单**：
- [ ] `retrieve_memory_context` 有完整的 docstring
- [ ] `format_evidence_pack` 有完整的 docstring
- [ ] Docstring 说明参数、返回值和异常

**验证方法**：
人工审查 `memory_retrieval.py` 的 docstring 是否完整。

---

## 合并前检查清单

在将 `feature/phase1.2-memory-retrieval` 合并到 `main` 之前，确认以下所有项：

### 功能完整性
- [ ] 检索功能验证通过（P0）
- [ ] 租户隔离验证通过（P0）
- [ ] 证据注入验证通过（P0）
- [ ] 无证据处理验证通过（P1，可选）

### 代码质量
- [ ] 类型检查通过（mypy --strict）
- [ ] 代码格式符合规范（black）
- [ ] 单元测试覆盖率 > 80%（memory_retrieval.py）

### 集成验证
- [ ] LLM 客户端集成验证通过
- [ ] 端到端场景验证通过（至少验证场景 1 和场景 2）

### 文档完整性
- [ ] README.md 包含检索链路使用说明
- [ ] 公共接口有 docstring
- [ ] `.env.example` 包含新增的配置项

### 无阻塞性 bug
- [ ] 无已知的崩溃或数据损坏问题
- [ ] 错误处理合理（有降级策略）
- [ ] 租户隔离无漏洞

### Git 提交规范
- [ ] 提交信息清晰（符合 Conventional Commits）
- [ ] 无敏感信息（API Key、密码）提交到代码仓库
- [ ] 分支从最新的 main 分支切出或已 rebase

---

## 验证失败处理流程

### 功能验证失败
1. 记录失败的测试用例和错误日志
2. 分析根本原因（代码 bug、Memory V2 API 变更、配置错误）
3. 修复后重新运行验证

### 租户隔离失败
1. 检查 Hard Filter 参数是否正确传递
2. 验证 Memory V2 的 `assemble_evidence_pack` 是否支持 Hard Filter
3. 添加调试日志，跟踪检索过程

### 代码质量验证失败
1. 运行自动格式化工具（black）
2. 修复类型错误（mypy）
3. 补充缺失的测试

### 文档验证失败
1. 更新 README.md 或 docstring
2. 确认示例代码可运行
3. 重新执行文档验证

---

## 验证报告模板

验证完成后，填写以下报告：

```markdown
## Phase 1.2 验证报告

**日期**：YYYY-MM-DD  
**验证人**：[姓名]  
**分支**：feature/phase1.2-memory-retrieval  
**Commit**：[commit hash]

### 功能验证结果
- [ ] 检索功能验证：通过 / 失败（原因：___）
- [ ] 租户隔离验证：通过 / 失败（原因：___）
- [ ] 证据注入验证：通过 / 失败（原因：___）
- [ ] 无证据处理验证：通过 / 失败 / 跳过

### 代码质量验证结果
- [ ] 类型检查：通过 / 失败（错误数：___）
- [ ] 代码格式：通过 / 失败
- [ ] 单元测试覆盖率：___%（目标 > 80%）

### 集成验证结果
- [ ] LLM 客户端集成：通过 / 失败
- [ ] 场景 1（有相关记忆）：通过 / 失败
- [ ] 场景 2（无相关记忆）：通过 / 失败
- [ ] 场景 3（租户隔离）：通过 / 失败 / 跳过

### 文档完整性验证结果
- [ ] README.md：完整 / 需补充（___）
- [ ] Docstring：充分 / 不足

### 合并建议
- [ ] 建议合并（所有 P0 验证通过）
- [ ] 建议修复后合并（列出待修复问题：___）
- [ ] 不建议合并（重大问题：___）

### 性能指标（可选）
- 检索平均延迟：___ ms
- 检索成功率：___%

### 备注
[其他需要说明的内容]
```

---

## 后续集成验证（Phase 1.3 之后）

Phase 1.2 合并后，还需要在后续阶段验证：
- Memory V2 写入链路集成（Phase 1.3）
- CLI 界面中检索结果的展示（Phase 1.4）
- 端到端场景测试（Phase 1.5）

这些验证将在各自的 validation.md 中定义。

---

## 关键验证指标

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| 检索成功率 | > 95% | 运行 100 次检索测试，统计成功率 |
| 检索延迟 | < 1s | 测量 `retrieve_memory_context` 执行时间 |
| 租户隔离 | 100% | 跨租户检索测试，确保无数据泄露 |
| 代码覆盖率 | > 80% | pytest --cov |
| 类型检查 | 0 错误 | mypy --strict |

---

## 验证环境要求

- Python 3.11+
- Memory V2 核心模块已安装
- MySQL 8.0+ 运行中
- Qdrant 运行中
- 有效的 BAILIAN_API_KEY（用于 LLM 调用测试）

---

**验证完成标志**：所有 P0 验证项通过，代码质量和文档完整性达标
