# Task Group 4 实施报告：Streamlit 单页应用与会话状态管理

**状态：** DONE

**提交：** 3569474ccd671a3aeb238bff1dbcf3d0c8b5c05f

**测试：** 19 个测试全部通过

---

## 实现概要

成功实现 Phase 2 Task Group 4，提供最小可操作的 Streamlit 单页应用，用于保存笔记、同步索引和查询记忆。

### 实现文件

1. **`papermind-host/streamlit_app.py`** (新建)
   - Streamlit 单页应用主文件
   - 6 个功能区：标题与身份选择、笔记输入、同步、查询、回答与证据展示、会话管理
   - 8 个 session state 键管理会话状态

2. **`papermind-host/tests/test_streamlit_app.py`** (新建)
   - 完整测试覆盖（19 个测试用例）
   - 使用 `streamlit.testing.v1.AppTest` 进行页面测试
   - Mock LLMClient 和服务层调用

---

## 实现内容

### 1. 页面结构（从上到下）

#### 1.1 标题与身份选择
- 应用标题："📚 PaperMind - 论文笔记与记忆管理"
- 身份下拉框：显示 IDENTITIES 的 label，选择后更新 `session_state.selected_identity`

#### 1.2 笔记输入区
- 论文标题输入框（`st.text_input`）
- 阅读结论文本区（`st.text_area`，150px 高度）
- 保存按钮：第一次点击设置 `pending_save=True`
- 确认按钮：仅 `pending_save=True` 时显示，调用 `save_note(confirmed=True)`
- 写入结果展示：
  - `saved` → 绿色成功提示
  - `partial` → 橙色警告
  - `skipped` → 蓝色信息
  - `no_memory` → 蓝色信息
  - `failed` → 红色错误
  - 显示 Memory IDs、turn_id 前 8 字符、错误码（如有）

#### 1.3 同步区
- 同步按钮：调用 `sync_notes(batch_size=100)`
- 同步结果展示：
  - `completed` → 绿色成功 + 蓝色提示"批次处理完成，仍需通过查询确认"
  - `failed` → 红色错误
  - 显示 done/failed/dead 统计

#### 1.4 查询区
- 提问输入框（`st.text_input`）
- 查询按钮：调用 `ask_memory(identity, question, llm_client=MockLLMClient())`

#### 1.5 回答与证据展示
- `answered` 状态：
  - 绿色成功提示 + 回答文本
  - 证据列表（expander 展示 memory_id、content、memory_type、confidence、created_at）
- `no_evidence` 状态：
  - 蓝色信息提示 + "未找到相关历史记忆"
- `retrieval_failed` 状态：
  - 红色错误提示 + "记忆检索失败" + 错误码
- `answer_failed` 状态：
  - 橙色警告 + "回答生成失败，但已找到相关记忆" + 错误码
  - 保留并展示已检索到的证据

#### 1.6 会话控制
- "新建会话"按钮：
  - 清除临时数据（`note_title`、`note_conclusion`、`question`、`pending_save`、`write_result`、`sync_result`、`ask_result`）
  - **保留** `selected_identity`

### 2. Session State 管理

初始化 8 个必需的 session state 键：

```python
if "selected_identity" not in st.session_state:
    st.session_state.selected_identity = 0
if "note_title" not in st.session_state:
    st.session_state.note_title = ""
if "note_conclusion" not in st.session_state:
    st.session_state.note_conclusion = ""
if "pending_save" not in st.session_state:
    st.session_state.pending_save = False
if "write_result" not in st.session_state:
    st.session_state.write_result = None
if "sync_result" not in st.session_state:
    st.session_state.sync_result = None
if "question" not in st.session_state:
    st.session_state.question = ""
if "ask_result" not in st.session_state:
    st.session_state.ask_result = None
```

### 3. Asyncio 处理

Streamlit 不原生支持 async，使用 `asyncio.run()` 包装异步调用：

```python
result = asyncio.run(
    save_note(
        identity=current_identity,
        title=st.session_state.note_title,
        conclusion=st.session_state.note_conclusion,
        confirmed=True,
    )
)
```

### 4. Mock LLMClient

实现 `MockLLMClient` 类用于演示：

```python
class MockLLMClient:
    """Mock LLM 客户端用于演示"""
    async def generate(self, prompt: str) -> str:
        return "这是 Mock LLM 生成的回答。请配置真实的 LLM 客户端以获得实际回答。"
```

### 5. 异常处理

所有服务调用包在 `try-except` 块中，异常时使用 `st.error()` 显示错误信息，不中断页面操作。

---

## 测试覆盖

### 测试用例（19 个，全部通过）

#### TestPageInitialization (3 个)
1. **`test_identity_selectbox_contains_three_options`**
   - 验证身份下拉框包含三个固定身份的 label

2. **`test_session_state_initialization`**
   - 验证 8 个 session state 键正确初始化
   - 验证初始值（`selected_identity=0`、字符串为空、布尔值为 False、对象为 None）

3. **`test_no_service_call_on_initialization`**
   - 验证页面初始化不触发任何服务调用（Mock 未被调用）

