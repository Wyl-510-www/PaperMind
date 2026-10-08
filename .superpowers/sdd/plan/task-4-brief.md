## Task Group 4: Streamlit 单页与会话状态

**目标：** 提供最小可操作页面，不让 UI 直接依赖存储实现。

**文件：** `streamlit_app.py`、`tests/test_streamlit_app.py`。

### Steps

- [ ] **步骤 1：** 先写页面测试：身份下拉框只包含三个固定组合；页面首次加载初始化 `selected_identity`、输入框、最近写入、同步结果、回答和证据状态；不触发写入或检索。
- [ ] **步骤 2：** 实现页面入口和布局：身份选择区、论文标题输入、阅读结论文本区、保存按钮、同步按钮、提问输入、回答区、证据区和"新建会话"按钮。
- [ ] **步骤 3：** 保存按钮第一次点击只生成待确认状态；确认按钮才调用 `save_note`，显示状态、Message、Memory ID 和当前 turn_id 的脱敏前缀。
- [ ] **步骤 4：** 同步按钮调用 `sync_notes` 并展示统计；页面文案使用"批次已处理/仍需通过查询确认"，不得直接写"当前笔记已可检索"。
- [ ] **步骤 5：** 提问按钮只调用 `ask_memory`；回答与 EvidenceItem 分栏渲染，空证据和故障使用不同颜色和文案。
- [ ] **步骤 6：** "新建会话"清除临时输入、回答、证据和结果状态，不调用删除接口、不清除数据库；测试确认下次查询重新调用服务层。
- [ ] **步骤 7：** 页面所有服务调用包在可恢复的异常处理内；显示脱敏错误码，异常后仍可切换身份和继续操作。
- [ ] **步骤 8：** 运行 `python -m pytest tests/test_streamlit_app.py -q`，再执行 `python -m compileall streamlit_app.py papermind`。

### Context from Global Constraints

- 只实现 P0；不加入 PDF、论文库、P2 摘要、REST API、自动 worker 或正式鉴权
- 页面只调用业务服务层，不直接操作数据库、Qdrant 或 Memory V2 内部对象
- 身份只能来自 `tenant_A/user_A`、`tenant_A/user_B`、`tenant_B/user_A` 三个固定组合
- 保存必须二次确认；查询入口不得调用保存入口；模型回答不得作为用户事实写入
- `saved`、`partial`、`skipped`、`no_memory`、`failed`、无证据和检索失败必须区分展示
- 批次同步完成不等价于当前 Memory ID 已可检索；只有实际证据返回当前 ID 才能显示可检索

### Interface Requirements

From Task Group 1 (app_service.py 已定义):

```python
@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str
    label: str

IDENTITIES: tuple[Identity, Identity, Identity]  # 三个固定身份

@dataclass(frozen=True)
class EvidenceItem:
    memory_id: str
    content: str
    memory_type: str
    confidence: float
    created_at: datetime | None

@dataclass(frozen=True)
class WriteResult:
    status: str  # saved | partial | skipped | no_memory | failed
    message: str
    memory_ids: list[str] | None
    turn_id: str
    error_code: str | None

@dataclass(frozen=True)
class SyncResult:
    status: str  # completed | failed
    done: int
    failed: int
    dead: int
    message: str
    error_code: str | None

@dataclass(frozen=True)
class AskResult:
    status: str  # answered | no_evidence | retrieval_failed | answer_failed
    answer: str
    evidence: list[EvidenceItem]
    error_code: str | None
```

From Task Group 2 & 3 (app_service.py 已实现):

```python
async def save_note(
    identity: Identity,
    title: str,
    conclusion: str,
    *,
    confirmed: bool,
) -> WriteResult

async def sync_notes(batch_size: int = 100) -> SyncResult

async def ask_memory(
    identity: Identity,
    question: str,
    *,
    llm_client: LLMClient,
) -> AskResult
```

### Streamlit Requirements

**页面布局顺序（从上到下）：**

1. **标题与身份选择**
   - 应用标题
   - 身份下拉框（label 展示，选择后更新 session state）

2. **笔记输入区**
   - 论文标题输入框
   - 阅读结论文本区（多行）
   - 保存按钮（第一次点击 → 待确认状态）
   - 确认按钮（仅待确认时显示，调用 save_note）
   - 写入结果展示（状态、消息、Memory ID、turn_id 前缀）

3. **同步区**
   - 同步按钮（调用 sync_notes）
   - 同步结果展示（done/failed/dead 统计，使用"批次已处理"文案）

4. **查询区**
   - 提问输入框
   - 查询按钮（调用 ask_memory）

5. **回答与证据展示**
   - 回答文本区（answered 状态显示回答）
   - 证据列表（EvidenceItem 分项展示：memory_id、content、confidence）
   - 无证据/检索失败使用不同颜色和文案

