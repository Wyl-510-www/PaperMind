# Phase 3: 元数据管理与标签过滤 - 验收文档

## 验收目标

验证 Phase 3 的所有功能正常工作，满足需求文档中的验收标准，可以安全合并到 main 分支。

---

## 验收前置条件

### 环境要求
- ✅ MySQL 8.0+ 运行中
- ✅ Qdrant 运行中
- ✅ Memory V2 数据库表已初始化
- ✅ Python 依赖已安装（requirements.txt）
- ✅ 环境变量已配置（.env）

### 数据准备
准备至少 5 条测试笔记，覆盖不同标签和日期：

| 笔记编号 | 标题 | 标签 | 阅读日期 | 笔记类型 |
|---------|------|------|---------|---------|
| 1 | Attention Is All You Need | Transformer, 注意力机制 | 2026-01-01 | 详细笔记 |
| 2 | RAG Survey | RAG（检索增强生成）, 向量数据库 | 2026-01-10 | 摘要 |
| 3 | Memory Architecture | 长期记忆, 记忆架构, Agent 智能体 | 2026-01-13 | 详细笔记 |
| 4 | Knowledge Graph | 知识图谱, 理论基础 | 2025-12-20 | 评论 |
| 5 | Embedding Techniques | 嵌入技术, Transformer | 2026-01-12 | 问题 |

---

## 自动化验收脚本

### 验收脚本文件

**文件路径**：`specs/2026-01-13-phase3-metadata-tags/validate.py`

