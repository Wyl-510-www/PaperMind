"""MemoryWriter：写入链路编排器。

流程：speech_act → TypedWriteRouter.plan → 并行 extract → temporal → gate → dispatch → V2WriteResult

B4 修复：返回类型化结果 V2WriteResult，而非内部追踪对象 WriteTrace
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..contracts import (
    ExtractionLane,
    LaneOutcome,
    WriteDecision,
    WriteTrace,
    V2WriteResult,
    LaneOutcome,
    CommitReceipt,
)
from .gate import MemoryGate, detect_signals
from .router import TypedWriteRouter, MemoryDispatcher
from ..temporal import normalize_relative_time
from ..speech_act import classify_speech_act, classify_ambiguity, MemorySpeechAct
from datetime import datetime, timezone
from ..monitoring import metrics_collector
from ..tracing.context import get_or_create_write_trace

logger = logging.getLogger(__name__)

# Lane → extractor 映射
LANE_EXTRACTOR_MAP: dict[ExtractionLane, str] = {
    ExtractionLane.SEMANTIC: "semantic",
    ExtractionLane.EVENT_TASK: "event_task",
    ExtractionLane.ENTITY_RELATION: "entity_relation",
    ExtractionLane.BEHAVIOR_POLICY: "behavior_policy",
    ExtractionLane.UPDATE_DELETE: "update_delete",
}


class MemoryWriter:
    """写入编排器：plan → extract → gate → dispatch"""

    def __init__(
        self,
        extractors: dict[str, Any],
        gate: MemoryGate | None = None,
        dispatcher: MemoryDispatcher | None = None,
        llm_client=None,
    ):
        """
        Args:
            extractors: {lane_name: extractor_instance}，至少含 'semantic'
            gate: 门控裁决器。None 时使用默认 MemoryGate
            dispatcher: 类型分发器。None 时只做 gate 裁决不落库
            llm_client: LLM 客户端。Phase 5D 用于 LLM 补漏
        """
        self.extractors = extractors
        self.gate = gate or MemoryGate()
        self.dispatcher = dispatcher
        self._lane_planner = TypedWriteRouter(llm_client=llm_client)

    async def write_turn(
        self,
        user_text: str,
        user_id: str,
        turn_id: str,
        occurred_at: datetime | None = None,
        tenant_id: str = "default",
        previous_user_text: str | None = None,
    ) -> V2WriteResult:
        """写入一轮对话的记忆。

        B4 修复：返回类型化结果 V2WriteResult

        Args:
            user_text: 用户输入原文
            user_id: 用户 ID
            turn_id: 轮次 ID
            occurred_at: 消息发生时间（UTC），默认当前时间
            tenant_id: 租户 ID
            previous_user_text: 前一轮用户消息（P1-1：透传给 extractor 作为上下文）

        Returns:
            V2WriteResult: 类型化写入结果
        """
        t0 = time.monotonic()
        # 监控: 记录写入开始
        _monitoring_start = metrics_collector.record_write_start()
        occurred_at = occurred_at or datetime.now(timezone.utc)
        # 归一化 user_id 为 str（BigInteger 列用 int 但 Pydantic 模型要求 str）
        user_id = str(user_id)
        trace = WriteTrace(turn_id=turn_id)

        # Chain Trace 集成：获取写入追踪对象
        w_trace = get_or_create_write_trace()

        # 0. Speech Act 分类：QUERY_EXISTING / AMBIGUOUS → 不写
        # P1-1修复：区分真实不确定、礼貌表达、数值精度
        sa = classify_speech_act(user_text)
        trace.speech_act = sa.value

        # P1-1修复：细化AMBIGUOUS检查
        if sa == MemorySpeechAct.AMBIGUOUS:
            # 已经是真实不确定，直接阻断
            logger.info(
                "Speech Act 阻断写入（真实不确定）: speech_act=%s user_id=%s turn_id=%s text_preview=%.80s",
                sa.value, user_id, turn_id, user_text,
            )
            trace.elapsed_ms = (time.monotonic() - t0) * 1000
            return _convert_trace_to_result(trace, user_id, turn_id, tenant_id, occurred_at)

        if sa in (MemorySpeechAct.QUERY_EXISTING, MemorySpeechAct.FILLER):
            logger.info(
                "Speech Act 阻断写入: speech_act=%s user_id=%s turn_id=%s text_preview=%.80s",
                sa.value, user_id, turn_id, user_text,
            )
            trace.elapsed_ms = (time.monotonic() - t0) * 1000
            # B4: 转换为 V2WriteResult
            return _convert_trace_to_result(trace, user_id, turn_id, tenant_id, occurred_at)

        # P1-1修复：检查歧义类型，用于标记candidate
        ambiguity_type = classify_ambiguity(user_text)
        precision_level = "exact"  # 默认精确
        if ambiguity_type == "数值精度":
            precision_level = "approximate"

        # 1. Lane 规划
        plan = await self._lane_planner.plan_async(user_text)
        trace.lanes_activated = [lane.value for lane in plan.lanes]

        # 2. 并行抽取
        import asyncio

        async def extract_lane(lane: ExtractionLane) -> LaneOutcome:
            """P0-3修复：extractor已返回LaneOutcome，直接使用"""
            lane_name = LANE_EXTRACTOR_MAP.get(lane)
            if not lane_name or lane_name not in self.extractors:
                return LaneOutcome(
                    lane=lane.value,
                    status="success_empty",
                    candidates=[],
                    error_code=None,
                    error_message=None,
                )

            extractor = self.extractors[lane_name]
            try:
                from .extractors.base import ExtractionInput
                inp = ExtractionInput(
                    user_text=user_text,
                    user_id=user_id,
                    turn_id=turn_id,
                    occurred_at=occurred_at.isoformat() if occurred_at else "",
                    previous_user_text=previous_user_text,
                )
                # P0-3修复：extractor.extract()现在直接返回LaneOutcome
                lane_outcome = await extractor.extract(inp)
                return lane_outcome
            except Exception as e:
                error_msg = f"Lane {lane.value} extraction failed: {str(e)}"
                logger.exception("Lane %s 抽取失败", lane.value)
                metrics_collector.record_write_failure(
                    error_type="extraction_failed",
                    error_msg=error_msg,
                    lane=lane.value,
                )
                return LaneOutcome(
                    lane=lane.value,
                    status="extraction_error",
                    candidates=[],
                    error_code="EXTRACTION_ERROR",
                    error_message=error_msg,
                )

        lane_results_list = await asyncio.gather(
            *[extract_lane(lane) for lane in plan.lanes]
        )

        # P0-3修复：保存所有lane outcomes到trace
        trace.lane_outcomes = lane_results_list

        # 3. 合并、门控、分发
        signals = detect_signals(user_text)

        for lane_outcome in lane_results_list:
            lane_key = lane_outcome.lane
            candidates = lane_outcome.candidates
            trace.lane_results[lane_key] = len(candidates)
            trace.candidates_total += len(candidates)

            for candidate in candidates:
                # Chain Trace: 记录 extractor_candidate_id
                if hasattr(candidate, 'candidate_id') and candidate.candidate_id:
                    w_trace.extractor_candidate_ids.append(candidate.candidate_id)

                # P1-1修复：标记precision和ambiguity_type
                if ambiguity_type:
                    candidate.ambiguity_type = ambiguity_type
                if precision_level != "exact":
                    candidate.precision = precision_level

                # 时间归一化
                candidate.time = normalize_relative_time(
                    candidate.source_span,
                    occurred_at,
                )
                # 门控裁决
                decision = self.gate.decide(candidate, signals)
                if decision.accepted:
                    trace.candidates_accepted += 1
                    if self.dispatcher:
                        commit_id = await self.dispatcher.dispatch(
                            decision, tenant_id, user_id, turn_id,
                            occurred_at=occurred_at,
                        )
                        # P0-2修复: 检查落库结果，错误时标记失败
                        trace.repository_commits.append(commit_id)
                        if commit_id == "error" or (isinstance(commit_id, str) and "failed" in commit_id):
                            trace.v2_write_success = False
                            logger.error("Repository 提交失败: %s", commit_id)
                        else:
                            # Chain Trace: 记录 truth_aggregate_id (memory_id/event_id)
                            # P0-2修复：从EntityWriteReceipt中提取memory_id，或直接使用str类型的commit_id
                            if hasattr(commit_id, 'memory_id'):
                                # EntityWriteReceipt对象
                                w_trace.truth_aggregate_ids.append(commit_id.memory_id)
                            elif isinstance(commit_id, str) and commit_id not in ["discarded", "pending_phase2", "pending_no_store"]:
                                # 普通的memory_id字符串
                                w_trace.truth_aggregate_ids.append(commit_id)
                else:
                    trace.candidates_rejected += 1
                    code = decision.reason_code
                    trace.reason_codes[code] = trace.reason_codes.get(code, 0) + 1

        trace.elapsed_ms = (time.monotonic() - t0) * 1000
        # 监控: 记录写入成功
        _elapsed = (time.time() - _monitoring_start) * 1000
        metrics_collector.record_write_success(
            elapsed_ms=_elapsed,
            lane=trace.lanes_activated[0] if trace.lanes_activated else None,
            speech_act=trace.speech_act,
            candidates_total=trace.candidates_total,
            candidates_accepted=trace.candidates_accepted,
        )
        # B4: 转换为 V2WriteResult
        return _convert_trace_to_result(trace, user_id, turn_id, tenant_id, occurred_at)


def _convert_trace_to_result(
    trace: WriteTrace,
    user_id: str,
    turn_id: str,
    tenant_id: str,
    occurred_at: datetime,
) -> V2WriteResult:
    """将内部 WriteTrace 转换为外部 V2WriteResult

    B4 修复：提供类型化结果，区分成功/失败状态
    P0-3修复：使用trace.lane_outcomes提供完整的可观测性
    """
    # P0-3修复：直接使用trace中已保存的lane_outcomes
    lane_outcomes = trace.lane_outcomes if hasattr(trace, 'lane_outcomes') and trace.lane_outcomes else []

    # 如果trace中没有lane_outcomes（向后兼容），则根据lane_results构建
    if not lane_outcomes:
        lane_outcomes = []
        for lane_key, count in trace.lane_results.items():
            lane_outcomes.append(
                LaneOutcome(
                    lane=lane_key,
                    status="success" if count > 0 else "success_empty",
                    candidates=[],  # 简化：不包含完整候选列表
                    error_code=None,
                    error_message=None,
                )
            )

    # 构建 CommitReceipt 列表
    # P0-2修复：识别并保留EntityWriteReceipt对象，不要包装成CommitReceipt
    commits = []
    if trace.repository_commits:
        for commit_result in trace.repository_commits:
            # 跳过错误和占位符
            if isinstance(commit_result, str) and commit_result in ["error", "discarded", "pending_phase2", "pending_no_store"]:
                continue

            # P0-2核心：如果是EntityWriteReceipt对象，直接保留
            if hasattr(commit_result, 'entity_id') and hasattr(commit_result, 'memory_id'):
                # 这是EntityWriteReceipt对象，直接添加
                commits.append(commit_result)
            elif isinstance(commit_result, str):
                # 是普通的memory_id字符串，包装成CommitReceipt
                commits.append(
                    CommitReceipt(
                        aggregate_type="MemoryRecord",  # 简化：默认类型
                        aggregate_id=commit_result,
                        projection_ids=[commit_result],
                        outbox_ids=[],
                        truth_committed=True,
                        index_visible=None,  # 异步索引
                    )
                )

    # 判断是否成功
    v2_write_success = len(commits) > 0

    # P0-3修复：识别真正失败的lane（status为error类型）
    failed_lanes = []
    for outcome in lane_outcomes:
        if outcome.status in ("api_error", "parse_error", "extraction_error", "schema_error"):
            failed_lanes.append(outcome.lane)

    return V2WriteResult(
        user_id=user_id,
        turn_id=turn_id,
        tenant_id=tenant_id,
        occurred_at=occurred_at,
        speech_act=trace.speech_act,
        lane_outcomes=lane_outcomes,
        commits=commits,
        v2_write_success=v2_write_success,
        total_candidates=trace.candidates_total,
        total_commits=len(commits),
        failed_lanes=failed_lanes,
    )
