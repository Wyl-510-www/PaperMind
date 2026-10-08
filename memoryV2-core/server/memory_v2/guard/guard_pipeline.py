"""
Guard Pipeline - M4 批次

完整的 Guard 流水线：Policy → Blocked → Critical → Claim

修复的问题：
- Case 005: Evidence 正确但仍违规使用"小公主"
- Case 008: Critical "她" 正确但回答用"你"
- Case 100: 使用旧昵称"阿晚"
- 100 条 Guard Trace 均显示 not_run 和 keep 矛盾状态
"""

from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from server.memory_v2.guard.guard_action import GuardAction, GuardStatus
from server.memory_v2.guard.policy_guard import PolicyGuard, PolicyPack
from server.memory_v2.guard.blocked_guard import BlockedGuard
from server.memory_v2.guard.critical_guard import CriticalGuard, CriticalProfile
from server.memory_v2.guard.claim_guard import ClaimGuard

logger = logging.getLogger(__name__)


class GuardTrace(BaseModel):
    """Guard 执行 Trace - 真实记录执行状态"""

    # 执行状态
    enabled: bool  # Guard 是否启用
    attempted: bool  # 是否尝试执行
    succeeded: bool  # 是否执行成功

    # 各 Guard 的详细结果
    policy_status: GuardStatus = GuardStatus.NOT_RUN
    policy_violations: list[str] = Field(default_factory=list)

    blocked_status: GuardStatus = GuardStatus.NOT_RUN
    blocked_values: list[str] = Field(default_factory=list)

    critical_status: GuardStatus = GuardStatus.NOT_RUN
    critical_violations: list[str] = Field(default_factory=list)

    claim_status: GuardStatus = GuardStatus.NOT_RUN
    claims: list[str] = Field(default_factory=list)

    # 最终动作（使用枚举，不是字符串）
    overall_action: Optional[GuardAction] = None

    # 重生成
    regeneration_count: int = 0

    # 错误
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # 时间
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GuardResult(BaseModel):
    """Guard 最终结果"""
    action: GuardAction
    claims: list[str] = Field(default_factory=list)
    clarifying_question: Optional[str] = None
    trace: GuardTrace


