# Plan — Phase 1.2: Memory V2 检索链路

## 任务组概览

本计划将 Phase 1.2 拆解为 4 个任务组，每组聚焦一个独立的交付物。

## 任务组 1：Memory V2 依赖和配置

**目标**：确保 Memory V2 核心模块可被导入，配置检索相关参数

**任务清单**：
1. 验证 Memory V2 核心模块导入
   ```python
   # 测试是否可以导入关键模块
   from memoryV2_core.retrieval import assemble_evidence_pack
   from memoryV2_core.models import EvidencePack
   ```

2. 在 `config.py` 中添加检索相关配置
   ```python
   class Config(BaseSettings):
       # 现有配置...
       
       # Memory V2 检索配置
       memory_retrieval_limit: int = 5  # 默认返回前 5 条证据
       memory_retrieval_timeout: float = 1.0  # 检索超时（秒）
       memory_enable_reranker: bool = True  # 是否启用 Reranker
   ```

3. 更新 `.env.example` 添加新配置项
   ```bash
   # Memory V2 检索配置
   MEMORY_RETRIEVAL_LIMIT=5
   MEMORY_RETRIEVAL_TIMEOUT=1.0
   MEMORY_ENABLE_RERANKER=true
   ```

4. 验证 MySQL 和 Qdrant 连接
   - 编写简单脚本测试 Memory V2 数据库连接
   - 确认可以正常查询 facts 表和 Qdrant collection

**产出**：
- 配置模块支持 Memory V2 检索参数
- 依赖验证脚本确认环境可用

**验收**：
- `from memoryV2_core.retrieval import assemble_evidence_pack` 无报错
- 配置加载测试通过

---

## 任务组 2：实现 memory_retrieval.py 核心逻辑

**目标**：封装 `assemble_evidence_pack` 调用，实现租户隔离的检索

**任务清单**：
1. 创建 `papermind/memory_retrieval.py` 文件

2. 实现核心检索函数
   ```python
   from memoryV2_core.retrieval import assemble_evidence_pack
   from memoryV2_core.models import EvidencePack
   from typing import Optional
   
   async def retrieve_memory_context(
       query: str,
       tenant_id: str,
       user_id: str,
       limit: int = 5
   ) -> str:
       """
       检索用户长期记忆并格式化为 prompt 注入文本
       
       Args:
           query: 用户查询文本
           tenant_id: 租户 ID（用于隔离）
           user_id: 用户 ID（用于隔离）
           limit: 返回的最大证据数量
       
       Returns:
           格式化的证据文本，如果无相关记忆则返回明确提示
       """
       # 1. 构造 Hard Filter（租户+用户隔离）
       hard_filters = {
           "tenant_id": tenant_id,
           "user_id": user_id
       }
       
       # 2. 调用 Memory V2 检索
       evidence_pack: Optional[EvidencePack] = await assemble_evidence_pack(
           query=query,
           hard_filters=hard_filters,
           top_k=limit,
           enable_reranker=True
       )
       
       # 3. 格式化证据（见任务组 3）
       return format_evidence_pack(evidence_pack)
   ```

3. 实现错误处理和降级逻辑
   ```python
   try:
       evidence_pack = await assemble_evidence_pack(...)
   except Exception as e:
       # 记录错误日志
       logger.error(f"Memory retrieval failed: {e}")
       # 降级：返回无记忆提示
       return "[记忆检索失败，将基于当前对话回答]"
   ```

4. 添加超时控制
   ```python
   import asyncio
   
   try:
       evidence_pack = await asyncio.wait_for(
           assemble_evidence_pack(...),
           timeout=config.memory_retrieval_timeout
       )
   except asyncio.TimeoutError:
       logger.warning("Memory retrieval timeout")
       return "[记忆检索超时]"
   ```

**产出**：
- `memory_retrieval.py` 实现核心检索逻辑
- 错误处理和降级策略完整

**验收**：
- 可以成功调用 `assemble_evidence_pack`
- 租户/用户 Hard Filter 生效

---

## 任务组 3：证据格式化和 Prompt 注入

**目标**：将检索到的证据格式化为易读的 prompt 注入文本

