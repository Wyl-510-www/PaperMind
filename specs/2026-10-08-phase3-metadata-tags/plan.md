# Phase 3: 元数据管理与标签过滤 - 实施计划

## 总览

**预计工作量**：3-4 天  
**技术风险**：低  
**依赖关系**：依赖 Phase 2.2（PDF 提取功能已完成）

---

## 任务分组

### Task Group 1：数据模型与常量定义（0.5 天）

#### 1.1 定义标签和笔记类型常量
**目标**：创建集中管理的常量文件，避免硬编码

**文件**：`src/papermind/constants.py`（新建）

**内容**：
```python
"""
PaperMind 常量定义
"""

# 预定义标签库（10 个核心标签）
PREDEFINED_TAGS = [
    "长期记忆",
    "记忆架构",
    "知识图谱",
    "向量数据库",
    "RAG（检索增强生成）",
    "Agent 智能体",
    "Transformer",
    "注意力机制",
    "评测基准",
    "应用案例",
]

# 笔记类型
NOTE_TYPES = [
    "摘要",
    "详细笔记",
    "评论",
    "问题",
]

# 时间范围选项
TIME_RANGE_OPTIONS = [
    "全部时间",
    "本周",
    "本月",
    "本年",
    "自定义",
]
```

**验收标准**：
- ✅ 常量文件创建完成
- ✅ 标签列表包含 10 个核心标签
- ✅ 笔记类型包含 4 种类型

---

#### 1.2 定义元数据数据模型
**目标**：使用 Pydantic 定义元数据结构，确保类型安全

**文件**：`src/papermind/models.py`（新建或扩展现有文件）

**内容**：
```python
from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from .constants import PREDEFINED_TAGS, NOTE_TYPES


class NoteMetadata(BaseModel):
    """笔记元数据模型"""
    
    title: str = Field(..., min_length=1, description="论文标题")
    author: Optional[str] = Field(None, description="论文作者")
    year: Optional[str] = Field(None, description="发表年份或会议")
    read_date: date = Field(..., description="阅读日期")
    tags: List[str] = Field(..., min_length=1, description="标签列表（至少1个）")
    note_type: str = Field(..., description="笔记类型")
    
    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """验证标签是否在预定义列表中"""
        invalid_tags = [tag for tag in v if tag not in PREDEFINED_TAGS]
        if invalid_tags:
            raise ValueError(f"无效标签: {invalid_tags}。必须在预定义列表中。")
        return v
    
    @field_validator("note_type")
    @classmethod
    def validate_note_type(cls, v: str) -> str:
        """验证笔记类型是否有效"""
        if v not in NOTE_TYPES:
            raise ValueError(f"无效笔记类型: {v}。可选值: {NOTE_TYPES}")
        return v
```

**验收标准**：
- ✅ Pydantic 模型定义完成
- ✅ 必填字段验证（title, read_date, tags, note_type）
- ✅ 标签和笔记类型枚举验证

---

### Task Group 2：写入链路更新（0.5 天）

#### 2.1 更新笔记保存接口
**目标**：扩展笔记保存函数，接收并验证元数据

**文件**：`src/papermind/note_service.py`（新建或扩展）

**函数签名**：
```python
async def save_note(
    tenant_id: str,
    user_id: str,
    content: str,
    metadata: NoteMetadata,
    memory_facade: MemoryFacade,
) -> str:
    """
    保存笔记到 Memory V2
    
    Args:
        tenant_id: 租户 ID
        user_id: 用户 ID
        content: 笔记内容
        metadata: 元数据对象
        memory_facade: Memory V2 门面对象
        
    Returns:
        保存的 Memory ID
    """
    # 构造 Memory V2 的 metadata 字段
    memory_metadata = metadata.model_dump(mode="json")
    
    # 调用 Memory V2 写入
    result = await memory_facade.add(
        messages=[
            {"role": "user", "content": f"标题: {metadata.title}\n\n{content}"}
        ],
        tenant_id=tenant_id,
        user_id=user_id,
        metadata=memory_metadata,
    )
    
    return result["memory_id"]
```

**验收标准**：
- ✅ 保存函数接收 `NoteMetadata` 对象
- ✅ 元数据序列化为 JSON 并存入 Memory metadata 字段
- ✅ 异常处理：验证失败时抛出清晰错误信息

