"""Synonyms, the 未命中 report and the weekly digest (issue #8)."""
import asyncio
import time

import pytest

from wxbot import bot as bot_mod, config, hub
from wxbot.brain import Brain
from wxbot.kb import KB

ADMIN, USER = "admin@im.wechat", "mp:openid1"
DAY = 86400


@pytest.fixture
def b(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    return Brain(KB(tmp_path / "kb.sqlite"), http=None, admins={ADMIN})


def say(b, who, text):
    return asyncio.run(b.handle(who, text))[0].text


# ---- synonyms --------------------------------------------------------------------------------------

def test_synonyms_make_a_question_in_other_words_match(b):
    b.kb.add_qa("学生签证怎么续签", "SORS 上申请")
    assert b.kb.match_qa("visa怎么续签")[0].score < config.QA_STRONG      # a different word: unsure at best
    assert "签证 = visa = emgs" in say(b, ADMIN, "同义词 签证=visa=EMGS")
    assert b.kb.match_qa("visa怎么续签")[0].score >= config.QA_STRONG
    assert "SORS" in say(b, USER, "EMGS怎么续签")
    assert b.kb.rewrite("my VISA 和 emgs") == "my  签证  和  签证 "
    # Listing, joining a group through a shared word, and removing one word.
    assert "· 签证 = visa = emgs" in say(b, ADMIN, "同义词")
    assert say(b, ADMIN, "同义词 visa=学生签证") == "✅ 这些词现在算同一个词：签证 = visa = emgs = 学生签证"
    assert say(b, ADMIN, "同义词 删 emgs") == "🗑 已移除同义词 emgs"
    assert b.kb.synonyms() == [["签证", "visa", "学生签证"]]
    assert "没有同义词" in say(b, ADMIN, "同义词 删 emgs")
    assert "至少两个词" in say(b, ADMIN, "同义词 签证")


def test_chinese_synonym_is_one_token(b):
    b.kb.add_qa("M-Pass怎么申请", "在 Let's Begin 上传照片")
    assert b.kb.match_qa("学生卡怎么申请")[0].score < config.QA_WEAK          # 申请 alone
    b.kb.add_synonyms(["m-pass", "学生卡", "mpass"])
    assert b.kb.match_qa("学生卡怎么申请")[0].score >= config.QA_STRONG
    assert b.kb.match_qa("mpass怎么申请")[0].score >= config.QA_STRONG
    assert b.kb.match_qa("学生怎么申请")[0].score < config.QA_STRONG         # 学生 alone is not 学生卡


def test_synonyms_added_by_another_process_are_picked_up(tmp_path):
    path = tmp_path / "kb.sqlite"
    service, cli = KB(path), KB(path)
    service.add_qa("学生签证怎么续签", "SORS")
    assert service.match_qa("visa怎么续签")[0].score < config.QA_STRONG
    cli.add_synonyms(["签证", "visa"])
    assert service.match_qa("visa怎么续签")[0].score >= config.QA_STRONG


# ---- 未命中 -------------------------------------------------------------------------------------------

def test_near_miss_report_names_the_qa_almost_hit_and_the_phrase_to_add(b):
    b.kb.add_qa("怎么申请住宿", "在 Residential Services 网站申请")
    b.kb.add_qa("学费怎么交", "WES 里交")
    assert say(b, ADMIN, "未命中") == "近 7 天每个问题都答上了 👍"
    for _ in range(3):
        say(b, USER, "宿舍申请要多少钱")                     # a near miss of #1, three times
    say(b, "mp:openid2", "食堂几点开")                       # a plain miss
    say(b, "mp:openid3", "学费多少钱")                       # answered unsurely (你问的是不是…)
    report = say(b, ADMIN, "未命中")
    assert report.startswith("近 7 天答不上来的问题（按次数）：\n· 3× 宿舍申请要多少钱，差一点命中 #1「怎么申请住宿」(0.")
    assert "可以发「也问 1 宿舍申请要多少钱」" in report
    assert "· 1× 食堂几点开\n" in report and "食堂几点开，差" not in report
    assert "拿不准才回答的（回了“你问的是不是…”）：\n· 1× 学费多少钱 → #2「学费怎么交」(0." in report
    # Once taught, the report says so instead of suggesting a phrasing.
    say(b, ADMIN, "也问 1 宿舍申请要多少钱")
    assert "· 3× 宿舍申请要多少钱，现在能答了（#1）" in say(b, ADMIN, "未命中 30")
    # Only the asked-for window counts.
    b.kb.db.execute("UPDATE log SET at=at-?", (8 * DAY,))
    assert say(b, ADMIN, "未命中") == "近 7 天每个问题都答上了 👍"
    assert "食堂几点开" in say(b, ADMIN, "未命中 30")


def test_near_miss_report_fits_a_message(b):
    for n in range(30):
        say(b, f"mp:u{n}", f"没人知道的问题{n}")
    report = say(b, ADMIN, "未命中")
    assert report.count("\n") <= 13                            # at most 10 misses listed


# ---- the weekly digest ------------------------------------------------------------------------------

def _at(wday, hour):
    base = time.mktime((2026, 10, 19, hour, 0, 0, 0, 0, -1))   # 2026-10-19 is a Monday
    return base + wday * DAY


def test_digest_is_due_monday_morning_once():
    assert not bot_mod.digest_due(_at(0, 8), "")                 # too early
    assert bot_mod.digest_due(_at(0, 9), "")                     # never sent
    assert bot_mod.digest_due(_at(0, 23), str(int(_at(0, 9) - 7 * DAY)))
    assert not bot_mod.digest_due(_at(0, 10), str(int(_at(0, 9))))   # sent an hour ago
    assert not bot_mod.digest_due(_at(2, 9), "")                 # Wednesday


def test_digest_goes_to_the_owner_only_when_there_were_misses(b, monkeypatch):
    sent = []

    async def deliver(outs):
        sent.extend(outs)
    monkeypatch.setattr(bot_mod, "DIGEST_CHECK_S", 0)
    monkeypatch.setattr(bot_mod, "digest_due", lambda now, last: not last)

    async def one_round():
        task = asyncio.ensure_future(bot_mod.weekly_digest(b, deliver))
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(one_round())
    assert sent == [] and b.kb.kv_get("digest_sent")              # a quiet week: nothing sent, still marked
    say(b, USER, "食堂几点开")
    b.kb.kv_set("digest_sent", "")
    asyncio.run(one_round())
    assert [o.to for o in sent] == [ADMIN] and sent[0].text.startswith("📊 本周小结\n近 7 天答不上来的问题")
