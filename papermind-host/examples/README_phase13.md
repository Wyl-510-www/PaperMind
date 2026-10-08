# Phase 1.3 验收测试说明

## 环境要求

Phase 1.3 验收测试需要以下环境：

1. **MySQL 数据库**：用于存储记忆事实
2. **Qdrant 向量数据库**：用于向量索引
3. **DashScope API Key**：用于 LLM 调用（事实抽取和 Embedding）

## 配置步骤

### 1. 启动 Docker 服务

```bash
cd memoryV2-local-env
docker compose up -d
```

这会启动：
- MySQL (端口 8700)
- Qdrant (端口 8701)

### 2. 配置 API Key

编辑 `memoryV2-core/.env` 文件，添加：

```bash
DASHSCOPE_API_KEY=sk-your-api-key-here
```

或者从 `memoryV2-local-env/.env` 复制现有配置：

```bash
cp memoryV2-local-env/.env memoryV2-core/.env
```

### 3. 验证环境

```bash
cd memoryV2-local-env
python verify_environment.py
```

确保所有检查项通过。

## 运行验收测试

### 自动化验收测试

```bash
cd papermind-host/examples
python verify_phase13.py
```

测试覆盖：
- ✓ 写入-同步-检索闭环
- ✓ 租户隔离
- ✓ 未确认输入跳过
- ✓ 查询请求跳过
- ✓ 空输入失败处理

### 交互式手动测试

```bash
cd papermind-host/examples
python simple_chat.py --tenant tenant_demo --user user_alice
```

可用命令：
- `save` - 保存论文笔记
- `sync` - 同步 Outbox
- `ask` - 提问并检索
- `quit` - 退出

#### 示例流程

1. **保存笔记**：
   ```
   请输入命令 (save/sync/ask/quit): save
   笔记内容: 我的论文《Transformer架构研究》的阅读结论是：多头注意力机制显著提升了模型的表达能力。
   确认 (y/n): y
   ```

2. **同步 Outbox**：
   ```
   请输入命令 (save/sync/ask/quit): sync
   批次大小 (默认 100): 
   ```

3. **检索提问**：
   ```
   请输入命令 (save/sync/ask/quit): ask
   请输入问题: 多头注意力有什么作用？
   ```

## 单元测试

运行所有单元测试（不需要真实环境）：

```bash
cd papermind-host
python -m pytest tests/ -v
```

仅运行 Phase 1.3 相关测试：

```bash
python -m pytest tests/test_memory_writer.py tests/test_outbox_sync.py -v
```

## 故障排查

### API Key 未配置

**错误**：
```
openai.OpenAIError: Missing credentials
```

**解决**：检查 `.env` 文件是否正确配置 `DASHSCOPE_API_KEY`。

### 数据库连接失败

**错误**：
```
sqlalchemy.exc.OperationalError: Can't connect to MySQL server
```

**解决**：
```bash
cd memoryV2-local-env
docker compose ps  # 检查服务状态
docker compose up -d  # 启动服务
```

### Qdrant 连接失败

**错误**：
```
qdrant_client.exceptions.ResponseHandlingException
```

**解决**：检查 Qdrant 服务是否运行，端口 8701 是否可访问。

### 编码错误（Windows）

**错误**：
```
UnicodeEncodeError: 'gbk' codec can't encode character
```

**解决**：已在代码中修复，使用 ASCII 兼容字符代替特殊 Unicode 符号。

## 验收标准

Phase 1.3 验收通过条件：

1. ✓ 所有单元测试通过（63 passed）
2. ✓ 自动化验收测试全部通过（5/5）
3. ✓ 手动交互测试：保存-同步-检索流程正常
4. ✓ 租户隔离验证通过
5. ✓ 失败场景正确处理

## 下一步

Phase 1.3 完成后，进入 Phase 1.4：
- 实现自动化 Outbox 后台消费
- 优化同步延迟
- 添加监控指标
