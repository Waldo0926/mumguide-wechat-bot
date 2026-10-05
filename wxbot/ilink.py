"""Minimal client for Tencent's iLink Bot API (the official personal-WeChat bot channel).

Protocol details follow Hermes Agent's weixin adapter (gateway/platforms/weixin.py on j1900):
long-polling getupdates, sendmessage with the per-conversation context_token echoed back.
Only text is handled - media goes through an AES-encrypted CDN we have no use for.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import uuid
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

BASE_URL = "https://ilinkai.weixin.qq.com"
APP_ID = "bot"
CHANNEL_VERSION = "2.2.0"
CLIENT_VERSION = str((2 << 16) | (2 << 8) | 0)

LONG_POLL_TIMEOUT_MS = 35_000
API_TIMEOUT_MS = 15_000
QR_TIMEOUT_MS = 35_000

SESSION_EXPIRED = -14
RATE_LIMITED = -2

ITEM_TEXT, ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO = 1, 2, 3, 4, 5
MSG_TYPE_BOT, MSG_STATE_FINISH = 2, 2


class HTTPError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# The international host (ilinkai.wechat.com, which overseas accounts are redirected to at login)
# sits behind Tencent EdgeOne, which cuts a request at ~15s with 524 - shorter than the 35s
# long-poll hold. The server answers at once when messages are waiting and the update cursor only
# advances on a 200, so a 524 just means "nothing yet".
EMPTY_POLL_STATUSES = {504, 524}


def _headers(token: str | None, body: str) -> dict[str, str]:
    uin = base64.b64encode(str(int.from_bytes(secrets.token_bytes(4), "big")).encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Content-Length": str(len(body.encode("utf-8"))),
        "X-WECHAT-UIN": uin,
        "iLink-App-Id": APP_ID,
        "iLink-App-ClientVersion": CLIENT_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def is_session_expired(resp: dict[str, Any]) -> bool:
    ret, errcode = resp.get("ret"), resp.get("errcode")
    if SESSION_EXPIRED in (ret, errcode):
        return True
    # ret=-2 with "unknown error" is a stale session, not a real rate limit (per Hermes).
    return RATE_LIMITED in (ret, errcode) and str(resp.get("errmsg") or "").lower() == "unknown error"


def is_error(resp: dict[str, Any]) -> bool:
    return resp.get("ret") not in (0, None) or resp.get("errcode") not in (0, None)


async def _request(session: aiohttp.ClientSession, method: str, url: str, *, headers: dict[str, str],
                   timeout_ms: int, body: str | None = None) -> dict[str, Any]:
    async def _do() -> dict[str, Any]:
        kwargs = {"data": body} if body is not None else {}
        async with session.request(method, url, headers=headers, **kwargs) as resp:
            raw = await resp.text()
            if not resp.ok:
                raise HTTPError(resp.status, f"iLink {method} {url.rsplit('/', 1)[-1]} HTTP {resp.status}: {raw[:200]}")
            return json.loads(raw) if raw else {}
    return await asyncio.wait_for(_do(), timeout=timeout_ms / 1000)


async def api_get(session: aiohttp.ClientSession, base_url: str, endpoint: str) -> dict[str, Any]:
    headers = {"iLink-App-Id": APP_ID, "iLink-App-ClientVersion": CLIENT_VERSION}
    return await _request(session, "GET", f"{base_url.rstrip('/')}/{endpoint}", headers=headers, timeout_ms=QR_TIMEOUT_MS)


class Client:
    def __init__(self, session: aiohttp.ClientSession, *, base_url: str, token: str):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.token = token

    async def post(self, endpoint: str, payload: dict[str, Any], timeout_ms: int = API_TIMEOUT_MS) -> dict[str, Any]:
        body = json.dumps({**payload, "base_info": {"channel_version": CHANNEL_VERSION}},
                          ensure_ascii=False, separators=(",", ":"))
        return await _request(self.session, "POST", f"{self.base_url}/{endpoint}",
                              headers=_headers(self.token, body), timeout_ms=timeout_ms, body=body)

    async def get_updates(self, sync_buf: str, timeout_ms: int) -> dict[str, Any]:
        try:
            # A little slack over the server-side hold so a normal empty poll isn't a client timeout.
            return await self.post("ilink/bot/getupdates", {"get_updates_buf": sync_buf}, timeout_ms + 5_000)
        except asyncio.TimeoutError:
            return {"ret": 0, "msgs": [], "get_updates_buf": sync_buf}
        except HTTPError as exc:
            if exc.status in EMPTY_POLL_STATUSES:
                return {"ret": 0, "msgs": [], "get_updates_buf": sync_buf}
            raise

    async def send_text(self, to: str, text: str, context_token: str | None) -> None:
        """Send one text message. Retries once without context_token when the session token is stale -
        iLink accepts tokenless sends as a degraded fallback."""
        for token in ([context_token, None] if context_token else [None]):
            msg: dict[str, Any] = {
                "from_user_id": "", "to_user_id": to, "client_id": uuid.uuid4().hex,
                "message_type": MSG_TYPE_BOT, "message_state": MSG_STATE_FINISH,
                "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
            }
            if token:
                msg["context_token"] = token
            resp = await self.post("ilink/bot/sendmessage", {"msg": msg})
            if not is_error(resp):
                return
            if is_session_expired(resp) and token:
                log.warning("send to %s: context token stale, retrying without it", to[:8])
                continue
            raise RuntimeError(f"sendmessage failed: {resp}")
        raise RuntimeError("sendmessage failed after tokenless retry")


def extract_text(item_list: list[dict[str, Any]]) -> str:
    for item in item_list:
        if item.get("type") == ITEM_TEXT:
            return str((item.get("text_item") or {}).get("text") or "").strip()
    for item in item_list:
        if item.get("type") == ITEM_VOICE:
            # Tencent's own speech-to-text; good enough for Chinese questions.
            return str((item.get("voice_item") or {}).get("text") or "").strip()
    return ""


def extract_quote(item_list: list[dict[str, Any]]) -> str:
    """Text of the message being quoted (WeChat's 引用), if any."""
    for item in item_list:
        ref = item.get("ref_msg") or {}
        if not ref:
            continue
        inner = ref.get("message_item") or {}
        quoted = extract_text([inner]) if inner else ""
        return " ".join(p for p in (str(ref.get("title") or ""), quoted) if p).strip()
    return ""


def chat_kind(message: dict[str, Any], account_id: str) -> tuple[str, str]:
    """('group', room_id) or ('dm', sender). Hermes' heuristic, plus group_id, which iLink sends
    on every message (empty in a DM)."""
    room = str(message.get("group_id") or message.get("room_id") or message.get("chat_room_id") or "").strip()
    to = str(message.get("to_user_id") or "").strip()
    if room or (to and account_id and to != account_id and message.get("msg_type") == 1):
        return "group", room or to
    return "dm", str(message.get("from_user_id") or "")
