"""UPDATE 语义检测器

检测用户输入是否包含"更新"语义，用于触发记忆更新而非新增。

更新语义的典型场景：
- "我以前喜欢苹果，现在改成喜欢橙子"
- "我现在不喜欢苹果了"
- "我的手机号改成 139..."
- "我已经不住在北京了，搬到上海了"
"""

from __future__ import annotations


class UpdateDetector:
    """更新语义检测器"""

    # 更新触发词列表
    UPDATE_TRIGGERS = [
        # 时间对比词
        "现在", "改成", "改为", "变成", "换成",
        "不再", "已经不", "不再是",
        "以前", "之前", "过去", "原来",
        # 否定词（用于否定之前的偏好）
        "不喜欢了", "不爱了", "不想了",
        # 替换词
        "替换", "更换", "修改", "更新",
    ]

    # 并列词列表（不应触发 UPDATE）
    PARALLEL_KEYWORDS = [
        "还", "也", "另外", "同时", "以及",
        "而且", "并且", "再加上", "加上",
    ]

    # 时间对比模式（同时出现时强烈暗示更新）
    TIME_COMPARISON_PATTERNS = [
        ("以前", "现在"),
        ("之前", "目前"),
        ("之前", "现在"),
        ("过去", "现在"),
        ("原来", "现在"),
    ]

    @classmethod
    def is_update_semantics(cls, user_input: str) -> bool:
        """检测用户输入是否包含更新语义

        Args:
            user_input: 用户输入文本

        Returns:
            True 表示检测到更新语义，False 表示普通新增

        Examples:
            >>> UpdateDetector.is_update_semantics("我喜欢吃苹果")
            False

            >>> UpdateDetector.is_update_semantics("我现在不喜欢苹果了，改成喜欢橙子")
            True

            >>> UpdateDetector.is_update_semantics("我还喜欢吃橙子")
            False

            >>> UpdateDetector.is_update_semantics("我以前喜欢苹果，现在喜欢橙子")
            True
        """
        # 优先检测并列词（如果存在并列词，不是更新）
        for parallel_word in cls.PARALLEL_KEYWORDS:
            if parallel_word in user_input:
                return False

        # 检测时间对比模式（强烈暗示更新）
        for before_word, after_word in cls.TIME_COMPARISON_PATTERNS:
            if before_word in user_input and after_word in user_input:
                return True

        # 检测更新触发词
        for trigger in cls.UPDATE_TRIGGERS:
            if trigger in user_input:
                return True

        return False

    @classmethod
    def get_update_confidence(cls, user_input: str) -> float:
        """计算更新语义的置信度（0.0 - 1.0）

        Args:
            user_input: 用户输入文本

        Returns:
            置信度分数，0.0 表示完全不是更新，1.0 表示强烈更新语义

        Examples:
            >>> UpdateDetector.get_update_confidence("我喜欢吃苹果")
            0.0

            >>> UpdateDetector.get_update_confidence("我现在喜欢橙子")
            0.6

            >>> UpdateDetector.get_update_confidence("我以前喜欢苹果，现在改成喜欢橙子")
            1.0
        """
        confidence = 0.0

        # 如果有并列词，置信度归零
        for parallel_word in cls.PARALLEL_KEYWORDS:
            if parallel_word in user_input:
                return 0.0

        # 时间对比模式：最强信号
        for before_word, after_word in cls.TIME_COMPARISON_PATTERNS:
            if before_word in user_input and after_word in user_input:
                confidence = max(confidence, 1.0)

        # 多个更新触发词：中等信号
        trigger_count = sum(1 for trigger in cls.UPDATE_TRIGGERS if trigger in user_input)
        if trigger_count >= 2:
            confidence = max(confidence, 0.8)
        elif trigger_count == 1:
            confidence = max(confidence, 0.6)

        return confidence


# 便捷函数
def is_update_operation(user_input: str) -> bool:
    """检测是否为更新操作的便捷函数

    Args:
        user_input: 用户输入文本

    Returns:
        True 表示更新操作，False 表示新增操作
    """
    return UpdateDetector.is_update_semantics(user_input)