---

#### 2.2 更新 PDF 提取流程
**目标**：PDF 提取后，引导用户补充元数据

**文件**：`src/papermind/pdf_extractor.py`（扩展现有文件）

**修改点**：
- 保持现有 PDF 文本提取逻辑
- 提取完成后，返回文本内容，由 UI 层处理元数据输入
- 不在提取器内部自动保存，改为返回提取结果

**验收标准**：
- ✅ PDF 提取逻辑不变
- ✅ 提取结果包含：原始文本、文件名（可作为默认标题）
- ✅ 与 UI 层解耦，由 UI 组装完整数据后调用 `save_note`

---

### Task Group 3：检索链路更新（1 天）

#### 3.1 实现时间范围计算工具函数
**目标**：根据用户选择的时间范围，计算起止日期

**文件**：`src/papermind/utils/date_utils.py`（新建）

**函数**：
```python
from datetime import date, timedelta
from typing import Optional, Tuple


def calculate_date_range(
    range_option: str,
    custom_start: Optional[date] = None,
    custom_end: Optional[date] = None,
) -> Tuple[Optional[date], Optional[date]]:
    """
    根据时间范围选项计算起止日期
    
    Args:
        range_option: 时间范围选项（"全部时间", "本周", "本月", "本年", "自定义"）
        custom_start: 自定义起始日期（仅当 range_option="自定义" 时使用）
        custom_end: 自定义结束日期（仅当 range_option="自定义" 时使用）
        
    Returns:
        (start_date, end_date) 元组，None 表示不限制
    """
    today = date.today()
    
    if range_option == "全部时间":
        return None, None
    
    elif range_option == "本周":
        # 本周一作为起始日期
        start = today - timedelta(days=today.weekday())
        return start, today
    
    elif range_option == "本月":
        # 本月第一天
        start = today.replace(day=1)
        return start, today
    
    elif range_option == "本年":
        # 本年第一天
        start = today.replace(month=1, day=1)
        return start, today
    
    elif range_option == "自定义":
        return custom_start, custom_end
    
    else:
        raise ValueError(f"未知的时间范围选项: {range_option}")
```

**单元测试**：
- 测试"本周"边界（周一、周日）
- 测试"本月"边界（月初、月末）
- 测试"本年"边界（1月1日、12月31日）
- 测试自定义日期

**验收标准**：
- ✅ 时间范围计算准确
- ✅ 单元测试覆盖所有选项和边界情况
- ✅ 返回值类型正确（Optional[date]）

---

#### 3.2 实现标签和时间过滤查询
**目标**：从 MySQL 查询符合标签和时间条件的 Memory IDs

**文件**：`src/papermind/retrieval_service.py`（新建或扩展）

**函数**：
```python
from typing import List, Optional
from datetime import date
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession


async def filter_memories_by_metadata(
    session: AsyncSession,
    tenant_id: str,
    tags: Optional[List[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[str]:
    """
    根据标签和时间范围过滤 Memory IDs
    
    Args:
        session: 数据库会话
        tenant_id: 租户 ID
        tags: 标签列表（OR 逻辑，匹配任一标签）
        start_date: 起始日期（包含）
        end_date: 结束日期（包含）
        
    Returns:
        符合条件的 Memory ID 列表
    """
    from memoryv2.storage.models import Memory  # 假设 Memory V2 的表名
    
    # 构造查询
    query = select(Memory.id).where(Memory.tenant_id == tenant_id)
    
    # 标签过滤（JSON 数组包含任一标签）
    if tags:
        # MySQL JSON_OVERLAPS 或 JSON_CONTAINS
        tag_conditions = [
            func.json_contains(Memory.metadata, func.json_quote(tag), "$.tags")
            for tag in tags
        ]
        query = query.where(or_(*tag_conditions))
    
    # 时间范围过滤（JSON 字段提取）
    if start_date:
        query = query.where(
            func.json_unquote(func.json_extract(Memory.metadata, "$.read_date")) >= str(start_date)
        )
    if end_date:
        query = query.where(
            func.json_unquote(func.json_extract(Memory.metadata, "$.read_date")) <= str(end_date)
        )
    
    result = await session.execute(query)
    return [row[0] for row in result.fetchall()]
```

