# Roadmap — PaperMind

## 实施原则

- **小步快跑**：每个 Phase 独立可演示，持续交付价值
- **技术优先**：优先展示 Memory V2 核心能力，UI 为辅
- **功能完整**：每个阶段完成后都是可用的最小完整产品
- **课程友好**：每个 Phase 有明确的验收标准和 Demo 脚本

## Phase 0：环境验证（已完成）

**时间**：已完成

**目标**：确认 Memory V2 核心可用

**任务清单**：
- [x] MySQL 和 Qdrant 本地环境启动
- [x] 数据库表和 Qdrant collection 初始化
- [x] Memory V2 核心模块导入验证
- [x] 提取边界测试通过

**验收**：
- `docker compose ps` 显示服务运行
- `verify_environment.py` 无报错
- `pytest tests/test_extraction_boundary.py` 通过

---

## Phase 1：最小命令行 Demo（3-5 天）

**目标**：构建可运行的智能体宿主层，接通 Memory V2 读写链路

### 1.1 创建智能体宿主模块（1 天）

**任务**：
- 新建 `papermind-host/` 目录结构
- 实现模型客户端封装（DashScope OpenAI 兼容接口）
- 实现会话状态管理（内存 dict，记录 tenant_id, user_id, turn_id）
- 配置环境变量加载（python-dotenv）

**产出**：
```text
papermind-host/
├── papermind/
│   ├── __init__.py
│   ├── config.py          # 环境变量和配置
│   ├── llm_client.py      # 模型客户端封装
│   └── session.py         # 会话状态管理
├── pyproject.toml
└── .env.example
```

**验收**：
- 可以成功调用 Qwen 模型生成回复
- 会话状态正确维护 tenant_id, user_id, turn_id

### 1.2 接入 Memory V2 检索链路（1 天）

**任务**：
- 封装 `assemble_evidence_pack` 调用
- 将检索到的证据注入 prompt
- 实现"无证据时明确说明未知"的提示词模板

**产出**：
```python
# papermind/memory_retrieval.py
def retrieve_memory_context(
    query: str,
    tenant_id: str,
    user_id: str,
    limit: int = 5
) -> str:
    """返回格式化的记忆上下文，用于注入 prompt"""
    pass
```

**验收**：
- 用户提问时能检索到相关历史记忆
- prompt 中正确包含证据来源和置信度
- 无证据时 AI 回复"我没有找到相关记忆"

### 1.3 接入 Memory V2 写入链路（1 天）

**任务**：
- 封装 `create_memory_writer` 和 `write_turn` 调用
- 实现 Speech Act 门控逻辑
- 处理写入失败时的降级策略（写入失败不阻断回答）

**产出**：
```python
# papermind/memory_writer.py
async def save_turn_to_memory(
    user_text: str,
    tenant_id: str,
    user_id: str,
    turn_id: str
) -> bool:
    """保存用户陈述到长期记忆，返回是否成功"""
    pass
```

**验收**：
- 陈述型消息被正确写入 MySQL
- 查询型消息被 Speech Act 门控拦截
- Outbox 同步后 Qdrant 可检索到新记忆

### 1.4 CLI 命令行界面（1 天）

**任务**：
- 使用 Click 构建命令行工具
- 使用 Rich 美化输出（彩色文本、表格、进度条）
- 支持多轮对话循环
- 显示记忆检索结果和写入状态

**产出**：
```bash
# 命令示例
papermind chat --user alice --tenant default
papermind memory list --user alice
papermind memory search "论文阅读" --user alice
```

**验收**：
- 可以进行流畅的多轮对话
- 每轮显示检索到的记忆证据
- 显示是否成功写入新记忆

### 1.5 端到端测试和 Demo 脚本（0.5 天）

**任务**：
- 编写多租户隔离测试脚本
- 编写跨会话记忆检索测试
- 准备课程展示 Demo 脚本（包含论文阅读和任务规划场景）

**Demo 脚本示例**：
```text
场景 1：论文阅读记忆
用户："我读了一篇关于 Transformer 的论文，核心创新是自注意力机制"
AI："已记录。这是你提到的第一篇关于 Transformer 的论文。"

（关闭会话，重新启动）

用户："我之前读过哪些关于 Transformer 的论文？"
AI："根据记忆，你提到过一篇关于 Transformer 的论文，核心创新是自注意力机制。"

场景 2：租户隔离
用户 Alice："我的研究方向是计算机视觉"
用户 Bob："我的研究方向是自然语言处理"

Alice 查询时不会看到 Bob 的记忆，反之亦然。
```

