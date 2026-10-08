# Validation — Phase 2：Streamlit 单页 P0 闭环

**日期**：2026-10-07  
**状态**：待实施；本文定义通过标准，不代表当前已通过。  
**规格**：`requirements.md`  
**计划**：`plan.md`

## 1. 通过与合并规则

实现必须同时满足以下条件才能合并：

1. 离线单元测试、页面测试和既有宿主回归全部通过。
2. Streamlit 入口可在无头模式启动并通过健康检查。
3. 使用真实本地 MySQL、Qdrant 和模型服务完成至少两次独立 P0 闭环：保存、同步、重置/重启、查询和证据展示。
4. 三个固定身份组合的用户隔离和租户隔离全部通过。
5. 查询、无确认输入、无证据、写入失败、同步失败和检索失败均显示正确状态，不把故障当作无历史或保存成功。
6. 所有关键用例都有 pass/fail/block 记录；关键服务不可用或用例跳过时不得以退出码 0 宣布通过。
7. `git diff --check` 通过，变更不包含凭据、完整连接串、原始笔记全文或无关阶段重构。

## 2. 环境与命令

从仓库根目录确认本地依赖：

```powershell
docker compose -f memoryV2-local-env/compose.yaml ps
python memoryV2-local-env/verify_environment.py
```

在 `papermind-host` 目录安装当前项目后运行：

```powershell
python -m pip install -e .
python -m pytest tests/ -q
python -m compileall streamlit_app.py papermind
git diff --check
```

启动冒烟使用固定端口并记录实际 Streamlit 版本：

```powershell
$streamlitProcess = Start-Process -FilePath python -ArgumentList '-m','streamlit','run','streamlit_app.py','--server.headless','true','--server.port','8501' -PassThru
try {
    Start-Sleep -Seconds 5
    (Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8501/_stcore/health').StatusCode | Should -Be 200
}
finally {
    Stop-Process -Id $streamlitProcess.Id -Force -ErrorAction SilentlyContinue
}
```

如果当前环境没有 Pester，健康检查脚本应改用实际 HTTP 状态断言；无论使用何种命令，都必须保留非零失败结果，不得只检查进程仍存在。

## 3. 离线用例

| 编号 | 场景 | 必须证明 |
|---|---|---|
| UT-01 | 页面首次加载 | 只显示三个固定身份，不调用写入、同步或检索 |
| UT-02 | 空标题/空正文 | 服务返回输入失败，页面不调用 Memory V2，不显示已保存 |
| UT-03 | 未确认保存 | `save_turn_to_memory` 调用次数为 0，页面显示待确认/已跳过 |
| UT-04 | 五种 WriteResult | `saved/partial/skipped/no_memory/failed` 文案和 ID/错误码映射准确 |
| UT-05 | 同步结果 | `done/failed/dead` 完整展示；空批次不显示当前笔记已可检索 |
| UT-06 | 结构化证据 | 每条证据显示实际 `content`、`memory_id`、类型、置信度和可用时间 |
| UT-07 | 无证据 | 不调用 LLM，不生成用户历史结论，显示明确无证据提示 |
| UT-08 | 检索/回答故障 | 检索失败与回答失败分别标记，保留已有证据，不伪装无证据 |
| UT-09 | 查询门控 | 提问路径不调用保存；查询文本误传保存入口时返回 `skipped` |
| UT-10 | 会话重置 | 只清除 `session_state` 临时值，不调用删除或清空存储接口 |
| UT-11 | 身份透传 | 三个固定组合分别传给保存、同步关联核验和查询服务；任意自定义身份被拒绝 |
| UT-12 | 异常恢复 | 服务异常后页面仍能切换身份、重新输入并执行下一次操作 |

## 4. 真实 P0 验收

每次运行生成新的短运行标记，例如 `phase2-20261007-<suffix>`；标记同时写入笔记标题和查询词，避免旧数据或模型常识造成误判。不得清空已有 MySQL/Qdrant 数据。

### IT-01：身份 A 保存并核对数据库

