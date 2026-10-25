"""The optional RAG answer (wxbot/rag.py, llm.py, Brain.answer) against a fake chat-model server: the model
is never called for real, and the ways it can go wrong are covered (slow, failing, quoting nothing, quoting
what the passages do not say)."""
import asyncio
import time

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from wxbot import config, hub, llm, rag
from wxbot.brain import Brain
from wxbot.chunks import Chunks, Doc
from wxbot.kb import KB
from wxbot.rag import NOTE, Rag, ground
from wxbot.retrieve import Hit, Retriever

ADMIN, USER, MP_USER = "admin@im.wechat", "stranger@im.wechat", "mp:openid123"
VISA_URL = "https://www.monash.edu.my/visa-renewal"


def hit(i, source="hub_faq", url=None, title="t", text=None):
    return Hit(i, source, str(i), url, title, text or f"第 {i} 段资料的原文。", 0.0)


def test_ground_sends_quotes_found_word_for_word_with_their_pages_renumbered():
    hits = [hit(1, "hub_guide", url="https://a", text="续签要在签证到期前三个月提交。"),
            hit(2, "qa", None, "宿舍怎么申请", "答：去 Monash Residence 官网申请住宿。"),
            hit(3, "article", "https://mp.weixin.qq.com/s/x", text="先在 EMGS 网站\n交申请，再等邮件通知。")]
    text, why = ground("[3] 先在 EMGS 网站交申请\n[1] 「续签要在签证到期前三个月提交」\n[9] 还有别的", hits)
    assert why == "ok cut 1"                    # [9] names no passage given
    body, sources = text.split("\n\n参考：\n")
    # Each quote is sent as the whole sentence it is in.
    assert body == "资料原文：\n「先在 EMGS 网站交申请，再等邮件通知。」[1]\n「续签要在签证到期前三个月提交。」[2]"
    assert sources.splitlines()[:4] == ["[1] 马莫百科：t", "https://mp.weixin.qq.com/s/x", "[2] 官网：t", "https://a"]
    assert sources.endswith(NOTE)
    assert ground("[2] 去 Monash Residence 官网申请住宿", hits)[0].endswith(
        "「去 Monash Residence 官网申请住宿。」[1]\n\n参考：\n[1] 问答 #2：宿舍怎么申请\n" + NOTE)


def test_ground_lists_two_chunks_of_one_page_once():
    url = "https://mp.weixin.qq.com/s/visa"
    hits = [hit(1, "article", url, "续签指南", "最早提前约3个月提交。"), hit(2, "article", url, "续签指南", "一学期 18-24 学分。")]
    text, why = ground("[1] 最早提前约3个月提交\n[2] 一学期 18-24 学分", hits)
    assert why == "ok" and text.startswith("资料原文：\n「最早提前约3个月提交。」[1]\n「一学期 18-24 学分。」[1]\n\n参考：\n"
                                           "[1] 马莫百科：续签指南\n" + url + "\n")


def test_a_quote_that_is_not_in_its_passage_is_never_sent():
    hits = [hit(1, url="https://a", text="请在 Moodle 上传作业，并在三个工作日内提交医生证明。"),
            hit(2, url="https://b", text="ISP 会在贴纸剩 14 天或更少时收护照。")]
    # A paraphrase, an added step, and a quote put on the wrong passage.
    assert ground("[1] 老师收到证明后会替你申请特殊考虑\n[2] 过期后有 14 天宽限期", hits) == (None, "unsupported")
    assert ground("[2] 请在 Moodle 上传作业", hits) == (None, "unsupported")
    text, why = ground("[1] 请在 Moodle 上传作业，并在三个工作日内提交医生证明。\n[1] 老师会替你申请特殊考虑", hits)
    assert why == "ok cut 1" and "老师" not in text
    assert ground("[1] 上传", hits) == (None, "unsupported")       # too short to say anything


