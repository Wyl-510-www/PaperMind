# Validation — Phase 1.1: 智能体宿主模块

## 验证目标

确认 Phase 1.1 的交付物符合 requirements.md 中定义的验收标准，并且代码质量、文档完整性达到合并要求。

## 验证层级

### 第一层：功能验证（必需）

验证核心功能是否可用。

#### 1.1 LLM 调用验证（P0）

**目标**：确认可以成功调用 Qwen 模型并获得回复

**验证步骤**：
```bash
# 1. 配置环境变量
cd papermind-host
cp .env.example .env
# 编辑 .env，填入有效的 BAILIAN_API_KEY

# 2. 安装依赖
pip install -e .

# 3. 运行集成测试
pytest tests/test_llm_client.py -v

# 4. 运行示例脚本（如果提供）
python examples/simple_chat.py
```

**预期结果**：
- 测试通过，无 API 错误
- 示例脚本输出 Qwen 模型的回复文本
- 回复内容合理（非空，符合对话逻辑）

**失败条件**：
- API 调用超时或返回错误
- 回复为空或格式异常
- 认证失败（API Key 无效）

---

#### 1.2 配置加载验证（P1，可选）

**目标**：确认配置模块正确加载环境变量

**验证步骤**：
```bash
# 1. 测试正常配置加载
pytest tests/test_config.py::test_load_config_success -v

# 2. 测试缺失 API Key 时的错误提示
unset BAILIAN_API_KEY
pytest tests/test_config.py::test_missing_api_key -v
```

**预期结果**：
- 正常配置加载成功
- 缺失 API Key 时抛出清晰的异常（如 `ValidationError`）

---

#### 1.3 会话管理验证（P1，可选）

**目标**：确认会话状态正确维护

**验证步骤**：
```bash
pytest tests/test_session.py -v
```

**预期结果**：
- 会话创建和获取正常
- turn_id 在同一会话内单调递增
- 不同用户的会话相互隔离

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
- 所有公共接口有类型注解

**允许的例外**：
- 第三方库的类型存根缺失（可忽略）

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

#### 2.3 单元测试覆盖率（可选）

**验证步骤**：
```bash
pytest --cov=papermind tests/ --cov-report=term-missing
```

**目标覆盖率**：
- 核心模块（config.py, llm_client.py）> 80%
- 整体覆盖率 > 60%

**说明**：覆盖率仅作参考，不作为硬性合并条件

---

### 第三层：文档完整性验证（必需）

验证外部开发者能否根据文档快速上手。

#### 3.1 README.md 验证

**验证清单**：
- [ ] 包含项目介绍
- [ ] 包含安装步骤（清晰、可执行）
- [ ] 包含快速开始代码示例
- [ ] 代码示例可以直接运行（无遗漏导入或变量）

**验证方法**：
按照 README 步骤操作，确认能成功运行示例代码。

---

#### 3.2 .env.example 验证

**验证清单**：
- [ ] 列出所有必需的环境变量
- [ ] 每个变量有注释说明
- [ ] 提供示例值（敏感信息用占位符）

**验证方法**：
```bash
cp .env.example .env
# 检查 .env 是否包含所有必需字段
```

---

#### 3.3 Docstring 验证

**验证清单**：
- [ ] 公共函数和类有 docstring
- [ ] Docstring 说明参数、返回值和异常

**验证方法**：
人工审查核心模块的 docstring 是否完整。

---

## 集成验证场景

### 场景 1：首次使用者快速开始

**角色**：从未接触本项目的开发者

**步骤**：
1. Clone 代码仓库
2. 按照 README.md 安装依赖
3. 配置 .env 文件
4. 运行示例代码

**预期结果**：
- 15 分钟内完成上述步骤
- 成功获得 LLM 回复

---

### 场景 2：单元测试运行

**步骤**：
```bash
cd papermind-host
pip install -e ".[dev]"
pytest tests/ -v
```

**预期结果**：
- 所有测试通过（或仅有明确标记为 `skip` 的测试跳过）
- 无意外失败或错误

---