1. 选择 `tenant_A / user_A`。
2. 标题填写 `验收论文〔运行标记〕`，正文填写明确陈述，例如“我的阅读结论是：自注意力机制让模型直接建模序列内依赖”。
3. 点击保存并确认。
4. 通过页面结果和数据库核验确认：`status=saved`（或明确记录 partial）、`turn_id` 非空且为本次 UUID、至少一个 Memory ID 与当前 tenant/user 和 source turn 对应、正文内容匹配。

**通过证据：** 页面截图或日志只保留脱敏 ID；数据库查询结果保留 scope、状态和 ID，不保存全文到报告。

### IT-02：Outbox 同步与当前 ID 召回

1. 点击同步一批，记录 `done/failed/dead` 和耗时。
2. 检查 IT-01 Memory ID 关联的 Outbox 状态；不能用总 `done` 代替当前 ID 核验。
3. 使用同一身份提出包含运行标记的问题。
4. 只有检索证据实际包含 IT-01 的 Memory ID、运行标记和内容时，才判定当前笔记已可检索。

**失败判定：** 同步失败、当前 ID 未完成或查询没有当前证据时，页面必须显示未可确认，不得显示已检索。

### IT-03：跨会话/跨进程回忆

关闭浏览器页面或终止 Streamlit 进程，重新启动应用并清空新会话状态；重新选择 `tenant_A / user_A`，不粘贴旧笔记和旧答案，只提交查询。必须重新从持久化存储召回 IT-01 的证据和 Memory ID。

### IT-04：查询不误写

1. 记录当前 scope 下运行标记相关事实数量。
2. 提交“我之前记录过哪些论文结论？”和“我喜欢什么？”等问题。
3. 对比查询前后事实记录；数量不得因查询增加，查询结果不得进入写入接口。

### IT-05：无证据和故障反馈

- 使用未保存的随机运行标记提问：显示未找到相关历史记忆，不声称用户读过该论文。
- 通过依赖注入或局部故障模拟写入失败：不显示已保存，页面可继续操作。
- 模拟同步失败或 dead：保留已保存事实，显示索引未完成，不显示已可检索。
- 模拟检索失败/超时：显示检索故障，不降级为无证据，不使用通用模型答案冒充历史。

### IT-06：用户与租户隔离

分别使用以下身份查询 IT-01 的唯一运行标记：

| 查询身份 | 预期 |
|---|---|
| `tenant_A / user_A` | 能看到 IT-01 Memory ID 和内容 |
| `tenant_A / user_B` | 不能看到 IT-01 ID、内容或未授权历史结论 |
| `tenant_B / user_A` | 不能看到 IT-01 ID、内容或未授权历史结论 |

隔离判断以证据 ID、证据内容和持久化 scope 为准；不能仅以模型回答没有复述标记作为通过。

## 5. 两次闭环与报告

真实 P0 验收至少连续执行两次，每次使用独立运行标记和报告文件：

```powershell
python scripts/verify_phase2_ui.py --mode all --report .phase2-ui-report-1.json
python scripts/verify_phase2_ui.py --mode all --report .phase2-ui-report-2.json
```

脚本或人工报告至少包含：

- 执行日期、代码分支和 Streamlit 版本；
- 服务可用性检查结果；
- 每个 IT/UT 用例的 `pass/fail/block`；
- 脱敏 tenant/user、turn_id 前缀、Memory ID、保存状态、同步统计、证据 ID 和耗时；
- 失败原因、重试后的结果和未完成项；
- 是否满足合并规则。

退出码约定：`0` 表示所有 P0 通过；`1` 表示断言失败；`2` 表示环境缺失或关键检查无法执行。关键用例为 `block/skip` 时不得返回 `0`。

## 6. 合并前人工复核清单

- [ ] 页面只使用业务服务层，没有直接数据库/Qdrant 调用。
- [ ] 三个身份选项固定且每次保存/查询都传 tenant、user、turn。
- [ ] 保存需要明确确认；提问不会生成事实。
- [ ] 保存、同步、检索、回答、无证据和故障状态可区分。
- [ ] 证据显示真实内容和 Memory ID；没有伪造页码或来源。
- [ ] 新建会话/重启后能召回持久化事实。
- [ ] 两种隔离查询均无越权证据。
- [ ] 离线测试、启动冒烟、两次真实闭环和 `git diff --check` 全部通过。
- [ ] README、验收报告和已知限制已更新；没有把 P2 或延期能力写成已交付。
