"""Real reranker：实现 scorer.RerankerProtocol，后端用 SiliconFlow。

封装 server.core.reranker.SiliconFlowReranker，适配 Memory V2 的 Protocol。

scorer.RerankerProtocol 期望：
  def rerank(query: str, candidates: list[dict]) -> list[dict]
    - 输入 candidates 包含 memory_id + content/text_zh
    - 返回排序后的 candidates（降序），每个新增 rerank_score 字段

SiliconFlow API 配置（server/core/settings.py:Config_Bailian）：
- RERANKER_SF_API_KEY（必须环境变量注入）
- RERANKER_SF_MODEL = "Qwen/Qwen3-Reranker-0.6B"
- RERANKER_SF_BASE_URL
"""

from __future__ import annotations

from server.core.reranker import SiliconFlowReranker
from server.core.settings import Config_Bailian


class RealReranker:
    """scorer.RerankerProtocol 的真实实现，后端用 SiliconFlow Qwen3-Reranker-0.6B。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        top_n: int | None = None,
    ):
        """
        Args:
            api_key: SiliconFlow API key，默认从 RERANKER_SILICONFLOW_API_KEY 环境变量读取
            model: reranker 模型名，默认 Qwen/Qwen3-Reranker-0.6B
            base_url: rerank 端点，默认 https://api.siliconflow.cn/v1/rerank
            top_n: 返回条数上限（None 时返回全部候选），scorer 会再做裁剪
        """
        self._api_key = api_key or Config_Bailian.RERANKER_SF_API_KEY
        self._model = model or Config_Bailian.RERANKER_SF_MODEL
        self._base_url = base_url or Config_Bailian.RERANKER_SF_BASE_URL

        if not self._api_key:
            raise ValueError(
                "RealReranker requires api_key (from RERANKER_SILICONFLOW_API_KEY env var)"
            )

        self._backend = SiliconFlowReranker(
            api_key=self._api_key,
            model=self._model,
            base_url=self._base_url,
            top_n=top_n,
        )

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """重排序候选，返回按 rerank_score 降序排列的 candidates。

        Protocol 要求：
        - 输入 candidates 包含 memory_id/event_id + content/text_zh
        - 返回排序后的 candidates，新增 rerank_score 字段

        SiliconFlowReranker 期望 documents 含 text/content 字段，
        这里先把 text_zh/content 映射到 content 供后端调用。
        """
        if not candidates:
            return candidates

        # 准备输入：确保每个 candidate 有 content 字段供 SiliconFlowReranker 使用
        # 避免直接修改 candidates（副作用），复制一份
        docs_for_rerank = []
        for cand in candidates:
            doc = dict(cand)  # 浅拷贝
            if "content" not in doc:
                doc["content"] = doc.get("text_zh", doc.get("text", ""))
            docs_for_rerank.append(doc)

        # 调用后端 reranker（已按 rerank_score 降序排列）
        reranked = self._backend.rerank(query=query, documents=docs_for_rerank)
        return reranked
