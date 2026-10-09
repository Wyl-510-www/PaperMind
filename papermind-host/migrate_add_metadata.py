#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3 数据库迁移脚本
为 memory_v2_record 表添加 metadata 字段
"""
import os
import sys
import pymysql
from dotenv import load_dotenv

# 确保 Windows 控制台正确显示 UTF-8
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 加载环境变量（从 memoryV2-core/.env）
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(parent_dir, 'memoryV2-core', '.env')
load_dotenv(env_path)

def connect_db():
    """连接数据库"""
    config = {
        'host': os.getenv('DB_HOST', '127.0.0.1'),
        'port': int(os.getenv('DB_PORT', 3306)),
        'user': os.getenv('DB_USER', 'memoryv2'),
        'password': os.getenv('DB_PASS', ''),
        'database': os.getenv('DB_NAME', 'memory_v2'),
        'charset': 'utf8mb4',
    }
    print(f"正在连接数据库 {config['host']}:{config['port']}/{config['database']}...")
    return pymysql.connect(**config)

def check_table_structure(cursor):
    """检查当前表结构"""
    print("\n=== 当前表结构 ===")
    cursor.execute("DESC memory_v2_record")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col[0]:<20} {col[1]:<20} NULL={col[2]} KEY={col[3]}")
    return [col[0] for col in columns]

def add_metadata_column(cursor):
    """添加 metadata 字段"""
    sql = """
    ALTER TABLE memory_v2_record
    ADD COLUMN metadata JSON NULL
    COMMENT '笔记元数据（标签、阅读日期、作者、年份、笔记类型）'
    """
    print("\n=== 执行迁移 ===")
    print(f"SQL: {sql.strip()}")
    cursor.execute(sql)
    print("[OK] metadata 字段添加成功")

def verify_migration(cursor):
    """验证迁移结果"""
    print("\n=== 验证迁移结果 ===")

    # 1. 检查字段是否存在
    cursor.execute("SHOW COLUMNS FROM memory_v2_record LIKE 'metadata'")
    result = cursor.fetchone()
    if result:
        print(f"[OK] metadata 字段存在: {result[0]} {result[1]} NULL={result[2]}")
    else:
        print("[FAIL] metadata 字段不存在")
        return False

    # 2. 测试插入
    print("\n测试插入带 metadata 的记录...")
    test_memory_id = 'test_migration_001'
    test_metadata = '{"title": "Test Paper", "tags": ["AI", "Transformer"], "read_date": "2026-10-09", "note_type": "摘要"}'

    try:
        cursor.execute("""
            INSERT INTO memory_v2_record
            (memory_id, tenant_id, user_id, namespace, memory_type, text_zh, modality,
             status, metadata, confidence, importance, version, index_status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (test_memory_id, 'tenant_test', 'user_test', 'default', 'note',
              '测试笔记内容', 'text', 'active', test_metadata, 1.0, 1.0, 1, 'indexed'))
        print("[OK] 插入成功")

        # 3. 测试查询
        cursor.execute("""
            SELECT memory_id, metadata
            FROM memory_v2_record
            WHERE memory_id = %s
        """, (test_memory_id,))
        row = cursor.fetchone()
        if row:
            print(f"[OK] 查询成功: {row[0]} -> {row[1]}")

        # 4. 清理测试数据
        cursor.execute("DELETE FROM memory_v2_record WHERE memory_id = %s", (test_memory_id,))
        print("[OK] 测试数据已清理")

        return True
    except Exception as e:
        print(f"[FAIL] 测试失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print("Phase 3 数据库迁移：添加 metadata 字段")
    print("=" * 60)

    conn = None
    try:
        # 连接数据库
        conn = connect_db()
        cursor = conn.cursor()

        # 检查当前表结构
        columns = check_table_structure(cursor)

        # 检查 metadata 字段是否已存在
        if 'metadata' in columns:
            print("\n[WARN] metadata 字段已存在，跳过迁移")
            # 仍然执行验证
            if verify_migration(cursor):
                conn.commit()
                print("\n" + "=" * 60)
                print("[SUCCESS] 字段已存在且验证通过！")
                print("=" * 60)
                return 0
            else:
                print("\n" + "=" * 60)
                print("[FAIL] 字段验证失败")
                print("=" * 60)
                return 1

        # 执行迁移
        add_metadata_column(cursor)
        conn.commit()

        # 验证迁移
        if verify_migration(cursor):
            conn.commit()
            print("\n" + "=" * 60)
            print("[SUCCESS] 迁移成功完成！")
            print("=" * 60)
            return 0
        else:
            conn.rollback()
            print("\n" + "=" * 60)
            print("[FAIL] 迁移验证失败")
            print("=" * 60)
            return 1

    except pymysql.Error as e:
        print(f"\n[ERROR] 数据库错误: {e}")
        if conn:
            conn.rollback()
        return 1
    except Exception as e:
        print(f"\n[ERROR] 错误: {e}")
        if conn:
            conn.rollback()
        return 1
    finally:
        if conn:
            conn.close()
            print("\n数据库连接已关闭")

if __name__ == '__main__':
    sys.exit(main())
