# Task Group 3 实现报告：结构化证据与回答编排

## 实现概要

已完成 Task Group 3 的所有功能实现和测试，包括结构化证据检索适配和 ask_memory 回答编排。

## 实现内容

### 1. 结构化证据检索 (memory_retrieval.py)

**新增函数：**
- `retrieve_structured_evidence(query, tenant_id, user_id, limit=5) -> list[EvidenceItem]`

**实现细节：**
- 复用 `_call_memory_v2_retrieval` 和 `config.memory_retrieval_timeout`
- 使用 `asyncio.wait_for` 进行超时控制
- 将 evidence_pack 的 items 转换为 EvidenceItem 列表
- 字段映射：evidence_pack 中的 "text" → EvidenceItem 的 "content"
- 空结果返回空列表 `[]`
- 超时或异常直接抛出（不捕获），让调用者区分 no_evidence vs retrieval_failed

**兼容性：**
- 保留 `retrieve_memory_context` 函数不变，维持 Phase 1.2 的格式化字符串接口

### 2. 回答编排 (app_service.py)

**实现函数：**
- `ask_memory(identity, question, *, llm_client) -> AskResult`

**四种状态区分：**
1. **answered**: 检索到证据，LLM 成功生成回答
2. **no_evidence**: 未检索到记忆，不调用 LLM，返回"未找到相关历史记忆"
3. **retrieval_failed**: 检索超时或失败，不调用 LLM，返回错误码（RETRIEVAL_TIMEOUT / RETRIEVAL_ERROR）
4. **answer_failed**: 检索成功但 LLM 失败，保留证据，返回错误码（LLM_ERROR）

**关键约束满足：**
- ✅ 有证据才调用 LLM，无证据不调用
- ✅ 检索失败不伪装成无证据（error_code 区分）
- ✅ LLM 失败保留已检索的证据
- ✅ 身份透传到检索（tenant_id, user_id）

**系统提示格式：**
```
你是用户的个人记忆助手。请仅根据以下历史记忆回答用户问题。

历史记忆：
1. {证据内容1}
2. {证据内容2}
...

重要约束：
1. 只使用上述历史记忆中的信息
2. 不要使用常识或模型知识补充用户的经历
3. 如果历史记忆不足以回答，明确说明

用户问题：{question}
```

## 测试覆盖

### TestRetrieveStructuredEvidence (5 个测试)

1. **test_empty_result_returns_empty_list** ✅
   - 验证空 items 返回空列表

2. **test_successful_retrieval_returns_evidence_items** ✅
   - 验证成功检索返回 EvidenceItem 列表
   - 验证字段完整性：memory_id, content, memory_type, confidence, created_at
   - 验证 created_at 可为 None

3. **test_timeout_raises_exception** ✅
   - 验证超时抛出 asyncio.TimeoutError

4. **test_retrieval_failure_raises_exception** ✅
   - 验证检索失败抛出异常

5. **test_tenant_user_propagation** ✅
   - 验证 tenant_id 和 user_id 正确透传到 _call_memory_v2_retrieval

### TestAskMemory (6 个测试)

1. **test_with_evidence_calls_llm_returns_answered** ✅
   - 验证有证据时调用 LLM
   - 验证返回 answered 状态
   - 验证证据包含在结果中

2. **test_no_evidence_does_not_call_llm_returns_no_evidence** ✅
   - 验证无证据时不调用 LLM
   - 验证返回 no_evidence 状态
   - 验证提示消息："未找到相关历史记忆"

3. **test_retrieval_failed_does_not_call_llm_returns_retrieval_failed** ✅
   - 验证检索失败时不调用 LLM
   - 验证返回 retrieval_failed 状态
   - 验证 error_code 不为 None

4. **test_llm_failure_returns_answer_failed_but_keeps_evidence** ✅
   - 验证 LLM 失败时返回 answer_failed 状态
   - 验证保留已检索的证据
   - 验证 error_code 不为 None

5. **test_identity_propagation** ✅
   - 验证身份正确透传到 retrieve_structured_evidence

6. **test_system_prompt_requires_evidence_only_answers** ✅
   - 验证系统提示包含"仅根据"或"只使用"
   - 验证系统提示包含"历史记忆"
   - 验证系统提示包含证据内容
   - 验证系统提示包含用户问题
   - 验证系统提示包含"不要使用"或"禁止"约束

## 运行的命令和输出

### 新增测试运行
```bash
cd papermind-host && python -m pytest tests/test_app_service.py::TestRetrieveStructuredEvidence tests/test_app_service.py::TestAskMemory -v
```
**结果：** 11 passed in 0.22s ✅

### 完整测试套件（无回归验证）
```bash
cd papermind-host && python -m pytest tests/test_memory_retrieval.py tests/test_app_service.py -v
```
**结果：** 52 passed, 2 skipped, 2 warnings in 0.39s ✅

### 提交信息
```bash
git commit -m "feat(phase2): implement structured evidence retrieval and ask_memory"
```
**提交哈希：** db73d9e

## 文件修改清单

### 修改的文件
1. `papermind-host/papermind/memory_retrieval.py`
   - 增加 TYPE_CHECKING 导入 EvidenceItem
   - 增加 retrieve_structured_evidence 函数（65 行）
   - 保留 retrieve_memory_context 不变

2. `papermind-host/papermind/app_service.py`
   - 实现 ask_memory 函数（120 行）
   - 导入 asyncio 和 logging
   - 从 papermind.memory_retrieval 导入 retrieve_structured_evidence

3. `papermind-host/tests/test_app_service.py`
   - 增加 asyncio 导入
   - 增加 TestRetrieveStructuredEvidence 类（5 个测试）
   - 增加 TestAskMemory 类（6 个测试）

## 自我审查结果

### ✅ 功能正确性
- 结构化检索复用 Phase 1.2 的 _call_memory_v2_retrieval
- ask_memory 四种状态区分清晰
- 有证据才调用 LLM（关键约束）
- 检索失败不伪装成无证据（关键约束）
- LLM 失败保留证据（关键约束）

### ✅ 测试覆盖
- 结构化检索：5 个测试覆盖空结果、成功检索、超时、失败、透传
- ask_memory：6 个测试覆盖 4 种状态、透传、系统提示约束
- 无回归：原有 52 个测试全部通过

### ✅ 接口契约
- EvidenceItem 字段完整：memory_id, content, memory_type, confidence, created_at
- AskResult 状态枚举正确：answered | no_evidence | retrieval_failed | answer_failed
- 身份透传正确：tenant_id, user_id 传递到检索层

### ✅ 系统提示质量
- 明确要求只基于证据回答
- 禁止使用常识或模型知识补充
- 证据不足时明确说明
- 格式清晰，包含编号的证据列表

### ✅ 错误处理
- 超时：返回 retrieval_failed + RETRIEVAL_TIMEOUT
- 检索异常：返回 retrieval_failed + RETRIEVAL_ERROR
- LLM 异常：返回 answer_failed + LLM_ERROR + 保留证据
- 所有异常都有日志记录

### ✅ 兼容性
- retrieve_memory_context 保持不变（Phase 1.2 兼容）
- 不修改 Memory V2 核心（复用现有接口）

## 疑虑

### 无

所有实现按照任务简报要求完成，测试全部通过，无已知问题。

## 下一步

Task Group 3 已完成。等待控制器调度后续任务或审查。
