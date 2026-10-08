"""Test extractors/base.py 和 semantic.py（Phase 5 #03）"""

import pytest

from server.memory_v2.write.extractors.base import BaseExtractor, ExtractionInput
from server.memory_v2.write.extractors.semantic import SemanticExtractor


@pytest.fixture
def extraction_input():
    return ExtractionInput(
        user_text="我不吃香菜",
        user_id="user_123",
        turn_id="turn_456",
        occurred_at="2026-08-03T10:00:00Z",
    )


def test_extraction_input_fields(extraction_input):
    """ExtractionInput 包含必需字段"""
    assert extraction_input.user_text == "我不吃香菜"
    assert extraction_input.user_id == "user_123"
    assert extraction_input.turn_id == "turn_456"
    assert extraction_input.occurred_at == "2026-08-03T10:00:00Z"


def test_base_extractor_is_abstract():
    """BaseExtractor 是抽象类，不能直接实例化"""
    with pytest.raises(TypeError):
        BaseExtractor()


def test_base_extractor_validate_source_span():
    """BaseExtractor._validate_source_span 校验逻辑"""

    class FakeCandidate:
        def __init__(self, source_span):
            self.source_span = source_span

    extractor = SemanticExtractor()

    candidate = FakeCandidate(source_span="不吃香菜")

    # source_span 存在于 user_text 中
    assert extractor._validate_source_span(candidate, "我不吃香菜") is True

    # source_span 不存在于 user_text 中
    assert extractor._validate_source_span(candidate, "我喜欢吃辣") is False


@pytest.mark.asyncio
async def test_semantic_extractor_no_llm_returns_empty(extraction_input):
    """SemanticExtractor 无 LLM 客户端时返回空列表（测试模式）"""
    extractor = SemanticExtractor(llm_client=None)
    result = await extractor.extract(extraction_input)
    assert result == []


def test_semantic_extractor_has_llm_client_attribute():
    """SemanticExtractor 正确初始化 llm_client"""
    extractor_no_llm = SemanticExtractor(llm_client=None)
    assert extractor_no_llm.llm_client is None

    fake_llm = object()
    extractor_with_llm = SemanticExtractor(llm_client=fake_llm)
    assert extractor_with_llm.llm_client is fake_llm

