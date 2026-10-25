import asyncio
import time

import pytest

from wxbot import brain as brain_mod, config, hub
from wxbot.brain import Brain
from wxbot.kb import KB

ADMIN, USER = "admin@im.wechat", "stranger@im.wechat"


@pytest.fixture
def b(tmp_path, monkeypatch):
    async def no_hub(http, q):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    return Brain(KB(tmp_path / "kb.sqlite"), http=None, admins={ADMIN})


def say(b, who, text):
    return asyncio.run(b.handle(who, text))


def notes(b):
    """The 待答 notes, sent once nothing more has come from the asker for a while."""
    return b.due_notes(time.time() + 3600)


def test_teach_then_answer(b):
    out = say(b, ADMIN, "教 图书馆几点关门 | 晚上十点 | https://www.monash.edu/library")
    assert "#1" in out[0].text
    reply = say(b, USER, "图书馆几点关门？")[0].text
    assert "晚上十点" in reply and "monash.edu/library" in reply


def test_non_admin_cannot_teach(b):
    out = say(b, USER, "教 a | b")
    assert b.kb.count("qa") == 0
    assert not any("记住了" in o.text for o in out if o.to == USER)


def test_miss_escalates_and_answer_flows_back(b):
    out = say(b, USER, "食堂哪家好吃")
    assert {o.to for o in out} == {USER}
    assert [o.to for o in notes(b)] == [ADMIN]
    pid = b.kb.open_pending()[0]["id"]
    out = say(b, ADMIN, f"答 {pid} 推荐 Campus Centre 的越南粉")
    assert {o.to for o in out} == {ADMIN, USER}
    relayed = next(o.text for o in out if o.to == USER)
    assert "越南粉" in relayed and "📘 Monash Hub 上查看更多：https://monashhub.secureview.tech/search?q=" in relayed
    assert not b.kb.open_pending()
    # ... and it is now known.
    assert "越南粉" in say(b, USER, "食堂哪家好吃")[0].text


def test_repeat_miss_does_not_duplicate_pending(b):
    say(b, USER, "食堂哪家好吃")
    say(b, USER, "人工")
    assert len(b.kb.open_pending()) == 1


def test_alias_and_edit(b):
    say(b, ADMIN, "教 怎么在 WES 选课 | 登录 WES 添加")
    assert "没有" not in say(b, ADMIN, "也问 1 WES 怎么加课")[0].text
    assert "登录 WES" in say(b, USER, "WES 怎么加课")[0].text
    assert "✅" in say(b, ADMIN, "不问 1 WES 怎么加课")[0].text
    assert b.kb.phrases(1) == ["怎么在 WES 选课"]
    assert "不能去" in say(b, ADMIN, "不问 1 怎么在 WES 选课")[0].text
    say(b, ADMIN, "也问 1 WES 怎么加课")
    say(b, ADMIN, "改 1 新答案 | https://x.example")
    assert "新答案" in say(b, USER, "WES 怎么加课")[0].text
    say(b, ADMIN, "删 1")
    assert b.kb.count("qa") == 0


def test_greeting_and_rate_limit(b):
    assert "小助手" in say(b, USER, "你好")[0].text
    for _ in range(8):
        say(b, "spam@x", "你好")
    assert say(b, "spam@x", "你好") == []


def _articles(b):
    b.kb.upsert_article("https://mp.weixin.qq.com/s/visa", "马莫百科｜学生签证快到期？续签完整指南",
                        "WAM、出勤率有什么要求？SORS上怎么申请？", "续签 EMGS 护照 签证", None)
    b.kb.upsert_article("https://mp.weixin.qq.com/s/italy", "马莫同学专访｜在意大利上3周课、游玩欧洲6个国家",
                        "Monash 意大利校区课程与国际交换踩坑", "交换 意大利 欧洲 签证 旅行", None)


def test_article_match_prefers_title(b):
    _articles(b)
    assert b.kb.match_articles("学生签证快到期了怎么续签")[0].phrase.startswith("马莫百科｜学生签证")
    assert b.kb.match_articles("想去意大利交换")[0].phrase.startswith("马莫同学专访")


def test_articles_answer_with_link(b):
    _articles(b)
    reply = say(b, USER, "签证续签要注意什么")[0].text
    assert "mp.weixin.qq.com/s/visa" in reply and "/s/italy" not in reply


