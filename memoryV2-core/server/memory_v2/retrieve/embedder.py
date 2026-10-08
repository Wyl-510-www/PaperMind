"""Real embedder：OpenAI 兼容协议的向量化服务（阿里云百炼 text-embedding-v4）。

实现 outbox.Embedder Protocol。worker 消费 outbox 记录时用它把文本转向量写入 Qdrant。

维度必须与 Qdrant collection 一致（默认 1536），构造时可 fail-fast 校验。

配置来源（server/core/settings.py:Config_Bailian）：
- API_KEY（BAILIAN_API_KEY）
- MODEL_EMBEDDING_QWEN = "text-embedding-v4"
- MODEL_EMBEDDING_QWEN_URL（OpenAI 兼容端点）
- MODEL_EMBEDDING_QWEN_DIM = 1536
"""

from __future__ import annotations

from openai import OpenAI

from server.core.settings import Config_Bailian


class RealEmbedder:
    """OpenAI 兼容 embedding 适配器，实现 outbox.Embedder Protocol。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        dimensions: int | None = None,
    ):
        """
        Args:
            api_key: 百炼 API key，默认从 Config_Bailian.API_KEY 读取
            model: embedding 模型名，默认 text-embedding-v4
            base_url: OpenAI 兼容端点，默认百炼 compatible-mode
            dimensions: 向量维度，默认 1536（须与 Qdrant collection 对齐）
        """
        self.api_key = api_key or Config_Bailian.API_KEY
        if not self.api_key:
            raise ValueError(
                "RealEmbedder requires api_key (from BAILIAN_API_KEY env var)"
            )
        self.model = model or Config_Bailian.MODEL_EMBEDDING_QWEN
        self.base_url = base_url or Config_Bailian.MODEL_EMBEDDING_QWEN_URL
        self.dimensions = dimensions or Config_Bailian.MODEL_EMBEDDING_QWEN_DIM

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60.0,  # 增加超时到 60 秒
            max_retries=2,  # 最多重试 2 次
        )

    def embed(self, text: str) -> list[float]:
        """把文本转成向量，返回 list[float]（长度 = self.dimensions）。"""
        # OpenAI embedding 建议把换行替换成空格
        cleaned = text.replace("\n", " ")
        resp = self._client.embeddings.create(
            model=self.model,
            input=[cleaned],
            dimensions=self.dimensions,
        )
        return resp.data[0].embedding

    def validate_dimension(self, expected_dim: int) -> None:
        """探针校验：embed 一个样本，确认维度匹配 expected_dim，不匹配 fail-fast。"""
        probe = self.embed("维度校验探针")
        if len(probe) != expected_dim:
            raise ValueError(
                f"Embedder dimension mismatch: model '{self.model}' returned "
                f"{len(probe)}, but collection expects {expected_dim}"
            )
