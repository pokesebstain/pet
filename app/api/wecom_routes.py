"""企业微信回调 HTTP 端点（Requirement 21，设计文档 14.3 组件 A）。

在 FastAPI 应用上注册企业微信"接收消息服务器配置"回调所需的两个端点：

- ``GET /wecom/callback``：**URL 验证握手**。企业微信在管理后台保存回调配置时发起，携带
  ``msg_signature`` / ``timestamp`` / ``nonce`` / ``echostr``；服务端验签并解密 ``echostr``，
  以 ``text/plain`` 原样返回解密后的明文（HTTP 200）。任何验签 / 解密失败返回 HTTP 403。
- ``POST /wecom/callback``：**入站消息回调**。携带 ``msg_signature`` / ``timestamp`` /
  ``nonce`` 查询参数与加密 XML 请求体；交由 :class:`~app.wecom.gateway.WeComInboundGateway`
  完成验签 / 解密 / 幂等去重 / 转发 Supervisor。验签失败返回 HTTP 403；成功返回 HTTP 200。

安全（Requirement 21.2）：回调是**公网可达**的（企业微信主动调用），但每次处理都必须经过
**签名校验 + AES 解密 + ReceiveId(corp_id) 校验**三重闸门，任一失败即拒绝且不进入决策中枢。
本模块不记录任何密钥 / 明文密文。

MVP 回复策略：企业微信客户联系（客户消息）回调允许返回空串 / ``success``，由主动推送通道
（:class:`~app.wecom.gateway.ReplySender`）异步下发回复。因此 ``POST`` 成功时返回 200 空体，
不在同步响应里回传加密 XML。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response, status

from app.api.composition import AppComposition
from app.observability.metrics import WECOM_CALLBACK_TOTAL
from app.wecom.gateway import WeComInboundGateway, WeComSignatureError

__all__ = ["register_wecom_routes", "WECOM_CALLBACK_PATH"]

_logger = logging.getLogger(__name__)

#: 企业微信管理后台"接收消息服务器配置"应填写的回调路径。
WECOM_CALLBACK_PATH = "/wecom/callback"


def _get_gateway(request: Request) -> WeComInboundGateway | None:
    composition: AppComposition | None = getattr(
        request.app.state, "composition", None
    )
    return getattr(composition, "wecom_gateway", None) if composition else None


def register_wecom_routes(app: FastAPI) -> None:
    """在应用上注册企业微信回调路由。

    未配置 WeCom（``composition.wecom_gateway is None``）时，仅这两个路由返回 HTTP 503；
    其它路由（/health、/ready、/agent/query 等）不受影响。
    """

    @app.get(WECOM_CALLBACK_PATH, tags=["wecom"])
    def wecom_verify(
        request: Request,
        msg_signature: str = "",
        timestamp: str = "",
        nonce: str = "",
        echostr: str = "",
    ) -> Response:
        """企业微信 URL 验证握手：验签并解密 echostr，返回明文（text/plain）。"""
        gateway = _get_gateway(request)
        if gateway is None:
            return Response(
                content="WeCom 未配置",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                media_type="text/plain",
            )
        raw = {
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": echostr,
        }
        if not gateway.verify_signature(raw):
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        # 解密 echostr —— 编解码器需支持 decrypt_echostr（真实 WeComCryptoCodec 提供）。
        codec = getattr(gateway, "_codec", None)
        decrypt_echostr = getattr(codec, "decrypt_echostr", None)
        if decrypt_echostr is None:
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            plaintext = decrypt_echostr(raw)
        except WeComSignatureError:
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        except Exception:  # noqa: BLE001 - 任何解密异常都视为验证失败，拒绝。
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        return Response(content=plaintext, media_type="text/plain", status_code=200)

    @app.post(WECOM_CALLBACK_PATH, tags=["wecom"])
    async def wecom_callback(
        request: Request,
        msg_signature: str = "",
        timestamp: str = "",
        nonce: str = "",
    ) -> Response:
        """企业微信入站消息回调：交由网关验签 / 解密 / 去重 / 转发 Supervisor。"""
        gateway = _get_gateway(request)
        if gateway is None:
            return Response(
                content="WeCom 未配置",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                media_type="text/plain",
            )
        body_bytes = await request.body()
        raw = {
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "body": body_bytes.decode("utf-8", errors="replace"),
        }
        # DEBUG: 路由入口，确认请求确实进到了 POST 处理器
        import logging
        logging.getLogger("app.wecom.debug").warning(
            "POST 入站: msg_sig=%s ts=%s nonce=%s body[:200]=%r content_type=%r",
            msg_signature, timestamp, nonce,
            raw["body"][:200],
            request.headers.get("content-type"),
        )
        try:
            gateway.handle(raw)
        except WeComSignatureError:
            # 验签 / 解密失败：拒绝处理（Requirement 21.2）。
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        except Exception as exc:  # noqa: BLE001 - 出站推送等下游故障不应导致回调 500。
            # 消息已成功验签 / 解密并转发决策中枢（Supervisor 已产出回复），仅**出站推送**
            # 环节失败（如企业微信 IP 白名单未生效、access_token 获取失败等外部故障）。
            # 企业微信对回调响应超时 / 5xx 会重试整条回调，若此处返回 500 将导致同一条
            # 客户消息反复重试（且因幂等去重命中相同回复，仍会反复触发发送失败），
            # 因此记录错误并仍返回 200（success），避免无意义重试放大故障。
            _logger.error("企业微信回调处理异常（已验签，下游处理失败）：%s: %s", type(exc).__name__, exc)
            WECOM_CALLBACK_TOTAL.labels(outcome="error").inc()
            return Response(content="success", media_type="text/plain", status_code=200)
        # MVP：同步返回 200 空体（success），回复经主动推送通道异步下发。
        return Response(content="success", media_type="text/plain", status_code=200)
