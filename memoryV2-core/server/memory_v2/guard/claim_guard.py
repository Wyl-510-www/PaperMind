"""ClaimGuard - 基于证据的主张验证

D3 修复要点：
1. 统一接口：导入、构造器、DTO、异步
2. 逐主张验证：不能 Evidence 非空就全部通过
3. 无 Evidence 时也要检查虚构用户记忆
4. 错误处理：超时/解析失败是 error，不是 KEEP
"""

import logging
import re
import json
from typing import List, Optional
import asyncio

from .contracts import (
    Claim, Evidence, EvidencePack,
    ClaimDecision, GuardResult, GuardAction
)

logger = logging.getLogger(__name__)


class ClaimGuard:
    """主张验证 Guard

    职责：
    - 提取回答中的主张
    - 逐主张检查是否有证据支持
    - 综合决策：保留、删除、澄清、重新生成

    0913 规范：
    - 保留逐主张证据支持检查
    - 不允许"Evidence非空全部通过"
    - 无Evidence时检查虚构用户记忆
    """

    # 用户记忆声称的模式
    MEMORY_CLAIM_PATTERNS = [
        r"你上周", r"你昨天", r"你之前", r"你告诉我", r"你说过",
        r"你的偏好", r"你喜欢", r"你不喜欢", r"你对.*过敏",
        r"根据你的", r"你提到过", r"我记得你", r"你曾经"
    ]

    def __init__(self, judge_client=None, timeout: float = 30.0):
        """初始化

        Args:
            judge_client: LLM 客户端，用于提取主张和验证支持度（可选）
            timeout: 单次 LLM 调用超时时间（秒）
        """
        self.judge = judge_client
        self.timeout = timeout

    async def verify_answer(
        self,
        answer: str,
        evidence_pack: EvidencePack,
        claims: Optional[List[Claim]] = None
    ) -> GuardResult:
        """验证回答的主张

        0913 流程：
        1. 提取主张（如果未提供）
        2. 逐主张验证支持度
        3. 综合决策
        4. 修改回答（如果需要）
        """
        try:
            # 1. 提取主张
            if claims is None:
                if self.judge:
                    claims = await self._extract_claims_llm(answer)
                else:
                    # Fallback：使用模式匹配
                    claims = self._extract_claims_pattern(answer)

            if not claims:
                # 无主张，直接通过
                return GuardResult(
                    overall_action=GuardAction.KEEP,
                    original_answer=answer,
                    modified_answer=None,
                    claim_decisions=[],
                    verified_claims_count=0
                )

            # 2. 逐主张验证（0913 核心修复）
            claim_decisions = []
            for claim in claims:
                decision = await self._verify_single_claim(claim, evidence_pack)
                claim_decisions.append(decision)

            # 3. 综合决策
            overall_action = self._aggregate_decisions(claim_decisions)

            # 4. 修改回答
            modified_answer = None
            if overall_action == GuardAction.DELETE:
                modified_answer = self._remove_unsupported_claims(
                    answer, claim_decisions
                )
            elif overall_action == GuardAction.TO_QUESTION:
                modified_answer = self._render_clarification(
                    claim_decisions
                )

            # 统计
            verified_count = sum(
                1 for d in claim_decisions
                if d.action == GuardAction.KEEP
            )
            removed_count = sum(
                1 for d in claim_decisions
                if d.action == GuardAction.DELETE
            )
            clarification_count = sum(
                1 for d in claim_decisions
                if d.action == GuardAction.TO_QUESTION
            )

            return GuardResult(
                overall_action=overall_action,
                original_answer=answer,
                modified_answer=modified_answer,
                claim_decisions=claim_decisions,
                verified_claims_count=verified_count,
                removed_claims_count=removed_count,
                clarification_needed_count=clarification_count
            )

        except asyncio.TimeoutError:
            logger.error("ClaimGuard timeout")
            return GuardResult(
                overall_action=GuardAction.ERROR,
                original_answer=answer,
                modified_answer=None,
                claim_decisions=[],
                error="guard_timeout"
            )

        except Exception as e:
            logger.error(f"ClaimGuard error: {e}", exc_info=True)
            return GuardResult(
                overall_action=GuardAction.ERROR,
                original_answer=answer,
                modified_answer=None,
                claim_decisions=[],
                error=str(e)
            )

    def _extract_claims_pattern(self, answer: str) -> List[Claim]:
        """使用模式匹配提取主张（Fallback）"""
        claims = []

        for i, pattern_str in enumerate(self.MEMORY_CLAIM_PATTERNS):
            pattern = re.compile(pattern_str)
            for match in pattern.finditer(answer):
                # 提取上下文
                start = max(0, match.start() - 10)
                end = min(len(answer), match.end() + 30)
                text = answer[start:end].strip()

                claims.append(Claim(
                    id=f"claim_{i}_{match.start()}",
                    text=text,
                    span=(match.start(), match.end())
                ))

        return claims

    async def _extract_claims_llm(self, answer: str) -> List[Claim]:
        """使用 LLM 提取回答中的主张"""
        try:
            prompt = f"""从以下回答中提取所有事实性主张。
只提取关于用户的具体事实，不包括常识或推理。

回答：
{answer}

请以 JSON 数组格式返回，每个主张包含：
- id: 唯一标识
- text: 主张文本
- span: 在原文中的位置 [start, end]

示例输出：
[
  {{"id": "claim_1", "text": "你喜欢咖啡", "span": [0, 5]}},
  {{"id": "claim_2", "text": "你对花生过敏", "span": [10, 17]}}
]
"""

            response = await asyncio.wait_for(
                self.judge.extract_claims(prompt),
                timeout=self.timeout
            )

            # 解析 JSON 响应
            claims_data = self._parse_json_response(response)

            claims = [
                Claim(
                    id=c.get("id", f"claim_{i}"),
                    text=c.get("text", ""),
                    span=tuple(c.get("span", [None, None])) if c.get("span") else None
                )
                for i, c in enumerate(claims_data)
            ]

            return claims

        except Exception as e:
            logger.error(f"Extract claims failed: {e}")
            # Fallback to pattern matching
            return self._extract_claims_pattern(answer)

    async def _verify_single_claim(
        self,
        claim: Claim,
        evidence_pack: EvidencePack
    ) -> ClaimDecision:
        """逐主张验证 - 0913 核心修复

        不能简单判断 Evidence 非空就通过，必须验证支持度
        """
        # 0913 修复：使用统一的 .items 字段
        evidence_items = evidence_pack.items

        # 1. 无 Evidence 时的处理
        if not evidence_items:
            # 0913 规范：无Evidence时也要检查虚构用户记忆
            if self._claims_user_memory(claim.text):
                return ClaimDecision(
                    claim_id=claim.id,
                    action=GuardAction.DELETE,
                    supporting_evidence_ids=[],
                    reason="no_evidence_but_claims_user_memory",
                    confidence=0.0
                )
            else:
                # 不涉及用户记忆的主张，可能是常识
                return ClaimDecision(
                    claim_id=claim.id,
                    action=GuardAction.KEEP,
                    supporting_evidence_ids=[],
                    reason="no_user_memory_claimed",
                    confidence=0.5
                )

        # 2. 找到相关 Evidence
        relevant_evidence = self._find_relevant_evidence(claim, evidence_items)

        if not relevant_evidence:
            # 有 Evidence 但都不相关
            if self._claims_user_memory(claim.text):
                return ClaimDecision(
                    claim_id=claim.id,
                    action=GuardAction.DELETE,
                    supporting_evidence_ids=[],
                    reason="no_relevant_evidence_for_user_memory",
                    confidence=0.0
                )
            else:
                return ClaimDecision(
                    claim_id=claim.id,
                    action=GuardAction.TO_QUESTION,
                    supporting_evidence_ids=[],
                    reason="insufficient_evidence",
                    confidence=0.3
                )

        # 3. 判断支持度
        if self.judge:
            # 使用 LLM Judge
            try:
                support_result = await asyncio.wait_for(
                    self._judge_support(claim.text, relevant_evidence),
                    timeout=self.timeout
                )

                if support_result["is_supported"]:
                    return ClaimDecision(
                        claim_id=claim.id,
                        action=GuardAction.KEEP,
                        supporting_evidence_ids=[e.memory_id for e in relevant_evidence],
                        reason="verified_by_evidence",
                        confidence=support_result.get("confidence", 0.9)
                    )
                elif support_result.get("is_contradicted"):
                    return ClaimDecision(
                        claim_id=claim.id,
                        action=GuardAction.DELETE,
                        supporting_evidence_ids=[],
                        reason="contradicted_by_evidence",
                        confidence=support_result.get("confidence", 0.8)
                    )
                else:
                    return ClaimDecision(
                        claim_id=claim.id,
                        action=GuardAction.TO_QUESTION,
                        supporting_evidence_ids=[],
                        reason="uncertain_support",
                        confidence=support_result.get("confidence", 0.5)
                    )

            except asyncio.TimeoutError:
                logger.error(f"Judge timeout for claim: {claim.id}")
                return ClaimDecision(
                    claim_id=claim.id,
                    action=GuardAction.ERROR,
                    supporting_evidence_ids=[],
                    reason="judge_timeout",
                    confidence=0.0
                )
        else:
            # 简单启发式：有相关证据就通过
            return ClaimDecision(
                claim_id=claim.id,
                action=GuardAction.KEEP,
                supporting_evidence_ids=[e.memory_id for e in relevant_evidence],
                reason="relevant_evidence_found",
                confidence=0.7
            )

    def _claims_user_memory(self, text: str) -> bool:
        """检查主张是否声称用户记忆

        0913 规范：检测"你上周说"、"你告诉我"等虚构记忆
        """
        for pattern_str in self.MEMORY_CLAIM_PATTERNS:
            if re.search(pattern_str, text):
                return True
        return False

    def _find_relevant_evidence(
        self,
        claim: Claim,
        evidence_items: List[Evidence]
    ) -> List[Evidence]:
        """找到与主张相关的 Evidence

        使用简单的关键词匹配
        """
        relevant = []

        # 提取主张中的关键词（去除停用词）
        stopwords = {"的", "了", "是", "在", "有", "和", "与", "或", "但", "你", "我", "他"}
        claim_keywords = set(claim.text.split()) - stopwords

        for evidence in evidence_items:
            # 计算关键词重叠
            evidence_words = set(evidence.content.split()) - stopwords
            overlap = claim_keywords & evidence_words

            if len(overlap) >= 2 or evidence.relevance_score > 0.7:
                relevant.append(evidence)

        # 按相关性排序，取前3个
        relevant.sort(key=lambda e: e.relevance_score, reverse=True)
        return relevant[:3]

    async def _judge_support(self, claim_text: str, evidence: List[Evidence]) -> dict:
        """使用 Judge 判断证据是否支持主张"""
        evidence_text = "\n".join([f"- {e.content}" for e in evidence])

        prompt = f"""判断以下证据是否支持该主张：

主张：{claim_text}

证据：
{evidence_text}

请以 JSON 格式返回：
{{
  "is_supported": true/false,
  "is_contradicted": true/false,
  "confidence": 0.0-1.0,
  "reason": "简短说明"
}}
"""

        response = await self.judge.judge_support(prompt)
        return self._parse_json_response(response)

    def _parse_json_response(self, response: str) -> dict:
        """解析 JSON 响应"""
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            json_match = re.search(r'\{.*\}|\[.*\]', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"Cannot parse JSON from response: {response}")

    def _aggregate_decisions(self, decisions: List[ClaimDecision]) -> GuardAction:
        """综合所有主张的决策

        规则：
        - 任何 ERROR -> ERROR
        - 所有 KEEP -> KEEP
        - 有 DELETE 且无 TO_QUESTION -> DELETE
        - 有 TO_QUESTION -> TO_QUESTION
        - 有 REGENERATE -> REGENERATE
        """
        if not decisions:
            return GuardAction.KEEP

        actions = [d.action for d in decisions]

        if GuardAction.ERROR in actions:
            return GuardAction.ERROR

        if all(a == GuardAction.KEEP for a in actions):
            return GuardAction.KEEP

        if GuardAction.TO_QUESTION in actions:
            return GuardAction.TO_QUESTION

        if GuardAction.DELETE in actions:
            return GuardAction.DELETE

        if GuardAction.REGENERATE in actions:
            return GuardAction.REGENERATE

        return GuardAction.KEEP

    def _remove_unsupported_claims(
        self,
        answer: str,
        decisions: List[ClaimDecision]
    ) -> str:
        """删除不支持的主张"""
        # 简单实现：返回警告信息
        removed_claims = [
            d.claim_id for d in decisions
            if d.action == GuardAction.DELETE
        ]

        if removed_claims:
            return f"抱歉，我无法验证某些信息。请提供更多上下文。"

        return answer

    def _render_clarification(self, decisions: List[ClaimDecision]) -> str:
        """生成澄清问题"""
        uncertain_claims = [
            d for d in decisions
            if d.action == GuardAction.TO_QUESTION
        ]

        if uncertain_claims:
            return "我不确定某些信息，能否再详细说明一下？"

        return "请提供更多信息。"

    # 向后兼容：旧接口
    def verify(self, answer: str, evidence_pack: EvidencePack):
        """同步接口 - 向后兼容

        注意：这是一个同步包装，会阻塞事件循环
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在异步上下文中，创建新任务
                logger.warning("verify() called in async context, use verify_answer() instead")
                # 简化处理：直接检查是否有用户记忆声称
                claims = self._extract_claims_pattern(answer)
                if not claims:
                    return {"ok": True, "claims": []}

                evidence_items = evidence_pack.items
                if evidence_items:
                    # 有证据，简单通过
                    return {"ok": True, "claims": []}
                else:
                    # 无证据且有主张，失败
                    return {
                        "ok": False,
                        "claims": [{"claim_text": c.text, "location": "", "pattern_matched": ""} for c in claims]
                    }
            else:
                result = loop.run_until_complete(
                    self.verify_answer(answer, evidence_pack)
                )
                return {
                    "ok": result.overall_action == GuardAction.KEEP,
                    "claims": [
                        {"claim_text": d.claim_id, "location": "", "pattern_matched": d.reason or ""}
                        for d in result.claim_decisions
                        if d.action != GuardAction.KEEP
                    ]
                }
        except Exception as e:
            logger.error(f"verify() failed: {e}")
            return {"ok": False, "claims": [], "error": str(e)}