**注意事项**：
- MySQL JSON 函数语法可能因版本而异，需实测验证
- 考虑添加 EXPLAIN 分析查询性能

**验收标准**：
- ✅ 标签过滤使用 OR 逻辑
- ✅ 时间范围过滤准确（包含边界）
- ✅ 返回 Memory ID 列表供后续向量检索使用

---

#### 3.3 集成两阶段检索
**目标**：先硬过滤，再语义检索

**文件**：`src/papermind/retrieval_service.py`

**函数**：
```python
async def retrieve_notes(
    query: str,
    tenant_id: str,
    user_id: str,
    memory_facade: MemoryFacade,
    db_session: AsyncSession,
    tags: Optional[List[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    top_k: int = 5,
) -> List[dict]:
    """
    两阶段检索：硬过滤 + 语义检索
    
    Returns:
        检索结果列表，包含笔记内容和元数据
    """
    # 阶段 1：硬过滤
    if tags or start_date or end_date:
        filtered_ids = await filter_memories_by_metadata(
            session=db_session,
            tenant_id=tenant_id,
            tags=tags,
            start_date=start_date,
            end_date=end_date,
        )
        
        if not filtered_ids:
            # 硬过滤无结果
            return []
        
        # 阶段 2：在过滤后的 IDs 中进行语义检索
        results = await memory_facade.search(
            query=query,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=top_k,
            filters={"memory_ids": filtered_ids},  # 限制检索范围
        )
    else:
        # 无过滤条件，直接全局语义检索
        results = await memory_facade.search(
            query=query,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=top_k,
        )
    
    return results
```

**验收标准**：
- ✅ 有过滤条件时，先执行硬过滤
- ✅ 硬过滤无结果时，直接返回空列表
- ✅ 无过滤条件时，保持原有全局检索行为（兼容 Phase 2）

---

### Task Group 4：Streamlit UI 实现（1 天）

#### 4.1 更新手动输入笔记页面
**目标**：增加元数据输入表单

**文件**：`src/papermind/ui/pages/input_note.py`

**UI 组件**：
```python
import streamlit as st
from datetime import date
from papermind.constants import PREDEFINED_TAGS, NOTE_TYPES
from papermind.models import NoteMetadata

st.title("📝 手动输入笔记")

# 标题（必填）
title = st.text_input("论文标题 *", placeholder="例如：Attention Is All You Need 阅读笔记")

# 笔记内容（必填）
content = st.text_area("笔记内容 *", height=300, placeholder="输入您的阅读笔记...")

# 作者（选填）
author = st.text_input("论文作者（选填）", placeholder="例如：Vaswani et al.")

# 年份（选填）
year = st.text_input("发表年份/会议（选填）", placeholder="例如：2017 或 NeurIPS 2017")

# 阅读日期（必填，默认今天）
read_date = st.date_input("阅读日期 *", value=date.today())

# 标签（必选至少 1 个）
tags = st.multiselect(
    "标签 * (至少选择 1 个)",
    options=PREDEFINED_TAGS,
    help="选择与笔记相关的标签（10 个核心标签）"
)

# 笔记类型（必选）
note_type = st.selectbox("笔记类型 *", options=NOTE_TYPES)

# 保存按钮
if st.button("💾 保存笔记", type="primary"):
    # 验证必填字段
    if not title:
        st.error("❌ 请输入论文标题")
    elif not content:
        st.error("❌ 请输入笔记内容")
    elif not tags:
        st.error("❌ 请至少选择 1 个标签")
    else:
        try:
            # 构造元数据
            metadata = NoteMetadata(
                title=title,
                author=author if author else None,
                year=year if year else None,
                read_date=read_date,
                tags=tags,
                note_type=note_type,
            )
            
            # 调用保存函数
            memory_id = await save_note(
                tenant_id=st.session_state.tenant_id,
                user_id=st.session_state.user_id,
                content=content,
                metadata=metadata,
                memory_facade=st.session_state.memory_facade,
            )
            
            st.success(f"✅ 笔记保存成功！Memory ID: {memory_id}")
            
        except Exception as e:
            st.error(f"❌ 保存失败: {str(e)}")
```

