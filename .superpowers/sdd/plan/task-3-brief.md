## Task Group 3: 结构化证据与回答编排

**目标：** 让页面能够展示真实证据，并清楚区分有证据、无证据和检索故障。

**文件：** `papermind/memory_retrieval.py`、`papermind/app_service.py`、`tests/test_app_service.py`、既有检索测试。

### Steps

- [ ] **步骤 1：** 先为结构化检索适配写测试：返回 `memory_id/content/memory_type/confidence/created_at`；空 `items` 为 `no_evidence`；超时或异常为 `retrieval_failed`；tenant/user 必须透传。
- [ ] **步骤 2：** 在检索模块增加公开的结构化入口，复用现有 `_call_memory_v2_retrieval` 和超时配置；保留 `retrieve_memory_context` 兼容旧调用，不解析展示字符串反推 ID。
- [ ] **步骤 3：** 为 `ask_memory` 写测试：有证据才调用 LLM；无证据不调用 LLM 并返回明确提示；检索失败不伪装成无证据；LLM 失败返回 `answer_failed` 但保留已取得的证据。
- [ ] **步骤 4：** 实现 `ask_memory(identity, question, llm_client)`，使用当前身份和证据生成回答；系统提示要求只基于证据回答，禁止声称未检索到的历史事实。
- [ ] **步骤 5：** 运行 `python -m pytest tests/test_memory_retrieval.py tests/test_app_service.py -q`，确认原检索测试无回归且结构化结果可供页面使用。

### Context from Global Constraints

- `saved`、`partial`、`skipped`、`no_memory`、`failed`、无证据和检索失败必须区分展示
- 查询入口不得调用保存入口；模型回答不得作为用户事实写入
- 同租户不同用户、不同租户相同用户均不能看到未授权的 Memory ID

### Interface Requirements

From Task Group 1 (EvidenceItem 已定义):
```python
@dataclass(frozen=True)
class EvidenceItem:
    memory_id: str
    content: str
    memory_type: str
    confidence: float
    created_at: datetime | None

@dataclass(frozen=True)
class AskResult:
    status: str  # answered | no_evidence | retrieval_failed | answer_failed
    answer: str
    evidence: list[EvidenceItem]
    error_code: str | None = None
```

To implement:
```python
async def ask_memory(
    identity: Identity,
    question: str,
    *,
    llm_client: LLMClient,
) -> AskResult
```

### Phase 1.2 Context

Phase 1.2 已实现 `retrieve_memory_context(tenant_id, user_id, query)`，返回格式化字符串。

你需要：
1. 在 `memory_retrieval.py` 增加结构化检索函数（返回 EvidenceItem 列表）
2. 保留 `retrieve_memory_context` 兼容性（Phase 1.x 示例使用）
3. 在 `app_service.py` 实现 `ask_memory`

### Expected Test Coverage

**结构化检索适配测试（memory_retrieval.py）：**
1. 成功检索返回 EvidenceItem 列表
2. 空结果返回空列表
3. 超时返回错误或异常
4. tenant/user 透传到 Memory V2
5. 返回的 memory_id/content/memory_type/confidence/created_at 完整

**ask_memory 测试（app_service.py）：**
1. 有证据 → 调用 LLM → 返回 answered + 证据
2. 空证据 → 不调用 LLM → 返回 no_evidence + 明确提示
3. 检索失败 → 不调用 LLM → 返回 retrieval_failed
4. 检索成功但 LLM 失败 → 返回 answer_failed + 保留证据
5. 身份透传到检索
6. 系统提示要求只基于证据回答

### LLMClient Protocol

From Task Group 1:
```python
from typing import Protocol

class LLMClient(Protocol):
    async def generate(self, prompt: str) -> str:
        ...
```

### System Prompt 要求

系统提示必须：
- 明确说明只能根据提供的历史记忆回答
- 禁止使用常识或模型知识补充用户经历
- 如果证据不足，说明"根据您的历史记忆..."并给出有限回答
- 不声称未检索到的事实

建议格式：
```
你是用户的个人记忆助手。请仅根据以下历史记忆回答用户问题。

历史记忆：
{证据内容}

重要约束：
1. 只使用上述历史记忆中的信息
2. 不要使用常识或模型知识补充用户的经历
3. 如果历史记忆不足以回答，明确说明

用户问题：{问题}
```

### Dependencies from Prior Tasks

Task Group 1 提供：
- Identity dataclass
- EvidenceItem dataclass
- AskResult dataclass
- LLMClient Protocol

Phase 1.2 提供：
- `papermind/memory_retrieval.py` - retrieve_memory_context
- Memory V2 检索能力

### Implementation Notes

1. **不重写 Memory V2 核心** - 复用 `_call_memory_v2_retrieval`，只增加宿主层适配
2. **状态区分清晰** - answered/no_evidence/retrieval_failed/answer_failed 必须明确
3. **证据优先** - 有证据才调用 LLM
4. **错误传播** - 检索失败不伪装成无证据
5. **兼容性** - 保留 retrieve_memory_context 供 Phase 1.x 使用

### Report Requirements

Write full report to: `.superpowers/sdd/plan/task-3-report.md`

Return only:
- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Commits: <hash>...<hash>
- Tests: Brief summary
- Concerns: Any doubts or observations
