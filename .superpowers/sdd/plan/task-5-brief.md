## Task Group 5: 三身份隔离与真实验收脚本

**目标：** 用真实本地服务证明网页调用的仍是持久化 Memory V2 闭环。

**文件：** `scripts/verify_phase2_ui.py`、`README.md`、必要的集成测试 fixture。

### Steps

- [ ] **步骤 1：** 先定义脱敏报告格式：运行标记、身份、turn_id 前缀、Memory ID、保存状态、同步统计、证据 ID、耗时和 pass/fail/block；禁止写入笔记全文、prompt、密钥或连接串。
- [ ] **步骤 2：** 实现写入阶段：使用独立运行标记和 `tenant_A/user_A` 保存明确笔记，核对 MySQL MemoryRecord 和 Outbox，记录真实 Memory ID。
- [ ] **步骤 3：** 实现同步与召回阶段：显式处理 Outbox，使用新进程/新 Streamlit 会话查询，只有证据包含当前 ID 和运行标记才判定召回通过。
- [ ] **步骤 4：** 执行 `tenant_A/user_B` 和 `tenant_B/user_A` 的相同查询，确认证据不包含授权外的 ID 或内容；执行未保存标记查询，确认显示无证据。
- [ ] **步骤 5：** 验证查询不误写：记录查询前后当前身份的事实数量，提问和无确认输入不得新增事实；不要求 Outbox 或日志行数保持不变。
- [ ] **步骤 6：** 在 README 写明服务启动、依赖安装、`streamlit run streamlit_app.py`、同步步骤、验收脚本和当前不支持的功能。

### Context from Global Constraints

- 真实服务不可用或关键验收跳过时不得宣布完成或合并
- 批次同步完成不等价于当前 Memory ID 已可检索；只有实际证据返回当前 ID 才能显示可检索
- 身份只能来自 `tenant_A/user_A`、`tenant_A/user_B`、`tenant_B/user_A` 三个固定组合
- 同租户不同用户、不同租户相同用户均不能看到未授权的 Memory ID
- 每次保存使用 UUID `turn_id`；不记录密钥、凭据、完整连接串或笔记全文

### Validation Requirements

From `specs/2026-10-07-phase-2-streamlit-ui/validation.md`:

**P0 闭环验收必须包含：**

1. **写入阶段**
   - 使用唯一运行标记（如时间戳）
   - 使用 `tenant_A/user_A` 身份
   - 保存包含运行标记的笔记
   - 验证 MySQL MemoryRecord 表中存在对应记录
   - 验证 Outbox 表中存在待同步记录
   - 记录 Memory ID

2. **同步阶段**
   - 调用 sync_notes 或直接运行 sync_outbox_batch
   - 验证 Outbox 记录被处理（done/failed/dead）

3. **召回阶段**
   - 使用新会话（或重启 Streamlit）
   - 使用相同身份 `tenant_A/user_A`
   - 查询包含运行标记的关键词
   - 验证证据列表中包含当前 Memory ID
   - 验证证据内容包含运行标记

4. **隔离验证**
   - 使用 `tenant_A/user_B` 查询相同关键词 → 不得返回 `tenant_A/user_A` 的 Memory ID
   - 使用 `tenant_B/user_A` 查询相同关键词 → 不得返回 `tenant_A/user_A` 的 Memory ID
   - 查询未保存的运行标记 → 返回 no_evidence 状态

5. **查询不误写验证**
   - 记录查询前当前身份的 MemoryRecord 数量
   - 执行查询（不点击保存确认）
   - 记录查询后当前身份的 MemoryRecord 数量
   - 验证数量不变（查询不应新增事实）

### Verification Script Requirements

**文件位置：** `papermind-host/scripts/verify_phase2_ui.py`

**功能：**
1. 生成唯一运行标记（建议：`verify_phase2_YYYYMMDD_HHMMSS`）
2. 直接调用 app_service 层函数（不通过 Streamlit UI）
3. 连接 MySQL 验证 MemoryRecord 和 Outbox
4. 连接 Qdrant 或通过 Memory V2 API 验证索引
5. 生成脱敏验收报告

