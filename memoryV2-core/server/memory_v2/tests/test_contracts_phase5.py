"""Test contracts.py 的新增枚举和模型（Phase 5 #01）"""

import pytest
from pydantic import ValidationError

from server.memory_v2.contracts import (
    ExtractionLane,
    LanePlan,
    MemoryType,
)


def test_memory_type_has_behavior_policy():
    """MemoryType 枚举包含 BEHAVIOR_POLICY"""
    assert MemoryType.BEHAVIOR_POLICY == "behavior_policy"
    assert "behavior_policy" in [e.value for e in MemoryType]


def test_extraction_lane_enum():
    """ExtractionLane 枚举包含 6 个 lane"""
    assert ExtractionLane.SEMANTIC == "semantic"
    assert ExtractionLane.EVENT_TASK == "event_task"
    assert ExtractionLane.ENTITY_RELATION == "entity_relation"
    assert ExtractionLane.BEHAVIOR_POLICY == "behavior_policy"
    assert ExtractionLane.UPDATE_DELETE == "update_delete"
    assert len(list(ExtractionLane)) == 5


def test_lane_plan_model():
    """LanePlan 模型正常构造"""
    plan = LanePlan(
        lanes=[ExtractionLane.SEMANTIC, ExtractionLane.EVENT_TASK],
        reason_codes={
            "semantic": "baseline",
            "event_task": "EVENT_MARKERS",
        },
    )
    assert len(plan.lanes) == 2
    assert plan.reason_codes["semantic"] == "baseline"


def test_lane_plan_forbids_extra_fields():
    """LanePlan 禁止额外字段（StrictModel）"""
    with pytest.raises(ValidationError) as exc_info:
        LanePlan(
            lanes=[ExtractionLane.SEMANTIC],
            reason_codes={},
            extra_field="not_allowed",
        )
    assert "extra_field" in str(exc_info.value)


def test_lane_plan_default_reason_codes():
    """LanePlan reason_codes 默认为空字典"""
    plan = LanePlan(lanes=[ExtractionLane.SEMANTIC])
    assert plan.reason_codes == {}


def test_lane_plan_requires_lanes():
    """LanePlan 必须提供 lanes 字段"""
    with pytest.raises(ValidationError) as exc_info:
        LanePlan(reason_codes={})
    assert "lanes" in str(exc_info.value)
