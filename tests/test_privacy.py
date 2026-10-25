"""How long students' questions are kept, and deleting one person's data on request (issue #10)."""
import asyncio
import time

import pytest

from wxbot import brain as brain_mod, hub
from wxbot.brain import Brain
from wxbot.kb import KB

ADMIN, USER, OTHER = "admin@im.wechat", "mp:student", "mp:someone_else"
DAY = 86400


@pytest.fixture
def b(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    return Brain(KB(tmp_path / "kb.sqlite"), http=None, admins={ADMIN})


def say(b, who, text):
    return asyncio.run(b.handle(who, text))


def rows(kb: KB, table: str, user: str) -> int:
    return kb.db.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user,)).fetchone()[0]


def test_purge_keeps_recent_rows_open_questions_and_taught_answers(b):
    kb, now = b.kb, time.time()
    kb.log(USER, "老问题", "miss")
    kb.log(USER, "新问题", "miss")
    kb.db.execute("UPDATE log SET at=? WHERE question='老问题'", (now - 100 * DAY,))
    for text, created, delivered in (("送出很久了", 40, 35), ("刚送出", 10, 5), ("没送出但还在期限内", 40, None),
                                     ("没送出也过期了", 100, None)):
        kb.queue_outbox(USER, text)
        kb.db.execute("UPDATE outbox SET created_at=?, delivered_at=? WHERE text=?",
                      (now - created * DAY, now - delivered * DAY if delivered else None, text))
    old_open, old_done, new_done = (kb.add_pending(USER, q) for q in ("老的没答", "老的答了", "新的答了"))
    kb.db.execute("UPDATE pending SET created_at=? WHERE id IN (?,?)", (now - 100 * DAY, old_open, old_done))
    kb.close_pending(old_done, "answered", kb.add_qa("老的答了", "答案"))
    kb.close_pending(new_done, "ignored")

    assert kb.purge(90, 30, now) == {"log": 1, "outbox": 2, "pending": 1}
    assert [r["question"] for r in kb.db.execute("SELECT question FROM log")] == ["新问题"]
    assert {r["text"] for r in kb.db.execute("SELECT text FROM outbox")} == {"刚送出", "没送出但还在期限内"}
    assert {r["id"] for r in kb.db.execute("SELECT id FROM pending")} == {old_open, new_done}
    assert kb.count("qa") == 1                                   # what the owner taught is not users' data


def test_forget_me_deletes_everything_about_the_asker_only(b):
    for who in (USER, OTHER):
        b.kb.touch_contact(who, None)
        say(b, who, "食堂哪家好吃")                             # a miss: log + pending
    b.kb.queue_outbox(USER, "之前的回复")
    reply = say(b, USER, "删除我的数据！")[0].text
    assert reply.startswith("🗑 已经删掉你在这里留下的 4 条记录")
    assert all(rows(b.kb, t, USER) == 0 for t in ("log", "outbox", "pending", "contact"))
    assert rows(b.kb, "log", OTHER) == 1 and rows(b.kb, "pending", OTHER) == 1
    assert say(b, USER, "删除我的数据")[0].text == "这里没有你的记录。"
    assert rows(b.kb, "log", USER) == 0                         # the request itself is not logged either
    # "人工" right after has nothing left to forward
    assert "再发一遍" in say(b, USER, "人工")[0].text


def test_admin_deletes_an_askers_data_by_pending_number(b):
    say(b, USER, "食堂哪家好吃")
    pid = b.kb.open_pending()[0]["id"]
    assert say(b, ADMIN, f"删数据 {pid}")[0].text == "🗑 已删除 公众号用户 student 的 2 条记录"
    assert rows(b.kb, "log", USER) == 0 and not b.kb.open_pending()
    assert "没有待答 #99" in say(b, ADMIN, "删数据 99")[0].text
    assert "删数据" in brain_mod.ADMIN_HELP


def test_deleted_text_does_not_stay_in_the_file(tmp_path):
    kb = KB(tmp_path / "kb.sqlite")
    kb.log(USER, "一个很特别的问题ZQXJ", "miss")
    kb.forget_user(USER)
    kb.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert "ZQXJ".encode() not in (tmp_path / "kb.sqlite").read_bytes()
