import asyncio

import pytest

from wxbot import brain as brain_mod, hub
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
    assert {o.to for o in out} == {USER, ADMIN}
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


def test_questions_about_the_bot_get_the_introduction(b):
    for q in ["你能干什么", "你会什么", "你是什么大模型", "能问什么", "你是真人吗"]:
        out = say(b, USER, q)
        assert len(out) == 1 and "Monash 问答小助手" in out[0].text, q
    assert not b.kb.open_pending()
    assert not brain_mod.is_about_me("学校有什么功能性课程") and not brain_mod.is_about_me("你能帮我查FIT2102吗")


def test_every_reply_points_to_monash_hub(b, monkeypatch):
    site = "https://monashhub.secureview.tech"
    assert site in say(b, USER, "你好")[0].text
    b.kb.add_qa("图书馆几点关门", "晚上十点")
    assert f"晚上十点\n📘 Monash Hub 上查看更多：{site}/search?q=" in say(b, USER, "图书馆几点关门")[0].text
    miss = say(b, "other@im.wechat", "食堂哪家好吃")
    assert f"{site}/search?q=" in miss[0].text and site not in miss[1].text      # not in the owner's note

    async def pages(http, q):
        return hub.HubAnswer("weak", f"Monash Hub 里找到这些相关的官方页面：\n📘 中文全文：{site}/guides/visa", "official_search")
    monkeypatch.setattr(hub, "ask", pages)
    _articles(b)
    reply = say(b, "third@im.wechat", "学生签证怎么续签")[0].text
    assert "续签完整指南" in reply and f"{site}/guides/visa" in reply           # the article and the Hub's pages
