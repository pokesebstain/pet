"""营销 / 社区内容生成 Agent（对应设计文档 组件 2 ``MarketingAgent``，Requirement 15）。

``MarketingAgent`` 结合 **Cloud_LLM（提示工程）** 与 **RAG_Retriever（pgvector 检索）**，
在当前租户 + 平台级共享知识范围内生成营销 / 社区内容。核心语义与需求一致：

- 内容生成（15.1 / 15.2）：在 **30 秒** 预算内，通过 Cloud_LLM 结合提示工程与
  RAG_Retriever 在**当前租户私有 + 平台级共享**范围检索到的知识片段生成并返回内容。
- 租户上下文缺失（15.3）：上下文缺失或 ``tenant_id`` 为空（None、空串、纯空白）时拒绝
  请求、不生成任何内容，抛 :class:`~app.core.errors.TenantContextMissingError`。
- LLM 超时 / 不可用（15.4）：Cloud_LLM 调用超时或不可用（即客户端已降级）时**不返回
  生成内容**，返回指明失败原因的错误结果（``status=LLM_FAILED``）。
- 缺参考片段（15.5）：内容生成需要参考知识片段但 RAG_Retriever 未检索到任何相关片段时，
  **不基于未检索到的片段生成内容**（不臆造），返回缺少可参考知识片段的提示
  （``status=MISSING_REFERENCES``）。

范围约束（重要）：内容生成通过**云端 LLM + 提示工程 + RAG**实现，**不含任何模型微调**。

为便于在无真实网络 / 向量库的情况下测试，本 Agent 的三个依赖均通过构造函数注入：
Cloud_LLM 客户端（:class:`~app.llm.client.CloudLLMClient`）、RAG 检索器
（:class:`~app.rag.retriever.RAGRetriever`）与文本向量化提供者
（:class:`EmbeddingProvider`）。测试可注入伪实现。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from app.core.errors import PetOpsError, TenantContextMissingError
from app.llm.client import CloudLLMClient, FewShotExample
from app.rag.retriever import RAGRetriever, RetrievedChunk

__all__ = [
    "EmbeddingProvider",
    "ContentStatus",
    "ContentGenerationResult",
    "MarketingAgent",
    "MarketingError",
    "ContentGenerationTimeoutError",
    "DEFAULT_TIME_BUDGET_SECONDS",
    "DEFAULT_SYSTEM_PROMPT",
    "LLM_FAILED_MESSAGE",
    "MISSING_REFERENCES_MESSAGE",
]

#: 内容生成时间预算（秒）。超过该预算判定为超时（Requirements 15.1）。
DEFAULT_TIME_BUDGET_SECONDS: float = 30.0

#: 内容生成默认系统提示（提示工程）。
DEFAULT_SYSTEM_PROMPT: str = (
    "你是宠物店的营销与社区内容助手。请依据提供的知识片段，生成积极、准确、"
    "合规的营销或社区内容；不得编造未在知识片段中出现的事实信息。"
)

#: Cloud_LLM 超时 / 不可用（已降级）时返回的失败提示（Requirements 15.4）。
LLM_FAILED_MESSAGE: str = "内容生成失败：云端大模型当前超时或不可用，请稍后重试。"

#: 需要参考片段但未检索到任何相关片段时返回的提示（Requirements 15.5）。
MISSING_REFERENCES_MESSAGE: str = (
    "内容生成失败：知识库中缺少可参考的相关知识片段，未生成任何内容。"
)


class MarketingError(PetOpsError):
    """营销内容生成错误基类。"""


class ContentGenerationTimeoutError(MarketingError):
    """内容生成超时错误。

    当内容生成整体耗时超过配置的时间预算（默认 30 秒）时抛出（Requirements 15.1）。
    """


@runtime_checkable
class EmbeddingProvider(Protocol):
    """文本向量化提供者协议。

    将用户的自然语言查询转换为可用于 pgvector 相似度检索的向量。生产环境可注入基于
    云端 embedding 服务的实现；测试可注入确定性的伪实现（无需网络）。
    """

    def embed(self, text: str) -> Sequence[float]:  # pragma: no cover - 协议声明
        """将文本转换为向量表示。"""
        ...


class ContentStatus(str, Enum):
    """内容生成结果状态。"""

    #: 成功生成内容。
    GENERATED = "generated"
    #: Cloud_LLM 超时 / 不可用（已降级），未生成内容（Requirements 15.4）。
    LLM_FAILED = "llm_failed"
    #: 需要参考片段但未检索到任何相关片段，未生成内容（Requirements 15.5）。
    MISSING_REFERENCES = "missing_references"


@dataclass(frozen=True)
class ContentGenerationResult:
    """内容生成结果。

    Attributes:
        status: 结果状态，见 :class:`ContentStatus`。
        content: 生成内容（成功时非空；失败时为空串）。
        message: 失败 / 提示文案（成功时为空串）。
        references: 生成所依据的知识片段（成功且需参考时非空）。
    """

    status: ContentStatus
    content: str = ""
    message: str = ""
    references: tuple[RetrievedChunk, ...] = field(default_factory=tuple)

    @property
    def success(self) -> bool:
        """是否成功生成内容。"""
        return self.status is ContentStatus.GENERATED


class MarketingAgent:
    """营销 / 社区内容生成 Agent（Requirement 15）。

    Args:
        llm_client: 云端 LLM 客户端（提示工程 / 少样本 + 降级 / 熔断）。
        retriever: RAG 检索器（当前租户私有 + 平台级共享范围）。
        embedding_provider: 文本向量化提供者，用于将查询转为检索向量。
        system_prompt: 内容生成系统提示（提示工程）。
        time_budget_seconds: 内容生成时间预算（秒），超过判定为超时（Requirements 15.1）。
    """

    def __init__(
        self,
        llm_client: CloudLLMClient,
        retriever: RAGRetriever,
        embedding_provider: EmbeddingProvider,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
    ) -> None:
        self._llm = llm_client
        self._retriever = retriever
        self._embedder = embedding_provider
        self._system_prompt = system_prompt
        self._time_budget = float(time_budget_seconds)

    @staticmethod
    def _require_tenant_id(tenant_id: object) -> str:
        """校验并归一化租户上下文；缺失或为空时拒绝生成（Requirements 15.3）。"""
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise TenantContextMissingError(
                "缺少有效的租户上下文：营销内容生成要求非空 tenant_id。"
            )
        return tenant_id

    @staticmethod
    def _build_context_block(chunks: Sequence[RetrievedChunk]) -> str:
        """将检索到的知识片段拼装为提示中的参考上下文块。"""
        lines: list[str] = ["参考知识片段："]
        for index, chunk in enumerate(chunks, start=1):
            lines.append(f"[{index}] {chunk.content}")
        return "\n".join(lines)

    def generate_content(
        self,
        request: str,
        *,
        tenant_id: str,
        require_references: bool = True,
        examples: Sequence[FewShotExample] | None = None,
    ) -> ContentGenerationResult:
        """生成营销 / 社区内容。

        Args:
            request: 运营人员的自然语言内容生成请求。
            tenant_id: 当前租户上下文；缺失或为空时拒绝（Requirements 15.3）。
            require_references: 内容生成是否需要参考知识片段（默认需要）。为 ``True`` 时，
                若 RAG 未检索到任何相关片段则返回缺片段提示（Requirements 15.5）。
            examples: 可选的少样本示例（提示工程）。

        Returns:
            ContentGenerationResult: 成功（``GENERATED``）或失败
            （``LLM_FAILED`` / ``MISSING_REFERENCES``）结果。

        Raises:
            TenantContextMissingError: 上下文缺失或 ``tenant_id`` 为空（Requirements 15.3）。
            ContentGenerationTimeoutError: 内容生成耗时超过时间预算（Requirements 15.1）。
        """
        normalized = self._require_tenant_id(tenant_id)

        started = time.monotonic()

        references: tuple[RetrievedChunk, ...] = ()
        context_block = ""
        if require_references:
            # RAG 检索：当前租户私有 + 平台级共享范围（Requirements 15.2）。
            query_embedding = self._embedder.embed(request)
            retrieval = self._retriever.retrieve(
                query_embedding, tenant_id=normalized
            )
            # 需参考但无任何相关片段：不臆造，返回缺片段提示（Requirements 15.5）。
            if not retrieval.has_match:
                return ContentGenerationResult(
                    status=ContentStatus.MISSING_REFERENCES,
                    message=MISSING_REFERENCES_MESSAGE,
                )
            references = retrieval.chunks
            context_block = self._build_context_block(references)

        # 组织最终用户输入（提示工程）：请求 + 参考上下文。
        if context_block:
            user_input = f"{request}\n\n{context_block}"
        else:
            user_input = request

        response = self._llm.complete(
            user_input,
            system_prompt=self._system_prompt,
            examples=examples,
        )

        # 超时守卫：整体耗时超过预算判定为超时（Requirements 15.1）。
        elapsed = time.monotonic() - started
        if elapsed > self._time_budget:
            raise ContentGenerationTimeoutError(
                f"营销内容生成超过 {self._time_budget:.1f}s 预算（实际 {elapsed:.2f}s）。"
            )

        # LLM 超时 / 不可用（已降级）：不返回生成内容（Requirements 15.4）。
        if response.degraded:
            return ContentGenerationResult(
                status=ContentStatus.LLM_FAILED,
                message=LLM_FAILED_MESSAGE,
            )

        return ContentGenerationResult(
            status=ContentStatus.GENERATED,
            content=response.text,
            references=references,
        )
