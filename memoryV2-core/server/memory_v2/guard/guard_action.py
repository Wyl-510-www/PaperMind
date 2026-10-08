"""
Guard Action 枚举 - M4 批次

定义 Guard 流水线的所有可能动作
"""

from enum import Enum


class GuardAction(str, Enum):
    """Guard 决策动作"""

    KEEP = "keep"                   # 通过，保留回答
    DELETE = "delete"               # 删除违规部分
    REGENERATE = "regenerate"       # 重新生成
    TO_QUESTION = "to_question"     # 转为澄清问题


class GuardStatus(str, Enum):
    """Guard 执行状态"""

    NOT_RUN = "not_run"             # 未执行
    PASSED = "passed"               # 通过
    VIOLATED = "violated"           # 违规
    ERROR = "error"                 # 执行错误
