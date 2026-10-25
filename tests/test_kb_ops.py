"""Outbox expiry, the Q&A list, backups and the Q&A export (issues #1, #4, #5)."""
import asyncio
import sqlite3
import sys
import time

from wxbot import __main__ as cli, config, hub, mp
from wxbot.brain import Brain, _waited
from wxbot.kb import KB

ADMIN, USER = "admin@im.wechat", "mp:openid1"
DAY = 86400


def _age(kb, days):
    kb.db.execute("UPDATE outbox SET created_at=created_at-? WHERE delivered_at IS NULL", (days * DAY,))


def test_old_outbox_replies_expire_and_older_ones_carry_their_date(tmp_path):
    kb = KB(tmp_path / "kb.sqlite")
    kb.queue_outbox(USER, "很久以前的回复")
    _age(kb, 40)
    kb.queue_outbox(USER, "上周的回复")
    _age(kb, 5)
    kb.queue_outbox(USER, "刚才的回复")
    assert kb.expired_outbox(config.OUTBOX_DAYS * DAY) == 1
    texts = mp.take_queued(kb, USER)
    assert len(texts) == 2
    assert texts[0].startswith("（") and "日的回复）\n上周的回复" in texts[0]
    assert texts[1] == "刚才的回复"
    assert mp.take_queued(kb, USER) == []                       # delivered once; the expired one never


def test_queued_text_dates():
    now = time.mktime((2026, 10, 9, 12, 0, 0, 0, 0, -1))
    assert mp.queued_texts([(now - 4 * DAY, "答案")], now) == ["（10 月 5 日的回复）\n答案"]
    assert mp.queued_texts([(now - 2 * DAY, "答案")], now) == ["答案"]


def _brain(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    return Brain(KB(tmp_path / "kb.sqlite"), http=None, admins={ADMIN})


def say(b, who, text):
    return asyncio.run(b.handle(who, text))[0].text


def test_list_pages_through_every_qa(tmp_path, monkeypatch):
    b = _brain(tmp_path, monkeypatch)
    assert say(b, ADMIN, "列表") == "还没有教过的问答"
    for n in range(25):
        b.kb.add_qa(f"问题{n}", f"答案{n}")
    b.kb.add_phrase(1, "另一种问法")
    first = say(b, ADMIN, "列表")
    assert first.startswith("问答第 1/2 页，共 25 组") and "#1（命中 0）问题0" in first and "#20（" in first
    assert "另一种问法" not in first and "列表 2" in first
    second = say(b, ADMIN, "列表 2")
    assert "#25（命中 0）问题24" in second and "#1（" not in second and "下一页" not in second
    assert "没有第 3 页" in say(b, ADMIN, "列表 3")


def test_pending_shows_how_long_it_waited(tmp_path, monkeypatch):
    now = time.time()
    assert _waited(now - 3600, now) == "今天"
    assert _waited(now - 2 * DAY, now) == "2 天前"
    assert _waited(now - 5 * DAY, now) == "5 天前 ⏰"
    b = _brain(tmp_path, monkeypatch)
    asyncio.run(b.handle("stranger@im.wechat", "食堂哪家好吃"))
    assert "（stranger，今天）食堂哪家好吃" in say(b, ADMIN, "待答")


def test_stats_count_expired_replies(tmp_path, monkeypatch):
    b = _brain(tmp_path, monkeypatch)
    assert "作废" not in say(b, ADMIN, "统计")
    b.kb.queue_outbox(USER, "x")
    _age(b.kb, 31)
    assert "已作废的回复：1 条" in say(b, ADMIN, "统计")


def test_backup_is_a_working_copy_and_old_ones_are_pruned(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "kb.sqlite")
    kb = KB(config.DB_FILE)
    kb.add_qa("图书馆几点关门", "晚上十点")
    backups = tmp_path / "backups"
    backups.mkdir()
    for n in range(3):
        (backups / f"kb-2026010{n}-000000.sqlite").write_bytes(b"old")
    cli._backup(backups, keep=2)
    files = sorted(backups.glob("kb-*.sqlite"))
    assert len(files) == 2 and files[0].name == "kb-20260102-000000.sqlite"
    copy = sqlite3.connect(files[-1])
    assert copy.execute("SELECT answer FROM qa").fetchone()[0] == "晚上十点"
    assert not list(backups.glob("*.tmp"))


def test_export_has_no_personal_data_and_import_is_idempotent(tmp_path, monkeypatch, capsys):
    src = KB(tmp_path / "a.sqlite")
    qa = src.add_qa("图书馆几点关门", "晚上十点", "https://www.monash.edu/library")
    src.add_phrase(qa, "图书馆开到几点")
    src.add_pending("mp:openid1", "食堂哪家好吃")
    src.touch_contact("mp:openid1", None)
    items = src.export_qa()
    assert items == [{"phrases": ["图书馆几点关门", "图书馆开到几点"], "answer": "晚上十点",
                      "url": "https://www.monash.edu/library", "hits": 0}]
    assert "openid" not in str(items) and "食堂" not in str(items)

    dump = tmp_path / "qa.json"
    monkeypatch.setattr(sys, "argv", ["wxbot", "export-qa"])
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "a.sqlite")
    cli.main()
    dump.write_text(capsys.readouterr().out, encoding="utf-8")
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "b.sqlite")
    monkeypatch.setattr(sys, "argv", ["wxbot", "import-qa", str(dump)])
    cli.main()
    cli.main()                                                  # the same file again adds nothing
    out = capsys.readouterr().out
    assert "added 1 of 1" in out and "added 0 of 1" in out
    dst = KB(tmp_path / "b.sqlite")
    assert dst.count("qa") == 1 and dst.phrases(1) == ["图书馆几点关门", "图书馆开到几点"]
    assert dst.match_qa("图书馆开到几点")[0].id == 1


def test_import_adds_new_phrasings_to_a_pair_already_there(tmp_path):
    kb = KB(tmp_path / "kb.sqlite")
    assert kb.import_qa([{"phrases": ["图书馆几点关门"], "answer": "晚上十点"}]) == (1, 0, 0)
    grown = [{"phrases": ["图书馆几点关门", "图书馆开到几点", "图书馆开到几点"], "answer": "晚上十点"}]
    assert kb.import_qa(grown) == (0, 1, 0) and kb.import_qa(grown) == (0, 0, 0)
    assert kb.count("qa") == 1 and kb.phrases(1) == ["图书馆几点关门", "图书馆开到几点"]


def test_import_replace_updates_the_answer_in_place(tmp_path):
    kb = KB(tmp_path / "kb.sqlite")
    kb.import_qa([{"phrases": ["图书馆几点关门"], "answer": "晚上十点"}])
    kb.hit(1)
    new = [{"phrases": ["图书馆几点关门", "图书馆开到几点"], "answer": "晚上十一点", "url": "https://x.example"}]
    assert kb.import_qa(new) == (1, 0, 0)                      # without replace it is a second pair
    kb.delete_qa(2)
    assert kb.import_qa(new, replace=True) == (0, 1, 1) and kb.import_qa(new, replace=True) == (0, 0, 0)
    row = kb.get_qa(1)
    assert kb.count("qa") == 1 and row["answer"] == "晚上十一点" and row["url"] == "https://x.example"
    assert row["hits"] == 1 and kb.phrases(1) == ["图书馆几点关门", "图书馆开到几点"]
