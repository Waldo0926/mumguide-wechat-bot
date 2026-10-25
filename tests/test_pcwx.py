import asyncio
import base64
import time

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from wxbot import config, hub, pcwx
from wxbot.brain import Brain
from wxbot.kb import KB

ME, ROOM, ASKER = "wxid_bot", "123@chatroom", "WenSX0926"


def extra(sender=None, at=None):
    """BytesExtra the way wxbot sends it: protobuf entries, type 1 = group sender, type 7 = msgsource XML."""
    raw = b"\n\x04\x08\x10\x10\x00"
    if sender:
        s = sender.encode()
        raw += b"\x1a" + bytes([len(s) + 4]) + b"\x08\x01\x12" + bytes([len(s)]) + s
    xml = "<msgsource>" + (f"<atuserlist><![CDATA[{at}]]></atuserlist>" if at else "") + "<pua>1</pua></msgsource>"
    raw += b"\x1a\x10\x08\x07\x12" + bytes([len(xml)]) + xml.encode()
    return base64.b64encode(raw).decode()


def group_msg(text, at=ME, sender=ASKER, mid="1"):
    return {"StrTalker": ROOM, "StrContent": text, "Type": "1", "IsSender": "0", "MsgSvrID": mid,
            "BytesExtra": extra(sender, at)}


def dm(text, mid="9"):
    return {"StrTalker": ASKER, "StrContent": text, "Type": "1", "IsSender": "0", "MsgSvrID": mid,
            "BytesExtra": extra()}


@pytest.fixture
def pc(tmp_path):
    p = pcwx.PCWeChat(http=None, kb=KB(tmp_path / "kb.sqlite"), brain=None, route=None, api="http://x")
    p.me = ME
    return p


def test_only_mentions_and_private_messages_are_questions(pc):
    assert pc.question_of(group_msg("@马莫百科 学生签证怎么续签")) == (f"pc:{ROOM}|{ASKER}", "学生签证怎么续签")
    assert pc.question_of(group_msg("随便聊聊", at=None)) is None
    assert pc.question_of(group_msg("@所有人 开会", at="notify@all")) is None
    assert pc.question_of(group_msg("@马莫百科 我自己", sender=ME)) is None
    assert pc.question_of({**group_msg("@马莫百科 hi"), "IsSender": "1"}) is None
    assert pc.question_of({**group_msg("@马莫百科 hi"), "Type": "3"}) is None          # an image
    assert pc.question_of(dm("FIT2102有考试吗")) == (f"pc:{ASKER}", "FIT2102有考试吗")
    assert pc.question_of({**dm("推文"), "StrTalker": "gh_abc"}) is None
    assert pc.question_of(group_msg("@马莫百科 ")) == (f"pc:{ROOM}|{ASKER}", "你好")


def test_user_ids_round_trip():
    assert pcwx.parse_user(pcwx.user_id(ROOM, ASKER)) == (ROOM, ASKER)
    assert pcwx.parse_user(pcwx.user_id(None, ASKER)) == (None, ASKER)


def _fake_wxbot(sent, registered):
    async def checklogin(request):
        return web.json_response({"code": 200, "data": {"status": 1, "wxid": ME}})

    async def chatroom(request):
        return web.json_response({"code": 200, "data": {"Members": {ASKER: {"NickName": "Waldo Wen", "Remark": "私人备注"}}}})

    async def send(request):
        sent.append(await request.json())
        return web.json_response({"code": 200, "msg": "success"})

    async def sync(request):
        if request.method == "POST":
            registered.append(await request.json())
        return web.json_response({"code": 200, "data": {"generalMsg": registered}})
    app = web.Application()
    app.router.add_get("/api/checklogin", checklogin)
    app.router.add_get("/api/dbchatroom", chatroom)
    app.router.add_post("/api/sendtxtmsg", send)
    app.router.add_route("*", "/api/sync-url", sync)
    return app


