"""RAG 检索器单元测试（任务 10.1 / Requirements 16.1、16.3、16.4、16.5）。

覆盖租户可见性（私有 + 平台级共享）、相似度降序 / 阈值 / 最多 5 条、租户上下文缺失拒绝、
无匹配提示与超时预算。属性测试见任务 10.2。
"""

from __future__ import annotations

import pytest

from app.core.errors import TenantContextMissingError
from app.rag import (
    NO_MATCH_MESSAGE,
    InMemoryVectorSearchBackend,
    RAGRetriever,
    RetrievalTimeoutError,
    RetrievedChunk,
)


def _backend() -> InMemoryVectorSearchBackend:
    backend = InMemoryVectorSearchBackend()
    # 与查询向量 [1, 0] 完全对齐（相似度 1.0）的租户 A 私有片段。
    backend.add(chunk_id="a1", content="tenant-a private", embedding=[1.0, 0.0], tenant_id="tenant-a")
    # 平台级共享片段（tenant_id 为空），相似度较高。
    backend.add(chunk_id="s1", content="shared", embedding=[0.9, 0.1], tenant_id=None)
    # 租户 B 私有片段：即便相似度高也不可被 tenant-a 检索到。
    backend.add(chunk_id="b1", content="tenant-b private", embedding=[1.0, 0.0], tenant_id="tenant-b")
    # 低相似度片段（正交），应被阈值过滤。
    backend.add(chunk_id="a2", content="unrelated", embedding=[0.0, 1.0], tenant_id="tenant-a")
    return backend


def test_retrieve_returns_private_and_shared_only():
    retriever = RAGRetriever(_backend(), similarity_threshold=0.5)
    result = retriever.retrieve([1.0, 0.0], tenant_id="tenant-a")

    assert result.has_match
    ids = [c.chunk_id for c in result.chunks]
    # 命中租户 A 私有 + 平台级共享；绝不含租户 B 私有片段。
    assert "a1" in ids
    assert "s1" in ids
    assert "b1" not in ids
    # 每个片段的 tenant_id ∈ {上下文 tenant_id, None}（Property 12）。
    assert all(c.tenant_id in (None, "tenant-a") for c in result.chunks)


def test_results_sorted_by_similarity_desc():
    retriever = RAGRetriever(_backend(), similarity_threshold=0.5)
    result = retriever.retrieve([1.0, 0.0], tenant_id="tenant-a")
    scores = [c.score for c in result.chunks]
    assert scores == sorted(scores, reverse=True)
    # 完全对齐的私有片段（score=1.0）排在共享片段之前。
    assert result.chunks[0].chunk_id == "a1"


def test_threshold_filters_low_similarity():
    retriever = RAGRetriever(_backend(), similarity_threshold=0.5)
    result = retriever.retrieve([1.0, 0.0], tenant_id="tenant-a")
    # 正交的低相似度片段 a2 被阈值过滤。
    assert "a2" not in [c.chunk_id for c in result.chunks]
    assert all(c.score >= 0.5 for c in result.chunks)


def test_caps_at_max_results():
    backend = InMemoryVectorSearchBackend()
    for i in range(10):
        backend.add(chunk_id=f"c{i}", content=str(i), embedding=[1.0, 0.0], tenant_id="tenant-a")
    retriever = RAGRetriever(backend, similarity_threshold=0.5, max_results=5)
    result = retriever.retrieve([1.0, 0.0], tenant_id="tenant-a")
    assert len(result.chunks) == 5


@pytest.mark.parametrize("bad", [None, "", "   ", 123])
def test_missing_tenant_context_rejected(bad):
    retriever = RAGRetriever(_backend())
    with pytest.raises(TenantContextMissingError):
        retriever.retrieve([1.0, 0.0], tenant_id=bad)  # type: ignore[arg-type]


def test_no_match_returns_indicator():
    retriever = RAGRetriever(_backend(), similarity_threshold=0.99)
    # 查询与所有片段都不够相似（阈值极高，[1,1] 与各片段相似度 < 0.99）→ 无匹配。
    result = retriever.retrieve([1.0, 1.0], tenant_id="tenant-a")
    assert not result.has_match
    assert result.chunks == ()
    assert result.message == NO_MATCH_MESSAGE


def test_no_match_when_only_other_tenant_matches():
    backend = InMemoryVectorSearchBackend()
    backend.add(chunk_id="b1", content="tenant-b", embedding=[1.0, 0.0], tenant_id="tenant-b")
    retriever = RAGRetriever(backend, similarity_threshold=0.5)
    result = retriever.retrieve([1.0, 0.0], tenant_id="tenant-a")
    assert not result.has_match
    assert result.message == NO_MATCH_MESSAGE


def test_timeout_budget_exceeded():
    class _SlowBackend:
        def search(self, *, query_embedding, tenant_id, limit):
            import time

            time.sleep(0.05)
            return [RetrievedChunk("x", tenant_id, "c", "care_qa", 1.0)]

    retriever = RAGRetriever(_SlowBackend(), time_budget_seconds=0.0)
    with pytest.raises(RetrievalTimeoutError):
        retriever.retrieve([1.0, 0.0], tenant_id="tenant-a")


def test_defense_filters_backend_leaked_other_tenant():
    # 后端若"漏"出其他租户片段，检索器仍须过滤掉（防御式可见性校验）。
    class _LeakyBackend:
        def search(self, *, query_embedding, tenant_id, limit):
            return [
                RetrievedChunk("ok", "tenant-a", "c", "care_qa", 0.9),
                RetrievedChunk("leak", "tenant-b", "c", "care_qa", 0.95),
            ]

    retriever = RAGRetriever(_LeakyBackend(), similarity_threshold=0.5)
    result = retriever.retrieve([1.0, 0.0], tenant_id="tenant-a")
    ids = [c.chunk_id for c in result.chunks]
    assert ids == ["ok"]
    assert all(c.tenant_id in (None, "tenant-a") for c in result.chunks)