### 场景 3：异常处理

**步骤**：
1. 删除 .env 文件中的 API Key
2. 运行示例代码

**预期结果**：
- 抛出清晰的错误提示（如 "BAILIAN_API_KEY is required"）
- 不是神秘的堆栈跟踪或空指针错误

---

## 性能和资源验证（可选）

### API 延迟

**目标**：确认 LLM 调用在合理时间内完成

**验证方法**：
```python
import time
start = time.time()
reply = await client.chat([{"role": "user", "content": "你好"}])
elapsed = time.time() - start
assert elapsed < 10  # 10 秒内完成
```

**说明**：此项仅作参考，API 延迟受网络和模型负载影响

---

### 内存占用

**目标**：确认无明显内存泄漏

**验证方法**：
连续调用 LLM 100 次，观察内存增长情况

**说明**：MVP 阶段可跳过此项验证

---

## 合并前检查清单

在将 `feature/phase-1.1-agent-host` 合并到 `main` 之前，确认以下所有项：

### 功能完整性
- [ ] LLM 调用验证通过（P0）
- [ ] 配置加载验证通过（P1，可选）
- [ ] 会话管理验证通过（P1，可选）

### 代码质量
- [ ] 类型检查通过（mypy）
- [ ] 代码格式符合规范（black）
- [ ] 核心模块有单元测试

### 文档完整性
- [ ] README.md 完整且可执行
- [ ] .env.example 包含所有必需变量
- [ ] 公共接口有 docstring

### 无阻塞性 bug
- [ ] 无已知的崩溃或数据损坏问题
- [ ] 异常处理合理（有清晰的错误提示）

### Git 提交规范
- [ ] 提交信息清晰（符合 Conventional Commits）
- [ ] 无敏感信息（API Key、密码）提交到代码仓库
- [ ] 分支从最新的 main 分支切出或已 rebase

---

## 验证失败处理流程

### 功能验证失败
1. 记录失败的测试用例和错误日志
2. 分析根本原因（代码 bug、配置错误、环境问题）
3. 修复后重新运行验证

### 代码质量验证失败
1. 运行自动格式化工具（black）
2. 修复类型错误（mypy）
3. 补充缺失的测试

### 文档验证失败
1. 更新 README.md 或 .env.example
2. 确认示例代码可运行
3. 重新执行文档验证

---

## 验证报告模板

验证完成后，填写以下报告：

```markdown
## Phase 1.1 验证报告

**日期**：YYYY-MM-DD  
**验证人**：[姓名]  
**分支**：feature/phase-1.1-agent-host  
**Commit**：[commit hash]

### 功能验证结果
- [ ] LLM 调用验证：通过 / 失败（原因：___）
- [ ] 配置加载验证：通过 / 失败 / 跳过
- [ ] 会话管理验证：通过 / 失败 / 跳过

### 代码质量验证结果
- [ ] 类型检查：通过 / 失败（错误数：___）
- [ ] 代码格式：通过 / 失败
- [ ] 单元测试覆盖率：___%

### 文档完整性验证结果
- [ ] README.md：完整 / 需补充（___）
- [ ] .env.example：完整 / 需补充（___）
- [ ] Docstring：充分 / 不足

### 集成验证场景结果
- [ ] 场景 1（首次使用者）：通过 / 失败
- [ ] 场景 2（单元测试运行）：通过 / 失败
- [ ] 场景 3（异常处理）：通过 / 失败

### 合并建议
- [ ] 建议合并（所有 P0 验证通过）
- [ ] 建议修复后合并（列出待修复问题：___）
- [ ] 不建议合并（重大问题：___）

### 备注
[其他需要说明的内容]
```

---

## 后续集成验证（Phase 1.2 之后）

Phase 1.1 合并后，还需要在后续阶段验证：
- Memory V2 检索链路集成（Phase 1.2）
- Memory V2 写入链路集成（Phase 1.3）
- CLI 界面交互（Phase 1.4）
- 端到端场景测试（Phase 1.5）

这些验证将在各自的 validation.md 中定义。
