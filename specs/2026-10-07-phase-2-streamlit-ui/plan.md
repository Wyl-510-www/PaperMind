# Phase 2 Streamlit 单页 P0 闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务组执行。每个步骤完成独立测试后再勾选。

**Goal:** 在浏览器中交付真实的“选择身份 → 确认保存 → Outbox 同步 → 新会话提问 → 查看证据”闭环。

**Architecture:** Streamlit 页面只负责输入、会话状态和展示；`papermind.app_service` 负责身份约束、写入/同步/检索/回答编排，并复用 Phase 1.3 与 Phase 1.2 的接口。结构化证据由宿主适配层提供，MySQL、Qdrant 和 Memory V2 资源不直接暴露给页面。

**Tech Stack:** Python 3.11+、Streamlit 1.x（`>=1.36,<2.0`）、asyncio、现有 Pydantic/SQLAlchemy、Memory V2、MySQL、Qdrant、DashScope/Qwen。

**Spec:** `specs/2026-10-07-phase-2-streamlit-ui/requirements.md`

**Validation:** `specs/2026-10-07-phase-2-streamlit-ui/validation.md`

## Global Constraints

- 只实现 P0；不加入 PDF、论文库、P2 摘要、REST API、自动 worker 或正式鉴权。
- 页面只调用业务服务层，不直接操作数据库、Qdrant 或 Memory V2 内部对象。
- 身份只能来自 `tenant_A/user_A`、`tenant_A/user_B`、`tenant_B/user_A` 三个固定组合。
- 保存必须二次确认；查询入口不得调用保存入口；模型回答不得作为用户事实写入。
- `saved`、`partial`、`skipped`、`no_memory`、`failed`、无证据和检索失败必须区分展示。
- 批次同步完成不等价于当前 Memory ID 已可检索；只有实际证据返回当前 ID 才能显示可检索。
- 每次保存使用 UUID `turn_id`；不记录密钥、凭据、完整连接串或笔记全文。
- 真实服务不可用或关键验收跳过时不得宣布完成或合并。

## 文件与接口地图

| 文件 | 操作 | 职责 |
|---|---|---|
| `papermind-host/pyproject.toml` | 修改 | 增加 Streamlit 运行依赖和可重复安装约束 |
| `papermind-host/papermind/app_service.py` | 新增 | 固定身份、笔记保存、同步、结构化检索和回答编排；页面唯一业务入口 |
| `papermind-host/papermind/memory_retrieval.py` | 修改 | 增加公开结构化证据适配，保持既有 `retrieve_memory_context` 行为兼容 |
| `papermind-host/streamlit_app.py` | 新增 | Streamlit 单页、输入控件、session state、状态和证据展示 |
| `papermind-host/tests/test_app_service.py` | 新增 | 服务层离线契约、门控、身份透传、回答状态和错误测试 |
| `papermind-host/tests/test_streamlit_app.py` | 新增 | 页面渲染、确认门控、身份选项、会话清除和错误展示测试 |
| `papermind-host/scripts/verify_phase2_ui.py` | 新增 | 本地真实服务验收辅助脚本和脱敏报告 |
| `papermind-host/README.md` | 修改 | Streamlit 安装、启动、三身份流程、验收和限制说明 |

## Task Group 1: 依赖与公共契约

**目标：** 建立可导入、可测试且不绕过业务层的基础契约。

**文件：** `pyproject.toml`、`papermind/app_service.py`、`tests/test_app_service.py`。

- [ ] **步骤 1：** 在 `pyproject.toml` 增加 `streamlit>=1.36,<2.0`，保留现有 Python 版本和依赖，不替换已有 Memory V2 依赖。
- [ ] **步骤 2：** 在 `app_service.py` 定义 `Identity`、`EvidenceItem`、`AskResult` 和固定的 `IDENTITIES` 元组；断言三个组合恰好存在且没有重复。
- [ ] **步骤 3：** 为固定身份和非法身份写失败测试：任意自定义身份不能进入保存、同步或查询调用，三个固定组合必须逐一透传。
- [ ] **步骤 4：** 运行 `python -m pytest tests/test_app_service.py -q`，确认契约测试通过后再进入写入编排。