def test_index_sees_writes_from_another_process(tmp_path):
    path = tmp_path / "kb.sqlite"
    service, cli = KB(path), KB(path)
    assert service.match_qa("图书馆几点关门") == []       # builds and caches the index
    qa = cli.add_qa("图书馆几点关门", "晚上十点")
    assert service.match_qa("图书馆几点关门")[0].id == qa
    cli.add_phrase(qa, "图书馆开到几点")
    assert service.match_qa("图书馆开到几点")[0].score == 1.0


def test_admin_answer_shortcuts(b):
    say(b, USER, "食堂哪家好吃")
    say(b, "other@im.wechat", "健身房几点开")
    first, second = [p["id"] for p in b.kb.open_pending()]
    out = say(b, ADMIN, f"{first} 去 Campus Centre")                     # "N answer"
    assert any(o.to == USER and "Campus Centre" in o.text for o in out)
    out = asyncio.run(b.handle(ADMIN, "早上六点", quoted=f"❓ 待答 #{second}（来自 other）\n健身房几点开"))
    assert any(o.to == "other@im.wechat" and "早上六点" in o.text for o in out)
    assert not b.kb.open_pending()
    # A number that is not an open pending id is still just a question.
    assert "没命中" in say(b, ADMIN, "999 随便说说")[0].text


def test_command_without_space_before_id(b):
    say(b, USER, "食堂哪家好吃")
    pid = b.kb.open_pending()[0]["id"]
    out = say(b, ADMIN, f"答{pid} 去周边商场")
    assert any(o.to == USER and "周边商场" in o.text for o in out)


def test_unit_question_is_not_taken_by_an_unrelated_qa(b, monkeypatch):
    async def hub_answer(http, q, timeout=3.0):
        return hub.HubAnswer("strong", "FIT2004 开课安排", "handbook_offering")
    monkeypatch.setattr(hub, "ask", hub_answer)
    b.kb.add_qa("马来西亚校区开吗", "在 Bandar Sunway")
    b.kb.add_qa("FIT2004 马来西亚开吗", "Waldo 说开")
    assert say(b, USER, "FIT2004 马来西亚开吗")[0].text.startswith("Waldo 说开\n📘")  # taught about this unit: wins
    assert say(b, USER, "FIT1008 马来西亚开吗")[0].text.startswith("FIT2004 开课安排\n📘")


def test_hub_down_does_not_reach_waldo(b, monkeypatch):
    async def down(http, q):
        return hub.HubError("/ask 0")
    monkeypatch.setattr(hub, "ask", down)
    out = say(b, USER, "学生签证怎么续签")
    assert [o.to for o in out] == [USER] and out[0].text == brain_mod.HUB_DOWN
    assert not b.kb.open_pending()


def test_month_and_year_are_not_unit_codes(b):
    assert brain_mod.unit_codes("Nov 2026 什么时候考试") == set()
    assert brain_mod.unit_codes("fit 2004 和 FIT1008") == {"FIT2004", "FIT1008"}
    b.kb.add_qa("Nov 2026 什么时候考试", "11 月 2 日开始")
    assert "11 月 2 日" in say(b, USER, "Nov 2026 什么时候考试")[0].text


def test_greetings_alone_get_the_introduction(b):
    for q in ["你好在吗", "您好！在吗？", "老师您好，请问", "你好呀", "学长你好"]:
        out = say(b, USER, q)
        assert len(out) == 1 and "Monash 问答小助手" in out[0].text, q
    assert not b.kb.open_pending()
    assert not brain_mod.is_greeting("你好，请问学费怎么交")