def test_group_question_is_answered_with_an_at_and_misses_reach_the_owner(tmp_path, monkeypatch):
    async def hub_answer(http, q):
        return hub.HubAnswer("strong", "签证答案", "official_faq") if "签证" in q else None
    monkeypatch.setattr(hub, "ask", hub_answer)
    monkeypatch.setattr(config, "PCWX_SECRET", "s3cret")
    sent, registered, admin_notes = [], [], []

    async def go():
        async with TestServer(_fake_wxbot(sent, registered)) as wx, aiohttp.ClientSession() as http:
            kb = KB(tmp_path / "kb.sqlite")
            brain = Brain(kb, http, admins={"admin@im.wechat"})

            async def route(outs):
                for o in outs:
                    if o.to.startswith(pcwx.PREFIX):
                        await pc.send(o.to, o.text)
                    else:
                        admin_notes.append(o)
            pc = pcwx.PCWeChat(http, kb, brain, route, api=f"http://127.0.0.1:{wx.port}")
            await pc.whoami()
            await pc.register("http://172.17.0.1:8112/pcwx/s3cret")
            await pc.register("http://172.17.0.1:8112/pcwx/s3cret")        # idempotent
            async with TestClient(TestServer(pc.app())) as c:
                assert (await c.post("/pcwx/wrong", json={"data": []})).status == 404
                await c.post("/pcwx/s3cret", json={"wxid": ME, "total": 2, "data": [
                    group_msg("@马莫百科 学生签证怎么续签", mid="1"), group_msg("闲聊", at=None, mid="2")]})
                await asyncio.sleep(0.2)
                await c.post("/pcwx/s3cret", json={"data": [group_msg("@马莫百科 食堂哪家好吃", mid="3")]})
                await c.post("/pcwx/s3cret", json={"data": [group_msg("@马莫百科 食堂哪家好吃", mid="3")]})  # retry
                await asyncio.sleep(0.2)
            await route(brain.due_notes(time.time() + 3600))
            pid = kb.open_pending()[0]["id"]
            await route(await brain.handle("admin@im.wechat", f"答 {pid} 去 Campus Centre"))
            return kb
    kb = asyncio.run(go())
    assert len(registered) == 1
    assert sent[0]["wxid"] == ROOM and sent[0]["atlist"] == [ASKER]
    assert sent[0]["content"].startswith("@WaldoWen 签证答案\n📘 Monash Hub 上查看更多：https://monashhub.secureview.tech/search?q=")
    assert sum("答不上来" in s["content"] for s in sent) == 1                  # one reply despite the retry
    assert any("微信群" in o.text and "食堂哪家好吃" in o.text for o in admin_notes)
    assert sent[-1]["wxid"] == ROOM and "Campus Centre" in sent[-1]["content"] and sent[-1]["atlist"] == [ASKER]
    # Nothing from the unaddressed chat was kept.
    assert not kb.db.execute("SELECT 1 FROM log WHERE question LIKE '%闲聊%'").fetchone()


OWNER, OTHER = "wxid_waldo", "wxid_student2"


