# Requirements — Phase 1.3：最小记忆写入闭环

**修订日期**：2026-10-07

**状态**：规格已修订，待实施与验收。

**前置条件**：Phase 1.1 智能体宿主、Phase 1.2 记忆检索已完成，直接复用。

**时间边界**：[三天路线图](../roadmap.md)的 Day 1，约 7 小时；本阶段从写入开始，不重复开发宿主或检索模块。

## 1. 目标与交付物

完成一条真实链路：用户确认论文笔记 → Memory V2 抽取事实 → MySQL 提交 → 显式消费 Outbox → Qdrant 索引 → 已完成的 Phase 1.2 检索 → 清空历史并重启后仍可回忆。

交付宿主写入封装、一次批量同步封装、可操作的示例入口、针对新增行为的离线测试、真实集成验收脚本和运行说明。本次只改写规格；本文中的代码文件与命令属于后续实施交付物。

## 2. 范围

### 必须实现

- R1：用户明确确认后保存论文标题、阅读结论或研究背景，只接通 Fact Lane（核心名称为 semantic）。
- R2：复用核心 Speech Act 分类与 MemoryGate；提问、未确认输入和不支持的修改/删除请求跳过写入。
- R3：根据真实提交回执反馈状态，区分保存、部分保存、跳过、未生成记忆和失败。
- R4：提供显式 Outbox 单批同步入口，保留核心重试与退避行为。
- R5：复用已有检索验证新记忆与跨进程回忆，显示真实内容和 Memory ID。
- R6：所有写入、数据库核验、检索携带 tenant_id 与 user_id；通过用户与租户隔离验收。
- R7：写入与同步失败不导致示例进程退出；用户知道当前数据是否已保存、是否已可检索。
- R8：每次新保存操作使用独立 turn_id；记录真实结果和耗时，关闭已创建的数据库会话。

### 明确延期

Event、Entity、Policy 和 Update/Delete Lane；自动后台轮询与信号管理；完整 CLI、Rich 美化、Web/API；后台异步写入体验优化；自动重试整次写入；记忆编辑、删除、回滚；PDF、任务规划；并发压测与严格性能指标。Streamlit 页面在 Day 2 实现，完整录屏与交付材料在 Day 3 准备。

## 3. 输入与门控（R1、R2）

保存入口接收 user_text、tenant_id、user_id、turn_id 和 confirmed。空输入、空身份或空 turn_id 是输入错误；confirmed=False 返回 skipped，不能触发抽取或数据库写入。

复用 server.memory_v2.speech_act.classify_speech_act 和 MemorySpeechAct，实际枚举值如下：

| 分类值 | 本阶段处理 |
|--------|------------|
| assert | 允许进入事实抽取，仍由核心 MemoryGate 决定是否落库 |
| unknown | 允许交给核心事实抽取与 MemoryGate，不直接视为可信事实 |
| query_existing、ambiguous、filler | skipped，不触发写入 |
| explicit_update、explicit_delete | skipped，提示本阶段不支持修改或删除 |

“提问”入口只调用 Phase 1.2 检索与回答，不调用保存入口。即使用户误把查询提交到保存入口，也不能产生该问题的事实记录；用实际查询样例验证分类与核心门控，不能仅依赖界面按钮。

只保存用户确认的原始笔记，不将模型回复作为用户事实。复合句的自动拆分不新增宿主规则；若核心不能接受，返回未生成记忆，演示使用明确的陈述句。

## 4. 写入与结果契约（R3、R7、R8）

宿主定义 WriteResult，字段固定为 status、speech_act、memory_ids、turn_id、message、error_code。status 取 saved、partial、skipped、no_memory、failed；speech_act 未完成分类时为 None，error_code 无错误时为 None。

| 状态 | 判定依据 | 对用户的反馈 |
|------|----------|--------------|
| saved | 至少一条有效事实提交回执，且没有报告抽取/提交错误 | 已保存，等待索引同步；显示 Memory ID |
| partial | 部分事实已提交，同时存在抽取/提交错误 | 部分已保存；保留成功 ID，显示错误，不自动重写 |
| skipped | 未确认、查询、歧义、填充或不支持的操作 | 已跳过，并说明原因；不是系统故障 |
| no_memory | 无有效提交，且没有抽取或提交错误，例如没有事实候选或被门控拒绝 | 未生成可保存的事实；不能显示保存成功 |
| failed | 输入、模型、解析或数据库错误，且无已知成功提交 | 保存失败；说明原因，不宣称整次操作已回滚 |

核心 MemoryWriter.write_turn 返回 V2WriteResult，不是含 facts/events 的字典。事实 ID 取 CommitReceipt.aggregate_id，要求 truth_committed=True、aggregate_type=MemoryRecord 且 ID 有效；候选数不能当作保存数。

结合 lane_outcomes、failed_lanes、v2_write_success 与 commits 判断；提交回执与数据库不一致时，有已核验的成功 ID 则返回 partial，否则返回 failed。不只用一个成功布尔值掩盖错误。抽取成功但零提交不能报成功。模型错误有时由核心转成结果返回，不能只捕获抛出的异常。

发生数据库连接中断或超时时，结果可能需要再次核验，反馈“保存未确认，请检查后再重试”；不得保证所有数据均未写入。首版不自动重试整次写入。