def test_ground_reads_the_formats_models_write_and_keeps_four_quotes():
    hits = [hit(1, text="满分是 4.0，按学分加权平均。第二句话在这里。第三句话在这里。第四句话在这里。第五句话在这里。")]
    assert ground("【1†L9-L12】 满分是 4.0", hits)[1] == "ok"
    assert ground("- [1]：“满分是 4.0”[1]", hits)[0].startswith("资料原文：\n「满分是 4.0，按学分加权平均。」[1]\n")
    text, why = ground("[1] 满分是 4.0\n[1] 第二句话在这里\n[1] 第三句话在这里\n[1] 第四句话在这里\n[1] 第五句话在这里\n[1] 满分是 4.0", hits)
    assert why == "ok cut 1" and text.count("「") == 4 and "第五" not in text


def test_a_sentence_that_needs_what_is_around_it_is_not_sent():
    renew = hit(1, url="https://a", title="续签", text=(
        "续签\n最早可在到期前约 3 个月提交续签申请。\n如果你没有满足上述任何一项要求：\n"
        "· 你必须在你学生签证（Student Pass）和/或i-Kad到期前四个月提交续签申请；并且\n· 你必须联系 ISP。"))
    faq = hit(2, "hub_guide", url="https://b", title="补考", text="补考\n常见问题\n· 不，你必须使用补考申请表进行申请。")
    cancel = hit(3, url="https://c", title="取消签证", text="取消签证\n此流程也适用于你前往休学的情况。\n续签需要同时满足以下要求：\n· 成绩要求 WAM 至少 50。")
    hits = [renew, faq, cancel]
    # The deadline without the condition above it told everyone to apply four months ahead.
    text, why = ground("[1] 最早可在到期前约 3 个月提交续签申请\n[1] 你必须在你学生签证（Student Pass）和/或i-Kad到期前四个月提交续签申请", hits)
    assert why == "ok cut 1" and "四个月" not in text
    assert ground("[1] 你必须联系 ISP", hits) == (None, "fragment")              # a list item under a condition
    assert ground("[2] 你必须使用补考申请表进行申请", hits) == (None, "fragment")   # "不，" answers a question not shown
    assert ground("[3] 也适用于你前往休学的情况\n[3] 成绩要求 WAM 至少 50", hits) == (None, "fragment")
    assert ground("[1] 如果你没有满足上述任何一项要求", hits) == (None, "fragment")
    # "可以，" right after "答：" answers the question in the title of a taught Q&A or an FAQ.
    pause = hit(4, "hub_faq", url="https://www.monash.edu/x", title="可以休学吗", text="可以休学吗\n答：可以，这叫 intermission（休学）。")
    assert ground("[1] 可以，这叫 intermission（休学）", [pause])[0].startswith("资料原文：\n「可以，这叫 intermission（休学）。」[1]")
    # A question from the passage is not an answer.
    table = hit(5, "article", url="https://mp.weixin.qq.com/s/t", title="交换", text="交换\n多数项目按一学期规划\n最后一学期可以交换吗？")
    assert ground("[1] 多数项目按一学期规划", [table]) == (None, "fragment")


def test_taught_answers_and_the_faq_are_not_mixed_with_guide_pages():
    qa = hit(1, "qa", "https://www.monash.edu/exams/supplementary", "挂了一门有补考吗",
             "问：挂了一门有补考吗\n答：45 到 49 分自动有补考，不用申请也不能申请。")
    old = hit(2, "hub_guide", "https://www.monash.edu.my/business/faq", "商学院 FAQ",
              "商学院 FAQ\n如果你符合补考的资格要求，你必须选择参加考核。")
    assert not rag.australian(qa)
    text, why = ground("[1] 45 到 49 分自动有补考，不用申请也不能申请\n[2] 如果你符合补考的资格要求，你必须选择参加考核", [qa, old])
    assert why == "ok cut 1" and "必须选择" not in text
    assert ground("[2] 如果你符合补考的资格要求，你必须选择参加考核", [qa, old])[1] == "ok"


