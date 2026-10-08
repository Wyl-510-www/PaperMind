"""
Policy Guard - M4 批次

功能：
1. 检查回答是否违反 Policy 约束
2. 检测禁用词（如"小公主"）
3. 检测句数限制
4. 检测其他 Policy 规则

修复的问题：
- Case 005: Evidence 正确但仍违规使用"小公主"
"""

from typing import Optional
from pydantic import BaseModel
import re


class PolicyRule(BaseModel):
    """单条 Policy 规则"""
    rule_id: str
    rule_type: str  # "forbidden_terms" | "max_sentences" | "tone" | "custom"

    # 禁用词
    forbidden_terms: list[str] = []

    # 句数限制
    max_sentences: Optional[int] = None

    # 描述
    description: str = ""

    # 原因（用户为什么设置这条规则）
    reason: Optional[str] = None


class PolicyPack(BaseModel):
    """Policy 包：用户设置的所有行为准则"""
    tenant_id: str
    user_id: str
    namespace: str

    rules: list[PolicyRule]

    def to_prompt(self) -> str:
        """转换为 Prompt 约束文本"""
        if not self.rules:
            return ""

        prompt = "【行为准则 - 必须遵守】\n"

        for rule in self.rules:
            if rule.rule_type == "forbidden_terms" and rule.forbidden_terms:
                terms = ', '.join(f'"{term}"' for term in rule.forbidden_terms)
                prompt += f"- 禁止使用以下词语：{terms}\n"
                if rule.reason:
                    prompt += f"  原因：{rule.reason}\n"

            elif rule.rule_type == "max_sentences" and rule.max_sentences:
                prompt += f"- 回答不超过 {rule.max_sentences} 句\n"

            elif rule.rule_type == "custom":
                prompt += f"- {rule.description}\n"

        return prompt


class PolicyViolation(BaseModel):
    """Policy 违规记录"""
    rule_id: str
    rule_type: str
    violated_term: Optional[str] = None  # 违反的具体词语
    location: Optional[str] = None  # 违规位置（文本片段）
    severity: str = "high"  # "high" | "medium" | "low"
    suggestion: Optional[str] = None  # 修复建议


class PolicyCheckResult(BaseModel):
    """Policy 检查结果"""
    ok: bool  # True = 通过，False = 违规
    violations: list[PolicyViolation]
    action: str  # "keep" | "regenerate" | "rewrite"


class PolicyGuard:
    """Policy Guard - 检查 Policy 违规"""

    def verify(
        self,
        answer: str,
        policy_pack: PolicyPack,
    ) -> PolicyCheckResult:
        """验证回答是否违反 Policy

        Args:
            answer: 生成的回答
            policy_pack: Policy 包

        Returns:
            PolicyCheckResult
        """
        violations = []

        for rule in policy_pack.rules:
            if rule.rule_type == "forbidden_terms":
                # 检查禁用词
                term_violations = self._check_forbidden_terms(
                    answer,
                    rule.forbidden_terms,
                    rule.rule_id,
                )
                violations.extend(term_violations)

            elif rule.rule_type == "max_sentences":
                # 检查句数限制
                sentence_violation = self._check_max_sentences(
                    answer,
                    rule.max_sentences,
                    rule.rule_id,
                )
                if sentence_violation:
                    violations.append(sentence_violation)

        # 判断 action
        if not violations:
            return PolicyCheckResult(ok=True, violations=[], action="keep")

        # 有违规
        # 如果是禁用词违规 → regenerate（需要完全避免）
        # 如果是句数违规 → rewrite（可以截断）
        has_forbidden = any(v.rule_type == "forbidden_terms" for v in violations)
        action = "regenerate" if has_forbidden else "rewrite"

        return PolicyCheckResult(
            ok=False,
            violations=violations,
            action=action,
        )

    def _check_forbidden_terms(
        self,
        answer: str,
        forbidden_terms: list[str],
        rule_id: str,
    ) -> list[PolicyViolation]:
        """检查禁用词"""
        violations = []

        for term in forbidden_terms:
            # 不区分大小写
            if term.lower() in answer.lower():
                # 找到违规位置
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                matches = pattern.finditer(answer)

                for match in matches:
                    start = max(0, match.start() - 10)
                    end = min(len(answer), match.end() + 10)
                    location = answer[start:end]

                    violations.append(PolicyViolation(
                        rule_id=rule_id,
                        rule_type="forbidden_terms",
                        violated_term=term,
                        location=f"...{location}...",
                        severity="high",
                        suggestion=f"请移除 \"{term}\"",
                    ))

        return violations

    def _check_max_sentences(
        self,
        answer: str,
        max_sentences: int,
        rule_id: str,
    ) -> Optional[PolicyViolation]:
        """检查句数限制"""
        # 简单句子切分（按。！？切分）
        sentences = re.split(r'[。！？.!?]+', answer)
        sentences = [s.strip() for s in sentences if s.strip()]

        actual_count = len(sentences)

        if actual_count > max_sentences:
            return PolicyViolation(
                rule_id=rule_id,
                rule_type="max_sentences",
                location=f"实际 {actual_count} 句，超过限制 {max_sentences} 句",
                severity="medium",
                suggestion=f"请将回答缩减至 {max_sentences} 句以内",
            )

        return None


class PolicyCompiler:
    """编译用户的 Policy 规则"""

    def __init__(self, db_session):
        self.db = db_session

    async def compile(
        self,
        tenant_id: str,
        user_id: str,
        namespace: str = "user.policy",
    ) -> PolicyPack:
        """从数据库编译 Policy Pack

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            namespace: Policy 命名空间

        Returns:
            PolicyPack
        """
        from server.memory_v2.store.models import MemoryRecord

        # 查询 Policy 记录
        policy_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.namespace == namespace,
            MemoryRecord.active == True,
            MemoryRecord.predicate.like("policy.%"),
        ).all()

        rules = []

        for record in policy_records:
            # 解析 predicate
            # 例如：policy.forbidden_term.小公主
            parts = record.predicate.split(".")

            if len(parts) >= 2:
                rule_type = parts[1]  # forbidden_term, max_sentences, etc.

                if rule_type == "forbidden_term":
                    # 禁用词
                    term = record.value
                    rule = PolicyRule(
                        rule_id=record.memory_id,
                        rule_type="forbidden_terms",
                        forbidden_terms=[term],
                        description=f"禁止使用 \"{term}\"",
                        reason=record.metadata.get("reason") if record.metadata else None,
                    )
                    rules.append(rule)

                elif rule_type == "max_sentences":
                    # 句数限制
                    max_count = int(record.value)
                    rule = PolicyRule(
                        rule_id=record.memory_id,
                        rule_type="max_sentences",
                        max_sentences=max_count,
                        description=f"回答不超过 {max_count} 句",
                    )
                    rules.append(rule)

        return PolicyPack(
            tenant_id=tenant_id,
            user_id=user_id,
            namespace=namespace,
            rules=rules,
        )
