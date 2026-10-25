import asyncio
import logging

import aiohttp

from wxbot import alerts, bot, config, hub, pcwx
from wxbot.alerts import AlertHandler


def test_alerts_are_plain_and_rate_limited():
    sent = []

    async def go():
        async def send(text):
            sent.append(text)
        handler = AlertHandler(send, asyncio.get_running_loop())
        log = logging.getLogger("wxbot.test")
        log.addHandler(handler)
        log.propagate = False
        try:
            log.warning("hub POST /ask failed: connection refused")
            log.warning("hub GET /units/FIT2004 failed: TimeoutError")   # same kind: suppressed
            log.warning("mp: reply to abc took over 4.0s")
            logging.getLogger("wxbot.alerts").warning("could not deliver alert")   # never loops
            logging.getLogger("aiohttp.access").warning("not ours")
            await asyncio.sleep(0.01)
        finally:
            log.removeHandler(handler)
    asyncio.run(go())
    assert len(sent) == 2
    assert "连不上 Monash Hub" in sent[0] and "30 分钟内" in sent[0] and "超过 4 秒" in sent[1]


def test_what_hub_logs_when_down_is_reported_as_hub_down(monkeypatch):
    """The pattern must match hub._call's real log line, not a hand-written copy of it."""
    monkeypatch.setattr(config, "HUB_API", "http://127.0.0.1:9/api/v1")       # nothing listens on port 9
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logging.getLogger("wxbot.hub").addHandler(handler)

    async def go():
        async with aiohttp.ClientSession() as http:
            return await hub._call(http, "POST", "/ask", 1.0, json={"query": "x"})
    try:
        assert asyncio.run(go()) == (0, None)
    finally:
        logging.getLogger("wxbot.hub").removeHandler(handler)
    kind, plain, _ = alerts._match(records[0].getMessage())
    assert "连不上 Monash Hub" in plain


def test_expired_session_is_a_six_hour_reminder():
    _, plain, cooldown = alerts._match("iLink session expired - needs a new QR login (python -m wxbot login)")
    assert "重新扫码" in plain and cooldown == 6 * 3600


class _Client:
    def __init__(self, fail):
        self.fail, self.sent = fail, []

    async def send_text(self, to, text, token):
        if self.fail:
            raise RuntimeError("sendmessage failed: {'ret': -14}")
        self.sent.append((to, text))


class _ILink:
    def __init__(self, fail, kb=None):
        self.client = _Client(fail)
        self.kb = kb


class _KB:
    def context_token(self, user):
        return None


class _PC:
    def __init__(self):
        self.sent = []

    async def send(self, uid, text):
        self.sent.append((uid, text))


def test_alert_goes_to_monashguide_when_clawbot_cannot_send():
    ok, broken, pc = _ILink(False, _KB()), _ILink(True, _KB()), _PC()
    asyncio.run(bot.alert_sender(ok, {"admin@im.wechat"}, pc, "wxid_owner")("a"))
    assert ok.client.sent == [("admin@im.wechat", "a")] and pc.sent == []
    # admins added by pairing on the 公众号 or MonashGuide are not ClawBot users (issue #4)
    asyncio.run(bot.alert_sender(ok, {"admin@im.wechat", "mp:x", "pc:wxid_y"}, pc, "wxid_owner")("a2"))
    assert ok.client.sent[-1] == ("admin@im.wechat", "a2") and len(ok.client.sent) == 2
    asyncio.run(bot.alert_sender(broken, {"admin@im.wechat"}, pc, "wxid_owner")("b"))
    assert pc.sent == [(pcwx.user_id(None, "wxid_owner"), "b")]
    asyncio.run(bot.alert_sender(None, set(), pc, "wxid_owner")("c"))          # no iLink login at all
    assert pc.sent[-1] == ("pc:wxid_owner", "c")
    assert bot.alert_sender(None, set(), pc, "") is None                        # nowhere to send
    assert bot.alert_sender(None, set(), None, "wxid_owner") is None


def test_monashguide_logout_is_a_six_hour_reminder():
    kind, plain, cooldown = alerts._match("pcwx: MonashGuide not logged in for 15 min (wxbot: not logged in)")
    assert "MonashGuide 小号掉线" in plain and cooldown == 6 * 3600


def test_one_slow_hub_call_is_not_an_alert(monkeypatch, caplog):
    """A unit search that runs out of reply budget once (2026-10-12, 12:44) is not the Hub being down;
    SLOW_ALERT_AFTER timeouts in a row with no answer in between is."""
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def slow(request):
        await asyncio.sleep(1)
        return web.json_response({})

    async def fast(request):
        return web.json_response({})
    app = web.Application()
    app.router.add_get("/api/v1/slow", slow)
    app.router.add_get("/api/v1/fast", fast)
    monkeypatch.setattr(hub, "_timeouts_in_row", 0)
    caplog.set_level("INFO", logger="wxbot.hub")

    async def go():
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            monkeypatch.setattr(config, "HUB_API", f"http://127.0.0.1:{server.port}/api/v1")
            for path in ["/slow", "/slow", "/fast", "/slow", "/slow", "/slow"]:
                # The answer in between gets plenty of time: on a busy CI runner 0.3 s timed it out too.
                await hub._call(http, "GET", path, 5.0 if path == "/fast" else 0.3)
    asyncio.run(go())
    lines = [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "wxbot.hub"]
    assert [lvl for lvl, _ in lines] == [logging.INFO] * 4 + [logging.WARNING]
    assert lines[-1][1].endswith("TimeoutError") and "连不上 Monash Hub" in alerts._match(lines[-1][1])[1]