def test_a_malaysia_page_is_kept_next_to_the_hub_faq_but_not_next_to_a_taught_answer():
    my = hit(1, "hub_guide", "https://www.monash.edu.my/student-services/international-students/during-your-studies", "During Your Studies",
             "During Your Studies\n非医疗原因休学的，休学期间必须注销 Student Pass 并离开马来西亚。")
    faq = hit(2, "hub_faq", "https://www.monash.edu/students/admin/enrolments/change/intermission", "可以休学一个学期吗？",
              "可以休学一个学期吗？\n答：可以，这叫 intermission（休学）。")
    qa = hit(3, "qa", None, "休学会影响学生签证吗", "问：休学会影响学生签证吗\n答：先联系 ISP Helpdesk 再申请休学。")
    text, why = ground("[2] 可以，这叫 intermission（休学）\n[1] 非医疗原因休学的，休学期间必须注销 Student Pass 并离开马来西亚", [my, faq])
    assert why == "ok" and "注销 Student Pass" in text
    text, why = ground("[3] 先联系 ISP Helpdesk 再申请休学\n[1] 非医疗原因休学的，休学期间必须注销 Student Pass 并离开马来西亚", [my, faq, qa])
    assert why == "ok cut 1" and "注销" not in text


def test_a_table_row_or_a_past_year_is_not_sent(monkeypatch):
    finals = hit(1, "hub_guide", "https://www.monash.edu/students/admin/assessments/dates-timetables/finals", "期末考核日期",
                 "期末考核日期\n10 月入学（马来西亚） | OCT-MY-01 | 2025年1月6日 | 2025年2月3日至14日\n"
                 "期末考核期一般在每学期末。\n自 2022 年起改为线上考试。\n2027 年起考试周提前一周。\n"
                 "2025 年 3 月 1 日起实行新规，过渡期到 2026 年 12 月 31 日。")
    monkeypatch.setattr(rag.time, "localtime", lambda *a: time.struct_time((2026, 10, 24, 0, 0, 0, 5, 297, 0)))
    assert ground("[1] 10 月入学（马来西亚） | OCT-MY-01 | 2025年1月6日", [finals]) == (None, "fragment")
    assert ground("[1] 自 2022 年起改为线上考试", [finals]) == (None, "fragment")
    assert ground("[1] 2027 年起考试周提前一周", [finals])[1] == "ok"
    assert ground("[1] 期末考核期一般在每学期末", [finals])[1] == "ok"
    # A rule that started in a past year and still runs is kept.
    assert ground("[1] 2025 年 3 月 1 日起实行新规，过渡期到 2026 年 12 月 31 日", [finals])[1] == "ok"


def test_a_sentence_sending_students_to_ask_mira_is_not_sent():
    page = hit(1, "hub_guide", "https://www.monash.edu.my/sass/faqs", "SASS 常见问题",
               "SASS 常见问题\n通过 AskMira 联系学位课程顾问。\n线上 Ask Mira 提交工单。\n学位课程顾问可以帮你规划选课。")
    assert ground("[1] 通过 AskMira 联系学位课程顾问", [page]) == (None, "fragment")
    assert ground("[1] 线上 Ask Mira 提交工单", [page]) == (None, "fragment")
    assert ground("[1] 学位课程顾问可以帮你规划选课", [page])[1] == "ok"


def test_an_article_sentence_stops_at_a_checklist_mark_or_a_section_number():
    art = hit(1, "article", "https://mp.weixin.qq.com/s/v", "续签", "续签\n可以继续看《交换指南》\n10｜最后把重点压缩成一张清单\n"
              "✓ 最早可提前约 3 个月提交续签\n✓ Coursework：WAM 至少 50")
    text, why = ground("[1] 最早可提前约 3 个月提交续签", [art])
    assert why == "ok" and text.startswith("资料原文：\n「最早可提前约 3 个月提交续签」[1]\n")


