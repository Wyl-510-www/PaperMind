"""Real LLM judge：验证生成的主张是否有 EvidencePack 支撑。

实现 claim_guard.JudgeProtocol。用 LLM 判断主张能否映射到 evidence_pack 里的记忆，
返回 GuardAction（KEEP/DELETE/TO_QUESTION/REGENERATE）。

配置（server/core/settings.py:Config_Bailian）：
- API_KEY（BAILIAN_API_KEY）
- MODEL_QWEN（qwen-plus，或可配置其他模型）
- MODEL_QWEN_URL（OpenAI 兼容端点）

Prompt 设计：
- System: 你是记忆验证专家，判断主张是否有证据支撑
- User: 提供 claim_text + evidence_pack.items，要求返回 JSON：{"action": "keep/delete/to_question/regenerate", "reason": "..."}
"""

from __future__ import annotations

import json
import logging

from openai import OpenAI

from server.core.settings import Config_Bailian
from ..contracts import EvidencePack, GuardAction

logger = logging.getLogger(__name__)

# Judge prompt：要求 LLM 返回结构化 JSON
JUDGE_SYSTEM_PROMPT = """你是记忆验证专家。系统会给你一个 AI 角色对用户说出的「主张」和一份「证据列表」。
你需要判断这个主张是否能从证据中找到支撑。

重要上下文：
- 主张是 AI 角色在对话中对「用户」说的话，其中的「你」指代用户本人。
- 证据中的「用户」也指代同一个用户。因此「你喜欢X」与证据「用户喜欢X」指的是同一主体，应视为一致。
- 只要主张的核心事实能在证据中找到对应（即使措辞不同、主语用「你」或「用户」），就算有支撑。

返回 JSON 格式（不要任何其他文本）：
{
  "action": "keep" | "delete" | "to_question" | "regenerate",
  "reason": "简短理由"
}

动作选择规则：
- keep：主张的核心事实有证据支撑（允许措辞差异、你/用户 指代同一人）
- delete：主张与证据矛盾，或证据里完全没有相关事实
- to_question：证据部分相关但不足以确认，建议改成询问
- regenerate：主张有相关性但表述明显不当，建议重生成
"""


class RealJudge:
    """claim_guard.JudgeProtocol 的真实实现，用 LLM 做映射判断。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        """
        Args:
            api_key: 百炼 API key，默认从 Config_Bailian.API_KEY 读取
            model: LLM 模型名，默认 qwen-plus
            base_url: OpenAI 兼容端点，默认百炼 compatible-mode
        """
        self.api_key = api_key or Config_Bailian.API_KEY
        if not self.api_key:
            raise ValueError("RealJudge requires api_key (from BAILIAN_API_KEY env var)")
        self.model = model or Config_Bailian.MODEL_QWEN
        self.base_url = base_url or Config_Bailian.MODEL_QWEN_URL

        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def judge(self, claim_text: str, evidence_pack: EvidencePack) -> GuardAction:
        """判断主张是否能映射到 evidence_pack，返回处置动作。

        Args:
            claim_text: 待验证的主张（如"你之前说过喜欢猫"）
            evidence_pack: 检索到的证据包

        Returns:
            GuardAction（KEEP/DELETE/TO_QUESTION/REGENERATE）
        """
        # 构造 evidence 摘要
        evidence_lines = []
        for item in evidence_pack.items:
            evidence_lines.append(f"- {item.content} (来源: {item.source_kind})")
        evidence_text = "\n".join(evidence_lines) if evidence_lines else "（无证据）"

        user_prompt = f"""【主张】
{claim_text}

【证据列表】
{evidence_text}

请判断主张是否有证据支撑，返回 JSON。"""

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,  # 确定性输出
                max_tokens=200,
            )
            content = resp.choices[0].message.content or ""

            # 解析 JSON（LLM 可能前后有 markdown fence，先 strip）
            content = content.strip()
            if content.startswith("```"):
                # 去掉 ```json ... ```
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

            data = json.loads(content)
            action_str = data.get("action", "delete").lower()

            # 映射到 GuardAction
            action_map = {
                "keep": GuardAction.KEEP,
                "delete": GuardAction.DELETE,
                "to_question": GuardAction.TO_QUESTION,
                "regenerate": GuardAction.REGENERATE,
            }
            action = action_map.get(action_str, GuardAction.DELETE)

            logger.debug(
                f"Judge claim: {claim_text[:30]}... -> {action.value} (reason: {data.get('reason', 'N/A')})"
            )
            return action

        except Exception as e:
            logger.warning(f"Judge failed (default to DELETE): {e}")
            # 解析失败或 API 错误 → 保守策略：DELETE
            return GuardAction.DELETE

    async def judge_support(self, prompt: str) -> str:
        """异步判断方法 - 供 claim_guard 调用

        Args:
            prompt: 完整的判断 prompt（包含主张和证据）

        Returns:
            LLM 返回的 JSON 字符串
        """
        import asyncio
        return await asyncio.to_thread(self._judge_support_sync, prompt)

    def _judge_support_sync(self, prompt: str) -> str:
        """同步判断实现"""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"Judge support failed: {e}")
            return '{"action": "delete", "reason": "API error"}'
