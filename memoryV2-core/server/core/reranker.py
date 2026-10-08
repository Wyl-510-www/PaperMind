"""SiliconFlow Reranker 封装 —— Qwen3-Reranker-0.6B

移植自 memory_agent，用于替代 DashScope gte-rerank-v2（效果不佳已注释）。

用法::

    from server.core.reranker import SiliconFlowReranker
    from server.core.settings import Config_Bailian

    reranker = SiliconFlowReranker(
        api_key=Config_Bailian.RERANKER_SF_API_KEY,
        model=Config_Bailian.RERANKER_SF_MODEL,
        base_url=Config_Bailian.RERANKER_SF_BASE_URL,
    )
    results = reranker.rerank(query, documents, top_n=10)
"""
import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class SiliconFlowReranker:
    """SiliconFlow 重排序器，调用 /v1/rerank 对检索结果做二次排序。

    参数:
        api_key: SiliconFlow API key（必须通过环境变量注入）。
        model: 重排序模型，默认 ``"Qwen/Qwen3-Reranker-0.6B"``。
        base_url: API 地址，默认 ``"https://api.siliconflow.cn/v1/rerank"``。
        top_n: 默认返回条数，可被 ``rerank()`` 的 ``top_n`` 覆盖。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "Qwen/Qwen3-Reranker-0.6B",
        base_url: str = "https://api.siliconflow.cn/v1/rerank",
        top_n: Optional[int] = None,
    ) -> None:
        if not api_key:
            raise ValueError("SiliconFlowReranker requires api_key (from RERANKER_SILICONFLOW_API_KEY env var)")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self.top_n = top_n

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """对 documents 做重排序，返回带 ``rerank_score`` 的排序结果。

        参数:
            query: 搜索查询文本。
            documents: 待排序文档列表，每个文档需含 ``"text"`` 或 ``"content"`` 字段。
            top_n: 返回条数，为 ``None`` 时使用构造函数中的默认值。

        返回:
            按 ``rerank_score`` 降序排列的文档列表，每条记录新增
            ``"rerank_score"`` 字段（0.0 ~ 1.0）。
        """
        if not documents:
            return documents

        # 提取每篇文档的文本（兼容多种字段名）
        doc_texts: List[str] = []
        for doc in documents:
            text = doc.get("text", "") or doc.get("content", "") or doc.get("memory", "")
            doc_texts.append(text)

        limit = top_n or self.top_n or len(documents)

        payload: Dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": doc_texts,
            "top_n": limit,
            "return_documents": False,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                self._base_url,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if resp.status_code != 200:
                logger.error(
                    f"SiliconFlow rerank failed: status={resp.status_code} "
                    f"body={resp.text}"
                )
                return documents[:limit]

            data = resp.json()
            results = data.get("results", [])

            reranked: List[Dict[str, Any]] = []
            for item in results:
                idx = item.get("index")
                if idx is None or idx >= len(documents):
                    continue
                doc = dict(documents[idx])
                doc["rerank_score"] = item.get("relevance_score", 0.0)
                reranked.append(doc)

            return reranked

        except Exception as e:
            logger.warning(f"Reranking failed, returning original results: {e}")
            return documents[:limit]
