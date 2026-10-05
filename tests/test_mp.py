import asyncio
import hashlib
import xml.etree.ElementTree as ET

import pytest
from aiohttp.test_utils import TestClient, TestServer

from wxbot import config, hub, mp
from wxbot.brain import Brain
from wxbot.kb import KB

TOKEN = "t0ken"
ADMIN = "admin@im.wechat"


def sign(ts="1700000000", nonce="42"):
    sig = hashlib.sha1("".join(sorted([TOKEN, ts, nonce])).encode()).hexdigest()
    return {"signature": sig, "timestamp": ts, "nonce": nonce}


def msg(openid, content=None, event=None, msgid="1"):
    body = f"<ToUserName><![CDATA[gh_x]]></ToUserName><FromUserName><![CDATA[{openid}]]></FromUserName><CreateTime>1</CreateTime>"
    if event:
        body += f"<MsgType><![CDATA[event]]></MsgType><Event><![CDATA[{event}]]></Event>"
    else:
        body += f"<MsgType><![CDATA[text]]></MsgType><Content><![CDATA[{content}]]></Content><MsgId>{msgid}</MsgId>"
    return f"<xml>{body}</xml>"


def content_of(xml_text):
    return ET.fromstring(xml_text).find("Content").text


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MP_TOKEN", TOKEN)

    async def no_hub(http, q, timeout=3.0):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    kb = KB(tmp_path / "kb.sqlite")
    forwarded = []

    async def forward(outs):
        for o in outs:
            if o.to.startswith(mp.PREFIX):
                kb.queue_outbox(o.to, o.text)
            else:
                forwarded.append(o)
    brain = Brain(kb, http=None, admins={ADMIN})
    return kb, brain, mp.MPServer(brain, kb, forward), forwarded


def run(server, coro_fn):
    async def go():
        async with TestClient(TestServer(server.app())) as c:
            return await coro_fn(c)
    return asyncio.run(go())


def test_url_verification(env):
    _, _, server, _ = env

    async def go(c):
        ok = await c.get("/mp", params={**sign(), "echostr": "hello"})
        bad = await c.get("/mp", params={**sign(), "signature": "x", "echostr": "hello"})
        return await ok.text(), bad.status
    assert run(server, go) == ("hello", 403)


def test_subscribe_uses_welcome(env):
    kb, _, server, _ = env
    kb.kv_set("mp_welcome", "欢迎来到马莫百科")

    async def go(c):
        r = await c.post("/mp", params=sign(), data=msg("o1", event="subscribe"))
        return content_of(await r.text())
    text = run(server, go)
    assert text.startswith("欢迎来到马莫百科") and "自动问答已开启" in text


def test_miss_then_answer_arrives_on_next_message(env):
    kb, brain, server, forwarded = env

    async def go(c):
        r1 = await c.post("/mp", params=sign(), data=msg("o1", "食堂哪家好吃", msgid="1"))
        first = content_of(await r1.text())
        await asyncio.sleep(0.05)                    # let the admin notification go out
        pid = kb.open_pending()[0]["id"]
        admin_reply = await brain.handle(ADMIN, f"答 {pid} 推荐 Campus Centre")
        for o in admin_reply:
            if o.to != ADMIN:
                await server.forward([o])
        r2 = await c.post("/mp", params=sign(), data=msg("o1", "你好", msgid="2"))
        return first, content_of(await r2.text()), admin_reply
    first, second, admin_reply = run(server, go)
    assert "再给我发任意一条消息" in first
    assert any(o.to == ADMIN and "待答" in o.text for o in forwarded)
    assert "没法主动推送" in admin_reply[0].text
    assert second.startswith("关于你问的「食堂哪家好吃」") and "Campus Centre" in second


def test_retries_get_one_answer(env):
    kb, _, server, _ = env
    kb.add_qa("图书馆几点关门", "晚上十点")

    async def go(c):
        rs = await asyncio.gather(*[c.post("/mp", params=sign(), data=msg("o1", "图书馆几点关门", msgid="9"))
                                    for _ in range(3)])
        return [content_of(await r.text()) for r in rs]
    replies = run(server, go)
    assert len(set(replies)) == 1 and "晚上十点" in replies[0]
    assert kb.db.execute("SELECT COUNT(*) FROM log").fetchone()[0] == 1


def test_fit_bytes_keeps_links():
    text = "标题\n" + "很长的正文" * 300 + "\n🔗 官网：https://www.monash.edu/x"
    out = mp.fit_bytes(text, 600)
    assert len(out.encode()) <= 600 and out.endswith("https://www.monash.edu/x") and "…" in out


def test_first_message_gets_welcome_then_answer(env):
    kb, _, server, _ = env
    kb.kv_set("mp_welcome", "欢迎来到马莫百科\n我是 Waldo\n这里分享很多东西\nMonash Hub\nhttps://monashhub.secureview.tech")
    kb.add_qa("怎么进群", "加微信 群助手")

    async def go(c):
        r1 = await c.post("/mp", params=sign(), data=msg("o2", "怎么进群呢？", msgid="21"))
        r2 = await c.post("/mp", params=sign(), data=msg("o2", "怎么进群呢？", msgid="22"))
        r3 = await c.post("/mp", params=sign(), data=msg("o2", "你好", msgid="23"))
        return [content_of(await r.text()) for r in (r1, r2, r3)]
    first, second, hello = run(server, go)
    assert first.startswith("欢迎来到马莫百科") and first.index("———") < first.index("群助手")
    assert second.startswith("加微信 群助手")                 # only the first message gets it
    assert hello.startswith("欢迎来到马莫百科") and "自动问答已开启" in hello


def test_welcome_then_long_answer_keeps_the_answer_whole():
    welcome = "欢迎来到马莫百科\n我是 Waldo\n" + "很长的介绍\n" * 150 + "https://monashhub.secureview.tech"
    answer = "答案正文" * 40
    text = mp.welcome_then(welcome, answer)
    assert text.endswith(answer) and "很长的介绍" not in text
    assert "https://monashhub.secureview.tech" in text and "发「你好」查看完整介绍" in text
    huge = "答" * 700
    assert mp.welcome_then(welcome, huge).startswith(huge)


def test_a_late_answer_waits_in_the_outbox(env, monkeypatch):
    kb, brain, server, _ = env
    monkeypatch.setattr(mp, "REPLY_BUDGET_S", 0.05)
    kb.queue_outbox("mp:u9", "Waldo 的回复")

    async def slow(user, text, quoted=""):
        await asyncio.sleep(0.2)
        return [brain_mod_out(user, "迟到的答案")]
    monkeypatch.setattr(brain, "handle", slow)

    async def go(c):
        first = content_of(await (await c.post("/mp", params=sign(), data=msg("u9", "问题", msgid="77"))).text())
        await asyncio.sleep(0.3)
        later = content_of(await (await c.post("/mp", params=sign(), data=msg("u9", "1", msgid="78"))).text())
        return first, later
    first, later = run(server, go)
    assert first == mp.LATE
    assert "Waldo 的回复" in later and "迟到的答案" in later and "小助手" not in later


def brain_mod_out(to, text):
    from wxbot.brain import Out
    return Out(to, text)
