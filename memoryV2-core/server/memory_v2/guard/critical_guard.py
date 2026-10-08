"""
Critical Guard - M4 批次

功能：
1. 检查高敏信息是否正确使用（如代词）
2. 检测代词错误（"她" vs "你"）
3. 检测性别错误
4. 检测其他 Critical Profile 信息

修复的问题：
- Case 008: Critical "她" 正确但回答用"你"
"""

from typing import Optional
from pydantic import BaseModel
import re


class CriticalProfile(BaseModel):
    """Critical Profile: 高敏个人信息"""
    tenant_id: str
    user_id: str

    # 代词（第三人称）
    pronoun: Optional[str] = None  # "她" | "他" | "TA"

    # 性别
    gender: Optional[str] = None  # "female" | "male" | "other"

    # 姓名
    name: Optional[str] = None

    # 其他高敏信息
    metadata: dict = {}

    def to_prompt(self) -> str:
        """转换为 Prompt 约束文本"""
        if not self.pronoun and not self.gender and not self.name:
            return ""

        prompt = "【关键信息 - 必须遵守】\n"

        if self.pronoun:
            prompt += f"- 谈论用户时，必须使用第三人称代词：{self.pronoun}\n"
            prompt += f"- 禁止使用第二人称代词：你、您\n"

        if self.gender:
            gender_map = {
                "female": "女性",
                "male": "男性",
                "other": "其他",
            }
            prompt += f"- 用户性别：{gender_map.get(self.gender, self.gender)}\n"

        if self.name:
            prompt += f"- 用户姓名：{self.name}\n"

        return prompt


class CriticalViolation(BaseModel):
    """Critical 违规记录"""
    violation_type: str  # "pronoun" | "gender" | "name"
    expected: str  # 期望值
    actual: str  # 实际值
    location: str  # 违规位置
    severity: str = "critical"


class CriticalCheckResult(BaseModel):
    """Critical 检查结果"""
    ok: bool
    violations: list[CriticalViolation]
    suggested_question: Optional[str] = None  # 澄清问题


class CriticalGuard:
    """Critical Guard - 检查高敏信息"""

    def verify(
        self,
        answer: str,
        critical_profile: CriticalProfile,
    ) -> CriticalCheckResult:
        """验证回答是否正确使用 Critical 信息

        Args:
            answer: 生成的回答
            critical_profile: Critical Profile

        Returns:
            CriticalCheckResult
        """
        violations = []

        # 1. 检查代词
        if critical_profile.pronoun:
            pronoun_violations = self._check_pronoun(
                answer,
                critical_profile.pronoun,
            )
            violations.extend(pronoun_violations)

        # 2. 检查性别相关词
        if critical_profile.gender:
            gender_violations = self._check_gender(
                answer,
                critical_profile.gender,
            )
            violations.extend(gender_violations)

        if not violations:
            return CriticalCheckResult(ok=True, violations=[])

        # 有违规 → 建议澄清问题
        suggested_question = self._build_clarifying_question(
            critical_profile,
            violations,
        )

        return CriticalCheckResult(
            ok=False,
            violations=violations,
            suggested_question=suggested_question,
        )

    def _check_pronoun(
        self,
        answer: str,
        expected_pronoun: str,
    ) -> list[CriticalViolation]:
        """检查代词使用

        Case 008: 应该用"她"，但回答用了"你"
        """
        violations = []

        # 禁止的第二人称代词
        FORBIDDEN_SECOND_PERSON = ["你", "您", "你们"]

        for forbidden in FORBIDDEN_SECOND_PERSON:
            if forbidden in answer:
                # 找到所有出现位置
                pattern = re.compile(re.escape(forbidden))
                matches = pattern.finditer(answer)

                for match in matches:
                    start = max(0, match.start() - 10)
                    end = min(len(answer), match.end() + 10)
                    location = answer[start:end]

                    violations.append(CriticalViolation(
                        violation_type="pronoun",
                        expected=expected_pronoun,
                        actual=forbidden,
                        location=f"...{location}...",
                        severity="critical",
                    ))

        return violations

    def _check_gender(
        self,
        answer: str,
        expected_gender: str,
    ) -> list[CriticalViolation]:
        """检查性别相关词"""
        violations = []

        # 性别相关词映射
        GENDER_TERMS = {
            "female": {
                "correct": ["她", "女士", "女生", "女孩"],
                "wrong": ["他", "先生", "男生", "男孩"],
            },
            "male": {
                "correct": ["他", "先生", "男生", "男孩"],
                "wrong": ["她", "女士", "女生", "女孩"],
            },
        }

        if expected_gender not in GENDER_TERMS:
            return violations

        wrong_terms = GENDER_TERMS[expected_gender]["wrong"]

        for wrong_term in wrong_terms:
            if wrong_term in answer:
                pattern = re.compile(re.escape(wrong_term))
                matches = pattern.finditer(answer)

                for match in matches:
                    start = max(0, match.start() - 10)
                    end = min(len(answer), match.end() + 10)
                    location = answer[start:end]

                    violations.append(CriticalViolation(
                        violation_type="gender",
                        expected=expected_gender,
                        actual=wrong_term,
                        location=f"...{location}...",
                        severity="critical",
                    ))

        return violations

    def _build_clarifying_question(
        self,
        critical_profile: CriticalProfile,
        violations: list[CriticalViolation],
    ) -> str:
        """构建澄清问题"""

        # 检查是否有代词违规
        has_pronoun_violation = any(
            v.violation_type == "pronoun" for v in violations
        )

        if has_pronoun_violation and critical_profile.pronoun:
            return (
                f"抱歉，我需要确认一下：在谈论用户时，"
                f'应该使用"{critical_profile.pronoun}"还是其他称呼？'
            )

        # 检查是否有性别违规
        has_gender_violation = any(
            v.violation_type == "gender" for v in violations
        )

        if has_gender_violation:
            return "抱歉，我需要确认用户的性别信息，以便更准确地回答。"

        return "抱歉，我需要确认一些关键信息，以便更准确地回答。"


class CriticalStore:
    """Critical Profile 存储"""

    def __init__(self, db_session):
        self.db = db_session

    async def get_profile(
        self,
        tenant_id: str,
        user_id: str,
    ) -> Optional[CriticalProfile]:
        """获取用户的 Critical Profile

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            CriticalProfile 或 None
        """
        from server.memory_v2.store.models import MemoryRecord

        # 查询 critical 命名空间的记录
        critical_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.tenant_id == tenant_id,
            MemoryRecord.user_id == user_id,
            MemoryRecord.namespace == "user.critical",
            MemoryRecord.active == True,
        ).all()

        if not critical_records:
            return None

        # 解析 Critical 信息
        pronoun = None
        gender = None
        name = None

        for record in critical_records:
            if record.predicate == "critical.pronoun":
                pronoun = record.value
            elif record.predicate == "critical.gender":
                gender = record.value
            elif record.predicate == "critical.name":
                name = record.value

        if not pronoun and not gender and not name:
            return None

        return CriticalProfile(
            tenant_id=tenant_id,
            user_id=user_id,
            pronoun=pronoun,
            gender=gender,
            name=name,
        )