**任务清单**：
1. 实现证据格式化函数
   ```python
   def format_evidence_pack(evidence_pack: Optional[EvidencePack]) -> str:
       """
       将 EvidencePack 格式化为 prompt 注入文本
       
       Args:
           evidence_pack: Memory V2 返回的证据包，可能为 None
       
       Returns:
           格式化的证据文本
       """
       if not evidence_pack or not evidence_pack.evidences:
           return "[记忆检索结果]：未找到相关记忆，请基于当前对话回答。"
       
       # 构造结构化证据文本
       lines = ["[记忆检索结果]：找到以下相关记忆：\n"]
       
       for idx, evidence in enumerate(evidence_pack.evidences, start=1):
           lines.append(f"{idx}. {evidence.fact_text}")
           lines.append(f"   来源：Fact ID {evidence.fact_id}")
           lines.append(f"   时间：{evidence.created_at.strftime('%Y-%m-%d %H:%M')}")
           lines.append(f"   置信度：{evidence.confidence:.2f}\n")
       
       return "\n".join(lines)
   ```

2. 测试不同场景的格式化输出
   - 有多条证据
   - 只有一条证据
   - 无证据

3. 在 `llm_client.py` 中集成检索链路
   ```python
   async def chat_with_memory(
       self,
       user_message: str,
       tenant_id: str,
       user_id: str,
       **kwargs
   ) -> str:
       """支持记忆检索的对话接口"""
       # 1. 检索记忆
       memory_context = await retrieve_memory_context(
           query=user_message,
           tenant_id=tenant_id,
           user_id=user_id
       )
       
       # 2. 构造包含记忆的 prompt
       messages = [
           {"role": "system", "content": memory_context},
           {"role": "user", "content": user_message}
       ]
       
       # 3. 调用 LLM
       return await self.chat(messages, **kwargs)
   ```

**产出**：
- 证据格式化函数完整实现
- LLM 客户端集成检索链路

**验收**：
- 证据格式清晰易读
- prompt 正确包含检索结果

---

## 任务组 4：测试和验证

**目标**：编写单元测试和集成测试，验证检索链路正确性

**任务清单**：
1. 编写 Mock 测试（`tests/test_memory_retrieval.py`）
   ```python
   from unittest.mock import AsyncMock, patch
   import pytest
   
   @pytest.mark.asyncio
   async def test_retrieve_with_results():
       """测试：有相关记忆时返回格式化证据"""
       # Mock assemble_evidence_pack 返回值
       mock_evidence = EvidencePack(evidences=[
           Evidence(fact_id=1, fact_text="我的研究方向是计算机视觉", confidence=0.95)
       ])
       
       with patch('papermind.memory_retrieval.assemble_evidence_pack', 
                  new=AsyncMock(return_value=mock_evidence)):
           result = await retrieve_memory_context(
               query="我的研究方向是什么",
               tenant_id="tenant_1",
               user_id="alice"
           )
           
           assert "我的研究方向是计算机视觉" in result
           assert "置信度" in result
   
   @pytest.mark.asyncio
   async def test_retrieve_no_results():
       """测试：无相关记忆时返回明确提示"""
       with patch('papermind.memory_retrieval.assemble_evidence_pack', 
                  new=AsyncMock(return_value=None)):
           result = await retrieve_memory_context(
               query="我的研究方向是什么",
               tenant_id="tenant_1",
               user_id="bob"
           )
           
           assert "未找到相关记忆" in result
   
   @pytest.mark.asyncio
   async def test_retrieve_timeout():
       """测试：检索超时时返回降级提示"""
       with patch('papermind.memory_retrieval.assemble_evidence_pack', 
                  new=AsyncMock(side_effect=asyncio.TimeoutError)):
           result = await retrieve_memory_context(
               query="测试查询",
               tenant_id="tenant_1",
               user_id="alice"
           )
           
           assert "超时" in result or "失败" in result
   ```

2. 编写租户隔离测试
   ```python
   @pytest.mark.asyncio
   async def test_tenant_isolation():
       """测试：租户隔离生效，不同租户看不到彼此的记忆"""
       # 需要真实数据库连接（或精细的 Mock）
       # 验证 hard_filters 参数正确传递
       pass
   ```

