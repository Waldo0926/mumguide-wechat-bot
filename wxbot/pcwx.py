"""The MonashGuide personal WeChat account, so students can ask in group chats by @-ing it.

The account runs in PC WeChat 3.9.8.25 inside the jwping/wxbot Docker image on the same VPS
(container `wxbot-wechat`, API on 127.0.0.1:8110). That project hooks the client: it is unofficial,
and the account can be banned - which is why it is a separate small account, not the owner's.

wxbot POSTs every message the account sees to our callback. We act on two kinds only:
- a group message that @-mentions the account (anything else said in a group is dropped unread,
  never stored or logged);
- a private message to the account.
Replies go back through /api/sendtxtmsg; in a group they @ the person who asked.

User ids are "pc:<wxid>" for a private chat and "pc:<room>@chatroom|<wxid>" for a group, so a
forwarded question answered later by the owner goes back to the same group, @-ing the asker.
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import logging
import re
import time
from typing import Any, Awaitable, Callable

import aiohttp
from aiohttp import web

from . import config
from .brain import Brain, Out
from .kb import KB
from .tasks import spawn

log = logging.getLogger(__name__)

PREFIX = "pc:"
MAX_TEXT = 3800
ROOM_LIMIT = 20                 # answers per group per minute: an @-storm must not make the account spam
DEDUP_TTL = 600
CHECK_EVERY_S = 600             # while logged in; checklogin is a local call, so a logout is noticed within 10 min
DOWN_ALERT_S = 600              # how long MonashGuide may be away before the owner is told
SKIP_TALKERS = {"filehelper", "fmessage", "weixin", "floatbottle", "medianote", "newsapp", "notifymessage"}

# A mention in the text is "@name" followed by U+2005 (what WeChat inserts) or a space.
_MENTION = re.compile(r"@[^\s @]{1,40}[  ]?")
_AT_LIST = re.compile(r"<atuserlist>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</atuserlist>", re.S)


def user_id(room: str | None, sender: str) -> str:
    return f"{PREFIX}{room}|{sender}" if room else f"{PREFIX}{sender}"


def parse_user(uid: str) -> tuple[str | None, str]:
    """(room or None, person wxid)."""
    body = uid[len(PREFIX):]
    if "|" in body:
        room, sender = body.split("|", 1)
        return room, sender
    return None, body


def _extra(msg: dict[str, Any]) -> bytes:
    try:
        return base64.b64decode(msg.get("BytesExtra") or "")
    except Exception:
        return b""


def sender_of(msg: dict[str, Any]) -> str:
    """Who wrote a group message. wxbot documents a Sender field; the same wxid is also the type-1
    entry of BytesExtra (protobuf: 08 01 12 <len> <wxid>), which is what this version sends."""
    if msg.get("Sender"):
        return str(msg["Sender"])
    raw = _extra(msg)
    i = raw.find(b"\x08\x01\x12")
    if i >= 0 and i + 3 < len(raw):
        n = raw[i + 3]
        return raw[i + 4:i + 4 + n].decode(errors="ignore")
    return ""


def at_list(msg: dict[str, Any]) -> list[str]:
    m = _AT_LIST.search(_extra(msg).decode(errors="ignore"))
    return [w.strip() for w in m.group(1).split(",") if w.strip()] if m else []


def mentions(msg: dict[str, Any], me: str) -> bool:
    """True when the message @-mentions this account by wxid (not "@所有人", not a name in passing)."""
    return me in at_list(msg)


def named(text: str, names: list[str]) -> bool:
    """A mention typed by hand ("@马莫百科 ...") carries no atuserlist; accept the account's own names."""
    return any(f"@{n}" in text for n in names if n)


def strip_mentions(text: str) -> str:
    return _MENTION.sub(" ", text).strip()


