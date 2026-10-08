"""检查本地依赖；可显式建 Memory V2 表，向量测试仅使用独立临时集合。"""

import argparse
import asyncio
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
CORE = ROOT.parent / 'memoryV2-core'
sys.path.insert(0, str(CORE))

from dotenv import load_dotenv

load_dotenv(ROOT / '.env', override=False)


def verify(initialize_tables=False):
    import requests
    from sqlalchemy import create_engine, inspect, text
    from server.database.database_bailian_config import Config
    from server.core.settings import Config_Bailian
    from server.memory_v2.config import config
    from server.memory_v2.retrieve.index_v2 import IndexV2

    engine = create_engine(Config.Database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            assert connection.execute(text('SELECT 1')).scalar_one() == 1
            mysql_version = connection.execute(text('SELECT VERSION()')).scalar_one()
        if initialize_tables:
            from server.memory_v2.models import Base as MemoryBase
            from server.memory_v2.store.entity_store import Base as EntityBase
            from server.memory_v2.critical_identity import Base as IdentityBase
            from server.memory_v2.preference_repository import Base as PreferenceBase
            for base in (MemoryBase, EntityBase, IdentityBase, PreferenceBase):
                base.metadata.create_all(engine, checkfirst=True)
        tables = inspect(engine).get_table_names()
    finally:
        engine.dispose()

    async def verify_async_mysql():
        from sqlalchemy.ext.asyncio import create_async_engine
        async_engine = create_async_engine(Config.Database_url.replace('mysql+pymysql://', 'mysql+aiomysql://'))
        try:
            async with async_engine.connect() as connection:
                assert (await connection.execute(text('SELECT 1'))).scalar_one() == 1
        finally:
            await async_engine.dispose()

    asyncio.run(verify_async_mysql())

    response = requests.get(os.environ['MEMORY_V2_QDRANT_URL'].rstrip('/') + '/healthz', timeout=10)
    response.raise_for_status()
    assert config.embedding_dimension == Config_Bailian.MODEL_EMBEDDING_QWEN_DIM == 1536
    configured_collection = None
    if initialize_tables:
        configured_index = IndexV2(embedding_dim=1536)
        try:
            configured_index.create_collection_if_not_exists()
            info = configured_index.client.get_collection(configured_index.collection_name)
            assert info.config.params.vectors.size == 1536
            configured_collection = configured_index.collection_name
        finally:
            configured_index.client.close()
    name = 'bench_env_verify_' + uuid.uuid4().hex
    index = IndexV2(host=Config_Bailian.DB_VECTOR_QDRANT_HOST,
                    port=Config_Bailian.DB_VECTOR_QDRANT_PORT,
                    collection_name=name, embedding_dim=1536)
    created = False
    try:
        index.create_collection_if_not_exists()
        created = True
        memory_id = str(uuid.uuid4())
        vector = [1.0] + [0.0] * 1535
        index.upsert(memory_id, vector, {
            'memory_id': memory_id, 'tenant_id': 'env_verify', 'user_id': 'env_verify',
            'memory_type': 'semantic', 'subject_id': 'env_verify', 'status': 'active',
            'content': 'Local vector connectivity check',
        })
        result = index.search('semantic', 'check', 1, query_vector=vector,
                              tenant_id='env_verify', user_id='env_verify')
        assert result and result[0]['memory_id'] == memory_id
    finally:
        if created:
            index.client.delete_collection(name)
        index.client.close()

    if initialize_tables:
        assert 'memory_v2_outbox' in tables
    result = {
        'python': sys.version.split()[0],
        'python_executable': sys.executable,
        'mysql_version': mysql_version,
        'mysql_connected': True,
        'mysql_async_connected': True,
        'memory_tables_initialized': initialize_tables,
        'database_tables': tables,
        'qdrant_health': response.status_code,
        'vector_upsert_and_search': True,
        'temporary_vector_collection_removed': True,
        'embedding_dimension': 1536,
        'configured_collection': configured_collection,
        'core_switches_enabled': config.enable_all and config.write_enabled and config.read_enabled,
        'model_api_calls_tested': False,
        'packages': {name: metadata.version(name) for name in
                     ('SQLAlchemy', 'PyMySQL', 'aiomysql', 'qdrant-client', 'openai', 'pydantic')},
    }
    assert result['core_switches_enabled']
    (ROOT / 'environment-verification.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--initialize-memory-storage', '--initialize-memory-tables',
                        dest='initialize_memory_storage', action='store_true')
    args = parser.parse_args()
    verify(args.initialize_memory_storage)
