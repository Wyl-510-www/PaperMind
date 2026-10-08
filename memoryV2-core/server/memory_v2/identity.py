"""Identity 模块：构建 subject_id，区分 owner 和 subject

M2 实施：修复 Entity Subject 错误（056, 066, 057）。

0913 规范：
- 支持新旧两种 subject_id 格式（向后兼容）
- Entity 投影使用真实第三方主体，不是 current_user
- 提供解析和验证函数

设计原则：
- Owner（记忆归属用户）与 Subject（事实谈论对象）必须区分
- subject_id 格式必须明确标识实体类型和归属关系
- 向后兼容旧格式 "user@{user_id}"
"""
from __future__ import annotations
from typing import Optional


def build_subject_id_v2(
    canonical_name: str,
    is_current_user: bool,
    entity_type: str | None,
    owner_user_id: str,
    tenant_id: str,
    entity_id: str | None = None,
) -> str:
    """构建 subject_id，区分 owner 和 subject（新版本，显式参数）

    0913 规范：新格式，支持完整的 scope 信息
    B1 修复：使用 entity_id 作为唯一标识，防止同名不同实体合并

    subject_id 格式：
    - 用户自己：current_user:t:{tenant_id}:u:{user_id}
    - 第三方实体：entity:{entity_type}@{entity_id}:t:{tenant_id}:u:{owner_user_id}

    示例：
    - current_user:t:default:u:user123
    - entity:pet@ent_001:t:default:u:user123
    - entity:friend@ent_002:t:default:u:user123

    Args:
        canonical_name: 规范化名称（显示用，不作为唯一标识）
        is_current_user: 是否是当前用户本人
        entity_type: 实体类型（pet | friend | family | colleague | unknown）
        owner_user_id: 所有者用户 ID
        tenant_id: 租户 ID
        entity_id: 实体唯一 ID（必需，用于区分同名不同实体）

    Returns:
        str: subject_id（新格式）
    """
    if is_current_user:
        return f"current_user:t:{tenant_id}:u:{owner_user_id}"

    # 第三方实体：必须使用 entity_id
    if not entity_id:
        raise ValueError(
            f"entity_id is required for non-current_user entities (canonical_name={canonical_name})"
        )

    entity_type = entity_type or "unknown"
    # 格式: entity:{type}@{entity_id}:t:{tenant_id}:u:{owner_user_id}
    return f"entity:{entity_type}@{entity_id}:t:{tenant_id}:u:{owner_user_id}"


def build_subject_id_legacy(user_id: str) -> str:
    """构建旧格式 subject_id（向后兼容）

    0913 规范：支持旧格式 "user@{user_id}"

    Args:
        user_id: 用户 ID

    Returns:
        str: subject_id（旧格式）
    """
    return f"user@{user_id}"


def is_legacy_format(subject_id: str) -> bool:
    """检查是否是旧格式 subject_id

    0913 规范：旧格式为 "user@{user_id}"

    Args:
        subject_id: subject_id 字符串

    Returns:
        bool: 是否是旧格式
    """
    return subject_id.startswith("user@") and ":" not in subject_id


def normalize_subject_id(subject_id: str, tenant_id: str) -> str:
    """将旧格式 subject_id 转换为新格式（如果需要）

    0913 规范：向后兼容，但优先使用新格式

    Args:
        subject_id: subject_id 字符串（可能是旧格式）
        tenant_id: 租户 ID

    Returns:
        str: 新格式 subject_id
    """
    if is_legacy_format(subject_id):
        # 旧格式: user@{user_id}
        user_id = subject_id.split("@")[1]
        return f"current_user:t:{tenant_id}:u:{user_id}"

    # 已经是新格式，直接返回
    return subject_id


def build_subject_id(scope, subject_ref) -> str:
    """构建 subject_id（向后兼容入口）

    从 Scope 和 SubjectRef 对象构建 subject_id。
    这是兼容旧调用方式的入口函数。

    B1 修复：使用 SubjectRef.entity_id 作为唯一标识

    Args:
        scope: Scope 对象（包含 tenant_id, user_id, namespace）
        subject_ref: SubjectRef 对象（包含 canonical_name, is_current_user, kind, entity_id）

    Returns:
        str: subject_id
    """
    # 从 scope 提取参数
    tenant_id = scope.tenant_id
    user_id = scope.user_id

    # 从 subject_ref 提取参数
    canonical_name = subject_ref.canonical_name
    is_current_user = subject_ref.is_current_user
    entity_type = subject_ref.kind if not is_current_user else None
    entity_id = subject_ref.entity_id  # B1 修复：使用 entity_id

    # 调用新版本函数
    return build_subject_id_v2(
        canonical_name=canonical_name,
        is_current_user=is_current_user,
        entity_type=entity_type,
        owner_user_id=user_id,
        tenant_id=tenant_id,
        entity_id=entity_id,  # B1 修复：传递 entity_id
    )


