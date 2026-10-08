# Requirements — Phase 2：Streamlit 单页 P0 闭环

**日期**：2026-10-07  
**状态**：待实施  
**分支**：`feature/phase-2-streamlit-ui`

## 1. 目标与前置条件

本阶段实现路线图 Day 2 的最小可操作网页：用户在浏览器中选择固定身份、输入论文标题与阅读笔记、确认保存、显式同步 Outbox、发起历史查询，并查看基于真实 Memory V2 证据生成的回答。页面必须复用 Phase 1.3 的真实写入与同步能力，以及 Phase 1.2 的检索能力；不得用内存字典、静态答案或 Mock 数据宣称持久化闭环已完成。

前置条件：

- Phase 1.1 宿主配置、模型客户端和会话基础可复用。
- Phase 1.2 的检索封装和证据格式化可复用；如需展示结构化证据，只增加宿主层公开适配，不重写 Memory V2 检索核心。
- Phase 1.3 提供 `save_turn_to_memory(...)` 和 `sync_outbox_batch(...)`，其真实结果契约保持不变。
- 本阶段使用本地 MySQL、Qdrant 和模型服务；服务不可用时必须报告阻塞，不能降级为假成功。

## 2. 范围决策

### 2.1 本阶段必须交付（P0）

1. Streamlit 单页入口，可在浏览器完成身份选择、笔记保存、同步、提问和证据查看。
2. 固定展示三个身份组合：
   - `tenant_A / user_A`
   - `tenant_A / user_B`
   - `tenant_B / user_A`
3. 论文笔记输入包含标题和阅读结论正文；保存前必须由用户明确确认。
4. 保存操作只传递用户确认的原始内容，不把模型生成的回答写入事实记忆。
5. 查询操作只调用检索和回答服务，不调用保存接口。
6. 页面分别展示保存状态、Outbox 批次同步状态、检索状态和回答证据；失败状态不能显示为成功。
7. 证据至少展示实际内容、Memory ID、记忆类型和可用的创建时间或来源时间；不伪造页码、论文全文阅读状态或不存在的来源。
8. 清空当前 Streamlit 会话或重新启动应用后，同一身份仍可从 MySQL/Qdrant 回忆此前已保存的笔记。
9. 同租户不同用户、不同租户相同用户均不能看到未授权的 Memory ID、内容或基于其内容生成的回答。
10. 提供启动说明、离线测试命令、真实服务验收步骤和已知限制。

### 2.2 明确不在本阶段

- PDF 上传、解析、OCR、分块、全文 RAG、论文库和阅读状态管理。
- 任意账号注册、正式鉴权、租户管理或自定义身份输入；三个固定身份只用于本地演示和隔离验收。
- React、FastAPI、REST API、WebSocket、流式输出、独立 CLI 或第二套问答逻辑。
- 自动后台 Outbox worker、定时调度、整次写入自动重试、记忆编辑/删除/回滚。
- P2 摘要四项概览、PDF 文本提取、性能专项优化、云部署、监控和录屏材料。

## 3. 用户流程与验收语义

### 3.1 记录笔记

用户选择身份，填写非空论文标题和阅读结论，点击保存后先看到确认摘要，再点击“确认保存”。确认前不得调用 `save_turn_to_memory`。确认后由服务层生成独立 UUID `turn_id`，将标题与正文作为用户原始陈述传入 Phase 1.3。

页面必须按 `WriteResult.status` 显示以下状态：

| 状态 | 页面反馈 | 后续操作 |
|---|---|---|
| `saved` | 已保存，等待索引同步；展示 Memory ID | 可点击同步 |
| `partial` | 部分保存；展示已确认 ID 和脱敏错误码 | 不自动重写，可继续同步或重新输入 |
| `skipped` | 已跳过并说明未确认/查询/不支持操作 | 不显示保存成功 |
| `no_memory` | 未生成可保存事实 | 不显示保存成功 |
| `failed` | 保存失败或结果未确认；展示可操作错误 | 页面保持可用，不宣称回滚 |

### 3.2 索引同步

“同步一批”调用 `sync_outbox_batch(batch_size=100)`，展示 `done/failed/dead` 和耗时。批次 `done > 0` 只能说明批次有记录完成，不能直接说明当前笔记已可检索。只有后续查询实际返回当前 Memory ID 时，页面才显示该记忆已被检索到。

### 3.3 历史查询

用户输入问题后，服务层按当前固定身份调用检索；回答提示明确要求只依据返回证据回答。检索无证据时显示“未找到相关历史记忆”，不能用模型常识补写用户经历；检索失败、超时和模型回答失败必须与无证据分开显示。

回答区域和证据区域分离展示。回答区域显示生成的文本或明确失败提示，证据区域逐条显示实际内容和 Memory ID。当前输入中的论文名或术语不能单独作为历史证据。

### 3.4 会话重置

“新建会话”只清除 Streamlit `session_state` 中的临时对话、输入和展示状态，不删除 MySQL、Outbox、Qdrant 记录。重启应用后重新选择同一身份并查询，必须重新从持久化存储取得证据。

## 4. 架构与接口决策

页面只调用宿主业务服务层，不直接创建 SQLAlchemy session、调用 Qdrant 或读取 Memory V2 表。计划新增的公共服务契约如下：

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

`WriteResult` 和 `SyncResult` 复用 Phase 1.3 的字段与状态；不得重新引入只返回 `bool` 的成功契约。`ask_memory` 可在 Phase 1.2 检索封装中增加结构化结果入口，但保留现有字符串格式化函数供旧示例使用。

## 5. 非功能约束

- Python 3.11+、现有 asyncio、Pydantic、SQLAlchemy、Memory V2、MySQL、Qdrant、DashScope/Qwen 客户端；新增 Streamlit 依赖使用 `streamlit>=1.36,<2.0`。
- 每个保存操作传递明确的 `tenant_id`、`user_id`、UUID `turn_id`；每次同步和查询使用当前页面身份。
- UI 不记录 API Key、数据库凭据、完整连接串或笔记全文到日志；错误显示使用脱敏错误码和可操作说明。
- 所有异步任务必须被页面等待或明确完成；不创建无人等待的后台写入任务。
- 页面刷新、会话清除和服务异常不能删除或篡改已保存记忆。
- 固定身份选择是演示隔离，不等同于生产鉴权；页面文案必须明确这一限制。

## 6. 合并边界

只有在 `validation.md` 中的离线测试、Streamlit 启动冒烟、真实 P0 闭环和三种身份隔离全部通过后，才允许合并。任一真实 MySQL/Qdrant/模型检查因环境问题跳过，都只能标记为阻塞，不能标记为通过。实现过程中发现 Phase 1.3 真实写入或 Phase 1.2 检索不兼容时，只做宿主适配并在验收报告中记录，不扩大本阶段范围。
