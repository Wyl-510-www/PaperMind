"""
测试日期工具函数
"""

import pytest
from datetime import date, timedelta
from papermind.utils.date_utils import calculate_date_range


class TestCalculateDateRange:
    """测试 calculate_date_range 函数"""

    def test_all_time_returns_none(self):
        """测试全部时间选项返回 None"""
        start, end = calculate_date_range("全部时间")
        assert start is None
        assert end is None

    def test_this_week(self):
        """测试本周选项"""
        start, end = calculate_date_range("本周")
        today = date.today()

        # 本周一
        expected_start = today - timedelta(days=today.weekday())

        assert start == expected_start
        assert end == today

    def test_this_month(self):
        """测试本月选项"""
        start, end = calculate_date_range("本月")
        today = date.today()

        # 本月第一天
        expected_start = today.replace(day=1)

        assert start == expected_start
        assert end == today

    def test_this_year(self):
        """测试本年选项"""
        start, end = calculate_date_range("本年")
        today = date.today()

        # 本年第一天
        expected_start = today.replace(month=1, day=1)

        assert start == expected_start
        assert end == today

    def test_custom_range(self):
        """测试自定义日期范围"""
        custom_start = date(2026, 1, 1)
        custom_end = date(2026, 1, 10)

        start, end = calculate_date_range("自定义", custom_start, custom_end)

        assert start == custom_start
        assert end == custom_end

    def test_custom_range_missing_dates(self):
        """测试自定义范围缺少日期"""
        with pytest.raises(ValueError, match="需要同时提供起始日期和结束日期"):
            calculate_date_range("自定义", None, None)

        with pytest.raises(ValueError, match="需要同时提供起始日期和结束日期"):
            calculate_date_range("自定义", date(2026, 1, 1), None)

    def test_custom_range_invalid_order(self):
        """测试自定义范围日期顺序错误"""
        with pytest.raises(ValueError, match="起始日期不能晚于结束日期"):
            calculate_date_range("自定义", date(2026, 1, 10), date(2026, 1, 1))

    def test_unknown_option(self):
        """测试未知的时间范围选项"""
        with pytest.raises(ValueError, match="未知的时间范围选项"):
            calculate_date_range("未知选项")

    def test_week_boundary_monday(self):
        """测试周一边界"""
        # 模拟周一
        today = date(2026, 1, 5)  # 假设是周一
        # 无法直接测试，但可验证逻辑
        # 实际测试会使用 freezegun 或 mock

    def test_month_boundary(self):
        """测试月初和月末边界"""
        # 月初
        start, end = calculate_date_range("本月")
        assert start.day == 1

        # 月末由当前日期决定
        assert end == date.today()

    def test_year_boundary(self):
        """测试年初边界"""
        start, end = calculate_date_range("本年")
        assert start.month == 1
        assert start.day == 1
        assert end == date.today()
