"""MigrationMapper：旧 mem0 记忆 → 新 Memory V2 契约的分类映射（纯函数）。

旧 mem0 记忆结构简单：{memory_id, content, created_at, metadata?}，无 memory_type/modality。
MigrationMapper 基于关键词 + metadata 启发式分类，输出 MemoryRecord 或 Event，
无法分类或应跳过（如 joke）时返回 None。

⚠️ 启发式分类不保证 100% 准确，需人工 review sample（抽 5% 检查，见 Phase 4A spec）。

纯函数（staticmethod），无 I/O，单独可测。
见 Phase 4A spec、ADR 0008（模块命名）。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..models import Event, MemoryRecord


# 时间词/日期正则（含则判为 Event）
_TIME_PATTERNS = [
    r"今天|明天|后天|昨天|前天",
    r"下?周[一二三四五六日天末]",
    r"下?个?月[初中底]",
    r"\d{4}-\d{1,2}-\d{1,2}",
    r"\d{1,2}[:：]\d{2}",
    r"\d{1,2}月\d{1,2}[日号]",
]

# 事件类型关键词
_EVENT_TYPE_KEYWORDS = {
    "meeting": ["开会", "会议", "例会"],
    "appointment": ["约会", "见面", "预约", "看医生"],
    "party": ["聚会", "派对", "聚餐"],
    "travel": ["旅游", "旅行", "出差"],
}

# modality 推断关键词
_PLAN_KEYWORDS = ["想学", "打算", "计划", "准备", "要去学"]
_WISH_KEYWORDS = ["希望", "期待", "想要", "梦想", "但愿"]

# semantic 谓词关键词
_DIET_KEYWORDS = ["喜欢吃", "不喜欢吃", "爱吃", "不吃", "口味", "香菜", "甜食", "咸"]
_PREFERENCE_KEYWORDS = ["喜欢", "不喜欢", "讨厌", "爱好", "偏好"]
_ALLERGY_KEYWORDS = ["过敏", "忌口", "不能吃"]
_NICKNAME_KEYWORDS = ["昵称", "绰号", "外号", "叫我"]
_RELATIONSHIP_KEYWORDS = ["朋友", "家人", "姐姐", "妹妹", "哥哥", "弟弟", "妈妈", "爸爸", "宠物", "同事", "老板"]

# 默认置信度（旧记忆无 confidence 时）
DEFAULT_CONFIDENCE = 0.7


class MigrationMapper:
    """旧记忆 → 新契约的分类映射器（纯函数）。"""

    @staticmethod
    def classify(
        old_memory: dict[str, Any],
        tenant_id: str,
        user_id: str,
    ) -> MemoryRecord | Event | None:
        """分类映射。返回 MemoryRecord / Event / None（None 表示跳过，如 joke）。"""
        content = old_memory.get("content", "").strip()
        if not content:
            return None

        metadata = old_memory.get("metadata", {}) or {}

        # 跳过 joke/quote（不可作为用户事实）
        if metadata.get("modality") in ("joke", "quote"):
            return None

        created_at = MigrationMapper._parse_created_at(old_memory.get("created_at"))
        confidence = float(metadata.get("confidence", DEFAULT_CONFIDENCE))

        # 含时间词 → Event
        if MigrationMapper._has_time_word(content):
            return MigrationMapper._to_event(
                content, tenant_id, user_id, created_at, old_memory
            )

        # 否则 → MemoryRecord（semantic / relationship）
        return MigrationMapper._to_memory_record(
            content, tenant_id, user_id, created_at, confidence, old_memory
        )

    # ─── Event 分支 ─────────────────────────────────────────────────────

    @staticmethod
    def _to_event(
        content: str,
        tenant_id: str,
        user_id: str,
        created_at: datetime,
        old_memory: dict[str, Any],
    ) -> Event:
        """构造 Event。event_type 按关键词推断，缺省 appointment。"""
        event_type = "appointment"
        for etype, keywords in _EVENT_TYPE_KEYWORDS.items():
            if any(kw in content for kw in keywords):
                event_type = etype
                break

        return Event(
            event_id=str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            namespace="user_memory",
            event_type=event_type,
            title=content,
            status="scheduled",
            version=1,
            source_turn_id=old_memory.get("memory_id"),
            created_at=created_at,
            updated_at=created_at,
        )

    # ─── MemoryRecord 分支 ─────────────────────────────────────────────

    @staticmethod
    def _to_memory_record(
        content: str,
        tenant_id: str,
        user_id: str,
        created_at: datetime,
        confidence: float,
        old_memory: dict[str, Any],
    ) -> MemoryRecord:
        """构造 MemoryRecord。memory_type/predicate/modality 按关键词推断。"""
        memory_type, predicate = MigrationMapper._infer_type_predicate(content)
        modality = MigrationMapper._infer_modality(content)

        return MemoryRecord(
            memory_id=str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            namespace="user_memory",
            memory_type=memory_type,
            predicate=predicate,
            subject_id="user",
            text_zh=content,
            modality=modality,
            status="active",
            confidence=confidence,
            importance=0.5,
            version=1,
            index_status="pending",
            source_turn_id=old_memory.get("memory_id"),
            created_at=created_at,
            updated_at=created_at,
        )

    @staticmethod
    def _infer_type_predicate(content: str) -> tuple[str, str]:
        """推断 memory_type 和 predicate。"""
        # 关系类
        if any(kw in content for kw in _RELATIONSHIP_KEYWORDS):
            return ("relationship", "relation")
        # 昵称
        if any(kw in content for kw in _NICKNAME_KEYWORDS):
            return ("semantic", "nickname")
        # 过敏
        if any(kw in content for kw in _ALLERGY_KEYWORDS):
            return ("semantic", "diet.allergy")
        # 饮食偏好
        if any(kw in content for kw in _DIET_KEYWORDS):
            return ("semantic", "diet.preference")
        # 一般偏好
        if any(kw in content for kw in _PREFERENCE_KEYWORDS):
            return ("semantic", "preference")
        # 缺省
        return ("semantic", "general")

    @staticmethod
    def _infer_modality(content: str) -> str:
        """推断 modality：plan/wish/fact。"""
        if any(kw in content for kw in _PLAN_KEYWORDS):
            return "plan"
        if any(kw in content for kw in _WISH_KEYWORDS):
            return "wish"
        return "fact"

    # ─── 辅助 ───────────────────────────────────────────────────────────

    @staticmethod
    def _has_time_word(content: str) -> bool:
        """判断内容是否含时间词/日期。"""
        return any(re.search(p, content) for p in _TIME_PATTERNS)

    @staticmethod
    def _parse_created_at(value: Any) -> datetime:
        """解析 created_at，缺省当前 UTC。"""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def content_hash(content: str) -> str:
        """稳定 content hash，用于迁移幂等去重。"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
