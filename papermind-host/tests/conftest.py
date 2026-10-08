"""Pytest configuration for papermind-host tests.

设置核心模块导入路径，使测试可以访问 memoryV2-core。
"""

import sys
from pathlib import Path

# 添加 memoryV2-core 到 Python 路径
core_path = Path(__file__).parent.parent.parent / "memoryV2-core"
if core_path.exists():
    sys.path.insert(0, str(core_path))
