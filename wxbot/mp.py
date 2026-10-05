"""马莫百科 公众号 message server (developer mode, plaintext).

A personal subscription account can only answer *passively*: the reply goes in the HTTP response
to the user's message, within 5 seconds. Nothing can be pushed later, so anything addressed to a
公众号 user outside that window (Waldo's answer to a forwarded question) waits in the outbox and
is prepended to the reply to their next message.

User ids are namespaced "mp:<openid>" so they never collide with iLink ids.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
import xml.etree.ElementTree as ET
from typing import Awaitable, Callable

from aiohttp import web

from . import config
from .brain import Brain, Out, intro, intro_short, is_greeting
from .kb import KB

log = logging.getLogger(__name__)

PREFIX = "mp:"
REPLY_BUDGET_S = 4.0          # WeChat gives up (and retries) after 5s
MAX_REPLY_BYTES = 2000        # text replies are capped at 2048 bytes


def signature_ok(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    if not (token and signature and timestamp and nonce):
        return False
    expected = hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode()).hexdigest()
    return hmac.compare_digest(expected, signature)


def fit_bytes(text: str, limit: int = MAX_REPLY_BYTES) -> str:
    """Trim to the byte limit without losing link lines: body lines are shortened first."""
    if len(text.encode()) <= limit:
        return text
    lines = text.split("\n")
    links = [i for i, l in enumerate(lines) if "http" in l]
    budget = limit - sum(len(lines[i].encode()) + 1 for i in links) - len("…".encode())
    out, used = [], 0
    for i, line in enumerate(lines):
        if i in links:
            out.append(line)
            continue
        size = len(line.encode()) + 1
        if used + size <= budget:
            out.append(line)
            used += size
        elif used < budget:
            room = budget - used
            clipped = line.encode()[:max(room - 1, 0)].decode(errors="ignore")
            out.append(clipped + "…")
            used = budget
    text = "\n".join(out)
    return text.encode()[:limit].decode(errors="ignore")


def reply_xml(to: str, frm: str, content: str) -> str:
    content = fit_bytes(content).replace("]]>", "]] >")
    return (f"<xml><ToUserName><![CDATA[{to}]]></ToUserName><FromUserName><![CDATA[{frm}]]></FromUserName>"
            f"<CreateTime>{int(time.time())}</CreateTime><MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{content}]]></Content></xml>")


def default_welcome() -> str:
    return "欢迎关注“马莫百科”公众号！"


LATE = "我还在查 🙏 过几秒随便发一条消息（比如「1」），就能看到答案。"
SEPARATOR = "\n\n———————————\n"
MORE = "（发「你好」查看完整介绍）"


def compact_welcome(welcome: str) -> str:
    """The greeting lines plus every line with a link: enough to know what the account and
    Monash Hub are, when the full text would crowd out the answer."""
    lines = [l for l in welcome.split("\n") if l.strip()]
    keep = lines[:2] + [l for l in lines[2:] if "http" in l]
    return "\n".join(keep + [MORE])


def welcome_then(welcome: str, answer: str, limit: int = MAX_REPLY_BYTES) -> str:
    """A 订阅号 gets one reply per message, so "welcome, then the answer" is one message with a
    divider. The answer is never the part that gets cut."""
    for head in (welcome, compact_welcome(welcome)):
        text = head + SEPARATOR + answer
        if len(text.encode()) <= limit:
            return text
    return answer + "\n\n" + MORE


class MPServer:
    def __init__(self, brain: Brain, kb: KB, forward: Callable[[list[Out]], Awaitable[None]]):
        self.brain = brain
        self.kb = kb
        self.forward = forward        # delivers messages meant for someone other than the sender
        self.inflight: dict[str, asyncio.Task[str]] = {}
        self.done: dict[str, tuple[float, str]] = {}

    # WeChat retries the same message up to 3 times; all attempts must get one answer.
    async def _once(self, key: str, make: Callable[[], Awaitable[str]]) -> str:
        now = time.time()
        if len(self.done) > 1000:
            self.done = {k: v for k, v in self.done.items() if now - v[0] < 120}
        if key in self.done:
            return self.done[key][1]
        task = self.inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(make())
            self.inflight[key] = task
            task.add_done_callback(lambda t: self._finish(key, t))
        return await asyncio.shield(task)

    def _finish(self, key: str, task: asyncio.Task[str]) -> None:
        self.inflight.pop(key, None)
        if not task.cancelled() and task.exception() is None:
            self.done[key] = (time.time(), task.result())

    def _deliver_late(self, key: str, user: str) -> None:
        """The answer missed WeChat's window but is still being worked out. It may already hold
        outbox messages (marked delivered when it took them), so the whole of it goes back into the
        outbox for the user's next message instead of being dropped."""
        task = self.inflight.get(key)
        if task is None:
            return

        def done(t: asyncio.Task[str]) -> None:
            if t.cancelled() or t.exception() is not None or not t.result():
                return
            self.kb.queue_outbox(user, t.result())
            self.done[key] = (time.time(), "")     # a WeChat retry must not deliver it a second time
        task.add_done_callback(done)

    def welcome(self) -> str:
        custom = self.kb.kv_get("mp_welcome")
        return f"{custom}\n\n{intro_short()}" if custom else f"{default_welcome()}\n\n{intro()}"

    async def answer_text(self, user: str, text: str, first: bool = False) -> str:
        """first: this person has never messaged or followed since the bot took over, so they
        have not seen the 关注语 - it goes ahead of the answer."""
        if is_greeting(text):
            # "1" after a 稍等 is a request for the queued answer, not for the introduction again.
            queued = self.kb.take_outbox(user)
            return "\n\n".join(queued) if queued else self.welcome()
        outs = await self.brain.handle(user, text)
        mine = [o.text for o in outs if o.to == user]
        others = [o for o in outs if o.to != user]
        if others:
            asyncio.ensure_future(self.forward(others))
        queued = self.kb.take_outbox(user)
        reply = "\n\n".join(queued + mine)
        if first:
            custom = self.kb.kv_get("mp_welcome") or default_welcome()
            return welcome_then(custom, reply) if reply else self.welcome()
        return reply

    async def handle(self, request: web.Request) -> web.Response:
        q = request.query
        if not signature_ok(config.MP_TOKEN, q.get("signature", ""), q.get("timestamp", ""), q.get("nonce", "")):
            log.warning("mp: bad signature from %s", request.headers.get("X-Real-IP") or request.remote)
            return web.Response(status=403, text="forbidden")
        if request.method == "GET":                      # URL verification in the 公众号 backend
            return web.Response(text=q.get("echostr", ""))
        try:
            root = ET.fromstring(await request.text())
        except ET.ParseError:
            return web.Response(status=400, text="bad xml")
        f = {child.tag: (child.text or "") for child in root}
        openid, account = f.get("FromUserName", ""), f.get("ToUserName", "")
        user = PREFIX + openid
        mtype = f.get("MsgType", "")
        key = f.get("MsgId") or f"{openid}:{f.get('CreateTime')}:{f.get('Event', '')}"

        async def make() -> str:
            if mtype == "event":
                if f.get("Event") == "subscribe":
                    self.kb.touch_contact(user, None)
                    return self.welcome()
                return ""
            text = f.get("Content", "") if mtype == "text" else f.get("Recognition", "") if mtype == "voice" else ""
            text = text.strip()
            first = self.kb.touch_contact(user, None)
            if not text:
                return "目前我只看得懂文字消息，把问题打字发给我吧 🙂"
            return await self.answer_text(user, text, first=first)

        try:
            reply = await asyncio.wait_for(self._once(key, make), REPLY_BUDGET_S)
        except asyncio.TimeoutError:
            log.warning("mp: reply to %s took over %.1fs", openid[:8], REPLY_BUDGET_S)
            self._deliver_late(key, user)
            reply = LATE
        except Exception:
            log.exception("mp: handling message failed")
            reply = ""
        log.info("mp inbound type=%s event=%s from=%s replied=%s", mtype, f.get("Event", ""), openid[:8], bool(reply))
        if not reply:
            return web.Response(text="success")
        return web.Response(text=reply_xml(openid, account, reply), content_type="application/xml")

    def app(self) -> web.Application:
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_route("GET", "/mp", self.handle)
        app.router.add_route("POST", "/mp", self.handle)
        app.router.add_route("GET", "/health", lambda r: web.Response(text="ok"))
        return app


async def start(server: MPServer) -> web.AppRunner:
    runner = web.AppRunner(server.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", config.MP_PORT).start()
    log.info("mp server on 127.0.0.1:%d", config.MP_PORT)
    return runner
