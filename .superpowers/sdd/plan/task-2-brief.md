## Task Group 2: 业务服务层的保存与同步

**目标：** 将页面需要的笔记保存和索引同步统一封装，保持 Phase 1.3 状态语义。

**文件：** `papermind/app_service.py`、`tests/test_app_service.py`；复用 `papermind/memory_writer.py` 与 `papermind/outbox_sync.py`。

### Steps

- [ ] **步骤 1：** 先写 `save_note` 测试：空标题/正文失败；`confirmed=False` 不调用 `save_turn_to_memory`；确认后把标题和正文组合为用户输入并传递固定 tenant、user 和新 UUID turn_id。
- [ ] **步骤 2：** 写状态映射测试：逐一透传 `saved`、`partial`、`skipped`、`no_memory`、`failed`，保留 Memory ID 和错误码，不把失败转换成成功。
- [ ] **步骤 3：** 实现 `save_note(identity, title, conclusion, confirmed)`，仅调用既有写入入口；不在服务层复制 Speech Act、Fact Lane 或数据库逻辑。
- [ ] **步骤 4：** 先写 `sync_notes` 测试：默认 batch size 为 100、空批次合法、`failed/dead` 保留、异常返回失败；不把 `done > 0` 转换成"当前笔记已可检索"。
- [ ] **步骤 5：** 实现 `sync_notes(batch_size=100)`，调用既有 `sync_outbox_batch`，返回完整 `done/failed/dead` 和脱敏消息。
- [ ] **步骤 6：** 运行 `python -m pytest tests/test_app_service.py -q`，确认服务层在无真实数据库时也能用依赖注入覆盖全部分支。

### Context from Global Constraints

- 保存必须二次确认；查询入口不得调用保存入口；模型回答不得作为用户事实写入
- `saved`、`partial`、`skipped`、`no_memory`、`failed`、无证据和检索失败必须区分展示
- 批次同步完成不等价于当前 Memory ID 已可检索；只有实际证据返回当前 ID 才能显示可检索
- 每次保存使用 UUID `turn_id`

### Interface Requirements

From Phase 1.3 (existing):
- `save_turn_to_memory(tenant_id, user_id, turn_id, user_message, ...)` - 返回状态字典
- `sync_outbox_batch(batch_size)` - 返回 done/failed/dead 统计

To implement:
```python
async def save_note(
    identity: Identity,
    title: str,
    conclusion: str,
    *,
    confirmed: bool,
) -> WriteResult

async def sync_notes(batch_size: int = 100) -> SyncResult
```

### WriteResult and SyncResult Structure

From requirements.md section 3.1:
- WriteResult 必须包含：status (saved/partial/skipped/no_memory/failed), message, memory_id (可选), turn_id
- SyncResult 必须包含：done, failed, dead 计数，耗时信息

### Expected Test Coverage

**save_note tests:**
1. Empty title → 失败/跳过
2. Empty conclusion → 失败/跳过
3. confirmed=False → 不调用 save_turn_to_memory
4. confirmed=True → 调用 save_turn_to_memory，传递正确参数
5. 标题+正文组合为 user_message
6. 生成新的 UUID turn_id（每次不同）
7. 身份透传（tenant_id, user_id）
8. 状态映射：saved/partial/skipped/no_memory/failed 逐一正确返回

**sync_notes tests:**
1. 默认 batch_size=100
2. 空批次返回成功（done=0）
3. 调用 sync_outbox_batch 并返回统计
4. failed/dead 保留不转换
5. 异常处理返回失败状态

### Dependencies from Prior Tasks

Task Group 1 提供：
- Identity dataclass
- WriteResult, SyncResult dataclass（需在此任务定义或使用 TG1 已定义的）
- IDENTITIES 固定身份列表

Phase 1.3 提供：
- `papermind/memory_writer.py` - save_turn_to_memory
- `papermind/outbox_sync.py` - sync_outbox_batch

### Implementation Notes

1. **不实现新的写入逻辑** - 只封装 Phase 1.3 的接口
2. **状态透传，不转换** - Phase 1.3 返回的状态码直接映射到 WriteResult
3. **UUID turn_id 生成** - 每次 save_note 调用生成新的 UUID
4. **用户消息格式** - 将 title 和 conclusion 组合为清晰的用户陈述，例如："论文：{title}\n\n阅读结论：{conclusion}"
5. **confirmed 门控** - confirmed=False 时立即返回 skipped 状态，不调用写入

### Report Requirements

Write full report to: `.superpowers/sdd/plan/task-2-report.md`

Return only:
- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Commits: <hash>...<hash>
- Tests: Brief summary
- Concerns: Any doubts or observations
