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

from app.agents.intent import PUBLIC_CLARIFICATION_PROMPT
from app.agents.state import AgentState, new_state
from app.core.config import get_settings

__all__ = ["router"]

# 公众号超时、未知结果与异常时的可见回复。该文本仅保留宠主服务引导，既不泄露内部信息，
# 也不宣称消息已经受理或即将处理（Requirement 26.7 / 26.8）。
PUBLIC_ERROR_GUIDANCE: str = (
    "抱歉，刚才没有处理好这条消息。您可以告诉我想预约或调整的到店服务、宠物名称、"
    "期望时间，或想咨询的养护与健康问题；如需人工服务也可以说明。"
)

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


def _public_correlation_id(tenant_id: str, openid: str) -> str:
    """生成不含明文 openid 的公众号关联标识，供服务端标准错误日志关联。"""
    raw = f"{tenant_id}:{openid}".encode("utf-8")
    return f"wechat_public:{hashlib.sha256(raw).hexdigest()[:16]}"


def _onboarding_profile_note(missing_fields: object) -> str:
    """生成不打断当前服务的建档补充提示，不臆造缺失资料。"""
    labels = {
        "phone": "手机号",
        "species": "宠物物种（如猫或狗）",
        "breed": "宠物品种",
    }
    fields = missing_fields if isinstance(missing_fields, tuple) else ()
    details = "、".join(labels[field] for field in fields if field in labels)
    if not details:
        return ""
    return f"另外，为完善档案，请在方便时补充{details}；这不会影响本次服务。"


async def _invoke_public_supervisor(
    graph: Any,
    state: AgentState,
    *,
    graph_thread_id: str,
    correlation_id: str,
) -> str | None:
    """执行已受公号白名单约束的 Supervisor，并避免将 openid 作为持久化/追溯键。"""
    import asyncio

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                graph.invoke,
                state,
                config={"configurable": {"thread_id": graph_thread_id}},
            ),
            timeout=12.0,
        )
    except asyncio.TimeoutError:
        logger.error("wechat_public_message_timeout correlation_id=%s", correlation_id)
        return None
    if isinstance(result, Mapping):
        answer = result.get("final_answer")
        if isinstance(answer, str) and answer.strip():
            return answer
    return None


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
    # 入站 XML 含 openid 与客户原文；不得将其写入日志。
    logger.info("公众号文本消息入站，payload_bytes=%d", len(body))

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

    # 调用 Supervisor 处理（公众号只能返回宠主服务范围内的文本）
    correlation_id = _public_correlation_id(
        getattr(get_settings(), "resolved_default_tenant_id", None) or "default", from_user
    )
    try:
        reply_text = await _handle_message(request, from_user, content)
        logger.info(
            "公众号消息出站：correlation_id=%s reply_len=%d",
            correlation_id,
            len(reply_text),
        )
    except Exception:
        # logger.exception 会包含异常详情与堆栈；关联标识使用不可逆摘要，避免把 openid 写入错误日志。
        logger.exception(
            "wechat_public_message_processing_failed correlation_id=%s", correlation_id
        )
        reply_text = PUBLIC_ERROR_GUIDANCE

    reply_xml = _build_reply_xml(from_user, to_user, reply_text)
    return PlainTextResponse(content=reply_xml, media_type="application/xml")


# --------------------------------------------------------------------------- #
# 消息处理（复用 Supervisor）
# --------------------------------------------------------------------------- #