def test_an_article_sentence_broken_over_lines_is_sent_whole():
    art = hit(1, "article", "https://mp.weixin.qq.com/s/x", "交换", "交换\n多数项目按一学期\n算。一学期通常对应\n18–24\n个\nMonash\n学分。\n下一段")
    text, why = ground("[1] 一学期通常对应", [art])
    assert why == "ok" and text.startswith("资料原文：\n「一学期通常对应18–24个Monash学分。」[1]\n")
    assert ground("[1] 多数项目按一学期", [art])[0].startswith("资料原文：\n「多数项目按一学期算。」[1]\n")


def test_what_is_about_australia_comes_last_under_its_own_heading():
    au = hit(1, "hub_guide", url="https://www.monash.edu/students/admin/change-documents", title="医疗证明",
             text="医疗证明\n如果你在校园内，你可以在大学健康服务处预约医疗证明。")
    oshc = hit(2, "hub_guide", url="https://www.monash.edu/oshc", title="保险", text="保险\n对于不持学生签证的海外访客，我们强烈建议自行购买在澳期间的个人医疗保险。")
    my = hit(3, "hub_guide", url="https://www.monash.edu.my/health", title="健康", text="健康\n校内诊所可以开具医疗证明。")
    policy = hit(4, "hub_guide", url="https://www.monash.edu/policy-bank/x", title="政策", text="政策\n特殊考虑要在截止后两个工作日内申请。")
    assert rag.australian(au) and not rag.australian(my) and not rag.australian(policy)
    au_heading = rag.HEADINGS["au"]
    # Only Australia: the heading says so, and so does the source line.
    text, why = ground("[1] 如果你在校园内，你可以在大学健康服务处预约医疗证明", [au, oshc, my, policy])
    assert why == "ok" and text.startswith(f"资料原文：\n{au_heading}\n「如果你在校园内") and "（澳洲校区页面，马来西亚校区可能不同）" in text
    # Both: Malaysia first, then Australia under its heading, whatever order the model wrote them in.
    text, why = ground("[1] 如果你在校园内，你可以在大学健康服务处预约医疗证明\n[3] 校内诊所可以开具医疗证明\n[4] 特殊考虑要在截止后两个工作日内申请",
                       [au, oshc, my, policy])
    assert why == "ok"
    assert text.index(rag.HEADINGS["my"]) < text.index("校内诊所") < text.index(rag.HEADINGS["all"]) < text.index("特殊考虑") \
        < text.index(au_heading) < text.index("大学健康服务处")
    # A sentence about Australia on any page goes under the Australian heading.
    text, why = ground("[2] 我们强烈建议自行购买在澳期间的个人医疗保险", [au, oshc, my])
    assert why == "ok" and au_heading in text
    assert "澳洲校区" in rag.messages("q", [au, my])[1]["content"]
    # No heading when nothing is about Australia.
    text, why = ground("[4] 特殊考虑要在截止后两个工作日内申请", [au, oshc, my, policy])
    assert why == "ok" and "：\n「" in text and not any(h in text for h in rag.HEADINGS.values())
    # "在澳洲以外的校区" is about this campus.
    abroad = hit(5, "hub_guide", url="https://www.monash.edu.my/hurdles", title="Hurdle",
                 text="Hurdle\n在澳洲以外的校区（比如马来西亚），hurdle 规则相同。\nStudents outside Australia follow the same rule.")
    for quote in ("在澳洲以外的校区（比如马来西亚），hurdle 规则相同", "Students outside Australia follow the same rule"):
        text, why = ground(f"[1] {quote}", [abroad])
        assert why == "ok" and au_heading not in text
    # Words only the Australian campuses use count as Australian, even in the Hub's FAQ.
    faq = hit(6, "hub_faq", url="https://www.monash.edu/students/admin/enrolments/change/intermission", title="可以休学一个学期吗？",
              text="可以休学一个学期吗？\n答：可以，这叫 intermission（休学）。\n持学生签证的国际学生要在申请前先确认对签证的影响，因为休学会改变你的 CoE。\n"
                   "OSHC 要一直有效。\nCOE 和 coe 不是这个词。")
    text, why = ground("[1] 可以，这叫 intermission（休学）\n[1] 持学生签证的国际学生要在申请前先确认对签证的影响，因为休学会改变你的 CoE", [faq])
    assert why == "ok" and text.index("intermission") < text.index(au_heading) < text.index("CoE")
    assert au_heading in ground("[1] OSHC 要一直有效", [faq])[0]
    assert au_heading not in ground("[1] COE 和 coe 不是这个词", [faq])[0]

