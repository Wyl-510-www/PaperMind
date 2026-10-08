"""
Phase 2.2: 翻译服务模块

支持多种翻译服务，默认使用百度翻译API
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranslationResult:
    """翻译结果"""

    success: bool
    translated_text: str | None
    error_message: str | None
    source_lang: str | None  # 检测到的源语言
    target_lang: str  # 目标语言


class TranslatorBackend(Protocol):
    """翻译服务接口"""

    async def translate(
        self,
        text: str,
        target_lang: str = "zh",
        source_lang: str = "auto",
    ) -> TranslationResult:
        """翻译文本"""
        ...


class BaiduTranslator:
    """
    百度翻译API实现

    使用说明：
    1. 注册百度翻译开放平台：https://fanyi-api.baidu.com/
    2. 创建应用获取 APP ID 和密钥
    3. 通过环境变量或配置文件设置：
       - BAIDU_TRANSLATE_APP_ID
       - BAIDU_TRANSLATE_SECRET_KEY
    """

    def __init__(self, app_id: str, secret_key: str):
        self.app_id = app_id
        self.secret_key = secret_key
        self.endpoint = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    async def translate(
        self,
        text: str,
        target_lang: str = "zh",
        source_lang: str = "auto",
    ) -> TranslationResult:
        """
        调用百度翻译API

        Args:
            text: 待翻译文本
            target_lang: 目标语言（zh=中文, en=英文）
            source_lang: 源语言（auto=自动检测）
        """
        try:
            import httpx
        except ImportError:
            return TranslationResult(
                success=False,
                translated_text=None,
                error_message="httpx 未安装，请运行：pip install httpx",
                source_lang=None,
                target_lang=target_lang,
            )

        # 生成签名
        salt = str(random.randint(32768, 65536))
        sign_str = f"{self.app_id}{text}{salt}{self.secret_key}"
        sign = hashlib.md5(sign_str.encode()).hexdigest()

        # 构造请求参数
        params = {
            "q": text,
            "from": source_lang,
            "to": target_lang,
            "appid": self.app_id,
            "salt": salt,
            "sign": sign,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.endpoint, params=params)
                response.raise_for_status()
                data = response.json()

                # 检查错误码
                if "error_code" in data:
                    error_messages = {
                        "52001": "请求超时，请重试",
                        "52002": "系统错误，请重试",
                        "52003": "未授权用户，请检查 APP ID 和密钥",
                        "54000": "必填参数为空",
                        "54001": "签名错误，请检查密钥",
                        "54003": "访问频率受限",
                        "54004": "账户余额不足",
                        "54005": "长查询请求频繁",
                        "58000": "客户端IP非法",
                    }
                    error_msg = error_messages.get(
                        data["error_code"],
                        f"翻译失败，错误码：{data['error_code']}",
                    )
                    return TranslationResult(
                        success=False,
                        translated_text=None,
                        error_message=error_msg,
                        source_lang=None,
                        target_lang=target_lang,
                    )

                # 提取翻译结果
                if "trans_result" in data and len(data["trans_result"]) > 0:
                    translated_parts = [item["dst"] for item in data["trans_result"]]
                    translated_text = "\n".join(translated_parts)

                    return TranslationResult(
                        success=True,
                        translated_text=translated_text,
                        error_message=None,
                        source_lang=data.get("from"),
                        target_lang=target_lang,
                    )
                else:
                    return TranslationResult(
                        success=False,
                        translated_text=None,
                        error_message="未能获取翻译结果",
                        source_lang=None,
                        target_lang=target_lang,
                    )

        except httpx.TimeoutException:
            return TranslationResult(
                success=False,
                translated_text=None,
                error_message="翻译请求超时，请检查网络连接",
                source_lang=None,
                target_lang=target_lang,
            )
        except httpx.HTTPStatusError as e:
            return TranslationResult(
                success=False,
                translated_text=None,
                error_message=f"翻译服务错误：HTTP {e.response.status_code}",
                source_lang=None,
                target_lang=target_lang,
            )
        except Exception as e:
            return TranslationResult(
                success=False,
                translated_text=None,
                error_message=f"翻译失败：{str(e)}",
                source_lang=None,
                target_lang=target_lang,
            )


class MockTranslator:
    """
    Mock 翻译服务（用于演示和测试）
    """

    async def translate(
        self,
        text: str,
        target_lang: str = "zh",
        source_lang: str = "auto",
    ) -> TranslationResult:
        """返回 Mock 翻译结果"""
        return TranslationResult(
            success=True,
            translated_text=f"[Mock 翻译] 这是原文的中文翻译版本（实际部署请配置真实翻译API）\n\n原文前100字符：{text[:100]}...",
            error_message=None,
            source_lang="en",
            target_lang=target_lang,
        )


def create_translator(
    app_id: str | None = None,
    secret_key: str | None = None,
    use_mock: bool = False,
) -> TranslatorBackend:
    """
    创建翻译服务实例

    Args:
        app_id: 百度翻译 APP ID（可选，从环境变量读取）
        secret_key: 百度翻译密钥（可选，从环境变量读取）
        use_mock: 是否使用 Mock 服务（默认False）

    Returns:
        TranslatorBackend: 翻译服务实例
    """
    if use_mock:
        return MockTranslator()

    # 从环境变量读取配置
    import os

    # 尝试加载 .env 文件
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # python-dotenv 不是必需的

    app_id = app_id or os.getenv("BAIDU_TRANSLATE_APP_ID")
    secret_key = secret_key or os.getenv("BAIDU_TRANSLATE_SECRET_KEY")

    if app_id and secret_key:
        return BaiduTranslator(app_id=app_id, secret_key=secret_key)
    else:
        # 配置缺失时使用 Mock
        return MockTranslator()
