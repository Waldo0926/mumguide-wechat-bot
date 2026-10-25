"""Adding and removing admins from WeChat with a one-time pairing code (issue #4)."""
import asyncio

import pytest

from wxbot import brain as brain_mod, hub
from wxbot.brain import Brain
from wxbot.kb import KB

OWNER, FRIEND, STRANGER = "owner@im.wechat", "pc:wxid_friend", "mp:stranger"


@pytest.fixture
def b(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    return Brain(KB(tmp_path / "kb.sqlite"), http=None, admins={OWNER})


def say(b, who, text):
    return asyncio.run(b.handle(who, text))


def code_from(text: str) -> str:
    return text.split("配对码：")[1][:6]


def test_pairing_adds_an_admin_and_tells_the_owner(b):
    code = code_from(say(b, OWNER, "管理员 配对")[0].text)
    out = say(b, FRIEND, f"配对 {code}")
    assert {o.to for o in out} == {FRIEND, OWNER}
    assert "你现在是管理员" in next(o.text for o in out if o.to == FRIEND)
    assert "用配对码成为了管理员" in next(o.text for o in out if o.to == OWNER)
    assert FRIEND in b.admins and b.kb.kv_get("admins") == FRIEND
    # the new admin can use the commands, and the code cannot be used twice
    assert "记住了" in say(b, FRIEND, "教 图书馆几点关门 | 晚上十点")[0].text
    assert "没有可用的配对码" in say(b, STRANGER, f"配对 {code}")[0].text
    assert STRANGER not in b.admins


def test_wrong_codes_void_the_pairing(b):
    code = code_from(say(b, OWNER, "管理员 配对")[0].text)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(brain_mod.PAIR_MAX_TRIES):
        assert say(b, STRANGER, f"配对 {wrong}")[0].text == "配对码不对。"
    assert "没有可用的配对码" in say(b, STRANGER, f"配对 {code}")[0].text
    assert b.admins == {OWNER}


def test_expired_code_and_group_chats_do_not_pair(b, monkeypatch):
    code = code_from(say(b, OWNER, "管理员 配对")[0].text)
    # in a group the code would be public, so it is not taken there (and nothing is answered about it)
    assert not any("管理员" in o.text for o in say(b, "pc:123@chatroom|wxid_x", f"配对 {code}"))
    real = brain_mod.time.time
    monkeypatch.setattr(brain_mod.time, "time", lambda: real() + brain_mod.PAIR_TTL_S + 1)
    assert "过期" in say(b, FRIEND, f"配对 {code}")[0].text
    assert FRIEND not in b.admins


def test_list_and_remove(b):
    b.owner_pc = "pc:wxid_owner"
    code = code_from(say(b, OWNER, "管理员 配对")[0].text)
    say(b, STRANGER, f"配对 {code}")
    listing = say(b, OWNER, "管理员")[0].text
    assert "1. 公众号用户 stranger（配对加入）" in listing
    assert "2. owner（扫码的主人）" in listing and "3. MonashGuide 私聊 wxid_owner（WXBOT_OWNER_WXID）" in listing
    assert "不能在这里删" in say(b, OWNER, "管理员 删 2")[0].text
    assert "没有第 9 个" in say(b, OWNER, "管理员 删 9")[0].text
    assert "已删除管理员" in say(b, OWNER, "管理员 删 1")[0].text
    assert STRANGER not in b.admins and b.kb.kv_get("admins") == ""
    assert "记住了" not in say(b, STRANGER, "教 a | b")[0].text


def test_notes_skip_admins_on_the_official_account(b):
    b.admins.add(STRANGER)
    b.admins.add(FRIEND)
    assert b.note_targets() == [OWNER, FRIEND]
