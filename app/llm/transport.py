"""云端 LLM 真实 HTTP 传输实现（通义千问 / 智谱 GLM，OpenAI 兼容接口）。

此前 :class:`~app.llm.client.CloudLLMClient` 的传输层
（:class:`~app.llm.client.LLMTransport`）在测试中由伪实现注入；组合根在未注入时使用
"永远不可用"的桩，因此生产环境从未真正调用云端大模型。本模块补齐该缺口：提供一个基于
标准库 ``urllib`` 的真实传输 :class:`CloudLLMHttpTransport`，调用 **OpenAI 兼容的
``/chat/completions`` 接口**（通义千问 dashscope compatible-mode 与智谱 GLM 均兼容），
把 :class:`CloudLLMClient` 传入的完整 prompt 作为一条 user 消息发送，返回模型文本。

失败归一化为 :mod:`app.llm.errors` 中的错误类型，交由客户端的退避 / 熔断 / 降级处理：
- 超时 → :class:`~app.llm.errors.LLMTimeoutError`
- 429 限流 → :class:`~app.llm.errors.LLMRateLimitError`
- 其它网络 / 非 2xx / 解析失败 → :class:`~app.llm.errors.LLMUnavailableError`

安全：不记录 api_key；仅在请求头中使用。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from app.core.config import LLMSettings
from app.llm.errors import (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)

__all__ = ["CloudLLMHttpTransport", "build_llm_transport"]


class CloudLLMHttpTransport:
    """调用 OpenAI 兼容 ``/chat/completions`` 的真实 LLM 传输。

    Args:
        api_key: 云端 LLM 的 API Key（通义 dashscope / 智谱）。
        base_url: OpenAI 兼容基址，如 ``https://dashscope.aliyuncs.com/compatible-mode/v1``。
        model: 模型名，如 ``qwen-plus`` / ``glm-4``。
        temperature: 采样温度；意图识别 / 槽位抽取用低温更稳定。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("api_key 不可为空。")
        self._api_key = api_key.strip()
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._temperature = temperature

    def generate(self, prompt: str, *, timeout: float) -> str:
        """将 prompt 作为单条 user 消息发送，返回模型回复文本。

        Raises:
            LLMTimeoutError: 请求超时。
            LLMRateLimitError: 被限流（HTTP 429）。
            LLMUnavailableError: 其它网络错误 / 非 2xx / 响应解析失败。
        """
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise LLMRateLimitError("云端 LLM 被限流（HTTP 429）。") from exc
            raise LLMUnavailableError(
                f"云端 LLM 返回非 2xx：HTTP {exc.code}。"
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise LLMTimeoutError("云端 LLM 调用超时。") from exc
        except urllib.error.URLError as exc:
            # URLError 可能包裹超时。
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise LLMTimeoutError("云端 LLM 调用超时。") from exc
            raise LLMUnavailableError(f"云端 LLM 网络错误：{exc.reason}") from exc

        return self._extract_content(body)

    @staticmethod
    def _extract_content(body: str) -> str:
        """从 OpenAI 兼容响应中提取 ``choices[0].message.content``。"""
        try:
            parsed = json.loads(body)
            content = parsed["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError("云端 LLM 响应格式无法解析。") from exc
        if not isinstance(content, str):
            raise LLMUnavailableError("云端 LLM 响应内容为空或类型非法。")
        return content


def build_llm_transport(settings: LLMSettings) -> CloudLLMHttpTransport | None:
    """按配置构造真实 LLM 传输；未配置 api_key 时返回 ``None``（由调用方回退降级桩）。"""
    api_key = settings.api_key.get_secret_value() if settings.api_key else ""
    if not api_key.strip():
        return None
    return CloudLLMHttpTransport(
        api_key=api_key,
        base_url=settings.base_url,
        model=settings.model,
    )
