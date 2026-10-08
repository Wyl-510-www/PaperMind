"""独立环境配置桥接，保留核心代码使用的 Config_Bailian 名称。"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)


class Config_Bailian:
    API_KEY = os.getenv('BAILIAN_API_KEY') or os.getenv('DASHSCOPE_API_KEY', '')
    MODEL_QWEN = os.getenv('MODEL_QWEN', 'qwen3.5-plus')
    MODEL_QWEN_35_PLUS = os.getenv('MODEL_QWEN_35_PLUS', 'qwen3.5-plus')
    MODEL_QWEN_URL = os.getenv('MODEL_QWEN_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    MODEL_EMBEDDING_QWEN = os.getenv('MODEL_EMBEDDING_QWEN', 'text-embedding-v4')
    MODEL_EMBEDDING_QWEN_URL = os.getenv('MODEL_EMBEDDING_QWEN_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    MODEL_EMBEDDING_QWEN_DIM = int(os.getenv('MODEL_EMBEDDING_QWEN_DIM', '1536'))
    RERANKER_SF_API_KEY = os.getenv('RERANKER_SILICONFLOW_API_KEY', '')
    RERANKER_SF_MODEL = os.getenv('RERANKER_SILICONFLOW_MODEL', 'Qwen/Qwen3-Reranker-0.6B')
    RERANKER_SF_BASE_URL = os.getenv('RERANKER_SILICONFLOW_BASE_URL', 'https://api.siliconflow.cn/v1/rerank')
    DB_VECTOR_QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
    DB_VECTOR_QDRANT_PORT = int(os.getenv('QDRANT_PORT', '8701'))
