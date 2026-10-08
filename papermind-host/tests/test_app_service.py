"""
测试业务服务层契约的正确性
"""

import pytest
from papermind.app_service import (
    Identity,
    EvidenceItem,
    AskResult,
    IDENTITIES,
)
from datetime import datetime


class TestIdentities:
    """测试固定身份列表"""

    def test_identities_count(self):
        """测试 IDENTITIES 包含恰好 3 个身份"""
        assert len(IDENTITIES) == 3, "IDENTITIES must contain exactly 3 identities"

    def test_identities_combinations(self):
        """测试三个身份分别是 tenant_A/user_A, tenant_A/user_B, tenant_B/user_A"""
        expected_combinations = {
            ("tenant_A", "user_A"),
            ("tenant_A", "user_B"),
            ("tenant_B", "user_A"),
        }
        actual_combinations = {
            (identity.tenant_id, identity.user_id) for identity in IDENTITIES
        }
        assert actual_combinations == expected_combinations, (
            f"IDENTITIES must contain exactly these combinations: {expected_combinations}, "
            f"but got: {actual_combinations}"
        )

    def test_no_duplicates(self):
        """测试 IDENTITIES 无重复"""
        combinations = [(id_.tenant_id, id_.user_id) for id_ in IDENTITIES]
        assert len(combinations) == len(set(combinations)), (
            "IDENTITIES must not contain duplicate tenant/user combinations"
        )

    def test_all_labels_non_empty(self):
        """测试每个 Identity 有非空 label"""
        for identity in IDENTITIES:
            assert identity.label, f"Identity {identity.tenant_id}/{identity.user_id} must have a non-empty label"
            assert len(identity.label.strip()) > 0, (
                f"Identity {identity.tenant_id}/{identity.user_id} label must not be whitespace-only"
            )


class TestDataclassImmutability:
    """测试所有 dataclass 都是 frozen（不可变）"""

    def test_identity_is_frozen(self):
        """测试 Identity 是不可变的"""
        identity = IDENTITIES[0]
        with pytest.raises(Exception):  # FrozenInstanceError in dataclasses
            identity.tenant_id = "new_tenant"

    def test_evidence_item_is_frozen(self):
        """测试 EvidenceItem 是不可变的"""
        evidence = EvidenceItem(
            memory_id="mem123",
            content="test content",
            memory_type="note",
            confidence=0.95,
            created_at=datetime.now(),
        )
        with pytest.raises(Exception):
            evidence.memory_id = "new_id"

    def test_ask_result_is_frozen(self):
        """测试 AskResult 是不可变的"""
        result = AskResult(
            status="answered",
            answer="test answer",
            evidence=[],
            error_code=None,
        )
        with pytest.raises(Exception):
            result.status = "failed"


class TestDataclassStructure:
    """测试 dataclass 结构完整性"""

    def test_identity_fields(self):
        """测试 Identity 包含所有必需字段"""
        identity = Identity(
            tenant_id="tenant_test",
            user_id="user_test",
            label="Test Label",
        )
        assert identity.tenant_id == "tenant_test"
        assert identity.user_id == "user_test"
        assert identity.label == "Test Label"

    def test_evidence_item_fields(self):
        """测试 EvidenceItem 包含所有必需字段"""
        now = datetime.now()
        evidence = EvidenceItem(
            memory_id="mem123",
            content="test content",
            memory_type="note",
            confidence=0.95,
            created_at=now,
        )
        assert evidence.memory_id == "mem123"
        assert evidence.content == "test content"
        assert evidence.memory_type == "note"
        assert evidence.confidence == 0.95
        assert evidence.created_at == now

    def test_evidence_item_nullable_created_at(self):
        """测试 EvidenceItem 的 created_at 可以为 None"""
        evidence = EvidenceItem(
            memory_id="mem123",
            content="test content",
            memory_type="note",
            confidence=0.95,
            created_at=None,
        )
        assert evidence.created_at is None

    def test_ask_result_fields(self):
        """测试 AskResult 包含所有必需字段"""
        evidence_list = [
            EvidenceItem(
                memory_id="mem1",
                content="evidence 1",
                memory_type="note",
                confidence=0.9,
                created_at=None,
            )
        ]
        result = AskResult(
            status="answered",
            answer="test answer",
            evidence=evidence_list,
            error_code=None,
        )
        assert result.status == "answered"
        assert result.answer == "test answer"
        assert result.evidence == evidence_list
        assert result.error_code is None

    def test_ask_result_with_error_code(self):
        """测试 AskResult 可以包含 error_code"""
        result = AskResult(
            status="retrieval_failed",
            answer="",
            evidence=[],
            error_code="QDRANT_UNAVAILABLE",
        )
        assert result.error_code == "QDRANT_UNAVAILABLE"
