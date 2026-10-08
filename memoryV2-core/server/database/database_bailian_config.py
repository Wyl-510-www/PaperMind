"""独立数据库配置桥接，不包含原应用的业务表或导入时建表操作。"""

import os

from sqlalchemy.engine import URL

from server.core import settings as _settings  # 先加载本提取目录的 .env


class Config:
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASS = os.getenv('DB_PASS', '')
    DB_NAME = os.getenv('DB_NAME', 'memory_v2')
    DB_PORT = int(os.getenv('DB_PORT', '3306'))
    Database_url = os.getenv('MEMORY_V2_DB_URL') or URL.create(
        'mysql+pymysql', username=DB_USER, password=DB_PASS,
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        query={'charset': 'utf8mb4'},
    ).render_as_string(hide_password=False)