**验收**：
- 同一用户跨会话可以回忆历史信息
- 不同租户/用户之间记忆隔离
- Demo 脚本可以在 5 分钟内完整演示

---

## Phase 2：Web 界面和文档上传（2-3 周）

**目标**：提供完整的用户界面和 PDF 论文上传能力

### 2.1 FastAPI 后端 API（1 周）

**任务**：
- 实现 RESTful API（对话、记忆管理）
- WebSocket 支持流式回复
- 文件上传接口（PDF/Markdown）
- OpenAPI 文档自动生成

**核心接口**：
```text
POST   /api/v1/chat              # 发送消息
GET    /api/v1/memory            # 查询记忆
DELETE /api/v1/memory/{id}       # 删除记忆
POST   /api/v1/documents/upload  # 上传文档
GET    /api/v1/documents         # 文档列表
```

### 2.2 React 前端界面（1-2 周）

**页面结构**：
```text
/login          # 用户登录（模拟多租户）
/chat           # 对话界面
  ├─ 左侧：对话历史
  ├─ 中间：消息流
  └─ 右侧：当前检索到的记忆
/memory         # 记忆管理
  ├─ 记忆列表
  ├─ 筛选和搜索
  └─ 编辑/删除操作
/documents      # 文档管理
  ├─ 上传 PDF
  └─ 文档列表
```

**技术选型**：
- React 18 + TypeScript
- Ant Design（快速开发）或 Shadcn UI（现代风格）
- React Query（服务端状态管理）
- Vite（构建工具）

### 2.3 PDF 解析和分块（可选）

**任务**：
- 使用 PyMuPDF 或 pdfplumber 提取文本
- 使用 LangChain Text Splitters 分块
- 分块向量化并存入 Qdrant（独立 collection）
- 检索时同时查询记忆和文档分块

**注意**：此功能为加分项，MVP 可以仅支持手动粘贴论文摘要

---

## Phase 3：功能增强（可选，时间充裕时）

### 3.1 实验记录工作流
- 结构化实验模板（假设、步骤、结果、结论）
- 实验时间线可视化
- 实验对比和版本管理

### 3.2 研究任务规划
- 待办事项管理（类似 TODO list）
- 任务优先级和截止日期
- 任务完成度统计

### 3.3 记忆可视化
- 知识图谱展示（实体和关系）
- 记忆时间线
- 记忆置信度分布

### 3.4 多模型支持
- 切换不同 LLM（GPT-4, Claude, Qwen）
- 模型回复对比
- 成本和延迟统计

---

## Phase 4：生产优化（不在课程作业范围）

### 4.1 性能优化
- Redis 会话缓存
- Qdrant 向量索引调优
- API 请求限流和缓存

### 4.2 安全加固
- JWT 身份认证
- 租户级权限控制
- 敏感信息脱敏

### 4.3 监控和运维
- Prometheus + Grafana 监控
- 日志聚合（ELK / Loki）
- 错误追踪（Sentry）

### 4.4 云部署
- 云数据库（RDS MySQL + Qdrant Cloud）
- 容器化部署（Docker + Kubernetes）
- CI/CD 流水线

---

## 里程碑时间规划

| Phase | 时间 | 产出 | 优先级 |
|-------|------|------|--------|
| Phase 0 | 已完成 | Memory V2 环境可用 | P0 |
| Phase 1 | 3-5 天 | CLI Demo，核心功能验证 | P0 |
| Phase 2 | 2-3 周 | Web UI + 文档上传 | P1 |
| Phase 3 | 按需 | 功能增强 | P2 |
| Phase 4 | 不在范围 | 生产优化 | P3 |

**课程作业建议**：
- **最低要求**：完成 Phase 1，展示 CLI Demo
- **推荐目标**：完成 Phase 2，提供完整 Web 界面
- **加分项**：Phase 3 部分功能（如知识图谱可视化）

---

## 当前进度追踪

- [x] Phase 0：环境验证
- [ ] Phase 1：最小命令行 Demo
  - [ ] 1.1 智能体宿主模块
  - [ ] 1.2 Memory V2 检索链路
  - [ ] 1.3 Memory V2 写入链路
  - [ ] 1.4 CLI 命令行界面
  - [ ] 1.5 端到端测试和 Demo 脚本
- [ ] Phase 2：Web 界面和文档上传
- [ ] Phase 3：功能增强（可选）

**下一步行动**：开始 Phase 1.1 智能体宿主模块开发