## Task Group 2: 业务服务层的保存与同步

**目标：** 将页面需要的笔记保存和索引同步统一封装，保持 Phase 1.3 状态语义。

**文件：** `papermind/app_service.py`、`tests/test_app_service.py`；复用 `papermind/memory_writer.py` 与 `papermind/outbox_sync.py`。

- [ ] **步骤 1：** 先写 `save_note` 测试：空标题/正文失败；`confirmed=False` 不调用 `save_turn_to_memory`；确认后把标题和正文组合为用户输入并传递固定 tenant、user 和新 UUID turn_id。
- [ ] **步骤 2：** 写状态映射测试：逐一透传 `saved`、`partial`、`skipped`、`no_memory`、`failed`，保留 Memory ID 和错误码，不把失败转换成成功。
- [ ] **步骤 3：** 实现 `save_note(identity, title, conclusion, confirmed)`，仅调用既有写入入口；不在服务层复制 Speech Act、Fact Lane 或数据库逻辑。
- [ ] **步骤 4：** 先写 `sync_notes` 测试：默认 batch size 为 100、空批次合法、`failed/dead` 保留、异常返回失败；不把 `done > 0` 转换成“当前笔记已可检索”。
- [ ] **步骤 5：** 实现 `sync_notes(batch_size=100)`，调用既有 `sync_outbox_batch`，返回完整 `done/failed/dead` 和脱敏消息。
- [ ] **步骤 6：** 运行 `python -m pytest tests/test_app_service.py -q`，确认服务层在无真实数据库时也能用依赖注入覆盖全部分支。

## Task Group 3: 结构化证据与回答编排

**目标：** 让页面能够展示真实证据，并清楚区分有证据、无证据和检索故障。

**文件：** `papermind/memory_retrieval.py`、`papermind/app_service.py`、`tests/test_app_service.py`、既有检索测试。

- [ ] **步骤 1：** 先为结构化检索适配写测试：返回 `memory_id/content/memory_type/confidence/created_at`；空 `items` 为 `no_evidence`；超时或异常为 `retrieval_failed`；tenant/user 必须透传。
- [ ] **步骤 2：** 在检索模块增加公开的结构化入口，复用现有 `_call_memory_v2_retrieval` 和超时配置；保留 `retrieve_memory_context` 兼容旧调用，不解析展示字符串反推 ID。
- [ ] **步骤 3：** 为 `ask_memory` 写测试：有证据才调用 LLM；无证据不调用 LLM 并返回明确提示；检索失败不伪装成无证据；LLM 失败返回 `answer_failed` 但保留已取得的证据。
- [ ] **步骤 4：** 实现 `ask_memory(identity, question, llm_client)`，使用当前身份和证据生成回答；系统提示要求只基于证据回答，禁止声称未检索到的历史事实。
- [ ] **步骤 5：** 运行 `python -m pytest tests/test_memory_retrieval.py tests/test_app_service.py -q`，确认原检索测试无回归且结构化结果可供页面使用。

## Task Group 4: Streamlit 单页与会话状态

**目标：** 提供最小可操作页面，不让 UI 直接依赖存储实现。

**文件：** `streamlit_app.py`、`tests/test_streamlit_app.py`。