def test_ground_drops_a_reply_with_no_quote_or_no_answer():
    hits = [hit(1)]
    assert ground("签证可以在网上续签。", hits) == (None, "uncited")
    assert ground("这个我不确定。", hits) == (None, "unsure")
    assert ground("这个我不确定[1]。", hits) == (None, "unsure")
    assert ground("", hits) == (None, "unsure")


class FakeLLM:
    def __init__(self):
        self.reply = "[1] 签证到期前三个月在 EMGS 网站提交续签申请"
        self.delay = 0.0
        self.status = 200
        self.requests = []

    def app(self):
        async def completions(request):
            body = await request.json()
            self.requests.append((request.headers.get("Authorization"), body))
            await asyncio.sleep(self.delay)
            if self.status != 200:
                return web.json_response({"error": {"message": "rate limited"}}, status=self.status)
            return web.json_response({"choices": [{"message": {"content": self.reply}}],
                                      "usage": {"prompt_tokens": 300, "completion_tokens": 40}})
        app = web.Application()
        app.router.add_post("/v1/chat/completions", completions)
        return app


@pytest.fixture
def kb(tmp_path, monkeypatch):
    async def no_hub(http, q, **kw):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    monkeypatch.setattr(hub.guides, "refresh_soon", lambda http: None)
    monkeypatch.setattr(config, "LLM_KEY", "test-key")
    kb = KB(tmp_path / "kb.sqlite")
    kb.add_qa("宿舍怎么申请", "去 Monash Residence 官网申请住宿。")
    Chunks(kb).sync("hub_faq", [Doc("hub_faq", "visa", 0, VISA_URL, "学生签证怎么续签",
                                    "答：签证到期前三个月在 EMGS 网站提交续签申请，带护照。")])
    return kb


def run(kb, llm_server, steps, monkeypatch):
    """Run `steps(brain)` with a Brain whose RAG answer talks to the fake model."""
    async def go():
        async with TestServer(llm_server.app()) as server:
            monkeypatch.setattr(config, "LLM_BASE", f"http://127.0.0.1:{server.port}/v1")
            async with aiohttp.ClientSession() as http:
                brain = Brain(kb, http, {ADMIN}, Rag(kb, http, Retriever(kb)))
                return await steps(brain)
    return asyncio.run(go())


def test_a_question_the_rules_miss_is_answered_from_the_passages_with_sources(kb, monkeypatch):
    fake = FakeLLM()

    async def steps(b):
        return await b.handle(USER, "学生签证怎么续签"), b.kb.db.execute("SELECT route, detail FROM log").fetchone()
    outs, (route, detail) = run(kb, fake, steps, monkeypatch)
    assert [o.to for o in outs] == [USER]           # nothing forwarded to the owner
    text = outs[0].text
    assert text.startswith("资料原文：\n「签证到期前三个月在 EMGS 网站提交续签申请，带护照。」[1]\n\n参考：\n"
                           "[1] 官方 FAQ：学生签证怎么续签\n" + VISA_URL)
    assert NOTE in text and config.HUB_SITE in text
    assert route == "rag" and detail.startswith("chunks ") and " ok 340t " in detail
    auth, body = fake.requests[0]
    assert auth == "Bearer test-key" and body["model"] == "glm-4-flash" and body["temperature"] == 0
    assert "[1] 官方 FAQ《学生签证怎么续签》" in body["messages"][1]["content"]