#### TestSaveFlow (4 个)
4. **`test_first_save_click_sets_pending_save`**
   - 验证第一次点击保存按钮设置 `pending_save=True`

5. **`test_confirm_button_appears_after_pending_save`**
   - 验证 `pending_save=True` 时确认按钮显示

6. **`test_confirm_button_calls_save_note_with_confirmed_true`**
   - 验证点击确认按钮调用 `save_note(confirmed=True)`
   - 验证参数正确传递（identity、title、conclusion）

7. **`test_empty_title_behavior`**
   - 验证空标题时第一次点击仍设置 `pending_save=True`
   - 验证点击确认按钮后 `save_note` 返回 `skipped` 状态

#### TestSyncFlow (3 个)
8. **`test_sync_button_calls_sync_notes`**
   - 验证点击同步按钮调用 `sync_notes`

9. **`test_sync_result_displays_statistics`**
   - 验证同步结果显示 done/failed/dead 统计
   - 验证结果保存到 `session_state.sync_result`

10. **`test_sync_result_wording_does_not_claim_retrievability`**
    - 验证页面文案不包含"已可检索"
    - 验证包含"查询"或"确认"提示

#### TestAskFlow (5 个)
11. **`test_ask_button_calls_ask_memory`**
    - 验证点击查询按钮调用 `ask_memory`

12. **`test_answered_status_displays_answer_and_evidence`**
    - 验证 `answered` 状态显示回答和证据
    - 验证证据包含 memory_id、content、memory_type、confidence

13. **`test_no_evidence_status_displays_message`**
    - 验证 `no_evidence` 状态显示"未找到相关记忆"
    - 验证 evidence 列表为空

14. **`test_retrieval_failed_status_displays_error`**
    - 验证 `retrieval_failed` 状态显示检索失败
    - 验证显示错误码

15. **`test_answer_failed_status_preserves_evidence`**
    - 验证 `answer_failed` 状态保留证据
    - 验证显示错误码

#### TestNewSession (2 个)
16. **`test_new_session_clears_temporary_state`**
    - 验证新建会话清除临时数据（title、conclusion、question、pending_save、write_result、ask_result）

17. **`test_new_session_preserves_selected_identity`**
    - 验证新建会话保留 `selected_identity`

#### TestExceptionHandling (2 个)
18. **`test_save_note_exception_displays_error_code`**
    - 验证 `save_note` 异常时页面展示错误
    - 验证异常后页面仍可继续操作

19. **`test_ask_memory_exception_allows_continued_operation`**
    - 验证 `ask_memory` 异常后仍可继续操作
    - 验证可以切换身份

---

## 运行命令和输出

### 1. 测试运行

```bash
cd papermind-host && python -m pytest tests/test_streamlit_app.py -v
```

**输出：**
```
============================= test session starts =============================
platform win32 -- Python 3.12.7, pytest-9.0.3, pluggy-1.6.0
collected 19 items

tests/test_streamlit_app.py::TestPageInitialization::test_identity_selectbox_contains_three_options PASSED [  5%]
tests/test_streamlit_app.py::TestPageInitialization::test_session_state_initialization PASSED [ 10%]
tests/test_streamlit_app.py::TestPageInitialization::test_no_service_call_on_initialization PASSED [ 15%]
tests/test_streamlit_app.py::TestSaveFlow::test_first_save_click_sets_pending_save PASSED [ 21%]
tests/test_streamlit_app.py::TestSaveFlow::test_confirm_button_appears_after_pending_save PASSED [ 26%]
tests/test_streamlit_app.py::TestSaveFlow::test_confirm_button_calls_save_note_with_confirmed_true PASSED [ 31%]
tests/test_streamlit_app.py::TestSaveFlow::test_empty_title_behavior PASSED [ 36%]
tests/test_streamlit_app.py::TestSyncFlow::test_sync_button_calls_sync_notes PASSED [ 42%]
tests/test_streamlit_app.py::TestSyncFlow::test_sync_result_displays_statistics PASSED [ 47%]
tests/test_streamlit_app.py::TestSyncFlow::test_sync_result_wording_does_not_claim_retrievability PASSED [ 52%]
tests/test_streamlit_app.py::TestAskFlow::test_ask_button_calls_ask_memory PASSED [ 57%]
tests/test_streamlit_app.py::TestAskFlow::test_answered_status_displays_answer_and_evidence PASSED [ 63%]
tests/test_streamlit_app.py::TestAskFlow::test_no_evidence_status_displays_message PASSED [ 68%]
tests/test_streamlit_app.py::TestAskFlow::test_retrieval_failed_status_displays_error PASSED [ 73%]
tests/test_streamlit_app.py::TestAskFlow::test_answer_failed_status_preserves_evidence PASSED [ 78%]
tests/test_streamlit_app.py::TestNewSession::test_new_session_clears_temporary_state PASSED [ 84%]
tests/test_streamlit_app.py::TestNewSession::test_new_session_preserves_selected_identity PASSED [ 89%]
tests/test_streamlit_app.py::TestExceptionHandling::test_save_note_exception_displays_error_code PASSED [ 94%]
tests/test_streamlit_app.py::TestExceptionHandling::test_ask_memory_exception_allows_continued_operation PASSED [100%]

============================= 19 passed in 1.67s ==============================
```