class PCWeChat:
    def __init__(self, http: aiohttp.ClientSession, kb: KB, brain: Brain,
                 route: Callable[[list[Out]], Awaitable[None]], api: str | None = None):
        self.http = http
        self.kb = kb
        self.brain = brain
        self.route = route            # delivers everything a reply produces (asker, admins, other channels)
        self.api = (api or config.PCWX_API).rstrip("/")
        self.me = ""
        self.seen: dict[str, float] = {}
        self.room_stamps: dict[str, list[float]] = {}
        self.names: dict[tuple[str, str], tuple[float, str]] = {}
        self.owner = config.OWNER_WXID

    # -- wxbot API -------------------------------------------------------------------------------
    async def _api(self, method: str, path: str, **kw: Any) -> Any:
        async with self.http.request(method, f"{self.api}{path}", timeout=aiohttp.ClientTimeout(total=10),
                                     **kw) as resp:
            body = await resp.json(content_type=None)
        if not isinstance(body, dict) or body.get("code") != 200:
            raise RuntimeError(f"wxbot {path}: {str(body)[:200]}")
        return body.get("data")

    async def whoami(self) -> str:
        data = await self._api("GET", "/api/checklogin")
        if str((data or {}).get("status")) != "1":
            raise RuntimeError("wxbot: the WeChat account is not logged in")
        self.me = str(data["wxid"])
        return self.me

    async def register(self, url: str) -> None:
        """wxbot keeps registered callbacks in its config; add ours once."""
        data = await self._api("GET", "/api/sync-url") or {}
        if any(c.get("url") == url for c in data.get("generalMsg") or []):
            return
        await self._api("POST", "/api/sync-url", json={"url": url, "timeout": 3000, "type": "general-msg"})

    async def _members(self, room: str) -> dict[str, Any]:
        try:
            data = await self._api("GET", "/api/dbchatroom", params={"wxid": room}) or {}
        except Exception as exc:
            log.info("pcwx: no member list for %s: %s", room[:12], exc)
            return {}
        return data.get("Members") or {}

    async def nickname(self, room: str, wxid: str) -> str:
        key = (room, wxid)
        hit = self.names.get(key)
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
        # Members are under "Members" (the README shows them at the top level). NickName, never Remark:
        # a remark is MonashGuide's private note about the person, not something to post in a group.
        name = str(((await self._members(room)).get(wxid) or {}).get("NickName") or "")
        name = re.sub(r"[\s@]", "", name)[:20]
        name = name if len(name) >= 2 else "同学"     # wxbot needs at least two characters after @
        self.names[key] = (time.time(), name)
        return name

    async def send(self, uid: str, text: str) -> None:
        await self.deliver(Out(uid, text))

    async def deliver(self, o: Out) -> None:
        room, person = parse_user(o.to)
        text = o.text[:MAX_TEXT]
        if not room:
            await self._api("POST", "/api/sendtxtmsg", json={"wxid": person, "content": text})
            return
        content, atlist = f"@{await self.nickname(room, person)} {text}", [person]
        if o.mention_owner:
            # Every miss @-s him (the owner's choice: one student may really have many questions).
            if self.owner and self.owner in await self._members(room):
                content += f" @{await self.nickname(room, self.owner)} "
                atlist.append(self.owner)
            else:
                # He is not in this group: tell him privately instead.
                content = f"@{await self.nickname(room, person)} " + text.replace(
                    f"已经请 {config.OWNER_NAME} 来回答：", f"已经转给 {config.OWNER_NAME}，他看到后会回复你。")
                if self.owner and o.note:
                    await self._api("POST", "/api/sendtxtmsg", json={"wxid": self.owner, "content": o.note})
        await self._api("POST", "/api/sendtxtmsg", json={"wxid": room, "content": content, "atlist": atlist})

    def owner_reply(self, msg: dict[str, Any]) -> int:
        """The owner, in a group, @-ing people the bot could not answer: that reply is the answer.
        Only his messages are looked at, and only for askers with an open question from this group."""
        room = str(msg.get("StrTalker") or "")
        text = strip_mentions(str(msg.get("StrContent") or ""))
        learned = 0
        for asker in at_list(msg):
            if asker not in (self.me, self.owner, "notify@all") and self.brain.learn(user_id(room, asker), text):
                learned += 1
        return learned

    # -- inbound ---------------------------------------------------------------------------------
    def _duplicate(self, key: str) -> bool:
        now = time.time()
        if len(self.seen) > 5000:
            self.seen = {k: t for k, t in self.seen.items() if now - t < DEDUP_TTL}
        if key in self.seen:
            return True
        self.seen[key] = now
        return False

    def _room_busy(self, room: str) -> bool:
        now = time.time()
        stamps = [t for t in self.room_stamps.get(room, []) if now - t < 60]
        stamps.append(now)
        self.room_stamps[room] = stamps
        return len(stamps) > ROOM_LIMIT

    def question_of(self, msg: dict[str, Any]) -> tuple[str, str] | None:
        """(user id, question) for a message the bot should answer, else None."""
        if str(msg.get("IsSender")) == "1" or str(msg.get("Type")) != "1":
            return None
        talker = str(msg.get("StrTalker") or "")
        text = str(msg.get("StrContent") or "").strip()
        if not talker or talker in SKIP_TALKERS or talker.startswith("gh_") or talker.endswith("@openim"):
            return None
        if talker.endswith("@chatroom"):
            at_me = bool(self.me) and (mentions(msg, self.me) or named(text, config.PCWX_NAMES))
            sender = sender_of(msg)
            # Metadata only: what was said in a group is not logged unless it was addressed to us.
            log.info("pcwx group msg: room=%s at_me=%s sender_found=%s", talker[:8], at_me, bool(sender))
            if not at_me and sender and sender == self.owner and str(msg.get("Type")) == "1":
                n = self.owner_reply(msg)
                if n:
                    log.info("pcwx: learned %d answer(s) from the owner's reply in a group", n)
                return None
            if not at_me or not sender or sender == self.me:
                return None
            return user_id(talker, sender), strip_mentions(text) or "你好"
        return user_id(None, talker), text

    async def process(self, msg: dict[str, Any]) -> None:
        found = self.question_of(msg)
        if not found:
            log.info("pcwx skipped: type=%s sender_is_me=%s talker=%s", msg.get("Type"), msg.get("IsSender"),
                     str(msg.get("StrTalker") or "")[:8])
            return
        mid = str(msg.get("MsgSvrID") or msg.get("localId") or "")
        if mid and self._duplicate(mid):
            return
        uid, question = found
        room, _ = parse_user(uid)
        log.info("pcwx question from %s", "group" if room else "private chat")
        if room and self._room_busy(room):
            log.info("pcwx: %s over %d answers/min, skipping", room[:12], ROOM_LIMIT)
            return
        self.kb.touch_contact(uid, None)
        outs = await self.brain.handle(uid, question)
        await self.route(outs)

    async def callback(self, request: web.Request) -> web.Response:
        if not (config.PCWX_SECRET and hmac.compare_digest(request.match_info.get("secret", ""), config.PCWX_SECRET)):
            return web.Response(status=404)
        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400)
        msgs = body.get("data") if isinstance(body, dict) else None
        log.info("pcwx callback: %d message(s)", len(msgs) if isinstance(msgs, list) else int(isinstance(msgs, dict)))
        for msg in msgs if isinstance(msgs, list) else [msgs] if isinstance(msgs, dict) else []:
            spawn(self._safe(msg))
        return web.json_response({"code": 200})        # answer at once; wxbot gives a callback 3 s

    async def _safe(self, msg: dict[str, Any]) -> None:
        try:
            await self.process(msg)
        except Exception:
            log.exception("pcwx: handling message failed")

    def app(self) -> web.Application:
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_post("/pcwx/{secret}", self.callback)
        return app