class GuardPipeline:
    """完整的 Guard 流水线"""

    def __init__(self, db_session):
        self.db = db_session
        self.policy_guard = PolicyGuard()
        self.blocked_guard = BlockedGuard(db_session)
        self.critical_guard = CriticalGuard()
        self.claim_guard = ClaimGuard()

    async def apply(
        self,
        answer: str,
        evidence_pack,  # EvidencePack
        policy_pack: PolicyPack,
        critical_profile: Optional[CriticalProfile],
        tenant_id: str,
        user_id: str,
    ) -> GuardResult:
        """应用完整 Guard 流水线

        执行顺序：
        1. PolicyGuard - 检查 Policy 违规
        2. BlockedGuard - 检查已删除值
        3. CriticalGuard - 检查高敏信息
        4. ClaimGuard - 检查无证据主张

        Args:
            answer: 生成的回答
            evidence_pack: Evidence 包
            policy_pack: Policy 包
            critical_profile: Critical Profile
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            GuardResult
        """
        trace = GuardTrace(
            enabled=True,
            attempted=True,
            succeeded=False,
            started_at=datetime.utcnow(),
        )

        try:
            # 1. PolicyGuard
            logger.info("Guard Pipeline: 开始 PolicyGuard")
            policy_check = self.policy_guard.verify(answer, policy_pack)

            if policy_check.violations:
                trace.policy_status = GuardStatus.VIOLATED
                trace.policy_violations = [
                    f"{v.violated_term or v.rule_type}: {v.location}"
                    for v in policy_check.violations
                ]
            else:
                trace.policy_status = GuardStatus.PASSED

            if not policy_check.ok:
                logger.warning(
                    f"PolicyGuard 违规：{len(policy_check.violations)} 条"
                )
                if policy_check.action == "regenerate":
                    trace.overall_action = GuardAction.REGENERATE
                    trace.succeeded = True
                    trace.completed_at = datetime.utcnow()
                    return GuardResult(
                        action=GuardAction.REGENERATE,
                        trace=trace,
                    )
                elif policy_check.action == "rewrite":
                    trace.overall_action = GuardAction.DELETE
                    trace.succeeded = True
                    trace.completed_at = datetime.utcnow()
                    return GuardResult(
                        action=GuardAction.DELETE,
                        claims=[str(v.location) for v in policy_check.violations],
                        trace=trace,
                    )

            # 2. BlockedGuard
            logger.info("Guard Pipeline: 开始 BlockedGuard")
            blocked_check = await self.blocked_guard.verify(
                answer,
                tenant_id,
                user_id,
            )

            if blocked_check.blocked_values:
                trace.blocked_status = GuardStatus.VIOLATED
                trace.blocked_values = blocked_check.blocked_values
            else:
                trace.blocked_status = GuardStatus.PASSED

            if not blocked_check.ok:
                logger.warning(
                    f"BlockedGuard 违规：使用了已删除值 {blocked_check.blocked_values}"
                )
                trace.overall_action = GuardAction.REGENERATE
                trace.succeeded = True
                trace.completed_at = datetime.utcnow()
                return GuardResult(
                    action=GuardAction.REGENERATE,
                    trace=trace,
                )

            # 3. CriticalGuard
            if critical_profile:
                logger.info("Guard Pipeline: 开始 CriticalGuard")
                critical_check = self.critical_guard.verify(
                    answer,
                    critical_profile,
                )

                if critical_check.violations:
                    trace.critical_status = GuardStatus.VIOLATED
                    trace.critical_violations = [
                        f"{v.violation_type}: 期望 {v.expected}, 实际 {v.actual}"
                        for v in critical_check.violations
                    ]
                else:
                    trace.critical_status = GuardStatus.PASSED

                if not critical_check.ok:
                    logger.warning(
                        f"CriticalGuard 违规：{len(critical_check.violations)} 条"
                    )
                    trace.overall_action = GuardAction.TO_QUESTION
                    trace.succeeded = True
                    trace.completed_at = datetime.utcnow()
                    return GuardResult(
                        action=GuardAction.TO_QUESTION,
                        clarifying_question=critical_check.suggested_question,
                        trace=trace,
                    )

            # 4. ClaimGuard
            logger.info("Guard Pipeline: 开始 ClaimGuard")
            claim_check = self.claim_guard.verify(answer, evidence_pack)

            if claim_check.claims:
                trace.claim_status = GuardStatus.VIOLATED
                trace.claims = [c.claim_text for c in claim_check.claims]
            else:
                trace.claim_status = GuardStatus.PASSED

            if not claim_check.ok:
                logger.warning(
                    f"ClaimGuard 违规：{len(claim_check.claims)} 条无证据主张"
                )
                trace.overall_action = GuardAction.DELETE
                trace.succeeded = True
                trace.completed_at = datetime.utcnow()
                return GuardResult(
                    action=GuardAction.DELETE,
                    claims=[c.claim_text for c in claim_check.claims],
                    trace=trace,
                )

            # 5. 全部通过
            logger.info("Guard Pipeline: 全部通过")
            trace.overall_action = GuardAction.KEEP
            trace.succeeded = True
            trace.completed_at = datetime.utcnow()
            return GuardResult(
                action=GuardAction.KEEP,
                trace=trace,
            )

        except Exception as e:
            logger.exception("Guard 流水线异常")
            trace.succeeded = False
            trace.error_code = "GUARD_EXCEPTION"
            trace.error_message = str(e)
            trace.completed_at = datetime.utcnow()

            # 失败时保守：拒绝回答
            trace.overall_action = GuardAction.REGENERATE
            return GuardResult(
                action=GuardAction.REGENERATE,
                trace=trace,
            )