def test_the_hub_links_go_under_the_sources_even_when_a_quote_has_a_link(kb, monkeypatch):
    Chunks(kb).sync("hub_faq", [Doc("hub_faq", "fees", 0, "https://www.monash.edu.my/fees", "学费怎么交",
                                    "答：学费在 https://www.monash.edu.my/pay 网上缴纳。")])
    fake = FakeLLM()
    fake.reply = "[1] 学费在 https://www.monash.edu.my/pay 网上缴纳"
    monkeypatch.setattr(hub.guides, "link", lambda url: f"{config.HUB_SITE}/guides/x?u={url[-3:]}")

    async def steps(b):
        return await b.answer("学费怎么交")
    reply, route, _ = run(kb, fake, steps, monkeypatch)
    quoted, sources = reply.split("\n\n参考：\n")
    assert route == "rag" and "📘" not in quoted and "📘" in sources


def test_the_same_question_again_comes_from_the_cache(kb, monkeypatch):
    fake = FakeLLM()

    async def steps(b):
        first = await b.answer("学生签证怎么续签？")
        second = await b.answer("学生签证 怎么续签")
        return first, second
    first, second = run(kb, fake, steps, monkeypatch)
    assert len(fake.requests) == 1
    # Only the Hub search link at the end differs: it is built from the question as typed.
    assert second[0].split("📘")[0] == first[0].split("📘")[0] and second[2].endswith(" cached")


def test_an_answer_cached_before_the_prompt_changed_is_not_reused(kb, monkeypatch):
    fake = FakeLLM()

    async def steps(b):
        await b.answer("学生签证怎么续签")
        monkeypatch.setattr(rag, "SYSTEM", rag.SYSTEM + "\n6. 新规则。")
        return await b.answer("学生签证怎么续签")
    reply, route, detail = run(kb, fake, steps, monkeypatch)
    assert len(fake.requests) == 2 and not detail.endswith("cached")


def test_a_slow_model_falls_back_to_the_rules_and_fills_the_cache_for_next_time(kb, monkeypatch):
    fake = FakeLLM()
    fake.delay = 0.6
    monkeypatch.setattr(config, "LLM_TIMEOUT", 0.2)

    async def steps(b):
        outs = await b.handle(USER, "学生签证怎么续签")
        await asyncio.sleep(0.8)            # the call goes on in the background
        later = await b.answer("学生签证怎么续签")
        return outs, later
    outs, later = run(kb, fake, steps, monkeypatch)
    assert {o.to for o in outs} == {USER} and kb.open_pending()      # the usual 待答 forward
    assert "答不上来" in outs[0].text
    detail = kb.db.execute("SELECT detail FROM log WHERE route='miss'").fetchone()[0]
    assert "rag chunks" in detail and "timeout" in detail
    assert later[1] == "rag" and later[2].endswith("cached") and len(fake.requests) == 1


def test_a_reply_in_its_own_words_is_not_shown(kb, monkeypatch):
    fake = FakeLLM()
    fake.reply = "签证一般可以在网上续签，记得早点办。"

    async def steps(b):
        return await b.answer("学生签证怎么续签")
    reply, route, detail = run(kb, fake, steps, monkeypatch)
    assert reply is None and route == "miss" and "uncited" in detail


def test_a_failing_model_is_not_cached(kb, monkeypatch):
    fake = FakeLLM()
    fake.status = 429

    async def steps(b):
        first = await b.answer("学生签证怎么续签")
        fake.status = 200
        second = await b.answer("学生签证怎么续签")
        return first, second
    first, second = run(kb, fake, steps, monkeypatch)
    assert first[0] is None and "error" in first[2]
    assert second[1] == "rag" and len(fake.requests) == 2


def test_a_strong_taught_answer_and_a_unit_question_never_call_the_model(kb, monkeypatch):
    fake = FakeLLM()

    async def steps(b):
        return await b.answer("宿舍怎么申请"), await b.answer("FIT2004 学生签证怎么续签")
    (qa_reply, qa_route, _), (_, unit_route, _) = run(kb, fake, steps, monkeypatch)
    assert qa_route == "qa" and "Monash Residence" in qa_reply
    assert unit_route == "miss" and fake.requests == []