async def _handle_message(request: Request, openid: str, content: str) -> str:
    """构造公众号宠主上下文；未建档时在通用意图识别前短路到建档接待流程。"""
    from app.agents.supervisor import compile_supervisor_graph

    settings = get_settings()
    tenant_id = settings.resolved_default_tenant_id or "default"
    thread_id = f"wechat:{tenant_id}:{openid}"
    correlation_id = _public_correlation_id(tenant_id, openid)
    # 图的 checkpoint / 追溯键只使用不可逆关联标识，避免把完整 openid 写入记录。
    graph_thread_id = correlation_id
    composition = getattr(request.app.state, "composition", None)
    sessions = getattr(composition, "wechat_sessions", None)
    previous = sessions.load(thread_id) if sessions is not None else None

    if previous is None:
        state = new_state(
            tenant_id,
            messages=[{"role": "user", "content": content}],
            external_user_id=openid,
            openid=openid,
            thread_id=thread_id,
            channel="wechat_public",
            customer_facing=True,
            pending_service_request=content,
        )
    else:
        state = {**previous}
        state["messages"] = [*previous.get("messages", []), {"role": "user", "content": content}]
        state.update(
            {
                "tenant_id": tenant_id,
                "external_user_id": openid,
                "openid": openid,
                "thread_id": thread_id,
                "channel": "wechat_public",
                "customer_facing": True,
                "pending_service_request": "\n".join(
                    filter(None, (previous.get("pending_service_request"), content))
                ),
            }
        )

    resolver = getattr(composition, "customer_resolver", None)
    resolution = resolver.resolve(tenant_id, openid) if resolver is not None else None
    if resolution is not None:
        state["customer_id"] = resolution.customer_id
        state["onboarding_pending"] = bool(
            resolution.customer_id is None
            or getattr(resolution, "onboarding_pending", False)
        )

    # 未匹配客户或待完善档案必须先走渐进式建档；此分支绝不调用通用分类器。
    needs_onboarding = bool(state.get("onboarding_pending", False))
    has_saved_service = bool(previous and previous.get("pending_service_request"))
    reception_agent = getattr(composition, "reception_agent", None)
    if reception_agent is not None and (needs_onboarding or has_saved_service):
        import asyncio

        try:
            delta = await asyncio.wait_for(
                asyncio.to_thread(reception_agent.run, state), timeout=12.0
            )
        except asyncio.TimeoutError:
            logger.error(
                "wechat_public_onboarding_timeout correlation_id=%s", correlation_id
            )
            return PUBLIC_ERROR_GUIDANCE
        if isinstance(delta, Mapping):
            state.update(delta)

        refreshed = None
        if resolver is not None:
            refreshed = resolver.resolve(tenant_id, openid)
            state["customer_id"] = refreshed.customer_id
            state["onboarding_pending"] = bool(
                refreshed.customer_id is None
                or getattr(refreshed, "onboarding_pending", False)
            )

        # 在本轮已取得最小身份后才把非预约服务交给公号白名单 Supervisor；
        # 因此首条未建档消息不会抢先进入通用分类，而健康咨询也不会被档案补全阻塞。
        pending_intent = state.get("pending_service_intent")
        should_handoff_service = (
            bool(state.get("customer_id"))
            and isinstance(pending_intent, Mapping)
            and pending_intent.get("service_type") is None
        )
        service_reply: str | None = None
        if should_handoff_service:
            graph = getattr(composition, "supervisor_graph", None)
            if graph is None:
                graph = compile_supervisor_graph()
            service_reply = await _invoke_public_supervisor(
                graph,
                state,
                graph_thread_id=graph_thread_id,
                correlation_id=correlation_id,
            )

        output = state.get("agent_outputs", {}).get("reception", {})
        reply = output.get("reply_text") if isinstance(output, Mapping) else None
        status = output.get("status") if isinstance(output, Mapping) else None
        if sessions is not None:
            if not state.get("onboarding_pending") and status in {"booked", "full"}:
                sessions.clear(thread_id)
            else:
                sessions.save(thread_id, state)
        if service_reply:
            note = _onboarding_profile_note(
                getattr(refreshed, "missing_profile_fields", ())
            )
            return f"{service_reply}\n{note}" if note else service_reply
        if isinstance(reply, str) and reply.strip():
            return reply
        return PUBLIC_CLARIFICATION_PROMPT

    # 已建档客户沿用既有 Supervisor 图；上下文字段在 AgentState 中声明，因此会随图透传。
    graph = getattr(composition, "supervisor_graph", None)
    if graph is None:
        graph = compile_supervisor_graph()
    answer = await _invoke_public_supervisor(
        graph,
        state,
        graph_thread_id=graph_thread_id,
        correlation_id=correlation_id,
    )
    return answer or PUBLIC_CLARIFICATION_PROMPT
