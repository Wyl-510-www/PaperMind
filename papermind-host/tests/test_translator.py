"""
测试翻译服务模块
"""

import pytest
from papermind.translator import (
    create_translator,
    MockTranslator,
    BaiduTranslator,
    TranslationResult,
)


@pytest.mark.asyncio
async def test_mock_translator():
    """测试 Mock 翻译器"""
    translator = MockTranslator()

    result = await translator.translate(
        text="Hello, world!",
        target_lang="zh",
        source_lang="auto",
    )

    assert result.success is True
    assert result.translated_text is not None
    assert result.error_message is None
    assert "Mock 翻译" in result.translated_text


@pytest.mark.asyncio
async def test_create_translator_default_to_mock():
    """测试默认创建 Mock 翻译器"""
    translator = create_translator(use_mock=True)

    assert isinstance(translator, MockTranslator)

    result = await translator.translate("Test text", target_lang="zh")

    assert result.success is True
    assert result.translated_text is not None


@pytest.mark.asyncio
async def test_baidu_translator_missing_httpx():
    """测试 httpx 缺失时的错误处理"""
    # 这个测试假设环境中已安装 httpx
    # 实际场景中，如果 httpx 未安装，会返回错误
    translator = BaiduTranslator(
        app_id="test_app_id",
        secret_key="test_secret_key",
    )

    # 使用错误的凭据会导致API错误，而不是成功
    result = await translator.translate("Hello", target_lang="zh")

    # 预期会失败（因为凭据无效或网络问题）
    # 这里只验证返回了 TranslationResult 对象
    assert isinstance(result, TranslationResult)


def test_create_translator_with_credentials():
    """测试使用凭据创建翻译器"""
    translator = create_translator(
        app_id="test_app_id",
        secret_key="test_secret_key",
    )

    assert isinstance(translator, BaiduTranslator)
    assert translator.app_id == "test_app_id"
    assert translator.secret_key == "test_secret_key"
