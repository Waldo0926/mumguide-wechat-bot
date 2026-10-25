"""Tell Waldo about problems in his ClawBot chat, instead of him having to watch a log.

A logging handler picks up WARNING and above from the bot's own loggers and sends them through
the iLink channel, at most once per kind of problem per cooldown. When ClawBot itself cannot
deliver (its login expired, or there is no iLink login), bot.alert_sender passes the alert to the
owner's own WeChat through the MonashGuide account, if WXBOT_OWNER_WXID is set. Without that,
an expired session is only visible in the status file (`python -m wxbot status`).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable

from .tasks import spawn

COOLDOWN_S = 30 * 60
LOGGER = "wxbot.alerts"     # our own failures to deliver an alert must not become alerts

# What each kind of log line means for Waldo, in plain words, and how often he hears about it.
PLAIN = [
    (re.compile(r"reply to .* took over"), "公众号有一条回复超过 4 秒没算完，答案已放进待发，对方下一条消息时会看到", COOLDOWN_S),
    # hub._call logs "hub POST /ask failed: ..." and "hub GET /units/FIT2004 failed: ...": one kind for all.
    (re.compile(r"^hub (GET|POST) "), "连不上 Monash Hub（课程和官方政策的问题暂时答不了），看看网站是不是挂了", COOLDOWN_S),
    # Logged every 10 minutes until someone scans again; a reminder every 6 hours is enough.
    (re.compile(r"session expired"), "ClawBot 登录过期了，需要在 VPS 上重新扫码：python -m wxbot login", 6 * 3600),
    # pcwx.watch repeats this every 5 minutes while MonashGuide is away.
    (re.compile(r"MonashGuide not logged in"),
     "MonashGuide 小号掉线了，群里 @ 它不会回复。在 VPS 上 docker restart wxbot-wechat，再用 MonashGuide 的手机确认登录", 6 * 3600),
    (re.compile(r"getupdates|poll error"), "ClawBot 连续 3 次收消息出错，30 秒后自动重试；一直收到这条提醒的话，看看 VPS 的网络", COOLDOWN_S),
    (re.compile(r"handling message failed"), "处理一条消息时程序出错了", COOLDOWN_S),
    (re.compile(r"send to .* failed|dropped message"), "有一条消息没能发出去", COOLDOWN_S),
    (re.compile(r"bad signature"), "有请求用错误的签名访问公众号接口（可能是扫描器，一般可以忽略）", COOLDOWN_S),
    (re.compile(r"i18n files unavailable"), "读不到 Monash Hub 的中文词典，课程答案暂时会是英文", COOLDOWN_S),
]


def _match(message: str) -> tuple[str, str, float]:
    """(kind, plain words, cooldown) for a log message."""
    for pattern, text, cooldown in PLAIN:
        if pattern.search(message):
            return pattern.pattern, text, cooldown
    return re.sub(r"[0-9a-f]{6,}|\d+", "#", message)[:60], "程序报了一个错误", COOLDOWN_S


class AlertHandler(logging.Handler):
    def __init__(self, send: Callable[[str], Awaitable[None]], loop: asyncio.AbstractEventLoop):
        super().__init__(level=logging.WARNING)
        self.send = send
        self.loop = loop
        self.last: dict[str, float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(LOGGER) or not record.name.startswith("wxbot"):
            return
        try:
            message = record.getMessage()
        except Exception:
            return
        (kind, plain, cooldown), now = _match(message), time.time()
        if now - self.last.get(kind, 0) < cooldown:
            return
        self.last[kind] = now
        quiet = f"{cooldown // 3600:g} 小时" if cooldown >= 3600 else f"{cooldown // 60:g} 分钟"
        text = f"⚠️ 机器人提醒：{plain}\n（{time.strftime('%H:%M')}，同类问题 {quiet}内不再重复提醒）\n\n{message[:300]}"
        self.loop.call_soon_threadsafe(lambda: spawn(self._safe_send(text)))

    async def _safe_send(self, text: str) -> None:
        try:
            await self.send(text)
        except Exception as exc:
            logging.getLogger(LOGGER).warning("could not deliver alert: %s", exc)
