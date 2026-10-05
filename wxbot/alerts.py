"""Tell Waldo about problems in his ClawBot chat, instead of him having to watch a log.

A logging handler picks up WARNING and above from the bot's own loggers and sends them through
the iLink channel, at most once per kind of problem per COOLDOWN_S. The one thing it cannot
report is the iLink session itself expiring - that is the channel it would report through - so
that case is also written to the status file (`python -m wxbot status`).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Awaitable, Callable

COOLDOWN_S = 30 * 60
LOGGER = "wxbot.alerts"     # our own failures to deliver an alert must not become alerts

# What each kind of log line means for Waldo, in plain words.
PLAIN = [
    (re.compile(r"reply to .* took over"), "公众号有一条回复超过 4 秒没算完，答案已放进待发，对方下一条消息时会看到"),
    (re.compile(r"hub /ask"), "连不上 Monash Hub（课程和官方政策的问题暂时答不了），看看网站是不是挂了"),
    (re.compile(r"getupdates|poll error"), "ClawBot 收消息出错了，正在自动重试"),
    (re.compile(r"handling message failed"), "处理一条消息时程序出错了"),
    (re.compile(r"bad signature"), "有请求用错误的签名访问公众号接口（可能是扫描器，一般可以忽略）"),
    (re.compile(r"i18n files unavailable"), "读不到 Monash Hub 的中文词典，课程答案暂时会是英文"),
]


def _kind(message: str) -> str:
    for pattern, _ in PLAIN:
        if pattern.search(message):
            return pattern.pattern
    return re.sub(r"[0-9a-f]{6,}|\d+", "#", message)[:60]


def _plain(message: str) -> str:
    for pattern, text in PLAIN:
        if pattern.search(message):
            return text
    return "程序报了一个错误"


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
        kind, now = _kind(message), time.time()
        if now - self.last.get(kind, 0) < COOLDOWN_S:
            return
        self.last[kind] = now
        text = f"⚠️ 机器人提醒：{_plain(message)}\n（{time.strftime('%H:%M')}，同类问题 30 分钟内不再重复提醒）\n\n{message[:300]}"
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._safe_send(text)))

    async def _safe_send(self, text: str) -> None:
        try:
            await self.send(text)
        except Exception as exc:
            logging.getLogger(LOGGER).warning("could not deliver alert: %s", exc)
