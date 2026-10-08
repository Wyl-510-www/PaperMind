# Phase 1.3 最小记忆写入闭环实施计划

> **执行要求**：使用 Superpowers 的 subagent-driven-development 或 executing-plans 按任务执行；通过核验后勾选步骤。本计划只覆盖 Day 1，后续网页与录屏按路线图推进。

**目标**：复用已完成的 Phase 1.1、1.2，在约 7 小时内完成事实写入、显式 Outbox 同步和真实读写联调。

**架构**：宿主装配事实写入器，保留核心分类、抽取、门控和事务存储；同步直接复用 OutboxWorker。现有聊天示例提供确认保存、同步、提问三个操作，未来 Streamlit 复用同一接口。

**技术栈**：现有 Python 3.11+、asyncio、SQLAlchemy、Memory V2、MySQL、Qdrant、DashScope。

**规格**：[requirements.md](requirements.md)；**验收**：[validation.md](validation.md)；**排期**：[roadmap.md](../roadmap.md)。

## 1. 全局约束

- Phase 1.1、1.2 已完成，不重新搭建宿主或检索模块。
- 仅提供 semantic 事实抽取器及事实后端，不开发其他 Lane、Web、完整 CLI 或后台调度器。
- 用户确认原始笔记后才写入；提问只检索，模型回复不保存。
- tenant_id、user_id、turn_id 必须显式传递；新保存操作使用 UUID 字符串。
- 保存与同步按顺序等待；不承诺非阻塞回复、两秒写入或十秒同步。
- saved 依据有效提交回执及真值核验，已可检索依据当前 ID 的实际检索结果。
- 跳过不是失败，零候选不是成功，部分提交不能展示为全部成功。
- session 在 finally 关闭；不自动重试整次写入、不打印凭据或全文。
- 优先在宿主适配现有核心接口，不扩大为 Memory V2 内部重构。

## 2. 文件与接口

下列文件是实施时新增或修改的交付物，不表示当前已经存在。

| 文件（相对仓库根目录） | 操作与职责 |
|------------------------|------------|
| papermind-host/papermind/memory_writer.py | 新增：WriteResult、save_turn_to_memory、事实写入装配与结果归一化 |
| papermind-host/papermind/outbox_sync.py | 新增：SyncResult、sync_outbox_batch、单批消费及资源释放 |
| papermind-host/examples/simple_chat.py | 修改：确认保存、同步、提问与身份参数；复用现有会话和模型客户端 |
| papermind-host/tests/test_memory_writer.py | 新增：确认、门控、回执、失败及资源释放的离线测试 |
| papermind-host/tests/test_outbox_sync.py | 新增：同步统计、空批次、异常、部分失败和资源释放测试 |
| papermind-host/scripts/verify_phase13.py | 新增：真实服务验收、跨进程子任务和结果报告 |
| papermind-host/README.md | 修改：安装与运行、身份参数、显式同步步骤、限制 |
| papermind-host/papermind/memory_retrieval.py | 仅在读写联调出现接口不匹配时做必要适配，不重新实现检索 |

公共结果与签名如下；implementation 使用这些名称，不再返回只有 success 的布尔结果：

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class WriteResult:
    status: Literal["saved", "partial", "skipped", "no_memory", "failed"]
    speech_act: str | None
    memory_ids: list[str]
    turn_id: str
    message: str
    error_code: str | None = None

@dataclass
class SyncResult:
    status: Literal["completed", "failed"]
    done: int
    failed: int
    dead: int
    message: str
