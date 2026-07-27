"""基于 pgvector 的 RAG 检索器（对应设计文档 组件 3 ``rag_retrieval_tool``，Requirement 16）。

``RAGRetriever`` 负责养护问答 / 相似病例 / 营销内容的知识片段检索，核心语义与需求一致：

- 租户可见性（16.1 / 16.3）：检索范围为**当前租户私有知识** + **平台级共享知识**
  （``tenant_id`` 为空）。返回结果中每个片段的 ``tenant_id`` ∈ ``{上下文 tenant_id, None}``
  （Correctness Property 12）。
- 相似度约束（16.1）：结果按相似度得分**降序**、过滤掉**低于阈值**者、最多返回 **5 条**，
  并在 **5 秒**预算内完成，超预算抛 :class:`RetrievalTimeoutError`。
- 租户上下文缺失（16.4）：上下文缺失或 ``tenant_id`` 为空（None、空串、纯空白）时拒绝检索、
  不返回任何片段，抛 :class:`~app.core.errors.TenantContextMissingError`。
- 无匹配（16.5）：无任何满足阈值的片段时，返回显式的"无匹配"结果
  （:attr:`RetrievalResult.has_match` 为 ``False``，并携带无匹配提示文案）。

为便于在无实时 pgvector 的情况下测试，向量检索后端被抽象为协议
（:class:`VectorSearchBackend`）。本模块内置纯内存实现
（:class:`InMemoryVectorSearchBackend`，基于余弦相似度）作为默认与测试替身；
生产环境可注入基于 pgvector 的实现（``ORDER BY embedding <=> :q LIMIT k``）。
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.errors import PetOpsError, TenantContextMissingError

#: 默认相似度阈值：低于该得分的片段视为不相关而被过滤（Requirements 16.1）。
DEFAULT_SIMILARITY_THRESHOLD = 0.75

#: 单次检索最多返回的知识片段数（Requirements 16.1）。
DEFAULT_MAX_RESULTS = 5

#: 检索时间预算（秒）。超过该预算判定为超时（Requirements 16.1）。
DEFAULT_TIME_BUDGET_SECONDS = 5.0

#: 无匹配片段时返回的提示文案（Requirements 16.5）。
NO_MATCH_MESSAGE = "知识库中暂无匹配的养护知识片段。"


class RetrievalError(PetOpsError):
    """RAG 检索错误基类。"""


class RetrievalTimeoutError(RetrievalError):
    """检索超时错误。

    当检索耗时超过配置的时间预算（默认 5 秒）时抛出（Requirements 16.1）。
    """


@dataclass(frozen=True)
class RetrievedChunk:
    """一条检索命中的知识片段及其相似度得分。"""

    chunk_id: str
    #: ``None`` 表示平台级共享知识（对所有租户可见，Requirements 16.3）。
    tenant_id: str | None
    content: str
    source_type: str
    #: 相似度得分，越大越相似；用于降序排序与阈值过滤。
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    """检索结果，携带命中片段与显式的无匹配指示（Requirements 16.5）。"""

    chunks: tuple[RetrievedChunk, ...] = ()
    #: 无匹配时的提示文案；有匹配时为空串。
    message: str = ""

    @property
    def has_match(self) -> bool:
        """是否存在满足阈值的匹配片段。"""
        return bool(self.chunks)


@runtime_checkable
class VectorSearchBackend(Protocol):
    """向量检索后端协议（生产由 pgvector 支撑）。

    实现方须在**当前租户私有 + 平台级共享（``tenant_id`` 为空）**范围内检索，并按相似度
    降序返回至多 ``limit`` 条候选片段。检索器会对返回结果再次做可见性、阈值与条数校验，
    以保证不变量（防御式设计）。
    """

    def search(
        self,
        *,
        query_embedding: Sequence[float],
        tenant_id: str,
        limit: int,
    ) -> Iterable[RetrievedChunk]:  # pragma: no cover - 协议声明
        """在租户可见范围内检索候选片段（按相似度降序，至多 ``limit`` 条）。"""
        ...


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """计算两个等长向量的余弦相似度；任一向量为零向量时返回 0.0。"""
    if len(a) != len(b):
        raise ValueError("向量维度不一致，无法计算相似度。")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


@dataclass(frozen=True)
class _StoredChunk:
    """内存后端存放的知识片段（含 embedding），用于计算相似度。"""

    chunk_id: str
    tenant_id: str | None
    content: str
    source_type: str
    embedding: tuple[float, ...]


class InMemoryVectorSearchBackend:
    """纯内存向量检索后端（基于余弦相似度），用作默认与测试替身。

    仅返回**当前租户私有**或**平台级共享（``tenant_id`` 为空）**的片段，模拟 pgvector 侧的
    租户可见性过滤（Requirements 16.1 / 16.3）。
    """

    def __init__(self, chunks: Iterable[_StoredChunk] | None = None) -> None:
        self._chunks: list[_StoredChunk] = list(chunks) if chunks is not None else []

    def add(
        self,
        *,
        chunk_id: str,
        content: str,
        embedding: Sequence[float],
        source_type: str = "care_qa",
        tenant_id: str | None = None,
    ) -> None:
        """向内存库添加一条知识片段（``tenant_id`` 为空表示平台级共享）。"""
        self._chunks.append(
            _StoredChunk(
                chunk_id=chunk_id,
                tenant_id=tenant_id,
                content=content,
                source_type=source_type,
                embedding=tuple(float(v) for v in embedding),
            )
        )

    def search(
        self,
        *,
        query_embedding: Sequence[float],
        tenant_id: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        """在"当前租户私有 + 平台级共享"范围内按余弦相似度降序返回至多 ``limit`` 条。"""
        scored: list[RetrievedChunk] = []
        for chunk in self._chunks:
            # 可见性：仅当前租户私有或平台级共享（tenant_id 为空）。
            if chunk.tenant_id is not None and chunk.tenant_id != tenant_id:
                continue
            score = _cosine_similarity(query_embedding, chunk.embedding)
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    tenant_id=chunk.tenant_id,
                    content=chunk.content,
                    source_type=chunk.source_type,
                    score=score,
                )
            )
        # 相似度降序，并列时按 chunk_id 升序稳定排序。
        scored.sort(key=lambda c: (-c.score, c.chunk_id))
        return scored[: max(limit, 0)]


class RAGRetriever:
    """RAG 知识片段检索器（Requirement 16）。

    Args:
        backend: 向量检索后端。缺省使用内存实现（空库）。
        similarity_threshold: 相似度阈值，低于该值的片段被过滤（Requirements 16.1）。
        max_results: 最多返回的片段数（Requirements 16.1）。
        time_budget_seconds: 检索时间预算（秒），超过判定为超时（Requirements 16.1）。
    """

    def __init__(
        self,
        backend: VectorSearchBackend | None = None,
        *,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        max_results: int = DEFAULT_MAX_RESULTS,
        time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
    ) -> None:
        self._backend: VectorSearchBackend = backend or InMemoryVectorSearchBackend()
        self._threshold = similarity_threshold
        self._max_results = max(int(max_results), 0)
        self._time_budget = float(time_budget_seconds)

    @staticmethod
    def _require_tenant_id(tenant_id: object) -> str:
        """校验并归一化租户上下文；缺失或为空时拒绝检索（Requirements 16.4）。"""
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise TenantContextMissingError(
                "缺少有效的租户上下文：RAG 检索要求非空 tenant_id。"
            )
        return tenant_id

    def retrieve(
        self,
        query_embedding: Sequence[float],
        *,
        tenant_id: str,
    ) -> RetrievalResult:
        """在当前租户私有 + 平台级共享范围内检索知识片段。

        返回按相似度降序、不低于阈值、至多 :attr:`max_results` 条的结果；无匹配时返回
        携带无匹配提示的空结果（Requirements 16.1 / 16.3 / 16.5）。

        Raises:
            TenantContextMissingError: 上下文缺失或 ``tenant_id`` 为空（Requirements 16.4）。
            RetrievalTimeoutError: 检索耗时超过时间预算（Requirements 16.1）。
        """
        normalized = self._require_tenant_id(tenant_id)

        started = time.monotonic()
        # 向后端多取一些候选，避免可见性 / 阈值过滤后不足；最终仍截断到 max_results。
        candidates = list(
            self._backend.search(
                query_embedding=query_embedding,
                tenant_id=normalized,
                limit=max(self._max_results * 4, self._max_results),
            )
        )
        elapsed = time.monotonic() - started
        if elapsed > self._time_budget:
            raise RetrievalTimeoutError(
                f"RAG 检索超过 {self._time_budget:.1f}s 预算（实际 {elapsed:.2f}s）。"
            )

        # 防御式可见性校验：仅保留当前租户私有或平台级共享（tenant_id 为空）片段。
        visible = [
            c
            for c in candidates
            if c.tenant_id is None or c.tenant_id == normalized
        ]
        # 阈值过滤。
        filtered = [c for c in visible if c.score >= self._threshold]
        # 相似度降序，并列按 chunk_id 升序稳定排序；截断到最多 max_results 条。
        filtered.sort(key=lambda c: (-c.score, c.chunk_id))
        top = tuple(filtered[: self._max_results])

        if not top:
            return RetrievalResult(chunks=(), message=NO_MATCH_MESSAGE)
        return RetrievalResult(chunks=top)
