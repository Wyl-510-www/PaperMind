# Phase 3 数据库迁移任务

## 背景

Phase 3（元数据管理与标签过滤）的代码已全部实现并通过测试，但当前数据库表缺少 `metadata` 字段，导致核心功能无法在数据库层执行。

## 当前状态

✅ **已完成**:
- 元数据模型定义（`papermind/models.py`）
- 两阶段检索逻辑（`papermind/memory_retrieval.py`）
- UI 元数据表单（`streamlit_app.py`）
- 所有单元测试和核心功能测试通过

❌ **阻塞问题**:
- `memory_v2_record` 表缺少 `metadata` 列
- 无法将元数据持久化到数据库
- 标签和时间过滤只能在内存中执行，无法在数据库层优化

## 任务目标

为 `memory_v2_record` 表添加 `metadata` 字段，使 Phase 3 功能完整可用。

## 具体要求

### 1. 数据库表结构更新

**目标表**: `memory_v2_record`  
**需要添加的字段**: `metadata` (JSON类型)

**字段规格**:
- 类型: JSON
- 可空: YES（向后兼容已有数据）
- 默认值: NULL
- 备注: 存储笔记元数据（标签、日期等）

**参考 SQL**:
```sql
ALTER TABLE memory_v2_record 
ADD COLUMN metadata JSON NULL 
COMMENT '笔记元数据（标签、阅读日期、作者、年份、笔记类型）';
```

### 2. 验证数据库连接

确认可以连接到数据库：
- 检查 `.env` 文件中的数据库配置
- 验证数据库连接字符串
- 确认有足够的权限执行 ALTER TABLE

### 3. 执行迁移

**步骤**:
1. 备份数据库（如果是生产环境）
2. 在测试环境验证 SQL
3. 执行 ALTER TABLE 语句
4. 验证字段添加成功

### 4. 可选优化（性能考虑）

如果未来数据量大（>10,000条笔记），可以添加虚拟列和索引：

```sql
-- 为标签字段添加虚拟列（便于索引）
ALTER TABLE memory_v2_record
ADD COLUMN tags_virtual JSON 
GENERATED ALWAYS AS (JSON_EXTRACT(metadata, '$.tags')) VIRTUAL;

-- 为阅读日期添加虚拟列
ALTER TABLE memory_v2_record
ADD COLUMN read_date_virtual DATE 
GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(metadata, '$.read_date'))) VIRTUAL;

-- 添加索引
CREATE INDEX idx_tags ON memory_v2_record ((CAST(metadata->'$.tags' AS CHAR(500)) ARRAY));
CREATE INDEX idx_read_date ON memory_v2_record (read_date_virtual);
```

**注意**: 这一步是可选的，先完成基础字段添加即可。

### 5. 验证迁移结果

**验证检查清单**:
- [ ] 字段成功添加到表中
- [ ] 字段类型为 JSON
- [ ] 现有数据不受影响（metadata 为 NULL）
- [ ] 可以插入包含 metadata 的新记录
- [ ] 可以查询 metadata 字段

**验证 SQL**:
```sql
-- 检查字段是否添加
DESC memory_v2_record;

-- 或
SHOW COLUMNS FROM memory_v2_record LIKE 'metadata';

-- 测试插入
INSERT INTO memory_v2_record (memory_id, tenant_id, user_id, status, metadata, created_at)
VALUES (
  'test_mem_001',
  'tenant_test',
  'user_test',
  'active',
  '{"title": "Test Paper", "tags": ["Transformer"], "read_date": "2026-10-09", "note_type": "摘要"}',
  NOW()
);

-- 测试查询
SELECT memory_id, metadata FROM memory_v2_record WHERE memory_id = 'test_mem_001';

-- 清理测试数据
DELETE FROM memory_v2_record WHERE memory_id = 'test_mem_001';
```

### 6. 运行端到端测试

迁移完成后，运行完整的端到端测试验证功能：

```bash
cd papermind-host
python examples/verify_phase3_e2e.py
```

**期望结果**:
- 所有测试通过
- 标签过滤功能正常
- 时间范围过滤功能正常
- 组合过滤功能正常

## 关键文件位置

**数据库配置**:
- `.env` - 数据库连接配置
- `memoryV2-core/server/database/database_bailian_config.py` - 数据库配置类

**相关代码**:
- `papermind/memory_retrieval.py` - 包含 `_filter_memory_ids_by_metadata()` 函数
- `papermind/models.py` - 元数据模型定义
- `examples/verify_phase3_e2e.py` - 完整端到端测试

**文档**:
- `PHASE3_E2E_TEST_REPORT.md` - 测试报告
- `PHASE3_COMPLETION_REPORT.md` - 完成报告
- `specs/2026-10-08-phase3-metadata-tags/` - 完整规格文档

## 注意事项

### 数据库环境
- 确认当前使用的是**测试环境**还是**生产环境**
- 生产环境务必先备份
- 测试环境可以直接执行

### 兼容性
- 新字段为 NULL，不影响现有数据
- 现有代码已做好兼容处理（metadata 为 None 时降级到全局检索）

### 回滚计划
如果迁移失败，可以回滚：
```sql
ALTER TABLE memory_v2_record DROP COLUMN metadata;
```

## 成功标准

✅ **迁移成功的标志**:
1. 数据库表包含 `metadata` 字段
2. `verify_phase3_e2e.py` 所有测试通过
3. 可以成功保存和检索带元数据的笔记
4. 标签过滤返回正确结果
5. 时间范围过滤返回正确结果

## 执行提示

**如果你是下一个 AI 会话，请按以下步骤执行**:

1. **确认环境**
   ```bash
   # 检查当前位置
   pwd
   # 应该在 papermind-host 目录
   
   # 检查数据库配置
   cat .env | grep -i database
   ```

2. **连接数据库**
   - 使用 Python 脚本连接数据库
   - 或使用 MySQL 客户端连接

3. **检查表结构**
   ```sql
   DESC memory_v2_record;
   ```

4. **执行迁移**
   ```sql
   ALTER TABLE memory_v2_record ADD COLUMN metadata JSON NULL COMMENT '笔记元数据';
   ```

5. **验证迁移**
   ```bash
   python examples/verify_phase3_e2e.py
   ```

6. **报告结果**
   - 迁移成功：所有测试通过
   - 迁移失败：提供错误信息和日志

## 参考资料

- MySQL JSON 数据类型文档: https://dev.mysql.com/doc/refman/8.0/en/json.html
- Phase 3 完整规格: `specs/2026-10-08-phase3-metadata-tags/requirements.md`
- 测试报告: `PHASE3_E2E_TEST_REPORT.md`

---

**优先级**: 🔴 高  
**预计时间**: 30分钟  
**风险等级**: 低（可回滚）  
**阻塞**: Phase 3 完整功能上线