```

- `async save_turn_to_memory(user_text: str, tenant_id: str, user_id: str, turn_id: str, *, confirmed: bool = False) -> WriteResult`
- `async sync_outbox_batch(batch_size: int = 100) -> SyncResult`
- 写入模块内部 `_fact_writer()` 是资源上下文；`_normalize_write_result(raw, turn_id)` 将核心结果按需求第 4 节归一化，随后核验提交 ID 对应的 MySQL 真值。它不负责宣称索引可见。
- 同步模块内部 `_process_batch(batch_size)` 在同一个线程内创建、使用、关闭 worker 的数据库 session；返回核心 done/failed/dead 统计。

## 3. 七小时预算

| 任务 | 预算 | 规格覆盖 |
|------|------|----------|
| A：依赖与契约核对 | 1 小时 | R1、R6、R8 |
| B：事实写入、门控、状态反馈与离线测试 | 3 小时 | R1、R2、R3、R7、R8 |
| C：Outbox 单批同步与离线测试 | 1 小时 | R4、R7、R8 |
| D：示例入口与真实读写联调 | 1 小时 | R5、R6 |
| E：阻塞问题修复和复测 | 1 小时 | R1–R8 |

## 4. Task A：确认可复用基础（1 小时）

**读取**：现有 config.py、llm_client.py、session.py、memory_retrieval.py；核心 writer.py、contracts.py、speech_act.py、llm_gate.py、outbox.py。

- [ ] 使用同一个已有 Python 环境检查依赖与基础服务，不重装或替换已完成模块。命令在仓库根目录执行：

```powershell
docker compose -f memoryV2-local-env/compose.yaml ps
python memoryV2-local-env/verify_environment.py
```

- [ ] 核对写入模型需要 structured_extract 三元组接口。复用 DashScopeClient，不能将仅有 chat 的宿主 LLMClient 直接当作抽取器客户端。
- [ ] 核对核心返回 V2WriteResult、Fact 提交为 CommitReceipt、Speech Act 为小写枚举；不沿用旧文档的 QUERY / COMMIT / DECLARE 假设。
- [ ] 设置核心导入路径，确认未覆盖已有 PYTHONPATH；实施与测试命令从 papermind-host 运行。例：

```powershell
$phase13CorePath = (Resolve-Path ../memoryV2-core).Path
if ([string]::IsNullOrEmpty($env:PYTHONPATH)) {
    $env:PYTHONPATH = $phase13CorePath
} else {
    $env:PYTHONPATH = $phase13CorePath + [IO.Path]::PathSeparator + $env:PYTHONPATH
}
```

**通过条件**：明确核心可导入、服务可连接、抽取与索引使用同一套有效配置；故障如实记录，不把规格改写视为业务已实现。

## 5. Task B：事实写入封装（3 小时）

**新增**：memory_writer.py、test_memory_writer.py。消费核心 WriteResult 契约，向 Task D 提供 save_turn_to_memory。

- [ ] 先写有意义的失败测试：未确认和纯查询不进入抽取/落库；有效回执才 saved；零候选及门控拒绝为 no_memory；抽取错误与数据库异常为 failed；已有提交同时有错误为 partial；任何路径都关闭 session。
- [ ] 用 pytest 运行新增测试，确认最初失败源于缺失行为，再实现宿主包装。结果测试可直接构造核心契约，而不联网：

```python
from datetime import datetime, timezone
from server.memory_v2.contracts import V2WriteResult, LaneOutcome
from papermind.memory_writer import _normalize_write_result

def test_parse_error_is_failure_not_empty_memory():
    raw = V2WriteResult(
        user_id="user_A", turn_id="test-parse", tenant_id="tenant_A",
        occurred_at=datetime.now(timezone.utc), speech_act="assert",
        lane_outcomes=[LaneOutcome(
            lane="semantic", status="parse_error", error_code="PARSE_ERROR"
        )],
        commits=[], v2_write_success=False, failed_lanes=["semantic"],
    )
    result = _normalize_write_result(raw, "test-parse")
    assert result.status == "failed"
    assert result.memory_ids == []
```

- [ ] 使用事实资源上下文装配现有组件，不调用全 Lane 工厂再假定它只有事实功能：

```python
from contextlib import contextmanager
from server.database.connection_pool import db_pool
from server.memory_v2.llm_gate import DashScopeClient
from server.memory_v2.write.writer import MemoryWriter
from server.memory_v2.write.extractors.semantic import SemanticExtractor
from server.memory_v2.write.gate import MemoryGate
from server.memory_v2.write.router import MemoryDispatcher
from server.memory_v2.store.fact_store import FactStore

@contextmanager
def _fact_writer():
    session = db_pool.sync_session_factory()
    try:
        yield MemoryWriter(
            extractors={"semantic": SemanticExtractor(DashScopeClient())},
            gate=MemoryGate(),
            dispatcher=MemoryDispatcher(fact_store=FactStore(session)),
            llm_client=None,
        )
    finally:
        session.close()
```

- [ ] 在进入上下文前检查输入、confirmed 与实际 Speech Act。允许 assert/unknown 交给核心继续判断；其他类型按需求跳过。传入原始笔记与显式身份、UUID turn_id，await writer.write_turn。
- [ ] 归一化核心 lane_outcomes、failed_lanes 和有效 CommitReceipt，按需求表判定五种状态。保留已提交 ID；异常后核验能确认的记录，不宣称整个操作自动回滚。MySQL 查询按 scope 和 source_turn_id 过滤，不能读取其他用户事实。
- [ ] 核验核心返回中的 outbox_ids=[] 或 index_visible=None 不能当成“不需同步”；保存后只提示待同步。
- [ ] 示例与验收脚本启动时抑制核心记忆命名空间的原始日志；当前核心审计与抽取异常可能包含笔记内容。宿主另用 papermind 命名空间记录状态、数量、耗时与脱敏错误码，不将异常原文直接转发给用户。最小配置如下；核对是否存在子 logger 自有输出 handler，若有则一并移除原始输出：

```python
import logging

def _configure_core_logging() -> None:
    core_logger = logging.getLogger("server.memory_v2")
    core_logger.handlers = [logging.NullHandler()]
    core_logger.propagate = False
