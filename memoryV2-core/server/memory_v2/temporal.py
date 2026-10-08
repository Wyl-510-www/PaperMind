"""Deterministic relative-time normalization for Chinese expressions.

只处理高置信度中文时间表达。无法确定的返回 precision="unknown"，不猜测。
调用方必须提供带时区的 reference_time（Asia/Shanghai）。
存储结果统一用 UTC。
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .contracts import TimeCandidate


# 相对日期偏移（以 reference_time 当天为基准）
DAY_OFFSETS: dict[str, int] = {
    "前天": -2,
    "昨天": -1,
    "今天": 0,
    "明天": 1,
    "后天": 2,
}

# 时刻解析正则：匹配 "3点"、"3时"、"3:30"、"3点20" 等格式
_CLOCK_RE = re.compile(
    r"(?P<hour>\d{1,2})"
    r"(?:点|时|:)"
    r"(?P<minute>\d{1,2})?"
)

# 下午/晚上/傍晚 → hour+12（小时 < 12 时）
_PM_MARKERS = ("下午", "晚上", "傍晚")
# 中午 → 同上（但 < 11 才加）
_NOON_MARKERS = ("中午",)
# 凌晨 → hour=12 时视为 0
_DAWN_MARKERS = ("凌晨",)

# Phase 1 不支持的模糊时间表达（标记为 unknown，不猜测）
_UNSUPPORTED_EXPRESSIONS = (
    "这周", "本周", "下周", "上周",
    "这个月", "下个月", "上个月", "月底", "月初",
    "最近", "经常", "上次", "那天",
)


def normalize_relative_time(
    text: str,
    reference_time: datetime,
    timezone_name: str = "Asia/Shanghai",
) -> TimeCandidate:
    """将中文相对时间表达归一化为绝对时间（UTC）。

    只处理高置信度表达（前天/昨天/今天/明天/后天 + 可选时刻）。
    无法唯一确定的返回 TimeCandidate(precision="unknown")。

    Args:
        text: 包含时间表达的文本，如 "明天下午3点开会"
        reference_time: 消息接收时间，必须带时区（aware datetime）
        timezone_name: 用户时区，默认 Asia/Shanghai

    Returns:
        TimeCandidate，precision="unknown" 表示无法确定

    Raises:
        ValueError: reference_time 不带时区时抛出
    """
    if reference_time.tzinfo is None:
        raise ValueError(
            "reference_time 必须带时区信息。"
            "请使用 datetime.now(ZoneInfo('Asia/Shanghai')) 或带 tzinfo 的 datetime。"
        )

    local_tz = ZoneInfo(timezone_name)
    local_ref = reference_time.astimezone(local_tz)

    # 检查是否包含不支持的模糊表达
    for unsupported in _UNSUPPORTED_EXPRESSIONS:
        if unsupported in text:
            return TimeCandidate(
                original_expression=unsupported,
                precision="unknown",
                resolved_by="deterministic",
            )

    # 匹配日偏移关键词（前天/昨天/今天/明天/后天）
    for expression, offset in DAY_OFFSETS.items():
        if expression not in text:
            continue

        target_date = local_ref.date() + timedelta(days=offset)
        clock = _extract_clock(text)

        if clock is None:
            # 只有日期，精度为天
            start = datetime.combine(target_date, time.min, tzinfo=local_tz)
            end = start + timedelta(days=1)
            precision = "day"
        else:
            hour, minute = clock
            start = datetime.combine(
                target_date,
                time(hour=hour, minute=minute),
                tzinfo=local_tz,
            )
            end = None
            precision = "minute"

        return TimeCandidate(
            original_expression=expression,
            absolute_start=start.astimezone(timezone.utc),
            absolute_end=end.astimezone(timezone.utc) if end else None,
            precision=precision,
            resolved_by="deterministic",
        )

    # 没有匹配到任何高置信度表达
    return TimeCandidate(precision="unknown", resolved_by="none")


def merge_time(
    deterministic: TimeCandidate,
    llm_extracted: TimeCandidate,
) -> TimeCandidate:
    """合并代码解析结果和 LLM 抽取结果，代码结果优先。

    LLM 结果作为 fallback，只有代码无法解析时才使用。
    """
    if deterministic.absolute_start is not None:
        return deterministic
    return llm_extracted


def _extract_clock(text: str) -> tuple[int, int] | None:
    """从文本中提取时刻（小时, 分钟），处理上午/下午/凌晨修正。

    Returns:
        (hour, minute) 元组，无法解析时返回 None
    """
    match = _CLOCK_RE.search(text)
    if not match:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)

    # 下午/晚上/傍晚：小时 < 12 时加 12
    if any(marker in text for marker in _PM_MARKERS) and hour < 12:
        hour += 12
    # 中午：小时 < 11 时加 12（避免把"中午12点"变成24点）
    elif any(marker in text for marker in _NOON_MARKERS) and hour < 11:
        hour += 12
    # 凌晨：12点视为0点
    elif any(marker in text for marker in _DAWN_MARKERS) and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return hour, minute