- [ ] **步骤 1：** 先写页面测试：身份下拉框只包含三个固定组合；页面首次加载初始化 `selected_identity`、输入框、最近写入、同步结果、回答和证据状态；不触发写入或检索。
- [ ] **步骤 2：** 实现页面入口和布局：身份选择区、论文标题输入、阅读结论文本区、保存按钮、同步按钮、提问输入、回答区、证据区和“新建会话”按钮。
- [ ] **步骤 3：** 保存按钮第一次点击只生成待确认状态；确认按钮才调用 `save_note`，显示状态、Message、Memory ID 和当前 turn_id 的脱敏前缀。
- [ ] **步骤 4：** 同步按钮调用 `sync_notes` 并展示统计；页面文案使用“批次已处理/仍需通过查询确认”，不得直接写“当前笔记已可检索”。
- [ ] **步骤 5：** 提问按钮只调用 `ask_memory`；回答与 EvidenceItem 分栏渲染，空证据和故障使用不同颜色和文案。
- [ ] **步骤 6：** “新建会话”清除临时输入、回答、证据和结果状态，不调用删除接口、不清除数据库；测试确认下次查询重新调用服务层。
- [ ] **步骤 7：** 页面所有服务调用包在可恢复的异常处理内；显示脱敏错误码，异常后仍可切换身份和继续操作。
- [ ] **步骤 8：** 运行 `python -m pytest tests/test_streamlit_app.py -q`，再执行 `python -m compileall streamlit_app.py papermind`。

## Task Group 5: 三身份隔离与真实验收脚本

**目标：** 用真实本地服务证明网页调用的仍是持久化 Memory V2 闭环。

**文件：** `scripts/verify_phase2_ui.py`、`README.md`、必要的集成测试 fixture。

- [ ] **步骤 1：** 先定义脱敏报告格式：运行标记、身份、turn_id 前缀、Memory ID、保存状态、同步统计、证据 ID、耗时和 pass/fail/block；禁止写入笔记全文、prompt、密钥或连接串。
- [ ] **步骤 2：** 实现写入阶段：使用独立运行标记和 `tenant_A/user_A` 保存明确笔记，核对 MySQL MemoryRecord 和 Outbox，记录真实 Memory ID。
- [ ] **步骤 3：** 实现同步与召回阶段：显式处理 Outbox，使用新进程/新 Streamlit 会话查询，只有证据包含当前 ID 和运行标记才判定召回通过。
- [ ] **步骤 4：** 执行 `tenant_A/user_B` 和 `tenant_B/user_A` 的相同查询，确认证据不包含授权外的 ID 或内容；执行未保存标记查询，确认显示无证据。
- [ ] **步骤 5：** 验证查询不误写：记录查询前后当前身份的事实数量，提问和无确认输入不得新增事实；不要求 Outbox 或日志行数保持不变。
- [ ] **步骤 6：** 在 README 写明服务启动、依赖安装、`streamlit run streamlit_app.py`、同步步骤、验收脚本和当前不支持的功能。

## Task Group 6: 完整回归与合并前复核

**目标：** 以可复查证据确认功能达到合并条件。

- [ ] **步骤 1：** 运行离线回归：

  ```powershell
  python -m pytest tests/ -q
  python -m compileall streamlit_app.py papermind
  git diff --check
  ```

- [ ] **步骤 2：** 启动 Streamlit 无头冒烟，访问 `/_stcore/health`，确认页面可启动后干净停止；记录版本和端口，不把启动成功当作业务闭环通过。
- [ ] **步骤 3：** 按 `validation.md` 连续执行两次真实 P0 闭环，每次使用新的运行标记和独立报告；关键服务不可用时退出码必须非零。
- [ ] **步骤 4：** 对照 requirements.md 中的十项 P0 交付要求，检查每项都有测试或真实证据；检查页面文案没有“已可检索”的过早承诺。
- [ ] **步骤 5：** 复核 Git diff 仅包含本阶段实现、测试和说明；保留当前分支已有未提交修改，不将其误删或重置。

## 7. 交付停止条件

全部 Task Group 的离线测试通过、Streamlit 启动冒烟通过、三身份真实 P0 验收无跳过且报告可复查后，才可请求代码审查和合并。任何真实写入、同步、跨会话召回或隔离用例失败，都保持分支待修复状态，不用静态 Mock 或页面截图替代。