def test_thanks_and_goodbyes_get_a_short_reply_and_never_reach_the_owner(b):
    cases = {"好的谢谢学长": "不客气", "谢谢！": "不客气", "好的，谢谢": "不客气", "明白了，谢谢老师": "不客气",
             "Thank you so much": "不客气", "辛苦学长了[抱拳]": "不客气", "拜拜": "拜拜", "晚安": "拜拜",
             "看到了": "好的", "好的": "好的", "收到🙏": "好的", "嗯嗯": "好的", "没事了": "好的", "好的我去试试": "好的",
             "那我等你回复": "好的", "👍": "好的", "[强]": "好的", "我去看看再说": "好的",
             # Forwarded to the owner before this change (2026-10-24).
             "OK, OK, 谢谢": "不客气", "行吧 谢谢学长": "不客气", "谢谢呀ww！": "不客气", "哇谢谢！": "不客气",
             "[社会社会]感激不尽": "不客气", "进去了，我看到了谢谢": "不客气", "谢谢☺️": "不客气", "欧克欧克": "好的",
             "真的啊": "好的", "一样的诶": "好的", "不重要啊": "好的"}
    for q, start in cases.items():
        b.recent.clear()                         # not the rate limit's business here
        out = say(b, USER, q)
        assert len(out) == 1 and out[0].to == USER and out[0].text.startswith(start), q
    assert not b.kb.open_pending()
    for q in ["好的，学费怎么交", "谢谢，那签证怎么续签", "可以吗", "我去哪交学费", "你好", "学长好，谢谢", "好了吗"]:
        assert brain_mod.sign_off(q) is None, q


def test_questions_about_the_bot_get_the_introduction(b):
    for q in ["你能干什么", "你会什么", "你是什么大模型", "能问什么", "你是真人吗"]:
        out = say(b, USER, q)
        assert len(out) == 1 and "Monash 问答小助手" in out[0].text, q
    assert not b.kb.open_pending()
    assert "在群里 @我" in say(b, "pc:1@chatroom|wxid_a", "你能干什么")[0].text
    assert not brain_mod.is_about_me("学校有什么功能性课程") and not brain_mod.is_about_me("你能帮我查FIT2102吗")


def test_every_reply_points_to_monash_hub(b, monkeypatch):
    site = "https://monashhub.secureview.tech"
    assert site in say(b, USER, "你好")[0].text
    b.kb.add_qa("图书馆几点关门", "晚上十点")
    assert f"晚上十点\n📘 Monash Hub 上查看更多：{site}/search?q=" in say(b, USER, "图书馆几点关门")[0].text
    miss = say(b, "other@im.wechat", "食堂哪家好吃") + notes(b)
    assert f"{site}/search?q=" in miss[0].text and site not in miss[1].text      # not in the owner's note

    async def pages(http, q):
        return hub.HubAnswer("weak", f"Monash Hub 里找到这些相关的官方页面：\n📘 中文全文：{site}/guides/visa", "official_search")
    monkeypatch.setattr(hub, "ask", pages)
    _articles(b)
    reply = say(b, "third@im.wechat", "学生签证怎么续签")[0].text
    assert "续签完整指南" in reply and f"{site}/guides/visa" in reply           # the article and the Hub's pages


def test_answering_again_corrects_the_answer(b):
    say(b, USER, "食堂哪家好吃")
    pid = b.kb.open_pending()[0]["id"]
    say(b, ADMIN, f"答 {pid} 越南粉")
    out = say(b, ADMIN, f"答 {pid} 改成 Campus Centre 的麻辣烫")
    assert b.kb.count("qa") == 1                                  # corrected, not a second Q&A
    assert any(o.to == USER and "麻辣烫" in o.text for o in out)
    assert "麻辣烫" in say(b, USER, "食堂哪家好吃")[0].text


def test_number_glued_to_words_is_a_question_not_an_answer(b):
    say(b, USER, "食堂哪家好吃")
    say(b, "other@im.wechat", "健身房几点开")
    say(b, "third@im.wechat", "图书馆在哪")
    assert len(b.kb.open_pending()) == 3
    out = say(b, ADMIN, "3门课都挂了怎么办")
    assert [o.to for o in out] == [ADMIN] and "没命中" in out[0].text
    assert len(b.kb.open_pending()) == 3


def _guides(b):
    b.kb.upsert_article("https://mp.weixin.qq.com/s/sites", "马莫百科｜Monash常用网站与系统指南：学习、选课、行政、支持",
                        "学生邮箱・学习平台・课程选课・课表系统・咨询支持", "", None)
    b.kb.upsert_article("https://mp.weixin.qq.com/s/arrival", "马莫百科｜新生入境、报到、缴费、选课全流程指南",
                        "入境指南・校园报到・缴费指南・选课排课", "", None)
    b.kb.upsert_article("https://mp.weixin.qq.com/s/taipei", "马莫百科｜赴台必看：入台证申请条件、材料清单与完整办理指南",
                        "入台证申请条件・材料清单・完整办理流程", "", None)


