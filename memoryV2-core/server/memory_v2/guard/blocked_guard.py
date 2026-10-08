"""
Blocked Guard - M4 批次

功能：
1. 检查回答是否使用了已删除的禁止值
2. 防止旧昵称、已删除敏感信息出现在回答中

修复的问题：
- Case 100: 使用旧昵称"阿晚"（已通过 DELETE 操作标记为 blocked）
"""

from typing import Optional
from pydantic import BaseModel
import re


class BlockedValue(BaseModel):
    """被阻止的值"""
    value: str
    predicate: str  # 来自哪个谓词（如 nickname.current）
    blocked_at: str  # ISO 时间戳
    reason: Optional[str] = None


class BlockedCheckResult(BaseModel):
    """Blocked 检查结果"""
    ok: bool
    blocked_values: list[str]  # 检测到的被阻止值
    locations: list[str]  # 违规位置


class BlockedGuard:
    """Blocked Guard - 检查已删除的禁止值"""

    def __init__(self, db_session):
        self.db = db_session

    async def verify(
        self,
        answer: str,
        tenant_id: str,
        user_id: str,
    ) -> BlockedCheckResult:
        """验证回答是否使用了被阻止的值

        Args:
            answer: 生成的回答
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            BlockedCheckResult
        """
        # 1. 查询所有被阻止的值
        blocked_values = await self._get_blocked_values(tenant_id, user_id)

        if not blocked_values:
            return BlockedCheckResult(ok=True, blocked_values=[], locations=[])

        # 2. 检查回答中是否包含这些值
        found_values = []
        locations = []

        for blocked in blocked_values:
            if blocked.value.lower() in answer.lower():
                found_values.append(blocked.value)

                # 找到违规位置
                pattern = re.compile(re.escape(blocked.value), re.IGNORECASE)
                matches = pattern.finditer(answer)

                for match in matches:
                    start = max(0, match.start() - 10)
                    end = min(len(answer), match.end() + 10)
                    location = answer[start:end]
                    locations.append(f"...{location}...")

        if found_values:
            return BlockedCheckResult(
                ok=False,
                blocked_values=found_values,
                locations=locations,
            )

        return BlockedCheckResult(ok=True, blocked_values=[], locations=[])

    async def _get_blocked_values(
        self,
        tenant_id: str,
        user_id: str,
    ) -> list[BlockedValue]:
        """查询所有被阻止的值

        被阻止的值来自：
        1. DELETE 操作标记的 blocked_value
        2. superseded 的旧值（如旧昵称）
        """
        from server.memory_v2.store.models import MemoryRecord

        blocked_list = []

        # 查询已删除且有 blocked_value 的记录
        # 注意：需要数据库支持 blocked_value 字段（M2 引入）
        deleted_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.active == False,
            MemoryRecord.deleted_at.isnot(None),
        ).all()

        for record in deleted_records:
            # 高敏谓词：nickname, diet.dislike, contact.private
            HIGH_SENSITIVITY_PREDICATES = {
                "nickname.current",
                "diet.dislike",
                "contact.phone",
                "contact.email",
            }

            if record.predicate in HIGH_SENSITIVITY_PREDICATES:
                blocked_list.append(BlockedValue(
                    value=record.value,
                    predicate=record.predicate,
                    blocked_at=record.deleted_at.isoformat() if record.deleted_at else "",
                    reason=f"已删除的 {record.predicate}",
                ))

        # 查询被 supersede 的旧值
        superseded_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.active == False,
            MemoryRecord.superseded_by.isnot(None),
        ).all()

        for record in superseded_records:
            # 旧昵称特别需要阻止
            if record.predicate == "nickname.current":
                blocked_list.append(BlockedValue(
                    value=record.value,
                    predicate=record.predicate,
                    blocked_at=record.superseded_at.isoformat() if hasattr(record, 'superseded_at') and record.superseded_at else "",
                    reason=f"旧昵称（已更新为新值）",
                ))

        return blocked_list