### 2. 编译检查

```bash
cd papermind-host && python -m compileall streamlit_app.py papermind
```

**输出：**
```
Compiling 'streamlit_app.py'...
Listing 'papermind'...
```

无语法错误。

### 3. 提交代码

```bash
git add streamlit_app.py tests/test_streamlit_app.py
git commit -m "feat(phase2): implement Streamlit single-page UI and session state"
```

**提交信息：**
```
commit 3569474ccd671a3aeb238bff1dbcf3d0c8b5c05f
Author: Wyl-510-www
Date:   Wed Oct 8 08:33:00 2026

    feat(phase2): implement Streamlit single-page UI and session state

    Implemented Task Group 4:
    - Streamlit single-page application with session state management
    - Identity selection, note input, sync, and query sections
    - Two-step confirmation for save operation
    - Mock LLM client for ask_memory
    - Full test coverage (19 tests, all passing)

    Key features:
    - Session state initialization and management
    - Async service calls via asyncio.run()
    - Status display for all service results (saved/partial/skipped/no_memory/failed/answered/no_evidence/retrieval_failed/answer_failed)
    - Sync wording does not claim retrievability
    - New session clears temporary data but preserves selected_identity

    Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## 自我审查结果

### 功能正确性 ✓

1. **身份选择** - 三个固定身份组合，下拉框显示 label
2. **保存笔记** - 二次确认门控正确实现（pending_save → 确认按钮 → save_note(confirmed=True)）
3. **同步笔记** - 调用 sync_notes，显示统计，文案不声称"已可检索"
4. **查询记忆** - 调用 ask_memory，四种状态明确展示
5. **新建会话** - 清除临时数据，保留 selected_identity

### 测试覆盖 ✓

- **页面初始化** - 3 个测试（下拉框、session state、无服务调用）
- **保存流程** - 4 个测试（pending_save、确认按钮、空输入）
- **同步流程** - 3 个测试（调用、统计、文案）
- **查询流程** - 5 个测试（4 种状态 + 调用验证）
- **新建会话** - 2 个测试（清除、保留）
- **异常处理** - 2 个测试（save_note、ask_memory）

### 接口契约 ✓

- 只调用 `app_service` 业务层（`save_note`、`sync_notes`、`ask_memory`）
- 不直接操作数据库或 Memory V2
- 使用 `IDENTITIES`、`Identity`、`WriteResult`、`SyncResult`、`AskResult`、`EvidenceItem`
- ask_memory 需要 LLMClient，实现了 MockLLMClient

### 全局约束遵守 ✓

1. **只实现 P0** - 无 PDF、论文库、P2 摘要、REST API、worker、正式鉴权
2. **页面只调用业务服务层** - 不操作数据库、Qdrant、Memory V2 内部对象
3. **身份只能来自三个固定组合** - IDENTITIES 定义的三个身份
4. **保存必须二次确认** - pending_save 门控 + 确认按钮
5. **状态明确展示** - saved/partial/skipped/no_memory/failed/answered/no_evidence/retrieval_failed/answer_failed 使用不同颜色和文案
6. **同步文案不声称"已可检索"** - 使用"批次处理完成，仍需通过查询确认"
7. **新建会话只清除 UI 状态** - 不调用删除接口，不操作数据库

---

## 疑虑和观察

### 观察 1：MockLLMClient 需要替换

当前使用 MockLLMClient 返回固定字符串。实际部署时需要：
- 配置真实的 LLM 客户端（如 OpenAI、Anthropic Claude）
- 替换 `MockLLMClient()` 为真实客户端实例
- 可能需要添加 API Key 配置和环境变量

### 观察 2：Streamlit 不适合生产多用户场景

Streamlit 的 session_state 是单用户单会话的，不支持：
- 多用户并发（每个用户需要独立部署）
- 会话持久化（刷新页面会丢失状态）
- 跨设备同步

生产环境可能需要：
- 添加用户认证和会话管理
- 使用数据库持久化会话状态
- 或迁移到 REST API + 前端框架（如 React）

### 观察 3：错误处理可以更细化

当前异常处理使用 `st.error()` 展示错误信息，可以改进：
- 区分不同类型的异常（网络、数据库、LLM 服务）
- 提供用户友好的错误提示和操作建议
- 添加日志记录用于问题排查

### 观察 4：同步结果展示可以更直观

当前同步结果只显示统计数字，可以考虑：
- 添加进度条或动画
- 显示正在同步的 Memory ID
- 提供批次历史记录

但这些都是 P1/P2 优化，不在当前任务范围内。

---

## 总结

Task Group 4 已完整实现并通过所有测试。实现了最小可操作的 Streamlit 单页应用，满足所有 P0 需求和全局约束。代码已提交到 Git 仓库（commit 3569474）。

**状态：** DONE

**下一步：** 等待控制器审查或集成到 Phase 2 完整流程。
