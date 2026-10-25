"""The iLink client against a fake iLink server, the ClawBot message loop, and the 马莫百科 sync (issue #13)."""
import asyncio
import logging

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from wxbot import bot as bot_mod, hub, ilink, mamo
from wxbot.brain import Brain
from wxbot.kb import KB

# ---- ilink.Client ----------------------------------------------------------------------------------


def _fake_ilink(updates: list, sends: list):
    """getupdates answers from `updates` in order (an int is an HTTP status); sendmessage records each
    request and fails with -14 while the message still carries a context token."""
    async def getupdates(request):
        reply = updates.pop(0)
        if isinstance(reply, int):
            return web.Response(status=reply, text="<html>524</html>")
        return web.json_response(reply)

    async def sendmessage(request):
        body = await request.json()
        sends.append(body["msg"])
        if body["msg"].get("context_token") == "stale":
            return web.json_response({"ret": -14, "errmsg": "session timeout"})
        if body["msg"]["to_user_id"] == "gone@im.wechat":
            return web.json_response({"ret": -14})
        return web.json_response({"ret": 0})
    app = web.Application()
    app.router.add_post("/ilink/bot/getupdates", getupdates)
    app.router.add_post("/ilink/bot/sendmessage", sendmessage)
    return app


def _with_client(updates, sends, fn):
    async def go():
        async with TestServer(_fake_ilink(updates, sends)) as server, aiohttp.ClientSession() as http:
            client = ilink.Client(http, base_url=f"http://127.0.0.1:{server.port}", token="t")
            return await fn(client)
    return asyncio.run(go())


def test_524_from_the_international_host_is_an_empty_poll():
    resp = _with_client([524], [], lambda c: c.get_updates("CURSOR", 1000))
    assert resp == {"ret": 0, "msgs": [], "get_updates_buf": "CURSOR"}     # the cursor does not move


def test_other_http_errors_are_raised():
    with pytest.raises(ilink.HTTPError) as err:
        _with_client([500], [], lambda c: c.get_updates("CURSOR", 1000))
    assert err.value.status == 500


def test_updates_pass_through():
    resp = _with_client([{"ret": 0, "msgs": [{"message_id": 1}], "get_updates_buf": "NEXT"}], [],
                        lambda c: c.get_updates("CURSOR", 1000))
    assert resp["get_updates_buf"] == "NEXT" and resp["msgs"] == [{"message_id": 1}]


def test_stale_context_token_is_retried_without_it():
    sends = []
    _with_client([], sends, lambda c: c.send_text("u@im.wechat", "hi", "stale"))
    assert [m.get("context_token") for m in sends] == ["stale", None]
    assert sends[0]["item_list"][0]["text_item"]["text"] == "hi"


def test_send_fails_loudly_when_the_session_is_gone():
    sends = []
    with pytest.raises(RuntimeError):
        _with_client([], sends, lambda c: c.send_text("gone@im.wechat", "hi", None))
    assert len(sends) == 1


@pytest.mark.parametrize("resp,expired", [
    ({"ret": -14}, True), ({"errcode": -14}, True), ({"ret": -2, "errmsg": "unknown error"}, True),
    ({"ret": -2, "errmsg": "rate limited"}, False), ({"ret": 0}, False), ({}, False),
])
def test_session_expiry(resp, expired):
    assert ilink.is_session_expired(resp) is expired


def test_message_parsing():
    items = [{"type": ilink.ITEM_VOICE, "voice_item": {"text": " 语音问题 "}}]
    assert ilink.extract_text(items) == "语音问题"
    text_and_voice = [*items, {"type": ilink.ITEM_TEXT, "text_item": {"text": "文字"}}]
    assert ilink.extract_text(text_and_voice) == "文字"                          # text wins over voice
    quoted = [{"type": 1, "text_item": {"text": "早上六点"},
               "ref_msg": {"title": "", "message_item": {"type": 1, "text_item": {"text": "❓ 待答 #3"}}}}]
    assert ilink.extract_quote(quoted) == "❓ 待答 #3"
    assert ilink.chat_kind({"group_id": "g1", "from_user_id": "a"}, "bot") == ("group", "g1")
    assert ilink.chat_kind({"group_id": "", "from_user_id": "a"}, "bot") == ("dm", "a")


# ---- bot.Bot ---------------------------------------------------------------------------------------

ADMIN, USER = "admin@im.wechat", "stranger@im.wechat"


class FakeClient:
    def __init__(self, updates=()):
        self.updates, self.cursors, self.sent = list(updates), [], []

    async def get_updates(self, sync_buf, timeout_ms):
        self.cursors.append(sync_buf)
        nxt = self.updates.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    async def send_text(self, to, text, token):
        self.sent.append((to, text))


