# Phase 1.3 快速启动指南

## 🚀 快速开始（3 步）

### 步骤 1: 填入 API Key

编辑 `memoryV2-core/.env` 文件，填入您的 DashScope API Key：

```bash
DASHSCOPE_API_KEY=sk-your-actual-api-key-here
```

**获取 API Key**：https://dashscope.console.aliyun.com/apiKey

### 步骤 2: 确认服务运行

```bash
cd memoryV2-local-env
docker compose ps
```

确保 MySQL 和 Qdrant 都是 `Up` 状态。如果未运行：

```bash
docker compose up -d
```

### 步骤 3: 运行验收测试

```bash
cd papermind-host/examples
python verify_phase13.py
```

预期输出：
```
======================================================================
Phase 1.3 验收测试
======================================================================
运行: 核心闭环...
  [PASS] | 写入-同步-检索闭环
      写入 1 条 -> 同步 1 条 -> 检索成功

运行: 租户隔离...
  [PASS] | 租户隔离
      租户A可检索自己的记忆，租户B无法检索租户A的记忆

...

======================================================================
测试完成: 5/5 通过
======================================================================
[PASS] 所有测试通过！Phase 1.3 验收成功。
```

---

## 🧪 其他测试选项

### 单元测试（不需要 API key）

```bash
cd papermind-host
python -m pytest tests/ -v
```

### 交互式测试

```bash
cd papermind-host/examples
python simple_chat.py --tenant tenant_demo --user alice
```

**可用命令**：
- `save` - 保存论文笔记
- `sync` - 同步 Outbox 到 Qdrant
- `ask` - 提问并检索历史记忆
- `quit` - 退出

**示例流程**：
1. 输入 `save` → 输入笔记 → 确认
2. 输入 `sync` → 等待同步完成
3. 输入 `ask` → 输入问题 → 查看回答

---

## 📋 验收检查清单

运行完 `verify_phase13.py` 后，确认以下项目：

- [ ] ✅ 核心闭环测试通过（写入-同步-检索）
- [ ] ✅ 租户隔离测试通过
- [ ] ✅ 未确认跳过测试通过
- [ ] ✅ 查询跳过测试通过
- [ ] ✅ 空输入失败测试通过
- [ ] ✅ 测试完成显示 `5/5 通过`

---

## 🔧 故障排查

### 问题 1: API Key 错误

**错误信息**：
```
openai.OpenAIError: Missing credentials
```

**解决方法**：
1. 检查 `memoryV2-core/.env` 文件是否存在
2. 确认 `DASHSCOPE_API_KEY` 已填入且不为空
3. 重新运行测试

### 问题 2: 数据库连接失败

**错误信息**：
```
Can't connect to MySQL server
```

**解决方法**：
```bash
cd memoryV2-local-env
docker compose ps        # 检查状态
docker compose up -d     # 启动服务
docker compose logs mysql  # 查看日志
```

### 问题 3: Qdrant 连接失败

**错误信息**：
```
qdrant_client.exceptions.ResponseHandlingException
```

**解决方法**：
```bash
cd memoryV2-local-env
docker compose restart qdrant
docker compose logs qdrant
```

---

## 📊 当前完成状态

✅ **核心实现**：所有模块已实现  
✅ **单元测试**：63/63 通过  
⏳ **端到端测试**：待填入 API key 后执行  

---

## 📞 需要帮助？

如有问题，请检查：
1. `examples/README_phase13.md` - 详细配置说明
2. `specs/.../implementation-summary.md` - 完整实施总结
3. Docker 服务日志：`docker compose logs`

---

**祝测试顺利！🎉**