**验收标准**：
- ✅ 所有表单字段正确显示
- ✅ 必填字段验证生效
- ✅ 标签多选至少选择 1 个
- ✅ 保存成功后显示提示信息

---

#### 4.2 更新 PDF 上传页面
**目标**：提取后引导用户补充元数据

**文件**：`src/papermind/ui/pages/upload_pdf.py`

**流程**：
1. 用户上传 PDF
2. 提取文本并显示预览
3. 文件名自动填充到标题字段（用户可修改）
4. 用户补充其他元数据（标签、笔记类型等）
5. 点击保存

**验收标准**：
- ✅ PDF 提取功能保持不变
- ✅ 提取后显示元数据表单（与手动输入页面一致）
- ✅ 文件名作为默认标题
- ✅ 保存时验证元数据完整性

---

#### 4.3 更新查询页面
**目标**：增加标签和时间过滤器

**文件**：`src/papermind/ui/pages/query.py`

**UI 组件**：
```python
import streamlit as st
from papermind.constants import PREDEFINED_TAGS, TIME_RANGE_OPTIONS
from papermind.utils.date_utils import calculate_date_range

st.title("🔍 查询笔记")

# 查询输入
query = st.text_input("输入您的问题", placeholder="例如：Transformer 的注意力机制如何工作？")

# 过滤器（可折叠）
with st.expander("🔧 高级过滤（可选）", expanded=False):
    # 标签过滤
    selected_tags = st.multiselect(
        "按标签过滤（多选，匹配任一标签）",
        options=PREDEFINED_TAGS,
        help="留空则不按标签过滤"
    )
    
    # 时间范围过滤
    time_range = st.selectbox("时间范围", options=TIME_RANGE_OPTIONS, index=0)
    
    # 自定义日期范围
    custom_start, custom_end = None, None
    if time_range == "自定义":
        col1, col2 = st.columns(2)
        with col1:
            custom_start = st.date_input("起始日期")
        with col2:
            custom_end = st.date_input("结束日期")

# 查询按钮
if st.button("🔎 查询", type="primary"):
    if not query:
        st.warning("⚠️ 请输入查询内容")
    else:
        with st.spinner("正在检索笔记..."):
            # 计算时间范围
            start_date, end_date = calculate_date_range(
                range_option=time_range,
                custom_start=custom_start,
                custom_end=custom_end,
            )
            
            # 调用检索函数
            results = await retrieve_notes(
                query=query,
                tenant_id=st.session_state.tenant_id,
                user_id=st.session_state.user_id,
                memory_facade=st.session_state.memory_facade,
                db_session=st.session_state.db_session,
                tags=selected_tags if selected_tags else None,
                start_date=start_date,
                end_date=end_date,
            )
            
            # 显示结果
            if not results:
                st.info("📭 未找到符合条件的笔记，请尝试调整过滤条件或查询内容")
            else:
                st.success(f"✅ 找到 {len(results)} 条相关笔记")
                
                for idx, result in enumerate(results, 1):
                    render_note_card(result, idx)
```

**验收标准**：
- ✅ 过滤器组件正确显示
- ✅ 自定义日期范围仅在选择"自定义"时显示
- ✅ 查询时正确传递过滤参数
- ✅ 无结果时显示友好提示

---

#### 4.4 优化笔记展示卡片
**目标**：显示完整元数据，标签高亮

**函数**：
```python
def render_note_card(result: dict, index: int):
    """渲染单条笔记卡片"""
    metadata = result.get("metadata", {})
    
    with st.container():
        st.markdown(f"### 📄 {index}. {metadata.get('title', '无标题')}")
        
        # 元数据行
        col1, col2, col3 = st.columns(3)
        with col1:
            st.caption(f"👤 作者: {metadata.get('author', '未知')}")
        with col2:
            st.caption(f"📅 阅读日期: {metadata.get('read_date', '未知')}")
        with col3:
            st.caption(f"📚 类型: {metadata.get('note_type', '未知')}")
        
        # 标签徽章
        tags = metadata.get("tags", [])
        if tags:
            tag_html = " ".join([f'<span style="background-color:#E8F5E9;padding:2px 8px;border-radius:12px;font-size:12px;margin-right:4px;">🏷️ {tag}</span>' for tag in tags])
            st.markdown(tag_html, unsafe_allow_html=True)
        
        # 笔记内容
        st.markdown("**📝 笔记内容：**")
        st.text_area(
            label="",
            value=result.get("content", ""),
            height=150,
            disabled=True,
            key=f"note_content_{index}",
        )
        
        # 相似度信息
        st.caption(f"🔍 相似度: {result.get('similarity', 0):.2f}")
        
        st.divider()
```