@pytest.fixture
def clawbot(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    kb = KB(tmp_path / "kb.sqlite")
    b = bot_mod.Bot(None, kb, {"account_id": "bot@im.bot", "base_url": "http://x", "token": "t"},
                    Brain(kb, http=None, admins={ADMIN}))
    b.client = FakeClient()
    return b


def _dm(text, mid, sender=USER, **extra):
    return {"from_user_id": sender, "message_id": mid, "context_token": "ctx",
            "item_list": [{"type": ilink.ITEM_TEXT, "text_item": {"text": text}}], **extra}


def test_process_answers_dedupes_and_ignores_groups(clawbot):
    asyncio.run(clawbot.process(_dm("你好", 1)))
    assert clawbot.client.sent[-1][0] == USER and "小助手" in clawbot.client.sent[-1][1]
    asyncio.run(clawbot.process(_dm("你好", 1)))                                 # same message id
    asyncio.run(clawbot.process(_dm("你好", 2)))                                 # redelivered under a new id
    assert len(clawbot.client.sent) == 1
    asyncio.run(clawbot.process(_dm("大家好", 3, group_id="g1")))
    assert len(clawbot.client.sent) == 1 and clawbot.kb.kv_get("group_events") == "1"
    asyncio.run(clawbot.process({"from_user_id": USER, "message_id": 4, "item_list": [{"type": ilink.ITEM_IMAGE}]}))
    assert "文字消息" in clawbot.client.sent[-1][1]
    assert clawbot.kb.context_token(USER) == "ctx"


def test_bot_never_answers_itself(clawbot):
    asyncio.run(clawbot.process(_dm("你好", 1, sender="bot@im.bot")))
    asyncio.run(clawbot.process({**_dm("你好", 2), "message_type": ilink.MSG_TYPE_BOT}))
    assert clawbot.client.sent == []


def test_cursor_only_advances_on_success(clawbot, monkeypatch):
    async def no_wait(_):
        return None
    monkeypatch.setattr(bot_mod.asyncio, "sleep", no_wait)
    clawbot.client = FakeClient([
        {"ret": 0, "get_updates_buf": "B1", "msgs": []},
        {"ret": 1, "errmsg": "boom", "get_updates_buf": "BAD"},
        {"ret": -14},
        RuntimeError("network"),
        {"ret": 0, "get_updates_buf": "B2", "msgs": []},
        asyncio.CancelledError(),
    ])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(clawbot.run())
    assert clawbot.client.cursors == ["", "B1", "B1", "B1", "B1", "B2"]
    assert clawbot.kb.kv_get("sync_buf") == "B2"
    assert clawbot.kb.kv_get("session_expired") == ""                          # cleared by the next good poll


# ---- mamo.sync_from_hub ------------------------------------------------------------------------------

MAMO_TS = """
export const MAMO_POSTS: MamoPost[] = [
  {
    url: 'https://mp.weixin.qq.com/s/aaa',
    date: '2026-09-01',
    title: '马莫百科｜学生签证续签',
    summary: 'EMGS ' +
      'and passport',
  },
  {
    url: 'https://mp.weixin.qq.com/s/bbb',
    date: '2026-09-02',
    title: 'It\\'s exam season',
    summary: '考试周',
  },
]
"""


def test_mamo_sync_indexes_new_posts_and_skips_known_ones(tmp_path, monkeypatch):
    ts = tmp_path / "mamo.ts"
    ts.write_text(MAMO_TS, encoding="utf-8")
    kb = KB(tmp_path / "kb.sqlite")
    fetched = []

    async def fetch(session, url):
        fetched.append(url)
        if url.endswith("bbb"):
            raise RuntimeError("微信要求验证")
        return {"title": "x", "digest": "", "content": "续签 正文", "published_at": None}

    async def no_wait(_):
        return None
    monkeypatch.setattr(mamo, "fetch_article", fetch)
    monkeypatch.setattr(mamo.asyncio, "sleep", no_wait)
    assert asyncio.run(mamo.sync_from_hub(None, kb, str(ts))) == (2, 2)
    a = kb.db.execute("SELECT * FROM article WHERE url LIKE '%aaa'").fetchone()
    b = kb.db.execute("SELECT * FROM article WHERE url LIKE '%bbb'").fetchone()
    assert a["title"] == "马莫百科｜学生签证续签" and a["content"] == "续签 正文" and a["digest"] == "EMGS and passport"
    assert b["title"] == "It's exam season" and b["content"] is None and b["digest"] == "考试周"   # title + summary only
    fetched.clear()
    assert asyncio.run(mamo.sync_from_hub(None, kb, str(ts))) == (1, 2)
    assert fetched == ["https://mp.weixin.qq.com/s/bbb"]                       # only the one without a body is retried


def test_a_single_failed_poll_is_not_an_alert(clawbot, monkeypatch, caplog):
    """iLink's CDN answers one long poll in an hour or two with HTTP 522 and the retry works; only a run of
    MAX_FAILURES in a row reaches the owner (alerts pick up WARNING and above)."""
    async def no_wait(_):
        return None
    monkeypatch.setattr(bot_mod.asyncio, "sleep", no_wait)
    clawbot.client = FakeClient([
        ilink.HTTPError(522, ""),
        {"ret": 0, "get_updates_buf": "B1", "msgs": []},
        ilink.HTTPError(522, ""), {"ret": 1, "errmsg": "boom"}, RuntimeError("network"),
        asyncio.CancelledError(),
    ])
    caplog.set_level("INFO", logger="wxbot")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(clawbot.run())
    loud = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(loud) == 1 and "(3/3)" in loud[0]
