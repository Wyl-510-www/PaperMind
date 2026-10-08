"""PolicyGuard: 确定性规则验证回复合规性。

hard violation → regenerate, soft violation → rewrite。
"""

from __future__ import annotations

import re

from .models import PolicyCheck, PolicyPack, PolicyRule, PolicyStrength


class PolicyGuard:
    """回复行为约束验证器"""

    def verify(self, answer: str, policy_pack: PolicyPack) -> PolicyCheck:
        """验证回复是否符合所有 Policy。

        Args:
            answer: 生成的回复文本
            policy_pack: 编译后的策略包

        Returns:
            PolicyCheck: 验证结果
        """
        violations: list[str] = []
        has_hard_violation = False

        for rule in policy_pack.rules:
            v = self._check_rule(answer, rule)
            if v:
                violations.append(v)
                if rule.strength == PolicyStrength.HARD:
                    has_hard_violation = True

        if not violations:
            return PolicyCheck(ok=True, violations=[], action="keep")

        if has_hard_violation:
            return PolicyCheck(
                ok=False,
                violations=violations,
                action="regenerate",
            )
        return PolicyCheck(
            ok=False,
            violations=violations,
            action="rewrite",
        )

    def _check_rule(self, answer: str, rule: PolicyRule) -> str | None:
        """检查单条规则。返回违规描述或 None"""
        # forbidden_terms
        for term in rule.forbidden_terms:
            if term in answer:
                return f"forbidden_term: '{term}' found (rule: {rule.policy_id})"

        # required_terms_any
        if rule.required_terms_any:
            if not any(t in answer for t in rule.required_terms_any):
                return f"required_terms_any: none of {rule.required_terms_any} found (rule: {rule.policy_id})"

        # max_sentences
        if rule.max_sentences:
            sentences = len(re.split(r'[。！？.!?]', answer))
            if sentences > rule.max_sentences:
                return f"max_sentences: {sentences} > {rule.max_sentences} (rule: {rule.policy_id})"

        # max_questions
        if rule.max_questions:
            questions = len(re.findall(r'[？?]', answer))
            if questions > rule.max_questions:
                return f"max_questions: {questions} > {rule.max_questions} (rule: {rule.policy_id})"

        # forbidden_question_patterns
        for pattern in rule.forbidden_question_patterns:
            if re.search(pattern, answer):
                return f"forbidden_question_pattern: '{pattern}' matched (rule: {rule.policy_id})"

        return None
