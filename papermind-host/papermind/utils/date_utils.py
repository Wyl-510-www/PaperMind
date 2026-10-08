"""
日期工具函数

提供时间范围计算功能，支持本周/本月/本年/自定义范围。
"""

from datetime import date, timedelta
from typing import Optional, Tuple


def calculate_date_range(
    range_option: str,
    custom_start: Optional[date] = None,
    custom_end: Optional[date] = None,
) -> Tuple[Optional[date], Optional[date]]:
    """根据时间范围选项计算起止日期

    Args:
        range_option: 时间范围选项（"全部时间", "本周", "本月", "本年", "自定义"）
        custom_start: 自定义起始日期（仅当 range_option="自定义" 时使用）
        custom_end: 自定义结束日期（仅当 range_option="自定义" 时使用）

    Returns:
        (start_date, end_date) 元组，None 表示不限制

    Raises:
        ValueError: 未知的时间范围选项或自定义日期无效

    Examples:
        >>> calculate_date_range("全部时间")
        (None, None)

        >>> calculate_date_range("本周")  # 假设今天是周三
        (datetime.date(2026, 1, 13), datetime.date(2026, 1, 15))

        >>> calculate_date_range("自定义", date(2026, 1, 1), date(2026, 1, 10))
        (datetime.date(2026, 1, 1), datetime.date(2026, 1, 10))
    """
    today = date.today()

    if range_option == "全部时间":
        return None, None

    elif range_option == "本周":
        # 本周一作为起始日期
        start = today - timedelta(days=today.weekday())
        return start, today

    elif range_option == "本月":
        # 本月第一天
        start = today.replace(day=1)
        return start, today

    elif range_option == "本年":
        # 本年第一天
        start = today.replace(month=1, day=1)
        return start, today

    elif range_option == "自定义":
        if custom_start is None or custom_end is None:
            raise ValueError("自定义日期范围需要同时提供起始日期和结束日期")
        if custom_start > custom_end:
            raise ValueError("起始日期不能晚于结束日期")
        return custom_start, custom_end

    else:
        raise ValueError(f"未知的时间范围选项: {range_option}")