6. **会话控制**
   - "新建会话"按钮（清除 session state 中的临时数据）

### Session State Management

Streamlit 使用 `st.session_state` 管理会话状态，需要初始化和管理以下键：

**必需的 session state 键：**

- `selected_identity`: int (IDENTITIES 的索引，默认 0)
- `note_title`: str (论文标题输入)
- `note_conclusion`: str (阅读结论输入)
- `pending_save`: bool (待确认状态，默认 False)
- `write_result`: WriteResult | None (最近写入结果)
- `sync_result`: SyncResult | None (最近同步结果)
- `question`: str (提问输入)
- `ask_result`: AskResult | None (最近查询结果)

### Expected Test Coverage

**test_streamlit_app.py 测试（使用 Streamlit AppTest）：**

1. **页面初始化测试**
   - 身份下拉框包含三个固定身份的 label
   - 初始 session state 正确初始化
   - 未触发任何服务调用

2. **保存流程测试**
   - 第一次点击保存按钮 → pending_save = True
   - 显示确认按钮
   - 点击确认按钮 → 调用 save_note(confirmed=True)
   - 空标题/正文 → 跳过确认，直接调用 save_note(confirmed=False)

3. **同步流程测试**
   - 点击同步按钮 → 调用 sync_notes
   - 显示 done/failed/dead 统计
   - 文案不包含"已可检索"

4. **查询流程测试**
   - 点击查询按钮 → 调用 ask_memory
   - answered 状态显示回答和证据
   - no_evidence 状态显示"未找到相关记忆"
   - retrieval_failed 状态显示"检索失败"
   - answer_failed 状态显示"回答失败"但保留证据

5. **新建会话测试**
   - 点击"新建会话" → 清除输入和结果状态
   - selected_identity 不清除
   - 下次查询重新调用服务层

6. **异常处理测试**
   - 服务调用抛出异常 → 显示错误码
   - 异常后仍可继续操作

### Implementation Notes

1. **页面文件位置** - `papermind-host/streamlit_app.py`（与 papermind 包同级）
2. **测试文件位置** - `papermind-host/tests/test_streamlit_app.py`
3. **Streamlit AppTest** - 使用 `streamlit.testing.v1.AppTest` 进行页面测试
4. **Mock LLMClient** - ask_memory 需要 LLMClient，测试时 Mock
5. **Asyncio 运行** - Streamlit 不原生支持 async，使用 `asyncio.run()` 包装
6. **状态展示** - 所有状态字段（saved/partial/skipped/no_memory/failed/answered/no_evidence/retrieval_failed/answer_failed）必须明确展示
7. **脱敏展示** - turn_id 只显示前 8 字符，Memory ID 完整显示
8. **文案约束** - 同步结果不得写"当前笔记已可检索"，使用"批次已处理 X 条，仍需通过查询确认"
9. **确认门控** - 保存按钮第一次点击只设置 pending_save=True，确认按钮才调用 save_note(confirmed=True)
10. **新建会话语义** - 只清除 session state 中的临时数据，不调用删除接口，不影响数据库

### Dependencies from Prior Tasks

Task Group 1 提供：
- Identity dataclass
- IDENTITIES 固定身份列表
- EvidenceItem, WriteResult, SyncResult, AskResult dataclasses

Task Group 2 提供：
- save_note 函数
- sync_notes 函数

Task Group 3 提供：
- ask_memory 函数
- LLMClient Protocol

### Streamlit Testing References

Streamlit 提供 `streamlit.testing.v1.AppTest` 用于页面测试：

```python
from streamlit.testing.v1 import AppTest

def test_page_initialization():
    at = AppTest.from_file("streamlit_app.py")
    at.run()
    
    # 检查组件存在
    assert len(at.selectbox) > 0
    assert len(at.text_input) > 0
    assert len(at.button) > 0
    
    # 检查初始状态
    assert at.session_state.selected_identity == 0
```

**AppTest 主要方法：**
- `at.run()` - 运行页面脚本
- `at.selectbox[key].set_value(value)` - 设置下拉框值
- `at.text_input[key].set_value(value)` - 设置文本输入
- `at.text_area[key].set_value(value)` - 设置文本区域
- `at.button[key].click()` - 点击按钮
- `at.session_state[key]` - 访问 session state

### LLMClient Mock for Testing

测试时需要 Mock LLMClient：

```python
from unittest.mock import AsyncMock

class MockLLMClient:
    async def generate(self, prompt: str) -> str:
        return "Mock answer"

# 或使用 AsyncMock
mock_llm = AsyncMock()
mock_llm.generate.return_value = "Mock answer"
```

### Report Requirements

Write full report to: `.superpowers/sdd/plan/task-4-report.md`

Return only:
- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Commits: <hash>...<hash>
- Tests: Brief summary
- Concerns: Any doubts or observations
