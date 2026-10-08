"""Memory writer 模块测试。

测试覆盖：
1. 未确认输入和查询不触发写入（UT-01, UT-02）
2. 有效回执判定为 saved（UT-03）
3. 零候选判定为 no_memory（UT-04）
4. 错误判定为 failed（UT-05）
5. 部分提交判定为 partial（UT-06）
6. turn_id 正确传递（UT-09）
7. 数据库 session 释放
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from papermind.memory_writer import (
    save_turn_to_memory,
    _normalize_write_result,
    WriteResult,
)


class TestWriteResultNormalization:
    """测试 V2WriteResult 到 WriteResult 的归一化逻辑。"""

    def test_unconfirmed_returns_skipped(self):
        """UT-01: confirmed=False 返回 skipped，不触发抽取。"""
        import asyncio
        result = asyncio.run(save_turn_to_memory(
            user_text="我喜欢看论文",
            tenant_id="tenant_test",
            user_id="user_test",
            turn_id="test-unconfirmed",
            confirmed=False,
        ))

        assert result.status == "skipped"
        assert result.speech_act is None
        assert result.memory_ids == []
        assert "未确认" in result.message

    def test_query_returns_skipped(self):
        """UT-02: 查询返回 skipped。"""
        from server.memory_v2.contracts import V2WriteResult, LaneOutcome

        raw = V2WriteResult(
            user_id="user_A",
            turn_id="test-query",
            tenant_id="tenant_A",
            occurred_at=datetime.now(timezone.utc),
            speech_act="query_existing",
            lane_outcomes=[],
            commits=[],
            v2_write_success=False,
            failed_lanes=[],
        )

        result = _normalize_write_result(raw, "test-query")

        assert result.status == "skipped"
        assert result.speech_act == "query_existing"
        assert result.memory_ids == []
        assert "查询" in result.message

    def test_valid_commit_returns_saved(self):
        """UT-03: 有效 CommitReceipt 判定为 saved。"""
        from server.memory_v2.contracts import V2WriteResult, CommitReceipt, LaneOutcome

        raw = V2WriteResult(
            user_id="user_A",
            turn_id="test-saved",
            tenant_id="tenant_A",
            occurred_at=datetime.now(timezone.utc),
            speech_act="assert",
            lane_outcomes=[
                LaneOutcome(
                    lane="semantic",
                    status="success",
                    candidates=[],
                )
            ],
            commits=[
                CommitReceipt(
                    aggregate_type="MemoryRecord",
                    aggregate_id="mem-abc123",
                    projection_ids=["mem-abc123"],
                    outbox_ids=["1"],
                    truth_committed=True,
                    index_visible=None,
                )
            ],
            v2_write_success=True,
            total_candidates=1,
            total_commits=1,
            failed_lanes=[],
        )

        result = _normalize_write_result(raw, "test-saved")

        assert result.status == "saved"
        assert result.speech_act == "assert"
        assert result.memory_ids == ["mem-abc123"]
        assert "已保存" in result.message
        assert result.error_code is None

    def test_no_commit_no_error_returns_no_memory(self):
        """UT-04: 零提交且无错误返回 no_memory。"""
        from server.memory_v2.contracts import V2WriteResult, LaneOutcome

        raw = V2WriteResult(
            user_id="user_A",
            turn_id="test-no-memory",
            tenant_id="tenant_A",
            occurred_at=datetime.now(timezone.utc),
            speech_act="assert",
            lane_outcomes=[
                LaneOutcome(
                    lane="semantic",
                    status="success_empty",
                    candidates=[],
                )
            ],
            commits=[],
            v2_write_success=False,
            failed_lanes=[],
        )

        result = _normalize_write_result(raw, "test-no-memory")

        assert result.status == "no_memory"
        assert result.speech_act == "assert"
        assert result.memory_ids == []
        assert "未生成" in result.message

    def test_parse_error_returns_failed(self):
        """UT-05: 解析错误返回 failed。"""
        from server.memory_v2.contracts import V2WriteResult, LaneOutcome

        raw = V2WriteResult(
            user_id="user_A",
            turn_id="test-parse-error",
            tenant_id="tenant_A",
            occurred_at=datetime.now(timezone.utc),
            speech_act="assert",
            lane_outcomes=[
                LaneOutcome(
                    lane="semantic",
                    status="parse_error",
                    error_code="PARSE_ERROR",
                    error_message="JSON 解析失败",
                )
            ],
            commits=[],
            v2_write_success=False,
            failed_lanes=["semantic"],
        )

        result = _normalize_write_result(raw, "test-parse-error")

        assert result.status == "failed"
        assert result.memory_ids == []
        assert result.error_code == "PARSE_ERROR"
        assert "失败" in result.message

    def test_partial_commit_returns_partial(self):
        """UT-06: 部分提交且有错误返回 partial。"""
        from server.memory_v2.contracts import V2WriteResult, CommitReceipt, LaneOutcome

        raw = V2WriteResult(
            user_id="user_A",
            turn_id="test-partial",
            tenant_id="tenant_A",
            occurred_at=datetime.now(timezone.utc),
            speech_act="assert",
            lane_outcomes=[
                LaneOutcome(
                    lane="semantic",
                    status="success",
                    candidates=[],
                ),
                LaneOutcome(
                    lane="event_task",
                    status="api_error",
                    error_code="API_ERROR",
                )
            ],
            commits=[
                CommitReceipt(
                    aggregate_type="MemoryRecord",
                    aggregate_id="mem-xyz789",
                    projection_ids=["mem-xyz789"],
                    outbox_ids=["2"],
                    truth_committed=True,
                    index_visible=None,
                )
            ],
            v2_write_success=True,
            total_candidates=2,
            total_commits=1,
            failed_lanes=["event_task"],
        )

        result = _normalize_write_result(raw, "test-partial")

        assert result.status == "partial"
        assert result.memory_ids == ["mem-xyz789"]
        assert result.error_code == "PARTIAL_COMMIT"
        assert "部分已保存" in result.message

    def test_explicit_update_returns_skipped(self):
        """UT-02: 修改请求返回 skipped。"""
        from server.memory_v2.contracts import V2WriteResult

        raw = V2WriteResult(
            user_id="user_A",
            turn_id="test-update",
            tenant_id="tenant_A",
            occurred_at=datetime.now(timezone.utc),
            speech_act="explicit_update",
            lane_outcomes=[],
            commits=[],
            v2_write_success=False,
            failed_lanes=[],
        )

        result = _normalize_write_result(raw, "test-update")

        assert result.status == "skipped"
        assert result.speech_act == "explicit_update"
        assert "不支持修改或删除" in result.message


class TestInputValidation:
    """测试输入验证。"""

    def test_empty_text_returns_failed(self):
        """空文本返回 failed。"""
        import asyncio
        result = asyncio.run(save_turn_to_memory(
            user_text="",
            tenant_id="tenant_test",
            user_id="user_test",
            turn_id="test-empty",
            confirmed=True,
        ))

        assert result.status == "failed"
        assert result.error_code == "EMPTY_INPUT"

    def test_missing_identity_returns_failed(self):
        """缺少身份信息返回 failed。"""
        import asyncio
        result = asyncio.run(save_turn_to_memory(
            user_text="我喜欢论文",
            tenant_id="",
            user_id="user_test",
            turn_id="test-no-tenant",
            confirmed=True,
        ))

        assert result.status == "failed"
        assert result.error_code == "MISSING_IDENTITY"


class TestTurnIdHandling:
    """测试 turn_id 处理。"""

    def test_turn_id_preserved_in_result(self):
        """UT-09: turn_id 正确传递到结果中。"""
        from server.memory_v2.contracts import V2WriteResult

        turn_id = uuid4().hex
        raw = V2WriteResult(
            user_id="user_A",
            turn_id=turn_id,
            tenant_id="tenant_A",
            occurred_at=datetime.now(timezone.utc),
            speech_act="assert",
            lane_outcomes=[],
            commits=[],
            v2_write_success=False,
            failed_lanes=[],
        )

        result = _normalize_write_result(raw, turn_id)

        assert result.turn_id == turn_id


class TestSessionManagement:
    """测试数据库 session 管理。"""

    @patch('server.database.connection_pool.db_pool')
    def test_session_closed_on_success(self, mock_pool):
        """UT-08: 成功路径关闭 session。"""
        from papermind.memory_writer import _fact_writer

        mock_session = MagicMock()
        mock_pool.sync_session_factory.return_value = mock_session

        try:
            with _fact_writer() as writer:
                pass
        except Exception:
            pass

        mock_session.close.assert_called_once()

    @patch('server.memory_v2.llm_gate.DashScopeClient')
    @patch('server.database.connection_pool.db_pool')
    def test_session_closed_on_error(self, mock_pool, mock_client):
        """UT-08: 异常路径关闭 session。"""
        from papermind.memory_writer import _fact_writer

        mock_session = MagicMock()
        mock_pool.sync_session_factory.return_value = mock_session

        try:
            with _fact_writer() as writer:
                raise RuntimeError("Test error")
        except RuntimeError:
            pass

        mock_session.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
