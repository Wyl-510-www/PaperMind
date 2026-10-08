"""昵称版本管理。

昵称真值由 Memory V2 管理（独立 memory_v2_nickname 表）。
临时昵称自然日有效期（23:59:59），永久昵称无 valid_to。
修复方案 2.7 节指出的 DSM 昵称重启续期 bug。
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timezone

from sqlalchemy.orm import Session

from ..models import Nickname
from .repository import Repository, now_utc


class NicknameStore:
    """昵称版本管理"""

    def __init__(self, session: Session):
        self.session = session
        self.repo = Repository(session)

    def set_nickname(
        self,
        tenant_id: str,
        user_id: str,
        value: str,
        nickname_type: str,  # "temporary" / "permanent"
        reference_time: datetime,
    ) -> str:
        """设置昵称（新版本）。

        Args:
            tenant_id/user_id: 用户标识
            value: 昵称值
            nickname_type: temporary / permanent
            reference_time: 参考时间（带时区）。临时昵称的有效期基于此计算自然日 23:59:59

        Returns:
            nickname_id

        Raises:
            ValueError: reference_time 无时区
        """
        if reference_time.tzinfo is None:
            raise ValueError("reference_time 必须带时区")

        # 旧 active 版本标 superseded
        old_active = self.session.query(Nickname).filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
            status="active",
        ).first()
        if old_active:
            old_active.status = "superseded"
            old_active.updated_at = now_utc()

        # 计算有效期
        valid_from = now_utc()
        if nickname_type == "temporary":
            # 自然日 23:59:59（reference_time 所在日期的结束）
            ref_date = reference_time.date()
            end_of_day = datetime.combine(ref_date, time(23, 59, 59), tzinfo=reference_time.tzinfo)
            valid_to = end_of_day.astimezone(timezone.utc)
        else:
            valid_to = None  # 永久

        nickname_id = f"nick-{uuid.uuid4().hex[:16]}"
        version = (old_active.version + 1) if old_active else 1

        nick = Nickname(
            nickname_id=nickname_id,
            tenant_id=tenant_id,
            user_id=user_id,
            value=value,
            type=nickname_type,
            valid_from=valid_from,
            valid_to=valid_to,
            status="active",
            version=version,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        self.session.add(nick)
        self.repo._write_outbox(nickname_id, "upsert", {"nickname_id": nickname_id, "value": value})
        self.repo.commit()
        return nickname_id

    def get_active_nickname(
        self,
        tenant_id: str,
        user_id: str,
        now: datetime,
    ) -> str | None:
        """获取当前有效昵称。

        Args:
            tenant_id/user_id: 用户标识
            now: 当前时间（带时区），用于过滤过期昵称

        Returns:
            昵称值，无有效昵称返回 None
        """
        if now.tzinfo is None:
            raise ValueError("now 必须带时区")

        # 归一化到 UTC 再比较（valid_to 存的是 UTC，SQLite 不处理时区）
        now_utc_val = now.astimezone(timezone.utc)

        nick = self.session.query(Nickname).filter(
            Nickname.tenant_id == tenant_id,
            Nickname.user_id == user_id,
            Nickname.status == "active",
        ).filter(
            # valid_to 是最后有效时刻（23:59:59），用 >= 使该时刻仍有效
            (Nickname.valid_to.is_(None)) | (Nickname.valid_to >= now_utc_val)
        ).first()

        return nick.value if nick else None

    def delete_nickname(
        self,
        tenant_id: str,
        user_id: str,
    ) -> bool:
        """删除昵称（标记 deleted）。

        Returns:
            True 成功，False 无 active 昵称
        """
        result = self.session.query(Nickname).filter(
            Nickname.tenant_id == tenant_id,
            Nickname.user_id == user_id,
            Nickname.status == "active",
        ).update(
            {
                "status": "deleted",
                "updated_at": now_utc(),
            },
            synchronize_session=False,
        )

        if result > 0:
            # outbox 记录删除操作
            self.repo._write_outbox(f"{tenant_id}:{user_id}", "delete", {"action": "delete_nickname"})
            self.repo.commit()
            return True
        return False