def parse_subject_id(subject_id: str) -> dict[str, str | bool]:
    """解析 subject_id（支持新旧两种格式）

    0913 规范：向后兼容旧格式
    B1 修复：支持新的 entity_id 格式

    Args:
        subject_id: subject_id 字符串

    Returns:
        dict: 解析结果
            - is_current_user: bool
            - entity_type: str | None
            - entity_id: str | None
            - entity_name: str | None (已废弃，保留向后兼容)
            - user_id: str
            - tenant_id: str
            - format: str ("legacy" | "v2")
    """
    # 旧格式: user@{user_id}
    if is_legacy_format(subject_id):
        user_id = subject_id.split("@")[1]
        return {
            "is_current_user": True,
            "entity_type": None,
            "entity_id": None,
            "entity_name": None,
            "tenant_id": "unknown",  # 旧格式不包含 tenant_id
            "user_id": user_id,
            "format": "legacy"
        }

    parts = subject_id.split(":")

    # 新格式: current_user:t:{tenant_id}:u:{user_id}
    if subject_id.startswith("current_user:"):
        return {
            "is_current_user": True,
            "entity_type": None,
            "entity_id": None,
            "entity_name": None,
            "tenant_id": parts[2],
            "user_id": parts[4],
            "format": "v2"
        }

    # 新格式（B1）: entity:{entity_type}@{entity_id}:t:{tenant_id}:u:{owner_user_id}
    if subject_id.startswith("entity:") and "@" in parts[1]:
        # parts[1] = "{entity_type}@{entity_id}"
        entity_part = parts[1].split("@")
        entity_type = entity_part[0]
        entity_id = entity_part[1] if len(entity_part) > 1 else None

        return {
            "is_current_user": False,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": None,  # 新格式不在 subject_id 中存储 name
            "tenant_id": parts[3],
            "user_id": parts[5],
            "format": "v2"
        }

    # 旧实体格式: entity:{entity_type}:t:{tenant_id}:u:{owner_user_id}:e:{entity_name}
    if subject_id.startswith("entity:") and len(parts) == 8:
        return {
            "is_current_user": False,
            "entity_type": parts[1],
            "entity_id": None,  # 旧格式没有 entity_id
            "entity_name": parts[7],
            "tenant_id": parts[3],
            "user_id": parts[5],
            "format": "v2_legacy_entity"
        }

    # 未知格式
    return {
        "is_current_user": False,
        "entity_type": "unknown",
        "entity_id": None,
        "entity_name": "unknown",
        "tenant_id": "unknown",
        "user_id": "unknown",
        "format": "unknown"
    }


def validate_subject_id(subject_id: str) -> tuple[bool, Optional[str]]:
    """验证 subject_id 格式是否合法

    0913 规范：支持新旧两种格式
    B1 修复：支持新的 entity_id 格式

    Args:
        subject_id: subject_id 字符串

    Returns:
        (is_valid, error_message): 验证结果和错误信息
    """
    if not subject_id or not isinstance(subject_id, str):
        return False, "subject_id must be a non-empty string"

    # 旧格式验证
    if is_legacy_format(subject_id):
        if "@" not in subject_id:
            return False, "Legacy format must contain '@'"
        parts = subject_id.split("@")
        if len(parts) != 2:
            return False, "Legacy format must be 'user@{user_id}'"
        if not parts[1]:
            return False, "user_id cannot be empty in legacy format"
        return True, None

    # 新格式验证
    parts = subject_id.split(":")

    if subject_id.startswith("current_user:"):
        # 期望格式: current_user:t:{tenant_id}:u:{user_id}
        if len(parts) != 5:
            return False, "Invalid current_user format, expected 'current_user:t:{tenant_id}:u:{user_id}'"
        if parts[1] != "t" or parts[3] != "u":
            return False, "Invalid current_user format markers"
        if not parts[2] or not parts[4]:
            return False, "tenant_id and user_id cannot be empty"
        return True, None

    if subject_id.startswith("entity:"):
        # 新格式（B1）: entity:{type}@{entity_id}:t:{tenant_id}:u:{owner_id}
        if "@" in parts[1]:
            if len(parts) != 6:
                return False, "Invalid entity format, expected 'entity:{type}@{entity_id}:t:{tenant_id}:u:{owner_id}'"
            if parts[2] != "t" or parts[4] != "u":
                return False, "Invalid entity format markers"

            entity_part = parts[1].split("@")
            if len(entity_part) != 2 or not entity_part[0] or not entity_part[1]:
                return False, "entity_type and entity_id cannot be empty"

            if not parts[3] or not parts[5]:
                return False, "tenant_id and owner_id cannot be empty"
            return True, None

        # 旧实体格式: entity:{type}:t:{tenant_id}:u:{owner_id}:e:{name}
        if len(parts) == 8:
            if parts[2] != "t" or parts[4] != "u" or parts[6] != "e":
                return False, "Invalid legacy entity format markers"
            if not parts[1] or not parts[3] or not parts[5] or not parts[7]:
                return False, "entity_type, tenant_id, owner_id, and entity_name cannot be empty"
            return True, None

        return False, "Invalid entity format"

    return False, f"Unknown subject_id format: {subject_id}"


def get_subject_id_variants(subject_id: str) -> list[str]:
    """获取 subject_id 的所有可能格式（用于查询历史数据）

    B1 修复：支持新旧格式兼容查询，避免历史数据更新重复

    Args:
        subject_id: subject_id 字符串

    Returns:
        list[str]: 所有可能的 subject_id 变体（包含原值）
    """
    variants = [subject_id]

    # 如果是新格式 current_user，添加旧格式变体
    if subject_id.startswith("current_user:t:"):
        parts = subject_id.split(":")
        if len(parts) >= 5:
            user_id = parts[4]
            legacy_format = f"user@{user_id}"
            variants.append(legacy_format)

    # 如果是旧格式 user@，添加新格式变体
    if is_legacy_format(subject_id):
        user_id = subject_id.split("@")[1]
        # 需要 tenant_id，但旧格式不包含，这里无法生成完整新格式
        # 只能在有 tenant_id 上下文时调用 normalize_subject_id

    return variants


# 实体类型枚举
ENTITY_TYPES = {
    "pet",       # 宠物
    "friend",    # 朋友
    "family",    # 家人
    "colleague", # 同事
    "neighbor",  # 邻居
    "unknown",   # 未知
}