turn_id 使用 UUID 字符串，不能仅用 SessionManager 重启归零的整数轮次。UUID 防止新操作标识冲突，不代表已实现重复请求幂等；重试是否去重由核心机制验证。

## 5. Outbox 显式同步（R4、R5）

新增 sync_outbox_batch(batch_size=100)，调用核心 OutboxWorker.process_pending，返回 SyncResult：status（completed 或 failed）、done、failed、dead、message。返回完整统计；零条处理是合法的空批次，不是当前笔记已同步的证明。

OutboxWorker 使用 MySQL 会话、IndexV2 和 RealEmbedder，复用核心配置与 1536 维索引要求。同步包装负责资源关闭与异常反馈，不另外实现轮询调度器，也不吞掉批次异常后返回成功。

核心批次可能包含其他记忆，done > 0 不能证明当前 memory_ids 已可检索。只有当前写入 ID 的关联 Outbox 完成，且 Phase 1.2 实际召回这些 ID 后，才能显示“已可检索”。同步失败不否定已经成功提交的 MySQL 事实；用户看到“已保存，索引同步失败”。

重试复用核心 next_retry_at、retry_count、dead 状态。再次触发同步不绕过退避，不要求立即重新处理失败项。首版同步入口仅用于本地演示管理，批次处理的是数据库待处理队列，不作为按用户授权的管理 API。

## 6. 集成与错误处理（R5、R6、R7）

- 在现有聊天示例增加“确认保存 / 同步一批 / 提问 / 退出”操作；Phase 1.3 不新建完整 CLI 框架。
- 保存与同步按顺序等待，结果返回后再反馈，不要求后台非阻塞体验。不创建无人等待的写入任务。
- 历史回忆复用 Phase 1.2：无证据时明确没有找到记忆，检索失败时明确故障，不能用模型常识冒充用户历史。
- 使用三个隔离组合：(tenant_A, user_A)、(tenant_A, user_B)、(tenant_B, user_A)。实际运行使用独立验收身份，避免已有记录影响结果。
- 为写入、同步分别记录 turn_id、状态、数量、耗时及脱敏错误码；宿主日志不输出 API Key、数据库连接凭据或笔记全文。复用核心输出前检查其现有日志，不扩大为日志平台建设。
- 数据库会话在 finally 关闭；异常路径同样释放资源。不得在异步入口中直接执行长时间的同步网络循环并承诺超时可中断。

## 7. 接口依据与配置

| 复用能力 | 实际源码 |
|----------|----------|
| writer 工厂 | [wiring.py](../../memoryV2-core/server/memory_v2/wiring.py)：create_memory_writer(llm_client, tenant_id="default") |
| 核心写入 | [writer.py](../../memoryV2-core/server/memory_v2/write/writer.py)：write_turn(user_text, user_id, turn_id, occurred_at=None, tenant_id="default", previous_user_text=None) |
| 结构化抽取客户端 | [llm_gate.py](../../memoryV2-core/server/memory_v2/llm_gate.py)：DashScopeClient.structured_extract |
| 返回值契约 | [contracts.py](../../memoryV2-core/server/memory_v2/contracts.py)：V2WriteResult、CommitReceipt、LaneOutcome |
| 同步 worker | [outbox.py](../../memoryV2-core/server/memory_v2/store/outbox.py)：OutboxWorker.process_pending |
| 分类与门控 | [speech_act.py](../../memoryV2-core/server/memory_v2/speech_act.py)、[gate.py](../../memoryV2-core/server/memory_v2/write/gate.py) |
| 已完成检索 | [Phase 1.2 实施总结](../2026-10-07-phase1.2-memory-retrieval/implementation-summary.md) |

宿主 LLMClient.chat 不等于核心 structured_extract 接口。优先复用核心 DashScopeClient，不重复实现结构化抽取网关。create_memory_writer 默认装配多个 Lane，且没有 fact_only 参数；本次在宿主装配 MemoryWriter、SemanticExtractor、MemoryGate、MemoryDispatcher 和 FactStore，只提供 semantic 抽取器及事实后端。Writer 的 llm_client=None 关闭规划器额外模型补漏，SemanticExtractor 仍注入真实抽取客户端。保留核心规则路由与门控，不承诺路由追踪中只出现一个 Lane；缺少抽取器的 Lane 不产生事实提交。

复用本地 .env 中 DB_HOST、DB_PORT、DB_USER、DB_PASS、DB_NAME、QDRANT_HOST、QDRANT_PORT、BAILIAN_API_KEY。不得写入真实凭据，不新增无实现支持的 ENABLE_SPEECH_ACT_GATE 或 OUTBOX_SYNC_INTERVAL 开关。

## 8. 验收与退出条件

详见 [validation.md](validation.md)，R1–R8 均须有对应验证记录。最低结果：保存事实并核对数据库 → 同步并检索到当前 ID → 重启后回忆 → 查询不误写 → 两类身份隔离 → 失败状态反馈。

不要求写入小于两秒、同步小于十秒、固定覆盖率或十用户并发。记录实测耗时及失败原因；真实服务不可用或关键用例跳过时，本阶段不能宣布验收通过。

超过七小时预算时，先删辅助展示，只保留本地示例、写入、同步和验收。真实闭环未通过就记录阻塞项，不能用 Mock 演示替代；不自动开始 Day 2 网页开发。
