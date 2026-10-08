## Task Group 1: 依赖与公共契约

**目标：** 建立可导入、可测试且不绕过业务层的基础契约。

**文件：** `pyproject.toml`、`papermind/app_service.py`、`tests/test_app_service.py`。

### Steps

- [ ] **步骤 1：** 在 `pyproject.toml` 增加 `streamlit>=1.36,<2.0`，保留现有 Python 版本和依赖，不替换已有 Memory V2 依赖。
- [ ] **步骤 2：** 在 `app_service.py` 定义 `Identity`、`EvidenceItem`、`AskResult` 和固定的 `IDENTITIES` 元组；断言三个组合恰好存在且没有重复。
- [ ] **步骤 3：** 为固定身份和非法身份写失败测试：任意自定义身份不能进入保存、同步或查询调用，三个固定组合必须逐一透传。
- [ ] **步骤 4：** 运行 `python -m pytest tests/test_app_service.py -q`，确认契约测试通过后再进入写入编排。

### Context from Global Constraints

- 身份只能来自 `tenant_A/user_A`、`tenant_A/user_B`、`tenant_B/user_A` 三个固定组合
- 页面只调用业务服务层，不直接操作数据库、Qdrant 或 Memory V2 内部对象
- 每次保存使用 UUID `turn_id`；不记录密钥、凭据、完整连接串或笔记全文

### Interface Contract (from requirements.md)

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str
    label: str

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

IDENTITIES: tuple[Identity, ...]

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

### Expected Test Coverage

1. IDENTITIES contains exactly 3 identities with correct tenant/user combinations
2. IDENTITIES has no duplicates
3. Each fixed identity has a non-empty label
4. Identity is immutable (frozen dataclass)
5. EvidenceItem is immutable and has all required fields
6. AskResult is immutable and has all required fields with correct status values
7. Custom/arbitrary identities are rejected (not tested in this TG, placeholder for TG2/3)

### Dependencies from Prior Tasks

None - this is the first task group.

### Report Requirements

Write full report to: `.superpowers/sdd/plan/task-1-report.md`

Return only:
- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Commits: <hash>...<hash>
- Tests: Brief summary (e.g., "5/5 passing")
- Concerns: Any doubts or observations
