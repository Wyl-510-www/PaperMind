"""
测试业务服务层契约的正确性
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from papermind.app_service import (
    Identity,
    EvidenceItem,
    AskResult,
    IDENTITIES,
    save_note,
    sync_notes,
)
from papermind.memory_writer import WriteResult as Phase13WriteResult
from papermind.outbox_sync import SyncResult as Phase13SyncResult
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


class TestSaveNote:
    """测试 save_note 函数"""

    @pytest.mark.asyncio
    async def test_empty_title(self):
        """测试空标题返回 skipped"""
        identity = IDENTITIES[0]
        result = await save_note(
            identity=identity,
            title="",
            conclusion="这是一个结论",
            confirmed=True,
        )
        assert result.status == "skipped"
        assert "标题为空" in result.message
        assert result.memory_ids == []

    @pytest.mark.asyncio
    async def test_whitespace_only_title(self):
        """测试仅空格的标题返回 skipped"""
        identity = IDENTITIES[0]
        result = await save_note(
            identity=identity,
            title="   ",
            conclusion="这是一个结论",
            confirmed=True,
        )
        assert result.status == "skipped"
        assert "标题为空" in result.message

    @pytest.mark.asyncio
    async def test_empty_conclusion(self):
        """测试空结论返回 skipped"""
        identity = IDENTITIES[0]
        result = await save_note(
            identity=identity,
            title="论文标题",
            conclusion="",
            confirmed=True,
        )
        assert result.status == "skipped"
        assert "阅读结论为空" in result.message
        assert result.memory_ids == []

    @pytest.mark.asyncio
    async def test_whitespace_only_conclusion(self):
        """测试仅空格的结论返回 skipped"""
        identity = IDENTITIES[0]
        result = await save_note(
            identity=identity,
            title="论文标题",
            conclusion="   \n  ",
            confirmed=True,
        )
        assert result.status == "skipped"
        assert "阅读结论为空" in result.message

    @pytest.mark.asyncio
    async def test_confirmed_false_does_not_call_phase13(self):
        """测试 confirmed=False 不调用 save_turn_to_memory"""
        identity = IDENTITIES[0]

        with patch("papermind.app_service.save_turn_to_memory") as mock_save:
            result = await save_note(
                identity=identity,
                title="论文标题",
                conclusion="这是结论",
                confirmed=False,
            )

            # 不应调用 Phase 1.3
            mock_save.assert_not_called()

            # 应返回 skipped
            assert result.status == "skipped"
            assert "用户未确认保存" in result.message
            assert result.memory_ids == []

    @pytest.mark.asyncio
    async def test_confirmed_true_calls_phase13_with_correct_params(self):
        """测试 confirmed=True 调用 save_turn_to_memory 并传递正确参数"""
        identity = IDENTITIES[0]

        mock_result = Phase13WriteResult(
            status="saved",
            speech_act="explicit_state",
            memory_ids=["mem-123"],
            turn_id="turn-456",
            message="已保存 1 条记忆",
            error_code=None,
        )

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = mock_result

            result = await save_note(
                identity=identity,
                title="注意力机制研究",
                conclusion="自注意力有效提升了模型性能",
                confirmed=True,
            )

            # 应调用 Phase 1.3
            mock_save.assert_called_once()
            call_args = mock_save.call_args

            # 验证参数
            assert call_args.kwargs["tenant_id"] == "tenant_A"
            assert call_args.kwargs["user_id"] == "user_A"
            assert call_args.kwargs["confirmed"] is True
            assert "注意力机制研究" in call_args.kwargs["user_text"]
            assert "自注意力有效提升了模型性能" in call_args.kwargs["user_text"]

            # 验证 turn_id 是 UUID hex 格式（32 字符）
            turn_id = call_args.kwargs["turn_id"]
            assert isinstance(turn_id, str)
            assert len(turn_id) == 32

            # 应透传 Phase 1.3 的结果
            assert result.status == "saved"
            assert result.memory_ids == ["mem-123"]

    @pytest.mark.asyncio
    async def test_generates_unique_turn_id_each_call(self):
        """测试每次调用生成不同的 turn_id"""
        identity = IDENTITIES[0]

        turn_ids = []

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = Phase13WriteResult(
                status="saved",
                speech_act="explicit_state",
                memory_ids=[],
                turn_id="dummy",
                message="",
                error_code=None,
            )

            for _ in range(3):
                await save_note(
                    identity=identity,
                    title="标题",
                    conclusion="结论",
                    confirmed=True,
                )
                turn_ids.append(mock_save.call_args.kwargs["turn_id"])

            # 三次调用应生成三个不同的 turn_id
            assert len(set(turn_ids)) == 3

    @pytest.mark.asyncio
    async def test_user_message_format(self):
        """测试用户消息格式正确"""
        identity = IDENTITIES[0]

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = Phase13WriteResult(
                status="saved",
                speech_act="explicit_state",
                memory_ids=[],
                turn_id="dummy",
                message="",
                error_code=None,
            )

            await save_note(
                identity=identity,
                title="深度学习综述",
                conclusion="卷积神经网络在图像识别任务中表现优异",
                confirmed=True,
            )

            user_text = mock_save.call_args.kwargs["user_text"]
            assert user_text == "论文：深度学习综述\n\n阅读结论：卷积神经网络在图像识别任务中表现优异"

    @pytest.mark.asyncio
    async def test_identity_propagation(self):
        """测试身份正确透传"""
        identity = Identity(
            tenant_id="tenant_custom",
            user_id="user_custom",
            label="Custom",
        )

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = Phase13WriteResult(
                status="saved",
                speech_act="explicit_state",
                memory_ids=[],
                turn_id="dummy",
                message="",
                error_code=None,
            )

            await save_note(
                identity=identity,
                title="标题",
                conclusion="结论",
                confirmed=True,
            )

            assert mock_save.call_args.kwargs["tenant_id"] == "tenant_custom"
            assert mock_save.call_args.kwargs["user_id"] == "user_custom"

    @pytest.mark.asyncio
    async def test_status_saved_passthrough(self):
        """测试 saved 状态正确透传"""
        identity = IDENTITIES[0]

        mock_result = Phase13WriteResult(
            status="saved",
            speech_act="explicit_state",
            memory_ids=["mem-1", "mem-2"],
            turn_id="turn-123",
            message="已保存 2 条记忆",
            error_code=None,
        )

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = mock_result

            result = await save_note(
                identity=identity,
                title="标题",
                conclusion="结论",
                confirmed=True,
            )

            assert result.status == "saved"
            assert result.memory_ids == ["mem-1", "mem-2"]
            assert result.turn_id == "turn-123"
            assert result.message == "已保存 2 条记忆"
            assert result.error_code is None

    @pytest.mark.asyncio
    async def test_status_partial_passthrough(self):
        """测试 partial 状态正确透传"""
        identity = IDENTITIES[0]

        mock_result = Phase13WriteResult(
            status="partial",
            speech_act="explicit_state",
            memory_ids=["mem-1"],
            turn_id="turn-123",
            message="部分已保存（1 条），存在错误",
            error_code="PARTIAL_COMMIT",
        )

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = mock_result

            result = await save_note(
                identity=identity,
                title="标题",
                conclusion="结论",
                confirmed=True,
            )

            assert result.status == "partial"
            assert result.memory_ids == ["mem-1"]
            assert result.error_code == "PARTIAL_COMMIT"

    @pytest.mark.asyncio
    async def test_status_no_memory_passthrough(self):
        """测试 no_memory 状态正确透传"""
        identity = IDENTITIES[0]

        mock_result = Phase13WriteResult(
            status="no_memory",
            speech_act="explicit_state",
            memory_ids=[],
            turn_id="turn-123",
            message="未生成可保存的事实",
            error_code=None,
        )

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = mock_result

            result = await save_note(
                identity=identity,
                title="标题",
                conclusion="结论",
                confirmed=True,
            )

            assert result.status == "no_memory"
            assert result.memory_ids == []
            assert result.error_code is None

    @pytest.mark.asyncio
    async def test_status_failed_passthrough(self):
        """测试 failed 状态正确透传"""
        identity = IDENTITIES[0]

        mock_result = Phase13WriteResult(
            status="failed",
            speech_act="explicit_state",
            memory_ids=[],
            turn_id="turn-123",
            message="保存失败：模型调用失败",
            error_code="API_ERROR",
        )

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = mock_result

            result = await save_note(
                identity=identity,
                title="标题",
                conclusion="结论",
                confirmed=True,
            )

            assert result.status == "failed"
            assert result.memory_ids == []
            assert result.error_code == "API_ERROR"

    @pytest.mark.asyncio
    async def test_status_skipped_from_phase13_passthrough(self):
        """测试 Phase 1.3 返回的 skipped 状态正确透传"""
        identity = IDENTITIES[0]

        mock_result = Phase13WriteResult(
            status="skipped",
            speech_act="query_existing",
            memory_ids=[],
            turn_id="turn-123",
            message="已跳过：这是查询请求，不会写入记忆",
            error_code=None,
        )

        with patch("papermind.app_service.save_turn_to_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = mock_result

            result = await save_note(
                identity=identity,
                title="标题",
                conclusion="结论",
                confirmed=True,
            )

            assert result.status == "skipped"
            assert result.speech_act == "query_existing"


class TestSyncNotes:
    """测试 sync_notes 函数"""

    @pytest.mark.asyncio
    async def test_default_batch_size(self):
        """测试默认 batch_size 为 100"""
        mock_result = Phase13SyncResult(
            status="completed",
            done=5,
            failed=0,
            dead=0,
            message="同步完成：5 条记录已索引",
        )

        with patch("papermind.app_service.sync_outbox_batch", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = mock_result

            await sync_notes()

            mock_sync.assert_called_once_with(batch_size=100)

    @pytest.mark.asyncio
    async def test_custom_batch_size(self):
        """测试自定义 batch_size"""
        mock_result = Phase13SyncResult(
            status="completed",
            done=0,
            failed=0,
            dead=0,
            message="同步完成：当前批次为空",
        )

        with patch("papermind.app_service.sync_outbox_batch", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = mock_result

            await sync_notes(batch_size=50)

            mock_sync.assert_called_once_with(batch_size=50)

    @pytest.mark.asyncio
    async def test_empty_batch_returns_completed(self):
        """测试空批次返回 completed 状态"""
        mock_result = Phase13SyncResult(
            status="completed",
            done=0,
            failed=0,
            dead=0,
            message="同步完成：当前批次为空",
        )

        with patch("papermind.app_service.sync_outbox_batch", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = mock_result

            result = await sync_notes()

            assert result.status == "completed"
            assert result.done == 0
            assert result.failed == 0
            assert result.dead == 0

    @pytest.mark.asyncio
    async def test_successful_sync_passthrough(self):
        """测试成功同步的结果正确透传"""
        mock_result = Phase13SyncResult(
            status="completed",
            done=10,
            failed=0,
            dead=0,
            message="同步完成：10 条记录已索引",
        )

        with patch("papermind.app_service.sync_outbox_batch", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = mock_result

            result = await sync_notes()

            assert result.status == "completed"
            assert result.done == 10
            assert result.failed == 0
            assert result.dead == 0
            assert result.message == "同步完成：10 条记录已索引"

    @pytest.mark.asyncio
    async def test_failed_sync_passthrough(self):
        """测试失败同步的结果正确透传"""
        mock_result = Phase13SyncResult(
            status="failed",
            done=5,
            failed=3,
            dead=1,
            message="部分完成：5 条成功，3 条失败，1 条 dead",
        )

        with patch("papermind.app_service.sync_outbox_batch", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = mock_result

            result = await sync_notes()

            assert result.status == "failed"
            assert result.done == 5
            assert result.failed == 3
            assert result.dead == 1
            assert "部分完成" in result.message

    @pytest.mark.asyncio
    async def test_all_failed_passthrough(self):
        """测试全部失败的结果正确透传"""
        mock_result = Phase13SyncResult(
            status="failed",
            done=0,
            failed=5,
            dead=2,
            message="同步失败：5 条失败，2 条 dead",
        )

        with patch("papermind.app_service.sync_outbox_batch", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = mock_result

            result = await sync_notes()

            assert result.status == "failed"
            assert result.done == 0
            assert result.failed == 5
            assert result.dead == 2


class TestRetrieveStructuredEvidence:
    """测试结构化证据检索"""

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self):
        """测试空结果返回空列表"""
        from papermind.memory_retrieval import retrieve_structured_evidence
        from unittest.mock import MagicMock

        identity = IDENTITIES[0]

        # Mock get_config 和 _call_memory_v2_retrieval
        with patch("papermind.memory_retrieval.get_config") as mock_config, \
             patch("papermind.memory_retrieval._call_memory_v2_retrieval", new_callable=AsyncMock) as mock_retrieve:

            mock_config.return_value = MagicMock(memory_retrieval_timeout=1.0)
            mock_retrieve.return_value = {
                "query": "test query",
                "items": [],
                "generated_at": datetime.now(),
            }

            evidence_list = await retrieve_structured_evidence(
                query="test query",
                tenant_id=identity.tenant_id,
                user_id=identity.user_id,
                limit=5,
            )

            assert evidence_list == []
            mock_retrieve.assert_called_once_with(
                query="test query",
                tenant_id=identity.tenant_id,
                user_id=identity.user_id,
                limit=5,
            )

    @pytest.mark.asyncio
    async def test_successful_retrieval_returns_evidence_items(self):
        """测试成功检索返回 EvidenceItem 列表"""
        from papermind.memory_retrieval import retrieve_structured_evidence
        from unittest.mock import MagicMock

        identity = IDENTITIES[0]
        now = datetime.now()

        # Mock get_config 和 _call_memory_v2_retrieval
        with patch("papermind.memory_retrieval.get_config") as mock_config, \
             patch("papermind.memory_retrieval._call_memory_v2_retrieval", new_callable=AsyncMock) as mock_retrieve:

            mock_config.return_value = MagicMock(memory_retrieval_timeout=1.0)
            mock_retrieve.return_value = {
                "query": "test query",
                "items": [
                    {
                        "memory_id": "mem-1",
                        "text": "我的研究方向是计算机视觉",
                        "confidence": 0.95,
                        "memory_type": "semantic",
                        "created_at": now,
                    },
                    {
                        "memory_id": "mem-2",
                        "text": "我喜欢深度学习",
                        "confidence": 0.88,
                        "memory_type": "semantic",
                        "created_at": None,
                    },
                ],
                "generated_at": now,
            }

            evidence_list = await retrieve_structured_evidence(
                query="test query",
                tenant_id=identity.tenant_id,
                user_id=identity.user_id,
                limit=5,
            )

            assert len(evidence_list) == 2

            # 验证第一个 EvidenceItem
            assert evidence_list[0].memory_id == "mem-1"
            assert evidence_list[0].content == "我的研究方向是计算机视觉"
            assert evidence_list[0].confidence == 0.95
            assert evidence_list[0].memory_type == "semantic"
            assert evidence_list[0].created_at == now

            # 验证第二个 EvidenceItem
            assert evidence_list[1].memory_id == "mem-2"
            assert evidence_list[1].content == "我喜欢深度学习"
            assert evidence_list[1].confidence == 0.88
            assert evidence_list[1].memory_type == "semantic"
            assert evidence_list[1].created_at is None

    @pytest.mark.asyncio
    async def test_timeout_raises_exception(self):
        """测试超时抛出异常"""
        from papermind.memory_retrieval import retrieve_structured_evidence
        from unittest.mock import MagicMock

        identity = IDENTITIES[0]

        # Mock get_config (短超时)
        with patch("papermind.memory_retrieval.get_config") as mock_config, \
             patch("papermind.memory_retrieval._call_memory_v2_retrieval", new_callable=AsyncMock) as mock_retrieve:

            mock_config.return_value = MagicMock(memory_retrieval_timeout=0.01)

            # 模拟长时间运行
            async def long_running(*args, **kwargs):
                await asyncio.sleep(10)
            mock_retrieve.side_effect = long_running

            with pytest.raises(asyncio.TimeoutError):
                await retrieve_structured_evidence(
                    query="test query",
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    limit=5,
                )

    @pytest.mark.asyncio
    async def test_retrieval_failure_raises_exception(self):
        """测试检索失败抛出异常"""
        from papermind.memory_retrieval import retrieve_structured_evidence
        from unittest.mock import MagicMock

        identity = IDENTITIES[0]

        # Mock get_config 和 _call_memory_v2_retrieval (抛出异常)
        with patch("papermind.memory_retrieval.get_config") as mock_config, \
             patch("papermind.memory_retrieval._call_memory_v2_retrieval", new_callable=AsyncMock) as mock_retrieve:

            mock_config.return_value = MagicMock(memory_retrieval_timeout=1.0)
            mock_retrieve.side_effect = RuntimeError("Memory V2 unavailable")

            with pytest.raises(RuntimeError, match="Memory V2 unavailable"):
                await retrieve_structured_evidence(
                    query="test query",
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    limit=5,
                )

    @pytest.mark.asyncio
    async def test_tenant_user_propagation(self):
        """测试 tenant_id 和 user_id 正确透传"""
        from papermind.memory_retrieval import retrieve_structured_evidence
        from unittest.mock import MagicMock

        # Mock get_config 和 _call_memory_v2_retrieval
        with patch("papermind.memory_retrieval.get_config") as mock_config, \
             patch("papermind.memory_retrieval._call_memory_v2_retrieval", new_callable=AsyncMock) as mock_retrieve:

            mock_config.return_value = MagicMock(memory_retrieval_timeout=1.0)
            mock_retrieve.return_value = {
                "query": "test",
                "items": [],
                "generated_at": datetime.now(),
            }

            await retrieve_structured_evidence(
                query="my query",
                tenant_id="tenant_custom",
                user_id="user_custom",
                limit=10,
            )

            mock_retrieve.assert_called_once_with(
                query="my query",
                tenant_id="tenant_custom",
                user_id="user_custom",
                limit=10,
            )


class TestAskMemory:
    """测试 ask_memory 函数"""

    @pytest.mark.asyncio
    async def test_with_evidence_calls_llm_returns_answered(self):
        """测试有证据时调用 LLM 并返回 answered 状态"""
        from papermind.app_service import ask_memory

        identity = IDENTITIES[0]
        now = datetime.now()

        # Mock retrieve_structured_evidence 返回证据
        mock_evidence = [
            EvidenceItem(
                memory_id="mem-1",
                content="我的研究方向是计算机视觉",
                memory_type="semantic",
                confidence=0.95,
                created_at=now,
            ),
        ]

        # Mock LLM client
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "根据您的历史记忆，您的研究方向是计算机视觉。"

        with patch("papermind.memory_retrieval.retrieve_structured_evidence", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = mock_evidence

            result = await ask_memory(
                identity=identity,
                question="我的研究方向是什么？",
                llm_client=mock_llm,
            )

            # 验证检索被调用
            mock_retrieve.assert_called_once_with(
                query="我的研究方向是什么？",
                tenant_id=identity.tenant_id,
                user_id=identity.user_id,
                limit=5,
            )

            # 验证 LLM 被调用
            mock_llm.generate.assert_called_once()
            prompt = mock_llm.generate.call_args[0][0]
            assert "我的研究方向是计算机视觉" in prompt
            assert "我的研究方向是什么？" in prompt

            # 验证结果
            assert result.status == "answered"
            assert result.answer == "根据您的历史记忆，您的研究方向是计算机视觉。"
            assert result.evidence == mock_evidence
            assert result.error_code is None

    @pytest.mark.asyncio
    async def test_no_evidence_does_not_call_llm_returns_no_evidence(self):
        """测试无证据时不调用 LLM 并返回 no_evidence 状态"""
        from papermind.app_service import ask_memory

        identity = IDENTITIES[0]

        # Mock retrieve_structured_evidence 返回空列表
        mock_llm = AsyncMock()

        with patch("papermind.memory_retrieval.retrieve_structured_evidence", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            result = await ask_memory(
                identity=identity,
                question="我的兴趣爱好是什么？",
                llm_client=mock_llm,
            )

            # 验证检索被调用
            mock_retrieve.assert_called_once()

            # 验证 LLM 未被调用
            mock_llm.generate.assert_not_called()

            # 验证结果
            assert result.status == "no_evidence"
            assert "未找到相关历史记忆" in result.answer
            assert result.evidence == []
            assert result.error_code is None

    @pytest.mark.asyncio
    async def test_retrieval_failed_does_not_call_llm_returns_retrieval_failed(self):
        """测试检索失败时不调用 LLM 并返回 retrieval_failed 状态"""
        from papermind.app_service import ask_memory

        identity = IDENTITIES[0]

        # Mock retrieve_structured_evidence 抛出异常
        mock_llm = AsyncMock()

        with patch("papermind.memory_retrieval.retrieve_structured_evidence", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.side_effect = RuntimeError("Memory V2 unavailable")

            result = await ask_memory(
                identity=identity,
                question="我的研究方向是什么？",
                llm_client=mock_llm,
            )

            # 验证检索被调用
            mock_retrieve.assert_called_once()

            # 验证 LLM 未被调用
            mock_llm.generate.assert_not_called()

            # 验证结果
            assert result.status == "retrieval_failed"
            assert "检索失败" in result.answer or "记忆检索" in result.answer
            assert result.evidence == []
            assert result.error_code is not None

    @pytest.mark.asyncio
    async def test_llm_failure_returns_answer_failed_but_keeps_evidence(self):
        """测试检索成功但 LLM 失败时返回 answer_failed 并保留证据"""
        from papermind.app_service import ask_memory

        identity = IDENTITIES[0]
        now = datetime.now()

        # Mock retrieve_structured_evidence 返回证据
        mock_evidence = [
            EvidenceItem(
                memory_id="mem-1",
                content="我的研究方向是计算机视觉",
                memory_type="semantic",
                confidence=0.95,
                created_at=now,
            ),
        ]

        # Mock LLM client 抛出异常
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = RuntimeError("LLM API error")

        with patch("papermind.memory_retrieval.retrieve_structured_evidence", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = mock_evidence

            result = await ask_memory(
                identity=identity,
                question="我的研究方向是什么？",
                llm_client=mock_llm,
            )

            # 验证检索被调用
            mock_retrieve.assert_called_once()

            # 验证 LLM 被调用
            mock_llm.generate.assert_called_once()

            # 验证结果
            assert result.status == "answer_failed"
            assert "回答生成失败" in result.answer or "生成失败" in result.answer
            assert result.evidence == mock_evidence  # 保留证据
            assert result.error_code is not None

    @pytest.mark.asyncio
    async def test_identity_propagation(self):
        """测试身份正确透传到检索"""
        from papermind.app_service import ask_memory

        identity = Identity(
            tenant_id="tenant_custom",
            user_id="user_custom",
            label="Custom",
        )

        # Mock retrieve_structured_evidence
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "答案"

        with patch("papermind.memory_retrieval.retrieve_structured_evidence", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = [
                EvidenceItem(
                    memory_id="mem-1",
                    content="test",
                    memory_type="semantic",
                    confidence=0.9,
                    created_at=None,
                )
            ]

            await ask_memory(
                identity=identity,
                question="测试问题",
                llm_client=mock_llm,
            )

            # 验证身份透传
            mock_retrieve.assert_called_once_with(
                query="测试问题",
                tenant_id="tenant_custom",
                user_id="user_custom",
                limit=5,
            )

    @pytest.mark.asyncio
    async def test_system_prompt_requires_evidence_only_answers(self):
        """测试系统提示要求只基于证据回答"""
        from papermind.app_service import ask_memory

        identity = IDENTITIES[0]

        # Mock retrieve_structured_evidence 返回证据
        mock_evidence = [
            EvidenceItem(
                memory_id="mem-1",
                content="我喜欢打篮球",
                memory_type="semantic",
                confidence=0.9,
                created_at=None,
            ),
        ]

        # Mock LLM client
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "答案"

        with patch("papermind.memory_retrieval.retrieve_structured_evidence", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = mock_evidence

            await ask_memory(
                identity=identity,
                question="我的爱好是什么？",
                llm_client=mock_llm,
            )

            # 获取传给 LLM 的 prompt
            prompt = mock_llm.generate.call_args[0][0]

            # 验证系统提示包含关键约束
            assert "仅根据" in prompt or "只使用" in prompt or "只根据" in prompt
            assert "历史记忆" in prompt
            assert "我喜欢打篮球" in prompt  # 证据内容
            assert "我的爱好是什么？" in prompt  # 用户问题
            # 验证禁止使用模型知识的约束
            assert "不要使用" in prompt or "不使用" in prompt or "禁止" in prompt
