"""企业微信出站回复通道（Requirement 21，设计文档 14.3 组件 A 出站侧）。

本模块完成"客户消息 → 自动预约 → 回复回推客户"端到端闭环的**出站**一环：入站网关
（:class:`~app.wecom.gateway.WeComInboundGateway`）把 Supervisor 产出的 ``final_answer``
作为回复文本交给注入的 :class:`~app.wecom.gateway.ReplySender`，本模块提供其**真实实现**
:class:`WeComMessageSender`，经企业微信服务端 API 主动推送文本消息给客户。

组成：

- :class:`HttpTransport`：极简 HTTP 传输**协议**（``get_json`` / ``post_json``）。真实网络
  访问被隔离在协议之后，测试注入**无网络**的伪实现即可完整验证令牌缓存 / 刷新 / 重试 /
  错误处理逻辑。
- :class:`UrllibHttpTransport`：基于标准库 ``urllib`` 的默认传输（**不引入任何三方 HTTP
  依赖**）。
- :class:`WeComAccessTokenManager`：按 ``corpid`` + ``secret`` 获取并**缓存** access_token
  （``GET /cgi-bin/gettoken``），依据 ``expires_in`` 提前刷新，线程安全，并在企业微信返回
  ``errcode`` 42001/40014（令牌过期/失效）时强制失效并重取。
- :class:`WeComMessageSender`：实现 :class:`~app.wecom.gateway.ReplySender` 协议
  （``send(tenant_id, external_user_id, text)``），经可注入的发送策略把文本消息推送给
  客户；默认使用应用消息 ``POST /cgi-bin/message/send``，可替换为微信客服
  ``/cgi-bin/kf/send_msg`` 等能力而无需改动本类。

安全：**绝不**记录 access_token / secret；令牌仅在内存缓存并按需刷新。发送失败抛出
:class:`WeComSendError`（而非崩溃入站回调路径）。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from app.core.errors import PetOpsError

__all__ = [
    "HttpTransport",
    "UrllibHttpTransport",
    "WeComAccessTokenManager",
    "WeComMessageSender",
    "MessageSendStrategy",
    "AppMessageSendStrategy",
    "WeComSendError",
    "WeComTokenError",
    "WECOM_TOKEN_EXPIRED_ERRCODES",
    "DEFAULT_WECOM_API_BASE_URL",
]

#: 企业微信服务端 API 默认根地址。
DEFAULT_WECOM_API_BASE_URL = "https://qyapi.weixin.qq.com"

#: 表示 access_token 失效/过期、需刷新并重试一次的 WeCom errcode。
#: 42001 = access_token expired；40014 = invalid access_token。
WECOM_TOKEN_EXPIRED_ERRCODES: frozenset[int] = frozenset({42001, 40014})

#: 令牌提前刷新的安全余量（秒）：在服务端返回的 expires_in 到期前该秒数即视为过期。
_TOKEN_REFRESH_SKEW_SECONDS = 120.0


class WeComSendError(PetOpsError):
    """企业微信出站消息发送失败错误。

    在企业微信返回非零 ``errcode``（且非可重试的令牌失效场景，或重试后仍失败）或传输层
    异常时抛出。调用方（网关 / 回调路由）应捕获本错误，避免因出站失败而中断入站回调
    （回调仍应返回 200）。错误信息中**不含** access_token / secret。
    """


class WeComTokenError(WeComSendError):
    """获取企业微信 access_token 失败错误（``/cgi-bin/gettoken`` 返回非零 errcode）。"""


@runtime_checkable
class HttpTransport(Protocol):
    """极简 HTTP 传输协议：把真实网络访问隔离在接口之后（便于无网络测试）。"""

    def get_json(
        self, url: str, *, params: Mapping[str, str] | None = ..., timeout: float = ...
    ) -> Mapping[str, Any]:
        """发起 GET 请求并将响应体解析为 JSON 映射。"""
        ...

    def post_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = ...,
        json_body: Mapping[str, Any] | None = ...,
        timeout: float = ...,
    ) -> Mapping[str, Any]:
        """发起 POST（JSON 请求体）并将响应体解析为 JSON 映射。"""
        ...


class UrllibHttpTransport:
    """基于标准库 ``urllib`` 的默认 HTTP 传输（不引入任何三方依赖）。

    Args:
        default_timeout: 单次请求默认超时（秒）。
    """

    def __init__(self, *, default_timeout: float = 10.0) -> None:
        self._default_timeout = float(default_timeout)

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        full_url = self._with_params(url, params)
        request = urllib.request.Request(full_url, method="GET")
        return self._send(request, timeout)

    def post_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        full_url = self._with_params(url, params)
        data = json.dumps(json_body or {}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            full_url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        return self._send(request, timeout)

    # -- 内部辅助 -----------------------------------------------------------

    @staticmethod
    def _with_params(url: str, params: Mapping[str, str] | None) -> str:
        if not params:
            return url
        query = urllib.parse.urlencode(dict(params))
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{query}"

    def _send(
        self, request: urllib.request.Request, timeout: float | None
    ) -> Mapping[str, Any]:
        effective_timeout = self._default_timeout if timeout is None else float(timeout)
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as resp:
                payload = resp.read().decode("utf-8")
        except OSError as exc:  # URLError / timeout / 连接错误等
            # 不泄露 URL 上可能携带的凭据；仅报告类型。
            raise WeComSendError("企业微信 API 网络请求失败。") from exc
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise WeComSendError("企业微信 API 响应不是合法 JSON。") from exc
        if not isinstance(parsed, Mapping):
            raise WeComSendError("企业微信 API 响应结构非法（期望 JSON 对象）。")
        return parsed


class WeComAccessTokenManager:
    """企业微信 access_token 获取与缓存管理器（线程安全）。

    经 ``GET {base_url}/cgi-bin/gettoken?corpid=..&corpsecret=..`` 获取令牌，按服务端返回的
    ``expires_in`` 缓存并在到期前 :data:`_TOKEN_REFRESH_SKEW_SECONDS` 秒即视为过期而重取。
    当业务接口返回令牌失效错误码时，可经 :meth:`invalidate` 强制失效并在下次
    :meth:`get_token` 重新获取。

    Args:
        corp_id: 企业 ID（CorpID）。
        secret: 应用 Secret（敏感，**绝不记录**）。
        transport: HTTP 传输实现（可注入伪实现以便无网络测试）。
        base_url: 企业微信 API 根地址。
        timeout: 单次请求超时（秒）。
        time_func: 时间源（便于测试控制过期）；默认 :func:`time.monotonic`。
    """

    def __init__(
        self,
        *,
        corp_id: str,
        secret: str,
        transport: HttpTransport,
        base_url: str = DEFAULT_WECOM_API_BASE_URL,
        timeout: float = 10.0,
        time_func: Any = None,
    ) -> None:
        if not corp_id or not corp_id.strip():
            raise WeComTokenError("corp_id 不可为空。")
        if not secret or not secret.strip():
            raise WeComTokenError("secret 不可为空。")
        self._corp_id = corp_id.strip()
        self._secret = secret
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)
        self._now = time_func or time.monotonic
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self, *, force_refresh: bool = False) -> str:
        """返回有效的 access_token；缓存有效则复用，否则重新获取。

        Args:
            force_refresh: 为 ``True`` 时忽略缓存强制重取（用于令牌失效后的重试）。
        """
        with self._lock:
            if (
                not force_refresh
                and self._token is not None
                and self._now() < self._expires_at
            ):
                return self._token
            return self._fetch_locked()

    def invalidate(self) -> None:
        """使当前缓存令牌失效，下次 :meth:`get_token` 将重新获取。"""
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    # -- 内部辅助 -----------------------------------------------------------

    def _fetch_locked(self) -> str:
        """在持锁状态下从服务端获取并缓存令牌。"""
        response = self._transport.get_json(
            f"{self._base_url}/cgi-bin/gettoken",
            params={"corpid": self._corp_id, "corpsecret": self._secret},
            timeout=self._timeout,
        )
        errcode = int(response.get("errcode", 0) or 0)
        if errcode != 0:
            # 不回显 secret；仅报告 errcode 与服务端 errmsg。
            raise WeComTokenError(
                f"获取企业微信 access_token 失败：errcode={errcode}, "
                f"errmsg={response.get('errmsg', '')}"
            )
        token = response.get("access_token")
        if not isinstance(token, str) or not token:
            raise WeComTokenError("企业微信 gettoken 响应缺少 access_token。")
        expires_in = float(response.get("expires_in", 7200) or 7200)
        ttl = max(expires_in - _TOKEN_REFRESH_SKEW_SECONDS, 0.0)
        self._token = token
        self._expires_at = self._now() + ttl
        return token


@runtime_checkable
class MessageSendStrategy(Protocol):
    """出站消息发送策略：封装"用哪个 WeCom 能力 / 端点、如何构造载荷"。

    通过替换策略即可在**应用消息**（``/cgi-bin/message/send``）与**微信客服**
    （``/cgi-bin/kf/send_msg``）等能力间切换，而无需改动 :class:`WeComMessageSender`。
    """

    def endpoint(self, base_url: str) -> str:
        """返回发送消息的完整 URL（不含 access_token 查询参数）。"""
        ...

    def build_payload(
        self, *, tenant_id: str, external_user_id: str, text: str
    ) -> Mapping[str, Any]:
        """构造发送消息的 JSON 请求体。"""
        ...


class AppMessageSendStrategy:
    """默认策略：企业微信**应用消息** ``POST /cgi-bin/message/send``。

    载荷形如 ``{touser, msgtype: 'text', agentid, text: {content}}``。当外部联系人专用的
    客服发送 API 需要额外参数（如 ``open_kfid``）而不可得时，退回该标准应用消息发送即可
    完成回推闭环；如需客服能力，注入自定义策略替换本类。

    Args:
        agent_id: 应用 AgentId（``message/send`` 必填）。
    """

    def __init__(self, *, agent_id: int) -> None:
        self._agent_id = int(agent_id)

    def endpoint(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}/cgi-bin/message/send"

    def build_payload(
        self, *, tenant_id: str, external_user_id: str, text: str
    ) -> Mapping[str, Any]:
        # tenant_id 目前不参与载荷构造（单应用多租户经 external_user_id 定向），保留形参
        # 以符合策略协议并便于未来按租户切换应用 / agentid。
        return {
            "touser": external_user_id,
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": text},
        }


class WeComMessageSender:
    """企业微信出站文本消息发送器（实现 :class:`~app.wecom.gateway.ReplySender`）。

    调用 :meth:`send` 时：取有效 access_token → 经注入的发送策略构造载荷并 POST 到对应端点
    → 校验响应 ``errcode``。若返回令牌失效错误码（42001/40014），**刷新令牌并重试一次**；
    其它非零 errcode 抛出 :class:`WeComSendError`。

    Args:
        token_manager: access_token 管理器。
        transport: HTTP 传输实现（与 token_manager 可共享同一伪实现）。
        strategy: 发送策略；默认需由调用方提供（通常 :class:`AppMessageSendStrategy`）。
        base_url: 企业微信 API 根地址。
        timeout: 单次请求超时（秒）。
    """

    def __init__(
        self,
        *,
        token_manager: WeComAccessTokenManager,
        transport: HttpTransport,
        strategy: MessageSendStrategy,
        base_url: str = DEFAULT_WECOM_API_BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self._tokens = token_manager
        self._transport = transport
        self._strategy = strategy
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)

    def send(self, tenant_id: str, external_user_id: str, text: str) -> None:
        """向指定客户推送文本消息（:class:`~app.wecom.gateway.ReplySender` 协议）。

        Raises:
            WeComSendError: 发送失败（含令牌刷新重试后仍失败）。
        """
        payload = self._strategy.build_payload(
            tenant_id=tenant_id, external_user_id=external_user_id, text=text
        )
        endpoint = self._strategy.endpoint(self._base_url)

        response = self._post(endpoint, payload, force_refresh=False)
        errcode = int(response.get("errcode", 0) or 0)

        if errcode in WECOM_TOKEN_EXPIRED_ERRCODES:
            # 令牌失效：强制刷新并重试一次。
            self._tokens.invalidate()
            response = self._post(endpoint, payload, force_refresh=True)
            errcode = int(response.get("errcode", 0) or 0)

        if errcode != 0:
            raise WeComSendError(
                f"企业微信消息发送失败：errcode={errcode}, "
                f"errmsg={response.get('errmsg', '')}"
            )

    # -- 内部辅助 -----------------------------------------------------------

    def _post(
        self, endpoint: str, payload: Mapping[str, Any], *, force_refresh: bool
    ) -> Mapping[str, Any]:
        token = self._tokens.get_token(force_refresh=force_refresh)
        return self._transport.post_json(
            endpoint,
            params={"access_token": token},
            json_body=payload,
            timeout=self._timeout,
        )