def test_group_miss_ats_the_owner_and_his_reply_is_learned(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    monkeypatch.setattr(config, "OWNER_WXID", OWNER)
    sent = []

    async def go():
        async def checklogin(request):
            return web.json_response({"code": 200, "data": {"status": 1, "wxid": ME}})

        async def chatroom(request):
            return web.json_response({"code": 200, "data": {"Members": {
                ASKER: {"NickName": "sky"}, OTHER: {"NickName": "日耀"}, OWNER: {"NickName": "Waldo"}}}})

        async def send(request):
            sent.append(await request.json())
            return web.json_response({"code": 200})
        app = web.Application()
        app.router.add_get("/api/checklogin", checklogin)
        app.router.add_get("/api/dbchatroom", chatroom)
        app.router.add_post("/api/sendtxtmsg", send)
        async with TestServer(app) as wx, aiohttp.ClientSession() as http:
            kb = KB(tmp_path / "kb.sqlite")
            brain = Brain(kb, http, admins={"admin@im.wechat"})

            async def route(outs):
                for o in outs:
                    assert o.to.startswith(pcwx.PREFIX)          # nothing goes to ClawBot any more
                    await pc.deliver(o)
            pc = pcwx.PCWeChat(http, kb, brain, route, api=f"http://127.0.0.1:{wx.port}")
            await pc.whoami()
            await pc.process(group_msg("@马莫百科 食堂哪家好吃", mid="1"))
            await pc.process(group_msg("@马莫百科 健身房几点开", sender=OTHER, mid="2"))   # within the cooldown
            # Waldo answers sky in the group by @-ing them.
            reply = {**group_msg("@sky 去 Campus Centre", at=ASKER, sender=OWNER, mid="3")}
            assert pc.question_of(reply) is None
            # A private message from Waldo is an admin command.
            await pc.process({**dm("待答", mid="4"), "StrTalker": OWNER})
            return kb
    kb = asyncio.run(go())
    first, second = sent[0], sent[1]
    assert first["wxid"] == ROOM and first["atlist"] == [ASKER, OWNER]
    assert first["content"].startswith("@sky ") and first["content"].endswith("@Waldo ")
    assert second["atlist"] == [OTHER, OWNER]                                   # every miss @-s him
    assert kb.match_qa("食堂哪家好吃")[0].score == 1.0
    assert "去 Campus Centre" in kb.get_qa(kb.match_qa("食堂哪家好吃")[0].id)["answer"]
    assert [p["question"] for p in kb.open_pending()] == ["健身房几点开"]
    assert sent[-1]["wxid"] == OWNER and "健身房几点开" in sent[-1]["content"]     # 「待答」 answered to him


def test_owner_not_in_the_group_gets_a_private_note(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    monkeypatch.setattr(config, "OWNER_WXID", OWNER)
    sent = []

    async def go():
        async def chatroom(request):
            return web.json_response({"code": 200, "data": {"Members": {ASKER: {"NickName": "sky"}}}})

        async def send(request):
            sent.append(await request.json())
            return web.json_response({"code": 200})
        app = web.Application()
        app.router.add_get("/api/dbchatroom", chatroom)
        app.router.add_post("/api/sendtxtmsg", send)
        async with TestServer(app) as wx, aiohttp.ClientSession() as http:
            kb = KB(tmp_path / "kb.sqlite")
            brain = Brain(kb, http, admins=set())
            pc = pcwx.PCWeChat(http, kb, brain, None, api=f"http://127.0.0.1:{wx.port}")
            pc.me = ME
            for o in await brain.handle(f"pc:{ROOM}|{ASKER}", "食堂哪家好吃"):
                await pc.deliver(o)
    asyncio.run(go())
    assert sent[0]["wxid"] == OWNER and "待答 #1" in sent[0]["content"]
    assert sent[1]["atlist"] == [ASKER] and "已经转给 Waldo" in sent[1]["content"]


def test_mp_miss_note_goes_to_the_owner_wechat(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    monkeypatch.setattr(config, "OWNER_WXID", OWNER)
    brain = Brain(KB(tmp_path / "kb.sqlite"), http=None, admins={"admin@im.wechat"})
    outs = asyncio.run(brain.handle("mp:openid1", "食堂哪家好吃")) + brain.due_notes(time.time() + 3600)
    assert {o.to for o in outs} == {"mp:openid1", f"pc:{OWNER}"}


def test_watch_reattaches_after_a_logout_and_warns_when_it_lasts(monkeypatch, caplog):
    """MonashGuide logging out (issue seen on 2026-10-11) left group @s unanswered with only INFO lines."""
    clock = [0.0]
    states = [True] + [False] * 8 + [True]                        # logged in, out for about 15 minutes, back
    calls = []

    class Fake:
        async def whoami(self):
            calls.append("whoami")
            if not states.pop(0):
                raise RuntimeError("wxbot: the WeChat account is not logged in")
            return ME

        async def register(self, url):
            calls.append("register")

    async def fake_sleep(seconds):
        if not states:
            raise asyncio.CancelledError
        clock[0] += seconds
    monkeypatch.setattr(pcwx.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(pcwx.time, "monotonic", lambda: clock[0])
    caplog.set_level("INFO", logger="wxbot.pcwx")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pcwx.watch(Fake()))
    assert calls.count("register") == 2                            # once at start, once after the login came back
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings and all("MonashGuide not logged in" in w for w in warnings)
    first_warning = next(i for i, r in enumerate(caplog.records) if r.levelname == "WARNING")
    assert any("not ready" in r.getMessage() for r in caplog.records[:first_warning])   # quiet at first