def test_a_weak_rule_answer_on_the_public_account_only_waits_for_the_reply_budget(kb, monkeypatch):
    from wxbot import brain as brain_mod
    kb.add_qa("签证续签要等多久才能拿到新签证", "大约两到四周。")
    fake = FakeLLM()
    fake.delay = 1.0
    monkeypatch.setattr(brain_mod, "MP_BUDGET_S", 0.7)

    async def steps(b):
        return await b.answer("签证续签", brain_mod.MP_BUDGET_S), await b.answer("签证续签")
    (mp_reply, mp_route, mp_detail), (reply, route, _) = run(kb, fake, steps, monkeypatch)
    assert mp_route == "qa" and "你问的是不是" in mp_reply and "timeout" in mp_detail
    assert route == "rag"                   # elsewhere it may wait for the model (and the cache has it now)


def test_a_weak_rule_answer_is_withheld_when_the_model_finds_no_answer_in_the_passages(kb, monkeypatch):
    kb.add_qa("签证续签要等多久才能拿到新签证", "大约两到四周。")
    fake = FakeLLM()
    fake.reply = "这个我不确定。"

    async def steps(b):
        outs = await b.handle(USER, "签证续签")
        again = await b.answer("签证续签")          # from the cache: still withheld
        fake.status = 500
        failing = await b.answer("签证续签 要多久")    # a failing model still falls back to the rules
        return outs, again, failing
    outs, again, failing = run(kb, fake, steps, monkeypatch)
    assert {o.to for o in outs} == {USER} and kb.open_pending() and "答不上来" in outs[0].text   # the usual 待答
    route, detail = kb.db.execute("SELECT route, detail FROM log").fetchone()
    assert route == "miss" and "(weak)" in detail and "unsure" in detail
    assert again[0] is None and again[2].endswith("cached")
    assert failing[1] == "qa" and "你问的是不是" in failing[0] and "error" in failing[2]


def test_a_reply_with_no_quote_from_the_passages_goes_to_the_owner(kb, monkeypatch):
    kb.add_qa("签证续签要等多久才能拿到新签证", "大约两到四周。")
    fake = FakeLLM()
    fake.reply = "[1] 签证到期后还有 14 天宽限期"

    async def steps(b):
        return await b.handle(USER, "签证续签"), await b.answer("签证续签")
    outs, again = run(kb, fake, steps, monkeypatch)
    assert {o.to for o in outs} == {USER} and kb.open_pending()       # the weak rule answer is withheld too
    assert again[0] is None and " unsupported 340t " in again[2] and again[2].endswith("cached")


def test_llm_chat_strips_thinking_and_sends_extra_fields(monkeypatch):
    fake = FakeLLM()
    fake.reply = "<think>let me see</think>\n[1] 答案"
    monkeypatch.setattr(config, "LLM_KEY", "k")
    monkeypatch.setattr(config, "LLM_EXTRA", '{"reasoning_effort": "none"}')

    async def go():
        async with TestServer(fake.app()) as server:
            monkeypatch.setattr(config, "LLM_BASE", f"http://127.0.0.1:{server.port}/v1")
            async with aiohttp.ClientSession() as http:
                return await llm.chat(http, [{"role": "user", "content": "hi"}], timeout=2)
    reply = asyncio.run(go())
    assert reply.text == "[1] 答案" and reply.prompt_tokens == 300
    assert fake.requests[0][1]["reasoning_effort"] == "none"


def test_make_needs_the_switch_a_key_and_an_index(tmp_path, monkeypatch):
    kb = KB(tmp_path / "kb.sqlite")
    monkeypatch.setattr(config, "RAG", False)
    monkeypatch.setattr(config, "LLM_KEY", "k")
    assert rag.make(kb, None) is None
    assert rag.make(kb, None, force=True) is None            # no index yet
    Chunks(kb).sync("qa", [Doc("qa", "1", 0, None, "q", "问：q\n答：a")])
    monkeypatch.setattr("wxbot.embed.load", lambda name=None: None)
    assert isinstance(rag.make(kb, None, force=True), Rag)
    monkeypatch.setattr(config, "LLM_KEY", "")
    assert rag.make(kb, None, force=True) is None