**验收标准**：
- ✅ 元数据完整显示
- ✅ 标签使用徽章样式
- ✅ 布局清晰易读

---

### Task Group 5：测试与验收（0.5 天）

#### 5.1 单元测试
**文件**：`tests/test_date_utils.py`, `tests/test_metadata_validation.py`

**测试用例**：
- 日期范围计算（本周/本月/本年/自定义）
- 元数据验证（必填字段、标签枚举、笔记类型枚举）
- 标签过滤 OR 逻辑
- 时间范围边界

**验收标准**：
- ✅ 所有单元测试通过
- ✅ 测试覆盖率 > 80%

---

#### 5.2 集成测试
**测试场景**：

**场景 1：保存带完整元数据的笔记**
1. 手动输入笔记，填写所有字段
2. 验证保存成功
3. 查询 MySQL，验证 metadata 字段正确

**场景 2：标签过滤（OR 逻辑）**
1. 保存 3 条笔记：
   - 笔记 A：标签 ["长期记忆", "RAG"]
   - 笔记 B：标签 ["Transformer"]
   - 笔记 C：标签 ["长期记忆", "知识图谱"]
2. 查询时选择标签 ["长期记忆", "Transformer"]
3. 验证返回笔记 A, B, C（匹配任一标签）

**场景 3：时间范围过滤**
1. 保存 3 条笔记，阅读日期分别为：
   - 笔记 A：2026-01-01
   - 笔记 B：2026-01-10
   - 笔记 C：2026-01-15
2. 查询时选择时间范围"本月"（假设今天是 2026-01-13）
3. 验证返回笔记 A, B, C

**场景 4：组合过滤**
1. 查询时同时选择标签和时间范围
2. 验证先硬过滤，再语义检索
3. 验证返回结果同时满足标签和时间条件

**场景 5：边界情况**
1. 查询时不选择任何过滤条件 → 全局语义检索
2. 硬过滤后无结果 → 提示"未找到符合条件的笔记"
3. 保存时标签为空 → 显示错误提示

**验收标准**：
- ✅ 所有集成测试场景通过
- ✅ 边界情况正确处理

---

#### 5.3 手动验收
**检查清单**：
- [ ] 手动输入笔记页面：所有字段正确显示，必填验证生效
- [ ] PDF 上传页面：提取后可补充元数据
- [ ] 查询页面：过滤器正确显示，查询结果符合预期
- [ ] 笔记卡片：元数据完整，标签高亮
- [ ] 性能：查询响应时间 < 1 秒（少量笔记场景）

---

## 任务依赖关系

```
Task Group 1 (数据模型)
    ↓
Task Group 2 (写入链路)
    ↓
Task Group 3 (检索链路)
    ↓
Task Group 4 (UI 实现)
    ↓
Task Group 5 (测试验收)
```

---

## 风险缓解

### MySQL JSON 查询性能
- 先用 JSON 字段实现，观察性能
- 如查询慢（>500ms），添加计算列和索引
- 准备降级方案：将 `tags` 和 `read_date` 提升为独立列

### 时区问题
- 统一使用 UTC 或本地时区（与 Memory V2 一致）
- 日期比较时避免时区转换错误

### 标签列表变更
- 标签定义在 `constants.py`，方便修改
- 如需重命名标签，编写数据迁移脚本

---

## 下一步行动

1. 创建 `src/papermind/constants.py`
2. 定义 `NoteMetadata` 模型
3. 实现 `save_note` 函数
4. 实现 `calculate_date_range` 函数及单元测试
5. 实现 `filter_memories_by_metadata` 函数
6. 更新 Streamlit UI 页面
7. 运行集成测试
8. 手动验收
9. 提交代码并创建 PR

---

## 参考文档
- `specs/2026-01-13-phase3-metadata-tags/requirements.md`
- `specs/roadmap.md`
- Memory V2 API 文档
