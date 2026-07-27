"""基于 pgvector 的 RAG 检索组件（养护问答 / 相似病例 / 营销内容）。"""

from app.rag.retriever import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TIME_BUDGET_SECONDS,
    NO_MATCH_MESSAGE,
    InMemoryVectorSearchBackend,
    RAGRetriever,
    RetrievalError,
    RetrievalResult,
    RetrievalTimeoutError,
    RetrievedChunk,
    VectorSearchBackend,
)

__all__ = [
    "RAGRetriever",
    "RetrievalResult",
    "RetrievedChunk",
    "VectorSearchBackend",
    "InMemoryVectorSearchBackend",
    "RetrievalError",
    "RetrievalTimeoutError",
    "NO_MATCH_MESSAGE",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_TIME_BUDGET_SECONDS",
]