3. 编写集成测试（可选，需要真实数据库）
   ```python
   @pytest.mark.integration
   @pytest.mark.asyncio
   async def test_end_to_end_retrieval():
       """端到端测试：写入记忆 → 检索 → 验证结果"""
       # 1. 写入测试记忆到 MySQL + Qdrant
       # 2. 调用 retrieve_memory_context
       # 3. 验证检索到正确的记忆
       pass
   ```

4. 更新 README.md 添加使用示例
   ```python
   # 示例：使用记忆检索的对话
   from papermind.llm_client import LLMClient
   from papermind.memory_retrieval import retrieve_memory_context
   
   async def chat_with_memory_example():
       # 1. 检索记忆
       memory_context = await retrieve_memory_context(
           query="我的研究方向是什么",
           tenant_id="default",
           user_id="alice"
       )
       print(f"检索到的记忆：\n{memory_context}")
       
       # 2. 调用 LLM
       client = LLMClient(config)
       messages = [
           {"role": "system", "content": memory_context},
           {"role": "user", "content": "我的研究方向是什么"}
       ]
       reply = await client.chat(messages)
       print(f"AI 回复：{reply}")
   ```

**产出**：
- 单元测试覆盖核心逻辑（Mock）
- 租户隔离测试验证 Hard Filter
- README 包含使用示例

**验收**：
- `pytest tests/test_memory_retrieval.py` 通过
- 测试覆盖率 > 80%

---

## 任务执行顺序

建议按以下顺序执行：
1. **任务组 1**（依赖和配置）→ **任务组 2**（核心检索逻辑）
2. **任务组 3**（证据格式化）→ **任务组 4**（测试和验证）

## 关键路径

**最小可交付路径**：
- 任务组 1 + 任务组 2 + 任务组 3（核心功能）

**完整交付路径**：
- 任务组 1 + 任务组 2 + 任务组 3 + 任务组 4（包含完整测试）

## 时间分配建议

| 任务组 | 预估时间 | 优先级 |
|--------|---------|--------|
| 任务组 1：依赖和配置 | 0.5h | P0 |
| 任务组 2：核心检索逻辑 | 2h | P0 |
| 任务组 3：证据格式化和注入 | 1.5h | P0 |
| 任务组 4：测试和验证 | 2h | P0 |
| **总计** | **6h** | - |

**说明**：所有任务组均为 P0，确保检索链路完整可用

## 技术决策记录

| 决策点 | 选项 | 最终选择 | 理由 |
|--------|------|---------|------|
| 检索接口 | 同步 / 异步 | 异步（async/await） | 与 Phase 1.1 保持一致，支持并发 |
| 证据格式 | JSON / Markdown / 纯文本 | 纯文本（结构化） | 易读，适合注入 prompt |
| 降级策略 | 抛出异常 / 返回空 / 返回提示 | 返回明确提示 | 不阻断 LLM 回复，用户体验更好 |
| 测试策略 | Mock / 集成 / 端到端 | Mock + 租户隔离测试 | Mock 快速验证，隔离测试确保核心功能 |

## 风险缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Memory V2 API 变更 | 检索调用失败 | 参考 Memory V2 最新文档，测试常见场景 |
| 检索性能问题 | 用户体验差 | 设置超时控制，实现降级策略 |
| 租户隔离失效 | 数据泄露 | 编写专门的隔离测试，严格验证 Hard Filter |
| 证据格式不清晰 | LLM 理解困难 | 多次迭代格式，测试不同 prompt 模板 |

## 依赖和前置条件

- Phase 1.1（智能体宿主模块）已完成并合并
- Memory V2 核心模块可正常导入
- MySQL 和 Qdrant 服务运行正常
- 有测试数据可用于验证检索功能

## 成功标志

- 可以成功检索用户长期记忆并注入 prompt
- 租户和用户隔离生效（Hard Filter 正常工作）
- 无证据时有明确的 prompt 提示
- 所有单元测试通过，覆盖率 > 80%
- 代码通过类型检查（mypy --strict）
