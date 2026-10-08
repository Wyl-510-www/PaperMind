"""
Prompt 构建器 - M4 批次

功能：
1. 构建生成 Prompt，包含结构化约束
2. 注入 Policy 约束（禁用词、句数限制）
3. 注入 Critical 约束（代词、性别）
4. 注入 Evidence

解决的问题：
- Critical、Policy 当前只有文本 Evidence，未直接传结构
- LLM 生成时未明确收到约束
"""

from typing import Optional


def build_generation_prompt(
    user_query: str,
    evidence_pack,  # EvidencePack
    policy_profile,  # PolicyProfile
    critical_profile,  # CriticalProfile
    regeneration_hint: Optional[str] = None,
) -> str:
    """构建生成 Prompt

    Args:
        user_query: 用户查询
        evidence_pack: 证据包（包含 Subject Context）
        policy_profile: Policy 配置
        critical_profile: Critical 配置
        regeneration_hint: 重生成提示

    Returns:
        完整的生成 Prompt
    """
    prompt = f"用户问题：{user_query}\n\n"

    # 1. Subject Context（如果有）
    if evidence_pack.subject_context:
        prompt += f"{evidence_pack.subject_context}\n"

    # 2. Evidence 注入
    if evidence_pack.evidence_texts:
        prompt += "## 【记忆证据】\n"
        for ev in evidence_pack.evidence_texts:
            prompt += f"- {ev}\n"
        prompt += "\n"

    # 3. Policy 约束（关键：结构化注入）
    if policy_profile:
        policy_text = policy_profile.to_prompt()
        prompt += policy_text + "\n"

    # 4. Critical 约束（关键：结构化注入）
    if critical_profile:
        critical_text = critical_profile.to_prompt()
        prompt += critical_text + "\n"

    # 5. 重生成提示
    if regeneration_hint:
        prompt += f"## 【重要提示】\n{regeneration_hint}\n\n"

    # 6. 最终指示
    prompt += """
请根据以上约束回答用户问题。注意：
- 如果记忆证据不足，请直接询问用户，不要编造。
- 严格遵守行为准则和关键信息约束。
- 回答要简洁、准确、自然。
"""

    return prompt


def build_subject_context(
    subject_id: str,
    entity_name: Optional[str] = None,
) -> str:
    """构建 Subject 上下文约束

    用于修复 Case 056/066：实体读到但主体反转

    Args:
        subject_id: Subject ID
        entity_name: 实体名称（如"福妹"、"小乔"）

    Returns:
        Subject 约束文本
    """
    if "current_user:" in subject_id:
        return "【主体约束】\n- 以下信息是关于用户本人的\n"

    elif "entity:" in subject_id and entity_name:
        # 解析实体类型
        if ":pet:" in subject_id or "entity:pet:" in subject_id:
            entity_type = "宠物"
        elif ":friend:" in subject_id or "entity:friend:" in subject_id:
            entity_type = "朋友"
        elif ":family:" in subject_id or "entity:family:" in subject_id:
            entity_type = "家人"
        else:
            entity_type = "实体"

        # 使用 format 而不是 f-string 来避免中文引号问题
        constraint = "【主体约束】\n"
        constraint += '- 以下信息是关于用户的{}"{}"的，不是用户本人的\n'.format(entity_type, entity_name)
        constraint += '- 回答时请明确区分用户和"{}"\n'.format(entity_name)
        return constraint

    return ""


def build_regeneration_hint(
    guard_trace,  # GuardTrace
) -> str:
    """根据 Guard Trace 构建重生成提示

    Args:
        guard_trace: Guard 追踪结果

    Returns:
        重生成提示文本
    """
    if not guard_trace or not guard_trace.violations:
        return ""

    hint = "上一次回答存在以下问题，请重新生成时避免：\n"
    for v in guard_trace.violations:
        hint += f"- {v.description}\n"

    return hint


# Fact extraction prompt for mem0
USER_FACT_EXTRACTION_PROMPT_ZH = """
你是一个记忆提取专家。请从对话中提取关于用户的事实性信息。

提取要点：
1. 用户的基本信息（姓名、年龄、职业等）
2. 用户的喜好和兴趣
3. 用户的习惯和行为模式
4. 用户提到的重要事件和经历
5. 用户的关系网络（家人、朋友、宠物等）

要求：
- 只提取明确的事实，不要推断
- 每个事实应该简洁明确
- 使用用户的原话或准确的表述

输出格式：
请以 JSON 格式返回提取的事实，格式如下：
{"facts": ["事实1", "事实2", "事实3"]}

如果没有事实可提取，返回：{"facts": []}
"""

# Update memory prompt for mem0
UPDATE_MEMORY_PROMPT_ZH = """
你是一个记忆更新专家。请根据新的对话内容更新已有的记忆。

更新原则：
1. 如果新信息与旧记忆冲突，用新信息替换
2. 如果新信息是旧记忆的补充，合并信息
3. 如果新信息与旧记忆无关，保持旧记忆不变
4. 保持记忆的准确性和一致性

要求：
- 明确指出哪些记忆需要更新
- 说明更新的理由
- 保持记忆的简洁性
"""
