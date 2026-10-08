"""Tests for server/memory_v2/temporal.py"""

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from server.memory_v2.temporal import normalize_relative_time, merge_time, _extract_clock
from server.memory_v2.contracts import TimeCandidate

# 固定参考时间：2026-07-31 15:30:00+08:00
TZ = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
REF = datetime(2026, 7, 31, 15, 30, 0, tzinfo=TZ)


# ─── 基础日偏移 ──────────────────────────────────────────────────────────────

def test_today():
    r = normalize_relative_time("今天去图书馆", REF)
    assert r.precision == "day"
    assert r.resolved_by == "deterministic"
    assert r.absolute_start is not None
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.date() == REF.date()


def test_tomorrow():
    r = normalize_relative_time("明天去游泳", REF)
    start_local = r.absolute_start.astimezone(TZ)
    # REF 是 7月31日，明天是 8月1日
    assert start_local.date() == datetime(2026, 8, 1).date()


def test_day_after_tomorrow():
    r = normalize_relative_time("后天聚会", REF)
    start_local = r.absolute_start.astimezone(TZ)
    # REF 是 7月31日，后天是 8月2日
    assert start_local.date() == datetime(2026, 8, 2).date()


def test_yesterday():
    r = normalize_relative_time("昨天买了鞋", REF)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.date().day == REF.date().day - 1


def test_day_before_yesterday():
    r = normalize_relative_time("前天我们出去逛街了", REF)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.date().day == REF.date().day - 2


# ─── 带时刻 ──────────────────────────────────────────────────────────────────

def test_tomorrow_with_hour():
    r = normalize_relative_time("明天3点开会", REF)
    assert r.precision == "minute"
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.hour == 3
    assert start_local.minute == 0


def test_tomorrow_afternoon():
    r = normalize_relative_time("明天下午3点", REF)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.hour == 15


def test_tomorrow_evening():
    r = normalize_relative_time("明天晚上8点", REF)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.hour == 20


def test_tomorrow_noon():
    r = normalize_relative_time("明天中午12点吃饭", REF)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.hour == 12


def test_tomorrow_dawn():
    r = normalize_relative_time("明天凌晨12点", REF)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.hour == 0


def test_tomorrow_with_minute():
    r = normalize_relative_time("明天下午3:30开始", REF)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.hour == 15
    assert start_local.minute == 30


# ─── UTC 存储 ────────────────────────────────────────────────────────────────

def test_result_stored_in_utc():
    r = normalize_relative_time("明天去图书馆", REF)
    assert r.absolute_start.tzinfo is not None
    # UTC 时间应比北京时间早8小时
    start_utc = r.absolute_start.astimezone(UTC)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_utc.hour == (start_local.hour - 8) % 24


# ─── 边界情况 ────────────────────────────────────────────────────────────────

def test_midnight_edge_today():
    """晚上 23:50 说"今天"，不应该跨到明天"""
    ref_late = datetime(2026, 7, 31, 23, 50, 0, tzinfo=TZ)
    r = normalize_relative_time("今天开会", ref_late)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.date().day == 31


def test_early_morning_today():
    """凌晨 0:30 说"今天"，是当天不是昨天"""
    ref_early = datetime(2026, 7, 31, 0, 30, 0, tzinfo=TZ)
    r = normalize_relative_time("今天要写论文", ref_early)
    start_local = r.absolute_start.astimezone(TZ)
    assert start_local.date().day == 31


def test_day_precision_has_end():
    """只有日期时，end = start + 1天"""
    r = normalize_relative_time("明天去图书馆", REF)
    assert r.absolute_end is not None
    delta = r.absolute_end - r.absolute_start
    assert delta.total_seconds() == 86400


def test_minute_precision_no_end():
    """有具体时刻时，end 为 None"""
    r = normalize_relative_time("明天下午3点", REF)
    assert r.precision == "minute"
    assert r.absolute_end is None


# ─── unknown 情况 ────────────────────────────────────────────────────────────

def test_unsupported_expression_returns_unknown():
    r = normalize_relative_time("这周五聚餐", REF)
    assert r.precision == "unknown"


def test_next_week_unknown():
    r = normalize_relative_time("下周三开会", REF)
    assert r.precision == "unknown"


def test_month_end_unknown():
    r = normalize_relative_time("月底交报告", REF)
    assert r.precision == "unknown"


def test_no_time_expression_returns_unknown():
    r = normalize_relative_time("我去游泳了", REF)
    assert r.precision == "unknown"
    assert r.resolved_by == "none"


# ─── 错误处理 ────────────────────────────────────────────────────────────────

def test_naive_reference_time_raises():
    naive = datetime(2026, 7, 31, 15, 30, 0)  # 无时区
    with pytest.raises(ValueError, match="必须带时区信息"):
        normalize_relative_time("明天", naive)


# ─── merge_time ──────────────────────────────────────────────────────────────

def test_merge_prefers_deterministic():
    deterministic = normalize_relative_time("明天去图书馆", REF)
    llm_fallback = TimeCandidate(
        original_expression="明天",
        absolute_start=datetime(2026, 8, 2, 0, 0, 0, tzinfo=UTC),  # 不同的日期
        precision="day",
        resolved_by="llm",
    )
    result = merge_time(deterministic, llm_fallback)
    assert result.resolved_by == "deterministic"


def test_merge_uses_llm_when_deterministic_unknown():
    unknown = TimeCandidate(precision="unknown")
    llm = TimeCandidate(
        absolute_start=datetime(2026, 8, 5, 0, 0, 0, tzinfo=UTC),
        precision="day",
        resolved_by="llm",
    )
    result = merge_time(unknown, llm)
    assert result.resolved_by == "llm"