def test_articles_match_what_students_type(b):
    _guides(b)
    for q, url in [("Moodle怎么用", "/s/sites"), ("怎么交作业", "/s/sites"), ("allocate怎么用", "/s/sites"),
                   ("学费怎么交", "/s/arrival"), ("怎么报到", "/s/arrival"), ("去台湾要什么", "/s/taipei")]:
        top = b.kb.match_articles(q)[0]
        assert top.score >= brain_mod.config.ARTICLE_MIN and b.kb.get_article(top.id)["url"].endswith(url), q
    assert b.kb.match_articles("缴费")                      # one topic word from the titles is enough
    for q in ["我是学生", "指南", "学生卡怎么办", "食堂哪家好吃"]:
        assert not b.kb.match_articles(q), q


def test_miss_points_to_the_mamo_archive(b):
    out = say(b, USER, "食堂哪家好吃")
    assert "https://monashhub.secureview.tech/mamo" in out[0].text
    assert "/mamo" not in next(o.text for o in notes(b) if o.to == ADMIN)


def test_bigrams_do_not_cross_a_stopword():
    from wxbot.kb import tokens
    assert "么申" not in tokens("怎么申请宿舍") and "申请" in tokens("怎么申请宿舍")


def test_misses_sent_together_reach_the_owner_as_one_note(b):
    """2026-10-24: a student's three short messages became three 待答 notes; the owner wants one."""
    b.kb.add_qa("怎么交学费", "在 Finance 页面交")
    first = say(b, USER, "学长，之前我本校和马来这边都一起申请了")
    assert "答不上来" in first[0].text and [o.to for o in first] == [USER]
    assert "在 Finance 页面交" in say(b, USER, "怎么交学费")[0].text            # answered as usual
    assert say(b, USER, "澳大利亚那边的需要管吗？") == []                         # told once already
    assert say(b, USER, "马来这边的我已经交了") == []
    say(b, USER, "好的谢谢学长")                                                 # not context
    assert b.due_notes() == []                                                  # still writing: wait
    rows = b.kb.open_pending()
    assert len(rows) == 1 and rows[0]["parts"] == 3
    out = notes(b)
    assert [o.to for o in out] == [ADMIN]
    assert "3 句）\n学长，之前我本校和马来这边都一起申请了\n澳大利亚那边的需要管吗？\n马来这边的我已经交了\n" in out[0].text
    assert "同一时间还说了（机器人答过）：\n· 怎么交学费\n\n" in out[0].text and "谢谢" not in out[0].text
    assert notes(b) == []                                                       # sent once


def test_a_line_added_after_the_note_is_sent_again_and_the_answer_is_not_learned(b):
    say(b, USER, "澳大利亚那边的需要管吗？")
    notes(b)
    assert "已经补充给" in say(b, USER, "马来这边的我已经交了")[0].text
    out = notes(b)
    assert "有补充，2 句" in out[0].text and "几句合起来的不记成问答" in out[0].text
    pid = b.kb.open_pending()[0]["id"]
    out = say(b, ADMIN, f"答 {pid} 澳洲那边不用管")
    assert any(o.to == USER and "澳大利亚那边的需要管吗？ / 马来这边的我已经交了" in o.text and "不用管" in o.text
               for o in out)
    assert "没有记成问答" in next(o.text for o in out if o.to == ADMIN)
    assert b.kb.count("qa") == 0 and not b.kb.open_pending()


def test_a_miss_long_after_the_last_one_is_a_new_question(b, monkeypatch):
    monkeypatch.setattr(config, "PENDING_MERGE_S", 0)
    say(b, USER, "食堂哪家好吃")
    assert "答不上来" in say(b, USER, "健身房几点开")[0].text
    assert len(b.kb.open_pending()) == 2 and len(notes(b)) == 2


def test_an_old_database_gets_the_new_columns_and_is_not_sent_again(tmp_path):
    import sqlite3
    path = tmp_path / "kb.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE pending (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, question TEXT NOT NULL,"
                " created_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open', qa_id INTEGER)")
    old.execute("INSERT INTO pending(user_id, question, created_at) VALUES ('u', '食堂哪家好吃', 1)")
    old.commit()
    old.close()
    kb = KB(path)
    row = kb.open_pending()[0]
    assert (row["parts"], row["noted"]) == (1, 1)
    assert kb.due_pending(0) == []
