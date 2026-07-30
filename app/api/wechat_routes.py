"""微信公众号消息回调路由（明文模式）。

对应公众号后台"设置与开发 → 基本配置 → 服务器配置"的回调接入。
采用明文模式，无需 AES 解密，与企业微信回调完全隔离。

流程：
    GET  /wechat/callback  → 微信服务器地址验证（返回 echostr）
    POST /wechat/callback  → 接收用户消息 → 调用 Supervisor → 回复用户
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.agents.state import AgentState, new_state
from app.core.config import get_settings

__all__ = ["router"]

logger = logging.getLogger(__name__)
router = APIRouter(tags=["wechat"])

# --------------------------------------------------------------------------- #
# 配置读取
# --------------------------------------------------------------------------- #


def _get_token() -> str:
    """返回公众号配置的 Token（从环境变量读取，不硬编码）。"""
    # 复用企业微信配置里的 token，或单独配置 WECHAT_TOKEN
    token = getattr(get_settings(), "wechat_token", None)
    if token:
        return token.strip()
    # fallback：从 wecom token 复用（测试阶段方便）
    return get_settings().wecom.token.get_secret_value().strip()


# --------------------------------------------------------------------------- #
# 签名验证
# --------------------------------------------------------------------------- #


def _verify_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    """校验微信回调签名（明文模式同样需验签防伪造）。

    算法：将 token、timestamp、nonce 按字典序排序后拼接，SHA1 摘要。
    """
    if not all((token, signature, timestamp, nonce)):
        return False
    raw = "".join(sorted([token, timestamp, nonce]))
    expected = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return expected == signature


# --------------------------------------------------------------------------- #
# GET — 服务器地址验证
# --------------------------------------------------------------------------- #


@router.get("/wechat/callback")
async def wechat_verify(
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
) -> PlainTextResponse:
    """微信服务器地址验证。

    微信发送 GET 请求携带 signature/timestamp/nonce/echostr，
    验签通过后必须原样返回 echostr，否则配置失败。
    """
    token = _get_token()
    if not _verify_signature(token, signature, timestamp, nonce):
        logger.warning("公众号验证签名失败：sig=%s ts=%s nonce=%s", signature, timestamp, nonce)
        raise HTTPException(status_code=403, detail="signature verification failed")

    logger.info("公众号服务器验证通过，返回 echostr")
    return PlainTextResponse(content=echostr)


# --------------------------------------------------------------------------- #
# POST — 接收用户消息
# --------------------------------------------------------------------------- #


def _parse_wechat_xml(body: str) -> dict[str, str]:
    """解析微信明文 XML 消息体，提取关键字段。"""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(body)
    result: dict[str, str] = {}
    for child in root:
        result[child.tag] = child.text or ""
    return result


def _build_reply_xml(to_user: str, from_user: str, content: str) -> str:
    """构造被动回复的 XML 文本消息。"""
    import time

    return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""


@router.post("/wechat/callback")
async def wechat_callback(
    request: Request,
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
) -> PlainTextResponse:
    """接收公众号用户消息，调用 AI 处理并回复。

    明文模式下微信直接发送消息内容 XML，无需解密。
    必须在 15 秒内返回回复，否则微信认为超时。
    """
    token = _get_token()
    if not _verify_signature(token, signature, timestamp, nonce):
        logger.warning("公众号消息签名失败：sig=%s ts=%s nonce=%s", signature, timestamp, nonce)
        raise HTTPException(status_code=403, detail="signature verification failed")

    body = await request.body()
    body_text = body.decode("utf-8")
    logger.info("公众号消息入站：%s", body_text[:200])

    try:
        msg = _parse_wechat_xml(body_text)
    except Exception as exc:
        logger.error("解析公众号 XML 失败：%s", exc)
        return PlainTextResponse(content="success")  # 无法解析时返回 success 避免微信重试

    msg_type = msg.get("MsgType", "")
    from_user = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")
    content = msg.get("Content", "")

    # 只处理文本消息
    if msg_type != "text" or not content:
        return PlainTextResponse(content="success")

    # 调用 Supervisor 处理（复用企业微信同一条链路）
    try:
        reply_text = await _handle_message(request, from_user, content)
    except Exception as exc:
        logger.error("公众号消息处理失败：%s", exc)
        reply_text = "已收到您的消息，我们会尽快为您处理。"

    reply_xml = _build_reply_xml(from_user, to_user, reply_text)
    return PlainTextResponse(content=reply_xml, media_type="application/xml")


# --------------------------------------------------------------------------- #
# 消息处理（复用 Supervisor）
# --------------------------------------------------------------------------- #


async def _handle_message(request: Request, openid: str, content: str) -> str:
    """构造 AgentState 并调用 Supervisor 图处理用户消息。

    使用 openid 作为 thread_id 实现多轮会话隔离。

    注意：必须从 :attr:`request.app.state.composition` 拿已构造好的 supervisor_graph，
    不能自己 :func:`compile_supervisor_graph` 重建——那会绕过组合根里注入的 LLM client
    / classifier / experts，导致"需要注入 classifier、supervisor 或 llm_client 之一"。
    """
    from app.agents.supervisor import compile_supervisor_graph

    settings = get_settings()
    tenant_id = settings.resolved_default_tenant_id or "default"
    thread_id = f"wechat:{tenant_id}:{openid}"

    state = new_state(
        tenant_id,
        messages=[{"role": "user", "content": content}],
        external_user_id=openid,
    )

    # 优先使用组合根里已装配的 supervisor_graph（含 LLM client / 路由 / 专家）
    graph = getattr(request.app.state.composition, "supervisor_graph", None)
    if graph is None:
        # 兜底：组合根未装配时（比如纯单元测试），再尝试本地构造
        graph = compile_supervisor_graph()
    # wechat_callback 是 async 路由；LangGraph 的 ``graph.invoke`` 是同步阻塞调用，
    # 直接 await 会卡住事件循环。用 ``asyncio.to_thread`` 丢到默认线程池跑。
    import asyncio
    result = await asyncio.to_thread(
        graph.invoke,
        state,
        config={"configurable": {"thread_id": thread_id}},
    )

    # 从结果中提取 final_answer
    if isinstance(result, Mapping):
        answer = result.get("final_answer")
        if isinstance(answer, str) and answer.strip():
            return answer

    return "已收到您的消息，我们会尽快为您处理。"