```

- [ ] 用带可识别笔记文本的成功路径和抽取异常路径捕获实际输出，确认全文及凭据不出现，但宿主状态、数量、耗时与错误码仍可核查；该检查与现有写入状态测试一起完成，不建设新的日志系统。
- [ ] 运行 writer 单测与已完成宿主的离线回归，确认原有功能未受影响：

```powershell
python -m pytest tests/test_memory_writer.py -q
python -m pytest tests/test_config.py tests/test_session.py tests/test_llm_client.py tests/test_memory_retrieval.py -q
```

**通过条件**：R1、R2、R3、R7、R8 的行为都有可读测试结果；无有效提交不能显示保存成功。

## 6. Task C：显式同步一批（1 小时）

**新增**：outbox_sync.py、test_outbox_sync.py。向 Task D 提供 sync_outbox_batch。

- [ ] 先测试 done/failed/dead 透传、全零空批次、批次异常、输入 batch_size 非正数和 session 释放；部分失败必须返回 status=failed，同时保留 done。
- [ ] 同步函数在线程内持有并释放 session，直接使用 OutboxWorker.process_pending；不调用吞异常、仅打印日志的 process_batch 包装器：

```python
from server.database.connection_pool import db_pool
from server.memory_v2.retrieve.index_v2 import IndexV2
from server.memory_v2.retrieve.embedder import RealEmbedder
from server.memory_v2.store.outbox import OutboxWorker

def _process_batch(batch_size: int) -> dict[str, int]:
    session = db_pool.sync_session_factory()
    try:
        index = IndexV2()
        index.create_collection_if_not_exists()
        embedder = RealEmbedder()
        embedder.validate_dimension(index.embedding_dim)
        return OutboxWorker(session, index, embedder).process_pending(batch_size)
    finally:
        session.close()
```

- [ ] sync_outbox_batch 使用 asyncio.to_thread 调用上述函数；捕获异常为失败结果，failed 或 dead 大于零时同样反馈失败/部分完成，不抹掉成功数量。同步线程使用新 session，不复用写入线程的 session。
- [ ] 保存与同步分开，复用核心退避，不改 next_retry_at 来强制通过测试；不增加自动重试整个写入。
- [ ] 运行同步测试，确认空批次不触发“当前笔记已可检索”提示：

```powershell
python -m pytest tests/test_outbox_sync.py -q
```

**通过条件**：同步返回真实统计，异常路径释放 session；MySQL 提交状态与索引状态不混淆。

## 7. Task D：示例入口与真实联调（1 小时）

**修改**：examples/simple_chat.py、README.md。**新增**：scripts/verify_phase13.py。

- [ ] 示例用 argparse 接收 --tenant、--user；支持 save、sync、ask、quit。save 获取原始笔记后再次确认，调用保存接口；ask 只调用已有检索和模型问答。操作取消不生成保存请求。
- [ ] 每次新保存生成独立标识；不要复用进程重启归零的会话轮次：

```python
from uuid import uuid4
from papermind.memory_writer import save_turn_to_memory

async def save_confirmed_note(text: str, tenant_id: str, user_id: str):
    return await save_turn_to_memory(
        text, tenant_id, user_id, uuid4().hex, confirmed=True
    )
```

- [ ] 验收脚本支持 --mode all/write/recall、--manifest、--report。all 创建独立身份与运行标记，通过 subprocess 启动 write 与 recall 两个子进程，共用 MySQL/Qdrant，仅通过 manifest 传递 scope、turn_id、memory_ids、查询与运行标记，不传递旧对话历史或答案。
- [ ] write 子进程保存明确事实并核对 MySQL/Outbox；显式同步，核验当前 ID 对应的 Outbox 和真实向量结果。recall 子进程复用 Phase 1.2 查询，核对证据 ID、运行标记与答案；执行用户/租户隔离和无证据用例。
- [ ] 联调若出现检索类名、embedding 适配或 EvidenceItem 内容字段不匹配，只修必要宿主适配，保留 Phase 1.2 的已完成状态。具体检验步骤按 validation.md 执行。
- [ ] README 补充示例运行方式、确认保存与同步步骤、后续验收命令及五种状态解释。命令对应实际实现后才标记可用：

```powershell
python examples/simple_chat.py --tenant tenant_A --user user_A
python scripts/verify_phase13.py --mode all --manifest .phase13-manifest.json --report .phase13-report.json
```

**通过条件**：完成一次真实落库、同步、跨进程召回与身份隔离，关键检查返回可核验结果。

## 8. Task E：修复与最终复测（1 小时）

- [ ] 排查真实失败日志，按失败点修复，不扩展非必要功能。
- [ ] 运行本阶段离线测试和全流程验收；真实服务缺失必须非零退出，不能通过跳过关键测试过关：

```powershell
python -m pytest tests/ -q
python scripts/verify_phase13.py --mode all --manifest .phase13-manifest.json --report .phase13-report.json
```

- [ ] 对照 requirements.md 的 R1–R8，保存真实报告：命令、通过/失败/跳过、耗时、Memory ID、阻塞项。排期表不作为验证结果。
- [ ] 仅所有 P0 验收通过后进入 Day 2；超时先删辅助展示，继续核心排错，Day 3 的录屏交付时间仍保留。

## 9. 执行状态

- [ ] A：环境与契约确认。
- [ ] B：事实写入与状态测试。
- [ ] C：单批同步与状态测试。
- [ ] D：示例与真实联调。
- [ ] E：修复、复测与阶段验收记录。

当前勾选项保持为空，表示尚未执行本计划；不自动提交 Git，也不将规格改写计为业务实现完成。
