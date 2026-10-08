"""Memory V2 独立提取包；导入时不加载原项目应用。"""

# 在核心 dataclass 初始化功能开关之前加载本目录 .env。
from .core import settings as _settings