```python
#!/usr/bin/env python3
"""
Phase 3 自动化验收脚本
"""

import asyncio
from datetime import date, timedelta
from typing import List, Dict

# 假设项目结构
from papermind.constants import PREDEFINED_TAGS, NOTE_TYPES
from papermind.models import NoteMetadata
from papermind.note_service import save_note
from papermind.retrieval_service import retrieve_notes
from papermind.utils.date_utils import calculate_date_range


class Phase3Validator:
    """Phase 3 验收测试类"""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.test_notes = []
    
    def assert_true(self, condition: bool, message: str):
        """断言条件为真"""
        if condition:
            print(f"  ✅ {message}")
            self.passed += 1
        else:
            print(f"  ❌ {message}")
            self.failed += 1
    
    def assert_equal(self, actual, expected, message: str):
        """断言相等"""
        if actual == expected:
            print(f"  ✅ {message}")
            self.passed += 1
        else:
            print(f"  ❌ {message}")
            print(f"     期望: {expected}")
            print(f"     实际: {actual}")
            self.failed += 1
    
    async def setup_test_data(self):
        """准备测试数据"""
        print("\n📦 准备测试数据...")
        
        test_cases = [
            {
                "title": "Attention Is All You Need 阅读笔记",
                "content": "Transformer 架构使用自注意力机制...",
                "tags": ["Transformer", "注意力机制"],
                "read_date": date(2026, 1, 1),
                "note_type": "详细笔记",
                "author": "Vaswani et al.",
                "year": "2017",
            },
            {
                "title": "RAG Survey 总结",
                "content": "检索增强生成综述...",
                "tags": ["RAG（检索增强生成）", "向量数据库"],
                "read_date": date(2026, 1, 10),
                "note_type": "摘要",
            },
            {
                "title": "Memory Architecture 研究",
                "content": "智能体长期记忆架构设计...",
                "tags": ["长期记忆", "记忆架构", "Agent 智能体"],
                "read_date": date(2026, 1, 13),
                "note_type": "详细笔记",
            },
            {
                "title": "Knowledge Graph 评论",
                "content": "知识图谱在 NLP 中的应用...",
                "tags": ["知识图谱", "理论基础"],
                "read_date": date(2025, 12, 20),
                "note_type": "评论",
            },
            {
                "title": "Embedding Techniques 问题",
                "content": "如何优化嵌入向量质量？",
                "tags": ["嵌入技术", "Transformer"],
                "read_date": date(2026, 1, 12),
                "note_type": "问题",
            },
        ]
        
        for i, case in enumerate(test_cases, 1):
            try:
                metadata = NoteMetadata(**case)
                memory_id = await save_note(
                    tenant_id="test_tenant",
                    user_id="test_user",
                    content=case["content"],
                    metadata=metadata,
                    memory_facade=self.memory_facade,
                )
                self.test_notes.append(memory_id)
                print(f"  ✅ 测试笔记 {i} 保存成功 (ID: {memory_id})")
            except Exception as e:
                print(f"  ❌ 测试笔记 {i} 保存失败: {e}")
                raise
    
    async def test_metadata_validation(self):
        """测试 1: 元数据验证"""
        print("\n🧪 测试 1: 元数据验证")
        
        # 测试必填字段
        try:
            NoteMetadata(
                title="",  # 空标题
                tags=["长期记忆"],
                read_date=date.today(),
                note_type="摘要",
            )
            self.assert_true(False, "空标题应该触发验证错误")
        except Exception:
            self.assert_true(True, "空标题正确触发验证错误")
        
        # 测试标签验证
        try:
            NoteMetadata(
                title="测试",
                tags=["无效标签"],
                read_date=date.today(),
                note_type="摘要",
            )
            self.assert_true(False, "无效标签应该触发验证错误")
        except Exception:
            self.assert_true(True, "无效标签正确触发验证错误")
        
        # 测试笔记类型验证
        try:
            NoteMetadata(
                title="测试",
                tags=["长期记忆"],
                read_date=date.today(),
                note_type="无效类型",
            )
            self.assert_true(False, "无效笔记类型应该触发验证错误")
        except Exception:
            self.assert_true(True, "无效笔记类型正确触发验证错误")
        
        # 测试标签至少 1 个
        try:
            NoteMetadata(
                title="测试",
                tags=[],
                read_date=date.today(),
                note_type="摘要",
            )
            self.assert_true(False, "空标签列表应该触发验证错误")
        except Exception:
            self.assert_true(True, "空标签列表正确触发验证错误")
    
    async def test_date_range_calculation(self):
        """测试 2: 时间范围计算"""
        print("\n🧪 测试 2: 时间范围计算")
        
        today = date.today()
        
        # 全部时间
        start, end = calculate_date_range("全部时间")
        self.assert_equal(start, None, "全部时间：起始日期为 None")
        self.assert_equal(end, None, "全部时间：结束日期为 None")
        
        # 本周
        start, end = calculate_date_range("本周")
        expected_start = today - timedelta(days=today.weekday())
        self.assert_equal(start, expected_start, f"本周：起始日期为本周一 {expected_start}")
        self.assert_equal(end, today, f"本周：结束日期为今天 {today}")
        
        # 本月
        start, end = calculate_date_range("本月")
        expected_start = today.replace(day=1)
        self.assert_equal(start, expected_start, f"本月：起始日期为本月 1 日 {expected_start}")
        self.assert_equal(end, today, f"本月：结束日期为今天 {today}")
        
        # 本年
        start, end = calculate_date_range("本年")
        expected_start = today.replace(month=1, day=1)
        self.assert_equal(start, expected_start, f"本年：起始日期为本年 1 月 1 日 {expected_start}")
        self.assert_equal(end, today, f"本年：结束日期为今天 {today}")
        
        # 自定义
        custom_start = date(2026, 1, 1)
        custom_end = date(2026, 1, 15)
        start, end = calculate_date_range("自定义", custom_start, custom_end)
        self.assert_equal(start, custom_start, "自定义：起始日期正确")
        self.assert_equal(end, custom_end, "自定义：结束日期正确")
    
    async def test_tag_filtering_or_logic(self):
        """测试 3: 标签过滤 OR 逻辑"""
        print("\n🧪 测试 3: 标签过滤 OR 逻辑")
        
        # 查询标签: ["Transformer", "长期记忆"]
        # 应返回笔记 1, 3, 5（包含任一标签）
        results = await retrieve_notes(
            query="架构设计",
            tenant_id="test_tenant",
            user_id="test_user",
            memory_facade=self.memory_facade,
            db_session=self.db_session,
            tags=["Transformer", "长期记忆"],
        )
        
        result_titles = [r["metadata"]["title"] for r in results]
        expected_titles = [
            "Attention Is All You Need 阅读笔记",
            "Memory Architecture 研究",
            "Embedding Techniques 问题",
        ]
        
        self.assert_true(
            len(results) == 3,
            f"标签 OR 逻辑：返回 3 条笔记（实际: {len(results)}）"
        )
        
        for title in expected_titles:
            self.assert_true(
                title in result_titles,
                f"标签 OR 逻辑：包含笔记「{title}」"
            )
    
    async def test_time_range_filtering(self):
        """测试 4: 时间范围过滤"""
        print("\n🧪 测试 4: 时间范围过滤")
        
        # 查询本月笔记（2026-01-01 到 2026-01-13）
        # 应返回笔记 1, 2, 3, 5
        start_date, end_date = calculate_date_range("本月")
        results = await retrieve_notes(
            query="研究",
            tenant_id="test_tenant",
            user_id="test_user",
            memory_facade=self.memory_facade,
            db_session=self.db_session,
            start_date=start_date,
            end_date=end_date,
        )
        
        self.assert_true(
            len(results) >= 3,  # 至少包含本月的笔记
            f"时间范围过滤：返回本月笔记（实际: {len(results)}）"
        )
        
        # 验证所有返回笔记的阅读日期在本月
        for result in results:
            read_date_str = result["metadata"]["read_date"]
            read_date = date.fromisoformat(read_date_str)
            self.assert_true(
                start_date <= read_date <= end_date,
                f"时间范围过滤：笔记「{result['metadata']['title']}」日期在本月"
            )
    
    async def test_combined_filtering(self):
        """测试 5: 组合过滤（标签 + 时间）"""
        print("\n🧪 测试 5: 组合过滤（标签 + 时间）")
        
        # 查询标签: ["Transformer"]，时间: 本月
        # 应返回笔记 1, 5
        start_date, end_date = calculate_date_range("本月")
        results = await retrieve_notes(
            query="Transformer",
            tenant_id="test_tenant",
            user_id="test_user",
            memory_facade=self.memory_facade,
            db_session=self.db_session,
            tags=["Transformer"],
            start_date=start_date,
            end_date=end_date,
        )
        
        self.assert_true(
            len(results) == 2,
            f"组合过滤：返回 2 条笔记（实际: {len(results)}）"
        )
        
        for result in results:
            metadata = result["metadata"]
            tags = metadata["tags"]
            read_date = date.fromisoformat(metadata["read_date"])
            
            self.assert_true(
                "Transformer" in tags,
                f"组合过滤：笔记「{metadata['title']}」包含标签 Transformer"
            )
            self.assert_true(
                start_date <= read_date <= end_date,
                f"组合过滤：笔记「{metadata['title']}」日期在本月"
            )
    
    async def test_no_filter_global_search(self):
        """测试 6: 无过滤条件的全局检索"""
        print("\n🧪 测试 6: 无过滤条件的全局检索")
        
        # 不选择标签和时间，应执行全局语义检索
        results = await retrieve_notes(
            query="记忆",
            tenant_id="test_tenant",
            user_id="test_user",
            memory_facade=self.memory_facade,
            db_session=self.db_session,
        )
        
        self.assert_true(
            len(results) > 0,
            f"全局检索：返回结果（实际: {len(results)} 条）"
        )
    
    async def test_empty_filter_result(self):
        """测试 7: 硬过滤无结果"""
        print("\n🧪 测试 7: 硬过滤无结果")
        
        # 查询标签: ["长期记忆"]，时间: 2025 年
        # 笔记 3 有"长期记忆"标签，但日期是 2026-01-13
        start_date = date(2025, 1, 1)
        end_date = date(2025, 12, 31)
        results = await retrieve_notes(
            query="长期记忆",
            tenant_id="test_tenant",
            user_id="test_user",
            memory_facade=self.memory_facade,
            db_session=self.db_session,
            tags=["长期记忆"],
            start_date=start_date,
            end_date=end_date,
        )
        
        self.assert_true(
            len(results) == 0,
            f"硬过滤无结果：返回空列表（实际: {len(results)}）"
        )
    
    async def run_all_tests(self):
        """运行所有验收测试"""
        print("=" * 60)
        print("Phase 3: 元数据管理与标签过滤 - 自动化验收")
        print("=" * 60)
        
        await self.test_metadata_validation()
        await self.test_date_range_calculation()
        await self.setup_test_data()
        await self.test_tag_filtering_or_logic()
        await self.test_time_range_filtering()
        await self.test_combined_filtering()
        await self.test_no_filter_global_search()
        await self.test_empty_filter_result()
        
        # 汇总
        print("\n" + "=" * 60)
        print(f"验收结果: {self.passed} 通过, {self.failed} 失败")
        print("=" * 60)
        
        if self.failed == 0:
            print("✅ 所有验收测试通过！Phase 3 可以合并。")
            return True
        else:
            print("❌ 存在失败的测试用例，请修复后重新验收。")
            return False


async def main():
    """主函数"""
    validator = Phase3Validator()
    success = await validator.run_all_tests()
    exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 手动验收清单

### UI 验收

#### 1. 手动输入笔记页面
- [ ] 页面标题显示为"📝 手动输入笔记"
- [ ] 标题输入框显示，必填标记 `*`
- [ ] 笔记内容文本框显示，高度适中（≥300px）
- [ ] 作者输入框显示，标记为选填
- [ ] 年份输入框显示，标记为选填
- [ ] 阅读日期选择器显示，默认值为今天
- [ ] 标签多选框显示 15 个预定义标签
- [ ] 笔记类型下拉菜单显示 4 种类型
- [ ] 保存按钮显示，样式为主按钮（primary）
- [ ] 点击保存但标题为空时，显示错误提示
- [ ] 点击保存但内容为空时，显示错误提示
- [ ] 点击保存但未选择标签时，显示错误提示
- [ ] 填写完整信息后保存，显示成功提示和 Memory ID
- [ ] 保存失败时，显示清晰的错误信息

#### 2. PDF 上传页面
- [ ] 页面标题显示为"📄 上传 PDF 笔记"
- [ ] 文件上传组件正常工作
- [ ] 上传 PDF 后，显示提取进度
- [ ] 提取完成后，文本内容正确显示
- [ ] 文件名自动填充到标题字段
- [ ] 元数据表单与手动输入页面一致
- [ ] 用户可以修改自动填充的标题
- [ ] 保存时验证元数据完整性
- [ ] 保存成功后显示提示信息

#### 3. 查询页面
- [ ] 页面标题显示为"🔍 查询笔记"
- [ ] 查询输入框正确显示
- [ ] "高级过滤"折叠面板默认收起
- [ ] 展开折叠面板，显示标签多选框
- [ ] 展开折叠面板，显示时间范围下拉菜单
- [ ] 时间范围默认为"全部时间"
- [ ] 选择"自定义"时，显示起止日期选择器
- [ ] 选择其他时间范围时，日期选择器隐藏
- [ ] 查询按钮显示，样式为主按钮
- [ ] 点击查询但输入为空时，显示警告提示
- [ ] 查询有结果时，显示笔记数量
- [ ] 查询无结果时，显示友好提示
- [ ] 笔记卡片正确显示（见下一节）

#### 4. 笔记卡片展示
- [ ] 笔记标题正确显示，带序号
- [ ] 作者信息正确显示（或"未知"）
- [ ] 阅读日期正确显示（或"未知"）
- [ ] 笔记类型正确显示（或"未知"）
- [ ] 标签以徽章形式显示，样式美观
- [ ] 笔记内容完整显示，文本框禁用编辑
- [ ] 相似度信息显示（如有）
- [ ] 多条笔记之间有分隔线
- [ ] 布局清晰，易于阅读

---

### 功能验收

#### 5. 标签过滤测试
**测试步骤**：
1. 保存 3 条笔记：
   - 笔记 A：标签 ["长期记忆", "RAG（检索增强生成）"]
   - 笔记 B：标签 ["Transformer"]
   - 笔记 C：标签 ["长期记忆", "知识图谱"]
2. 查询页面选择标签 ["长期记忆", "Transformer"]
3. 输入查询："架构"
4. 点击查询

**预期结果**：
- [ ] 返回笔记 A, B, C（OR 逻辑，匹配任一标签）
- [ ] 查询结果中，匹配的标签有高亮或标记
- [ ] 如果语义相似度低，也会返回（硬过滤优先）

#### 6. 时间范围过滤测试
**测试步骤**：
1. 保存 3 条笔记，阅读日期分别为：
   - 笔记 A：本月第 1 天
   - 笔记 B：本月第 10 天
   - 笔记 C：上月第 20 天
2. 查询页面选择时间范围"本月"
3. 输入查询："总结"
4. 点击查询

**预期结果**：
- [ ] 返回笔记 A 和 B
- [ ] 不返回笔记 C
- [ ] 查询结果中，日期信息正确显示

#### 7. 组合过滤测试
**测试步骤**：
1. 查询页面选择标签 ["Transformer"]
2. 选择时间范围"本周"
3. 输入查询："注意力机制"
4. 点击查询

**预期结果**：
- [ ] 只返回同时满足标签和时间条件的笔记
- [ ] 查询结果正确

#### 8. 全局检索测试
**测试步骤**：
1. 查询页面不选择任何过滤条件
2. 输入查询："记忆"
3. 点击查询

**预期结果**：
- [ ] 返回所有语义相关的笔记
- [ ] 行为与 Phase 2 一致（兼容性验证）

#### 9. 边界情况测试
**测试场景**：
- [ ] 硬过滤无结果：选择标签和时间，但无笔记匹配 → 显示"未找到符合条件的笔记"
- [ ] 保存时标签为空 → 显示"请至少选择 1 个标签"
- [ ] 保存时标题为空 → 显示"请输入论文标题"
- [ ] 保存时笔记类型未选 → 显示"请选择笔记类型"
- [ ] 自定义日期范围：起始日期晚于结束日期 → 显示警告或自动调整

---

### 性能验收

#### 10. 查询性能
**测试条件**：数据库中有 50 条笔记

**测试步骤**：
1. 执行标签过滤查询
2. 记录响应时间

**预期结果**：
- [ ] 查询响应时间 < 1 秒（本地环境）
- [ ] 无明显卡顿

**如果超时**：
- 检查 MySQL JSON 字段查询是否有索引
- 考虑将 `tags` 和 `read_date` 提升为独立列

---

### 数据一致性验收

#### 11. 元数据存储验证
**测试步骤**：
1. 保存一条笔记，包含完整元数据
2. 直接查询 MySQL `memory` 表
3. 检查 `metadata` 字段（JSON）

**预期结果**：
- [ ] `metadata` 字段包含所有元数据键
- [ ] `tags` 为 JSON 数组
- [ ] `read_date` 为 ISO 8601 格式字符串（YYYY-MM-DD）
- [ ] 标签值在预定义列表中
- [ ] 笔记类型在预定义列表中

---

## 验收报告模板

### 验收日期
`YYYY-MM-DD`

### 验收人
`姓名`

### 验收结果

| 类别 | 通过 | 失败 | 备注 |
|------|------|------|------|
| 自动化测试 | X / Y | 0 / Y | 运行 `validate.py` |
| UI 验收 | X / 18 | 0 / 18 | 手动检查清单 |
| 功能验收 | X / 6 | 0 / 6 | 手动测试场景 |
| 性能验收 | X / 1 | 0 / 1 | 查询响应时间 |
| 数据一致性 | X / 1 | 0 / 1 | 元数据存储检查 |
| **总计** | **X** | **0** | |

### 发现的问题
1. 问题描述
   - 严重程度: [高/中/低]
   - 复现步骤: ...
   - 预期结果: ...
   - 实际结果: ...

### 验收结论
- [ ] ✅ 通过验收，可以合并到 main 分支
- [ ] ❌ 未通过验收，需要修复问题后重新验收

### 签名
`验收人签名` / `日期`

---

## 合并前检查清单

- [ ] 所有自动化测试通过
- [ ] 所有手动验收项通过
- [ ] 代码符合项目规范（类型提示、文档字符串、注释）
- [ ] 无遗留的 TODO 或 FIXME 注释
- [ ] README 或相关文档已更新
- [ ] 分支与 main 最新代码合并，无冲突
- [ ] 本地运行完整流程无错误
- [ ] Commit message 清晰，遵循约定式提交规范
- [ ] PR 描述包含功能说明和验收结果

---

## 快速验收命令

### 运行自动化验收脚本
```bash
cd specs/2026-01-13-phase3-metadata-tags
python validate.py
```

### 启动 Streamlit 应用进行手动验收
```bash
cd src/papermind
streamlit run app.py
```

### 查询 MySQL 验证元数据
```sql
SELECT id, metadata FROM memory WHERE tenant_id = 'test_tenant' ORDER BY created_at DESC LIMIT 5;
```

---

## 参考文档
- `specs/2026-01-13-phase3-metadata-tags/requirements.md`
- `specs/2026-01-13-phase3-metadata-tags/plan.md`
- `specs/roadmap.md` - Phase 3 验收标准