async def watch(pc: PCWeChat) -> None:
    """Keep MonashGuide attached for as long as the bot runs. wxbot can lose its WeChat login at any
    time (logged out on the phone, or a container restart waiting for the phone to confirm), and then
    group @s simply go unanswered: nothing fails on our side. So keep checking, register the callback
    again when the account is back, and warn (which alerts the owner) once it has been away for
    DOWN_ALERT_S."""
    delay, down_since, up = 10, None, False
    while True:
        try:
            me = await pc.whoami()
            if not up:
                await pc.register(f"http://{config.PCWX_LISTEN}/pcwx/{config.PCWX_SECRET}")
                log.info("pcwx: answering as %s", me)
            up, down_since, delay = True, None, 10
            await asyncio.sleep(CHECK_EVERY_S)
            continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            now = time.monotonic()
            if down_since is None:
                down_since = now
            up = False
            away = now - down_since
            if away >= DOWN_ALERT_S:
                log.warning("pcwx: MonashGuide not logged in for %d min (%s)", away // 60, exc)
            else:
                log.info("pcwx: wxbot not ready (%s); retrying in %ds", exc, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 300)


async def start(pc: PCWeChat) -> web.AppRunner:
    """Listen where the container can reach us (the docker bridge address), then keep MonashGuide
    attached in the background (it may still be logging in, or log out later)."""
    host, port = config.PCWX_LISTEN.rsplit(":", 1)
    runner = web.AppRunner(pc.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, int(port)).start()
    log.info("pcwx callback on %s", config.PCWX_LISTEN)
    spawn(watch(pc))
    return runner
