"""Test MemoryWriter 编排器（Phase 5 #05）"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from server.memory_v2.contracts import (
    ExtractionLane,
    MemoryCandidate,
    MemoryType,
    Modality,
    SubjectRef,
    WriteDecision,
    WriteTrace,
)
from server.memory_v2.write.writer import MemoryWriter


class FakeSemanticExtractor:
    """假 SEMANTIC extractor，返回预定义候选"""

    async def extract(self, inp):
        if "不吃香菜" in inp.user_text:
            return [
                MemoryCandidate(
                    candidate_id="c1",
                    value="香菜",
                    memory_type=MemoryType.SEMANTIC,
                    normalized_text_zh="用户不吃香菜",
                    source_span="不吃香菜",
                    predicate="diet.dislike",
                    modality=Modality.FACT,
                    confidence=0.95,
                    durability="stable",
                    subject=SubjectRef(canonical_name="user_123", is_current_user=True),
                )
            ]
        return []




class FakeEventTaskExtractor:
    async def extract(self, inp):
        return []


class FakeEntityRelationExtractor:
    async def extract(self, inp):
        return []


class FakeBehaviorPolicyExtractor:
    async def extract(self, inp):
        return []


class FakeUpdateDeleteExtractor:
    async def extract(self, inp):
        return []


@pytest.fixture
def writer_with_fake_extractors():
    """带假 extractor 的 MemoryWriter"""
    extractors = {
        "semantic": FakeSemanticExtractor(),
        "event_task": FakeEventTaskExtractor(),
        "entity_relation": FakeEntityRelationExtractor(),
        "behavior_policy": FakeBehaviorPolicyExtractor(),
        "update_delete": FakeUpdateDeleteExtractor(),
    }
    return MemoryWriter(extractors=extractors)


@pytest.mark.asyncio
async def test_writer_returns_write_trace(writer_with_fake_extractors):
    """MemoryWriter.write_turn 返回 WriteTrace"""
    trace = await writer_with_fake_extractors.write_turn(
        user_text="我不吃香菜",
        user_id="user_123",
        turn_id="turn_456",
    )

    assert isinstance(trace, WriteTrace)
    assert trace.turn_id == "turn_456"
    assert "semantic" in trace.lanes_activated
    assert trace.candidates_total >= 0
    assert trace.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_writer_baseline_semantic_activated(writer_with_fake_extractors):
    """普通输入至少激活 SEMANTIC lane"""
    trace = await writer_with_fake_extractors.write_turn(
        user_text="这是一句普通的话",
        user_id="user_123",
        turn_id="turn_456",
    )

    assert "semantic" in trace.lanes_activated


@pytest.mark.asyncio
async def test_writer_multi_lane_activation(writer_with_fake_extractors):
    """多关键词输入激活多个 lane"""
    trace = await writer_with_fake_extractors.write_turn(
        user_text="我朋友今天腿酸",
        user_id="user_123",
        turn_id="turn_456",
    )

    assert "semantic" in trace.lanes_activated
    # 应该激活 ENTITY_RELATION + EPISODIC_STATE
    assert len(trace.lanes_activated) >= 2


@pytest.mark.asyncio
async def test_writer_candidate_accepted(writer_with_fake_extractors):
    """SEMANTIC 候选通过 gate 并被接受"""
    trace = await writer_with_fake_extractors.write_turn(
        user_text="我不吃香菜",
        user_id="user_123",
        turn_id="turn_456",
    )

    assert trace.candidates_total == 1
    assert trace.candidates_accepted == 1
    assert trace.candidates_rejected == 0
    assert trace.lane_results.get("semantic", 0) == 1


@pytest.mark.asyncio
async def test_writer_track_rejected_candidates(writer_with_fake_extractors):
    """被拒候选正确统计（低置信度被拒）"""
    # 自定义一个会拒绝所有候选的 gate
    class RejectAllGate:
        def decide(self, candidate, signals):
            return WriteDecision(
                accepted=False,
                route=MemoryType.DISCARD,
                candidate=candidate,
                reason_code="LOW_CONFIDENCE",
            )

    writer = MemoryWriter(
        extractors={"semantic": FakeSemanticExtractor()},
        gate=RejectAllGate(),
    )

    trace = await writer.write_turn(
        user_text="我不吃香菜",
        user_id="user_123",
        turn_id="turn_456",
    )

    assert trace.candidates_rejected >= 1
    assert trace.reason_codes.get("LOW_CONFIDENCE", 0) >= 1


@pytest.mark.asyncio
async def test_writer_lane_failure_not_blocking():
    """某 lane 抽取失败不阻塞其他 lane"""
    class FailingExtractor:
        async def extract(self, inp):
            raise RuntimeError("LLM 调用失败")

    extractors = {
        "semantic": FailingExtractor()
    }
    writer = MemoryWriter(extractors=extractors)

    # 不应该抛异常
    trace = await writer.write_turn(
        user_text="我今天很累",
        user_id="user_123",
        turn_id="turn_456",
    )

    assert isinstance(trace, WriteTrace)
    assert trace.candidates_total == 0


@pytest.mark.asyncio
async def test_writer_dispatcher_called_for_accepted():
    """接受的候选会调用 dispatcher"""
    fake_dispatcher = MagicMock()
    fake_dispatcher.dispatch = AsyncMock()

    writer = MemoryWriter(
        extractors={"semantic": FakeSemanticExtractor()},
        dispatcher=fake_dispatcher,
    )

    await writer.write_turn(
        user_text="我不吃香菜",
        user_id="user_123",
        turn_id="turn_456",
    )

    fake_dispatcher.dispatch.assert_called_once()
