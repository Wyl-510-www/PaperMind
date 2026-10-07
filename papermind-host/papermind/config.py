"""Configuration management for PaperMind Agent Host.

This module provides type-safe configuration loading from environment variables
and .env files using Pydantic Settings.
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuration for PaperMind Agent Host.

    Loads settings from environment variables and .env files.
    Environment variables take precedence over .env file values.

    Attributes:
        bailian_api_key: DashScope API key (required)
        llm_model: Model name to use (default: qwen-max)
        llm_base_url: DashScope API base URL
        log_level: Logging level (default: INFO)
    """

    bailian_api_key: str = Field(
        ...,
        description="DashScope API Key from https://dashscope.console.aliyun.com/apiKey",
    )

    llm_model: str = Field(
        default="qwen-max",
        description="Model name to use for LLM calls",
    )

    llm_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="DashScope API base URL",
    )

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Memory V2 检索配置
    memory_retrieval_limit: int = Field(
        default=5,
        description="Maximum number of memory evidences to retrieve",
    )

    memory_retrieval_timeout: float = Field(
        default=1.0,
        description="Memory retrieval timeout in seconds",
    )

    memory_enable_reranker: bool = Field(
        default=True,
        description="Enable reranker for memory retrieval quality improvement",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("bailian_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate that API key is not empty or placeholder."""
        if not v or v.strip() == "" or v == "sk-xxx":
            raise ValueError(
                "BAILIAN_API_KEY is required. "
                "Please set it in .env file or environment variable. "
                "Get your API key from: https://dashscope.console.aliyun.com/apiKey"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the standard levels."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Invalid log_level: {v}. Must be one of {valid_levels}")
        return v_upper


def get_config() -> Config:
    """Load and validate configuration.

    Returns:
        Config: Validated configuration object

    Raises:
        ValidationError: If required fields are missing or invalid

    Example:
        >>> config = get_config()
        >>> print(config.llm_model)
        'qwen-max'
    """
    return Config()  # type: ignore[call-arg]