**脱敏报告格式：**
```
=== Phase 2 UI Verification Report ===
Run Marker: verify_phase2_20261008_143022
Date: 2026-10-08 14:30:22

[Stage 1: Write]
Identity: tenant_A/user_A
Turn ID: a1b2c3d4... (前8字符)
Memory ID: mem_xyz123...
Status: saved
Duration: 0.234s
MySQL MemoryRecord: ✅ Found
MySQL Outbox: ✅ Found (pending)

[Stage 2: Sync]
Batch Size: 100
Done: 1
Failed: 0
Dead: 0
Duration: 1.456s

[Stage 3: Recall]
Identity: tenant_A/user_A
Query: verify_phase2_20261008_143022
Evidence Count: 3
Evidence Contains Memory ID: ✅ Yes (mem_xyz123...)
Evidence Contains Run Marker: ✅ Yes
Duration: 0.567s
Result: PASS

[Stage 4: Isolation - tenant_A/user_B]
Identity: tenant_A/user_B
Query: verify_phase2_20261008_143022
Evidence Count: 0
Evidence Contains Unauthorized ID: ✅ No
Result: PASS

[Stage 4: Isolation - tenant_B/user_A]
Identity: tenant_B/user_A
Query: verify_phase2_20261008_143022
Evidence Count: 0
Evidence Contains Unauthorized ID: ✅ No
Result: PASS

[Stage 4: Isolation - Unsaved Marker]
Identity: tenant_A/user_A
Query: unsaved_marker_never_written
Status: no_evidence
Result: PASS

[Stage 5: Query Does Not Write]
Identity: tenant_A/user_A
MemoryRecord Count Before: 5
Query Executed: "test query"
MemoryRecord Count After: 5
Count Unchanged: ✅ Yes
Result: PASS

=== Summary ===
Total Tests: 6
Passed: 6
Failed: 0
Blocked: 0
Overall: PASS

禁止写入内容：
- 笔记全文（只记录 turn_id 前缀和 Memory ID）
- LLM prompt
- 数据库连接串
- API 密钥
```

### README Requirements

**文件：** `papermind-host/README.md`

**必需内容：**

1. **项目简介**
   - PaperMind Phase 2 Streamlit UI
   - P0 功能范围

2. **安装依赖**
   ```bash
   cd papermind-host
   pip install -e .
   ```

3. **服务启动**
   - MySQL 启动命令和初始化
   - Qdrant 启动命令
   - Memory V2 服务启动（如适用）
   - 配置文件位置和必需环境变量

4. **运行 Streamlit**
   ```bash
   cd papermind-host
   streamlit run streamlit_app.py
   ```

5. **使用流程**
   - 选择身份（3个固定组合）
   - 输入笔记并确认保存
   - 点击同步按钮
   - 输入问题并查询
   - 查看回答和证据
   - 新建会话重置

6. **验收脚本**
   ```bash
   cd papermind-host
   python scripts/verify_phase2_ui.py
   ```

7. **当前不支持的功能**
   - PDF 上传和解析
   - 论文库管理
   - P2 摘要生成
   - REST API
   - 自动后台 worker
   - 正式鉴权系统

### Dependencies from Prior Tasks

Task Group 1-4 提供：
- `papermind/app_service.py` - Identity, IDENTITIES, save_note, sync_notes, ask_memory
- `streamlit_app.py` - 完整 UI 实现
- `tests/test_app_service.py` - 离线测试（52个）
- `tests/test_streamlit_app.py` - 页面测试（19个）

Phase 1.x 提供：
- `papermind/memory_writer.py` - save_turn_to_memory
- `papermind/outbox_sync.py` - sync_outbox_batch
- `papermind/memory_retrieval.py` - retrieve_structured_evidence
- `papermind/database.py` - MySQL 连接
- `papermind/config.py` - 配置管理

### Implementation Notes

1. **验收脚本位置** - `papermind-host/scripts/verify_phase2_ui.py`
2. **直接调用服务层** - 不通过 Streamlit UI，直接调用 `app_service` 函数
3. **异步调用** - 使用 `asyncio.run()` 包装异步函数
4. **数据库连接** - 复用 `papermind.database` 模块
5. **运行标记** - 使用时间戳保证唯一性，格式：`verify_phase2_YYYYMMDD_HHMMSS`
6. **脱敏原则** - 只记录标识符（turn_id 前缀、Memory ID），不记录内容全文
7. **退出码** - 任何阶段失败或服务不可用时返回非零退出码
8. **独立运行** - 脚本可独立运行，不依赖 Streamlit 进程

### LLMClient for Verification

验收脚本需要提供 LLMClient 实例给 `ask_memory`：

```python
from papermind.llm_client import create_llm_client  # 如果存在
# 或
class VerificationLLMClient:
    async def generate(self, prompt: str) -> str:
        # 调用真实 LLM API
        pass
```

### Expected Test Coverage

验收脚本不需要单元测试，但需要：
- 清晰的阶段划分（5个阶段）
- 每个阶段的验证逻辑
- 脱敏报告输出
- 失败时的明确错误消息
- 非零退出码（失败时）

### Report Requirements

Write full report to: `.superpowers/sdd/plan/task-5-report.md`

Return only:
- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Commits: <hash>...<hash>
- Verification: Brief summary of verification results
- Concerns: Any doubts or observations
