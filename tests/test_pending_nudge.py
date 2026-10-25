"""The daily reminder about questions nobody answered (issue #3)."""
import asyncio
import time

import pytest

from wxbot import bot as bot_mod, hub
from wxbot.brain import Brain, Out
from wxbot.kb import KB

ADMIN = "admin@im.wechat"
DAY = 86400


@pytest.fixture
def b(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    return Brain(KB(tmp_path / "kb.sqlite"), http=None, admins={ADMIN})


def test_nudge_lists_the_oldest_questions_that_waited_over_a_day(b):
    now = time.time()
    assert bot_mod.nudge_text(b.kb, now) is None
    for n in range(7):
        pid = b.kb.add_pending(f"mp:u{n}", f"没人回的问题{n}")
        b.kb.db.execute("UPDATE pending SET created_at=? WHERE id=?", (now - (n + 2) * DAY, pid))
    fresh = b.kb.add_pending("mp:new", "刚问的")                            # under a day: not nagged about
    b.kb.close_pending(1, "answered")
    text = bot_mod.nudge_text(b.kb, now)
    assert text.startswith("⏰ 有 6 个问题等了超过一天还没回复：\n#2（3 天）没人回的问题1\n")
    assert "#6（7 天）" in text and "…还有 1 个，发「待答」查看" in text and "刚问的" not in text
    assert text.endswith("回复「答 编号 答案」或「忽略 编号」。")
    assert fresh


def test_nudge_goes_to_the_owner_once_a_day(b, monkeypatch):
    sent: list[Out] = []

    async def deliver(outs):
        sent.extend(outs)
    monkeypatch.setattr(bot_mod, "NUDGE_CHECK_S", 0)

    async def one_round():
        task = asyncio.ensure_future(bot_mod.pending_nudge(b, deliver))
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(one_round())
    assert sent == [] and not b.kb.kv_get("pending_nudged")                # nothing waiting: nothing sent
    pid = b.kb.add_pending("mp:u1", "宿舍怎么申请")
    b.kb.db.execute("UPDATE pending SET created_at=? WHERE id=?", (time.time() - 2 * DAY, pid))
    asyncio.run(one_round())
    assert len(sent) == 1 and sent[0].to == ADMIN and "宿舍怎么申请" in sent[0].text
    asyncio.run(one_round())
    assert len(sent) == 1                                                  # not again today
    b.kb.kv_set("pending_nudged", str(int(time.time()) - DAY - 1))
    asyncio.run(one_round())
    assert len(sent) == 2                                                  # tomorrow, while it still waits
