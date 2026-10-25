from wxbot.hub import format_answer
from wxbot.hub_i18n import HubI18n

INDEX_TS = """
const en: Messages = {
  'answer.col.number': '#',
  'answer.col.assessment': 'Assessment',
  'answer.assessment.title': '{code} · Assessment ({year} Handbook)',
  'answer.only.english': 'English only {x}',
}
const zh: Messages = {
  // a comment with a 'quote'
  'answer.col.number': '#',
  'answer.col.assessment': '考核项目',
  'answer.col.type': '类型',
  'answer.col.weight': '占比',
  'answer.col.hurdle': '必过要求',
  'answer.col.activity': '教学活动',
  'answer.col.duration': '时长',
  'answer.assessment.title': '{code} · 考核（{year} Handbook）',
  'answer.assessment.noExam':
    '{year} Handbook 的考核项目里没有列出期末考试。' +
    '这不等于保证一定没有考试。',
  'answer.assessment.caption': '共 {count} 项，合计 {total}%',
  'answer.workload.requirements': '工作量要求',
  'answer.workload.title': '{code} · 工作量（{year} Handbook）',
  'answer.caveat.moodle': '请以 Moodle 为准。',
  'translation.label.mixed': '机器翻译，部分已人工校对。',
  'it\\'s': 'escaped',
}
"""
TERMS_TS = """
const zhAssessmentType: Dictionary = {
  'Portfolio': '作品集',
  'Project': '项目作业',
  'Quiz / Test': '小测 / 测验'
}
const zhHurdle: Dictionary = {
  // A hurdle is a component you must pass
  'Competency': '能力达标'
}
const zhConnector: Dictionary = { AND: '且', OR: '或' }
const zhRequisiteType: Dictionary = { 'prerequisite': '先修要求' }
const zhMode: Dictionary = { 'ON-CAMPUS': '校内授课' }
const zhPeriod: Dictionary = { 'First semester': '第一学期', 'Second semester': '第二学期' }
const zhActivityType: Dictionary = { 'Workshops': '工作坊' }
"""
I18N = HubI18n.parse(INDEX_TS, TERMS_TS)


def test_parse_and_translate():
    assert I18N.t("answer.assessment.noExam", {"year": 2026}) == \
        "2026 Handbook 的考核项目里没有列出期末考试。这不等于保证一定没有考试。"
    assert I18N.t("it's") == "escaped"
    assert I18N.t("answer.only.english", {"x": 1}) == "English only 1"     # falls back to English
    assert I18N.t("answer.missing") is None
    assert I18N.term("connector", "OR") == "或"
    assert I18N.term("mode", "Teaching activities are on-campus (ON-CAMPUS)") == "校内授课（ON-CAMPUS）"
    assert I18N.term("period", "Second semester to First semester") == "第二学期 至 第一学期"
    assert I18N.term("period", "Term 9") == "Term 9"                        # unknown stays English
    assert I18N.assessment_name("2 - Portfolio") == "第 2 项 · 作品集"
    assert I18N.assessment_name("Weekly Quiz") == "Weekly Quiz"


ASSESSMENT = {
    "answer_type": "handbook_assessment", "unit_code": "FIT2004",
    "title": "FIT2004 · Assessment (2026 Handbook)", "title_key": "answer.assessment.title",
    "title_params": {"code": "FIT2004", "year": 2026},
    "blocks": [
        {"type": "verdict", "key": "answer.assessment.noExam", "params": {"year": 2026}, "text": "English verdict"},
        {"type": "table", "columns": ["#", "Assessment", "Type", "Weight", "Hurdle"],
         "column_keys": ["answer.col.number", "answer.col.assessment", "answer.col.type", "answer.col.weight",
                         "answer.col.hurdle"],
         "keys": ["number", "name", "type", "weight", "hurdle"],
         "terms": {"name": "assessmentName", "type": "assessmentType", "hurdle": "hurdle"},
         "rows": [{"number": 1, "name": "Learning Project Portfolio", "type": "Portfolio", "weight": "100%",
                   "hurdle": None},
                  {"number": 2, "name": "In class tests", "type": "Quiz / Test", "weight": "0%",
                   "hurdle": "Competency"}],
         "caption": "2 items", "caption_key": "answer.assessment.caption",
         "caption_params": {"count": 2, "total": 100}},
        {"type": "text", "title": "Workload requirements", "title_key": "answer.workload.requirements",
         "text": "Minimum total expected workload is 144 hours."},
        {"type": "table", "columns": ["Activity", "Duration"],
         "column_keys": ["answer.col.activity", "answer.col.duration"], "keys": ["activity_type", "name"],
         "terms": {"activity_type": "activityType"}, "rows": [{"activity_type": "Workshops", "name": "24 hours"}]},
    ],
    "caveat": "Teaching-period detail can still change", "caveat_key": "answer.caveat.moodle",
    "sources": [{"kind": "handbook", "url": "https://handbook.monash.edu/2026/units/FIT2004"}],
}


def test_handbook_answer_in_chinese():
    text = format_answer(ASSESSMENT, I18N).text
    assert text.startswith("FIT2004 · 考核（2026 Handbook）")
    assert "没有列出期末考试" in text and "English verdict" not in text
    assert "（考核项目｜类型｜占比｜必过要求）" in text
    assert "· In class tests｜小测 / 测验｜0%｜能力达标" in text
    assert "共 2 项，合计 100%" in text
    assert "144 hours" not in text and "【工作量要求】英文原文见" in text
    assert "· 工作坊｜24 小时" in text
    assert "⚠️ 请以 Moodle 为准。" in text
    assert "🔗 Handbook 官网：https://handbook.monash.edu/2026/units/FIT2004" in text


def test_translated_faq_says_so_and_flags_australia():
    faq = {"answer_type": "official_faq", "title": "怎么申请特殊考虑？",
           "blocks": [{"type": "text", "title": None, "text": "中文正文"}],
           "translation": {"machine": True, "reviewed": True, "stale": False},
           "applies_to": "australia",
           "sources": [{"kind": "official", "url": "https://www.monash.edu/x"}]}
    text = format_answer(faq, I18N).text
    assert "中文正文" in text and "机器翻译，部分已人工校对" in text
    assert "澳大利亚校区" in text and "🔗 官网原文：https://www.monash.edu/x" in text


def test_without_i18n_files_everything_stays_english():
    text = format_answer(ASSESSMENT, HubI18n.empty()).text
    assert text.startswith("FIT2004 · Assessment (2026 Handbook)") and "English verdict" in text


# ---- the unit summary, and falling back to an earlier Handbook year ---------------------------------
import asyncio
import time

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from wxbot import config, hub

UNIT_2102 = {
    "unit_code": "FIT2102", "title": "编程范式", "academic_year": 2027, "credit_points": 6, "level": "第 2 级",
    "faculty": "信息技术学院", "has_exam": False,
    "overview": "本课程通过比较命令式、面向对象、函数式和声明式编程风格，介绍了思考程序的主要方式。" + "它侧重于基本理念。" * 30,
    "learning_outcomes": [{"number": n, "description": f"学习目标{n}：" + "能够设计并评估程序" * 8} for n in range(1, 5)],
    "assessments": [
        {"number": 1, "name": "Assignment 1 Functional Reactive Programming ", "type": "Project", "weight": "30",
         "hurdle": None},
        {"number": 2, "name": "Applied quizzes", "type": "Quiz / Test", "weight": "20", "hurdle": "Competency"}],
    "offerings": [{"campus": "Clayton 校区", "teaching_period": "第二学期"},
                  {"campus": "马来西亚校区", "teaching_period": "第二学期"}],
    "requisites": [{"requisite_type": "prerequisite", "connector": "OR", "description": None,
                    "items": [{"code": "FIT1008"}, {"code": "FIT1054"}]}],
    "translation": {"machine": True, "reviewed": True, "stale": False},
    "source_url": "https://handbook.monash.edu/2027/units/FIT2102", "workload_requirements": "每学期 144 小时。",
}


def test_overview_has_summary_outcomes_assessment_then_links():
    text = hub.format_overview(UNIT_2102, I18N).text
    order = ["FIT2102 · 编程范式（2027 Handbook）", "6 学分｜第 2 级｜信息技术学院", "📖 课程简介：", "🎯 学习目标：",
             "📝 考核方式（Handbook 未列期末考试）：", "📍 开课：马来西亚校区（第二学期）；Clayton 校区",
             "先修要求：FIT1008 或 FIT1054", "ℹ️ 中文为机器翻译", "🔗 Handbook 官网：", "📘 Monash Hub："]
    positions = [text.index(x) for x in order]
    assert positions == sorted(positions)
    assert "· Assignment 1 Functional Reactive Pro…｜项目作业｜30%" in text
    assert "· Applied quizzes｜小测 / 测验｜20%（能力达标）" in text
    assert len(text.encode()) <= hub.OVERVIEW_BUDGET


def test_overview_never_pastes_english_prose():
    unit = {**UNIT_2102, "overview": "English only.", "translation": None,
            "learning_outcomes": [{"number": 1, "description": "English outcome"}]}
    text = hub.format_overview(unit, I18N).text
    assert "English only" not in text and "English outcome" not in text
    assert "暂无中文" in text and "📝 考核方式" in text and "🔗 Handbook 官网" in text


def test_overview_from_an_earlier_year_says_so():
    text = hub.format_overview({**UNIT_2102, "academic_year": 2026,
                                "source_url": "https://handbook.monash.edu/2026/units/FIT2102"}, I18N,
                               missing_year=2027).text
    assert "不在 2027 年 Handbook 中" in text and "2026 年 Handbook 的内容" in text
    assert "/units/FIT2102?year=2026" in text


def _fake_hub(unit_years: dict[str, list[int]], calls: list[str] | None = None):
    """A stand-in for Monash Hub: /ask knows only the default year (2027) unless told one; units
    are listed in the given years."""
    async def ask(request):
        body = await request.json()
        if calls is not None:
            calls.append(f"ask campus={body.get('campus')}")
        year = body.get("year") or 2027
        code = "FIT2004" if "FIT2004" in body["query"] else "FIT2102" if "FIT2102" in body["query"] else "FIT9999"
        if year not in unit_years.get(code, []):
            return web.json_response({"answer_type": "unit_not_found", "unit_code": code,
                                      "title_params": {"code": code, "year": year}, "blocks": []})
        if "学什么" in body["query"]:
            return web.json_response({"answer_type": "handbook_overview", "unit_code": code, "blocks": []})
        return web.json_response({
            "answer_type": "handbook_workload", "unit_code": code, "title": f"{code} · Workload ({year} Handbook)",
            "title_key": "answer.workload.title", "title_params": {"code": code, "year": year},
            "blocks": [{"type": "text", "title": "Workload requirements", "title_key": "answer.workload.requirements",
                        "text": "Minimum total expected workload is 144 hours."}],
            "sources": [{"kind": "handbook", "url": f"https://handbook.monash.edu/{year}/units/{code}"}]})

    async def unit(request):
        if calls is not None:
            calls.append(request.path_qs)
        code = request.match_info["code"]
        years = unit_years.get(code, [])
        if not years:
            return web.json_response({}, status=404)
        year = int(request.query["year"]) if "year" in request.query else (2027 if 2027 in years else max(years))
        return web.json_response({**UNIT_2102, "unit_code": code, "academic_year": year,
                                  "available_years": sorted(years, reverse=True),
                                  "not_in_year": None if 2027 in years or "year" in request.query else 2027})
    app = web.Application()
    app.router.add_post("/ask", ask)
    app.router.add_get("/units/{code}", unit)
    return app


def _run_ask(monkeypatch, unit_years, question, calls=None):
    async def go():
        async with TestServer(_fake_hub(unit_years, calls)) as server:
            monkeypatch.setattr(config, "HUB_API", f"http://127.0.0.1:{server.port}")
            monkeypatch.setattr(hub, "_i18n", type("C", (), {"get": staticmethod(lambda: I18N)}))
            async with aiohttp.ClientSession() as session:
                return await hub.ask(session, question)
    return asyncio.run(go())


def test_ask_turns_a_bare_link_answer_into_the_unit_summary(monkeypatch):
    answer = _run_ask(monkeypatch, {"FIT2102": [2027, 2026]}, "FIT2102学什么")
    assert answer.answer_type == "handbook_overview" and "🎯 学习目标：" in answer.text


def test_ask_falls_back_to_the_latest_year_that_lists_the_unit(monkeypatch):
    answer = _run_ask(monkeypatch, {"FIT2004": [2026, 2025]}, "FIT2004 工作量")
    assert answer.answer_type == "handbook_workload"
    assert "FIT2004 不在 2027 年 Handbook 中" in answer.text and "（2026 Handbook）" in answer.text
    assert "每学期 144 小时。" in answer.text                 # the Chinese workload text replaced the English one
    assert "/2026/units/FIT2004" in answer.text
    summary = _run_ask(monkeypatch, {"FIT2004": [2026, 2025]}, "FIT2004学什么")
    assert "2026 年 Handbook 的内容" in summary.text and "🎯 学习目标：" in summary.text


def test_each_unit_page_is_read_once_per_answer(monkeypatch):
    calls = []
    _run_ask(monkeypatch, {"FIT2004": [2026, 2025]}, "FIT2004 工作量", calls)
    # Year fallback, Chinese workload and teach-out notice share one read.
    assert len([c for c in calls if c.startswith("/units")]) == 1
    calls.clear()
    _run_ask(monkeypatch, {"FIT2102": [2027]}, "FIT2102 工作量", calls)
    assert len([c for c in calls if c.startswith("/units")]) == 1


def test_ask_asks_for_malaysia_pages_first(monkeypatch):
    calls = []
    _run_ask(monkeypatch, {"FIT2102": [2027]}, "FIT2102 工作量", calls)
    assert "ask campus=malaysia" in calls
    monkeypatch.setattr(config, "HUB_CAMPUS", "")
    calls.clear()
    _run_ask(monkeypatch, {"FIT2102": [2027]}, "FIT2102 工作量", calls)
    assert "ask campus=None" in calls


def test_ask_says_when_a_unit_is_in_no_year(monkeypatch):
    answer = _run_ask(monkeypatch, {}, "FIT9999 工作量")
    assert answer.answer_type == "unit_not_found" and "FIT9999" in answer.text


# ---- the Handbook year (issue #6) --------------------------------------------------------------------

def test_year_words_in_the_question():
    this = time.localtime().tm_year
    assert hub.split_year("FIT2004 工作量") == ("FIT2004 工作量", None)             # 2004 is the unit code
    assert hub.split_year("fit 2004 和 FIT1008 有考试吗") == ("fit 2004 和 FIT1008 有考试吗", None)
    assert hub.split_year("FIT2102 2026 工作量") == ("FIT2102 工作量", 2026)
    assert hub.split_year("2026版 FIT2102 有考试吗") == ("FIT2102 有考试吗", 2026)
    assert hub.split_year("编程范式 2026年的 考试") == ("编程范式 考试", 2026)
    assert hub.split_year("明年 FIT2102 开吗") == ("FIT2102 开吗", this + 1)
    assert hub.split_year("今年FIT2102开吗") == ("FIT2102开吗", this)
    assert hub.split_year("1958年建校") == ("1958年建校", None)                   # not a Handbook year
    # Degree codes too: B2026 and m2018 were read as the year 2026 and 2018 and the degree was lost (#36).
    assert hub.split_year("B2026要学什么课") == ("B2026要学什么课", None)
    assert hub.split_year("m2018属于哪个faculty") == ("m2018属于哪个faculty", None)
    assert hub.split_year("S2020 2026年 要学什么") == ("S2020 要学什么", 2026)


def test_year_asked_in_the_question_is_the_year_answered(monkeypatch):
    answer = _run_ask(monkeypatch, {"FIT2102": [2027, 2026]}, "FIT2102 2026 工作量")
    assert "（2026 Handbook）" in answer.text and "不在" not in answer.text
    assert "📅 FIT2102 还有 2027 年的 Handbook，回复「FIT2102 2027」查看" in answer.text
    assert "/2026/units/FIT2102" in answer.text
    # A year the unit is not in: the latest year that lists it, and which year was asked for.
    answer = _run_ask(monkeypatch, {"FIT2102": [2027]}, "FIT2102 2026 工作量")
    assert "FIT2102 不在 2026 年 Handbook 中" in answer.text and "（2027 Handbook）" in answer.text
    assert "还有" not in answer.text


def test_pinned_year(monkeypatch):
    monkeypatch.setattr(config, "HUB_YEAR", 2026)
    answer = _run_ask(monkeypatch, {"FIT2102": [2027, 2026]}, "FIT2102 工作量")
    assert "（2026 Handbook）" in answer.text and "还有 2027 年" in answer.text
    summary = _run_ask(monkeypatch, {"FIT2102": [2027, 2026]}, "FIT2102学什么")
    assert "（2026 Handbook）" in summary.text and "🎯 学习目标：" in summary.text
    assert "📅 FIT2102 还有 2027 年的 Handbook" in summary.text
    # A year typed in the question beats the pinned one.
    assert "（2027 Handbook）" in _run_ask(monkeypatch, {"FIT2102": [2027, 2026]}, "FIT2102 2027 工作量").text


def test_other_years_are_offered_after_a_fallback(monkeypatch):
    answer = _run_ask(monkeypatch, {"FIT2004": [2026, 2025]}, "FIT2004 工作量")
    assert "FIT2004 不在 2027 年 Handbook 中" in answer.text
    assert "📅 FIT2004 还有 2025 年的 Handbook，回复「FIT2004 2025」查看" in answer.text
    assert hub.years_hint("FIT2102", 2027, [2027]) is None
    assert hub.years_hint("FIT2102", 2027, [2027, 2026, 2025, 2024]) == \
        "📅 FIT2102 还有 2026 / 2025 年的 Handbook，回复「FIT2102 2026」查看"


# ---- community posts as a source (issue #14) -----------------------------------------------------------

def test_community_posts_are_labelled_solved_first_and_at_most_two():
    data = {"answer_type": "handbook_workload", "unit_code": "FIT2102", "title": "FIT2102 · Workload",
            "blocks": [{"type": "text", "text": "每学期 144 小时。"}],
            "related_community": [
                {"id": 7, "title": "FIT2102 期末难吗", "answer_count": 3, "is_solved": False},
                {"id": 9, "title": "FIT2102 作业怎么分配时间", "answer_count": 2, "is_solved": True},
                {"id": 11, "title": "没人回答的帖子", "answer_count": 0, "is_solved": False},
                {"id": 12, "title": "另一个已解决的帖子", "answer_count": 1, "is_solved": True}]}
    text = format_answer(data, I18N).text
    assert "💬 社区里相关的讨论（学生经验，非官方）：" in text
    assert "· FIT2102 作业怎么分配时间（已解决）https://monashhub.secureview.tech/community/post/9" in text
    assert "/community/post/12" in text
    assert "/community/post/7" not in text and "/community/post/11" not in text
    assert text.index("144 小时") < text.index("💬")                       # after the answer, never before
    # With no solved posts, the ones with answers are shown with their count.
    data["related_community"] = data["related_community"][:1]
    assert "（3 个回答）https://monashhub.secureview.tech/community/post/7" in format_answer(data, I18N).text
    data["related_community"] = []
    assert "💬" not in format_answer(data, I18N).text


def test_community_posts_alone_are_a_weak_answer_not_a_miss():
    posts = [{"id": 7, "title": "宿舍怎么申请", "answer_count": 1, "is_solved": False}]
    answer = format_answer({"answer_type": "community_fallback", "related_community": posts}, I18N)
    assert answer.strength == "weak" and answer.text.startswith("💬 社区里相关的讨论（学生经验，非官方）：")
    assert format_answer({"answer_type": "community_fallback", "related_community": []}, I18N) is None
    assert format_answer({"answer_type": "community_fallback",
                          "related_community": [{"id": 8, "title": "没人回答", "answer_count": 0}]}, I18N) is None


# ---- degrees, units by name, page ordering, the Hub being down --------------------------------------

COURSE_C2001 = {
    "course_code": "C2001", "title": "计算机科学学士", "abbreviated_name": "BCompSci", "credit_points": 144,
    "course_type": "本科（单一专业）", "faculty": "信息技术学院", "campuses": ["Clayton 校区", "马来西亚校区"],
    "duration_years": 3, "academic_year": 2026, "not_in_year": 2027,
    "overview": "该学位课程是为希望深入研究计算机的学生设计的。" * 10,
    "areas_of_study": [{"code": "ALG", "title": "算法与软件", "aos_type": "本科专业方向"},
                       {"code": "AI", "title": "人工智能", "aos_type": "本科专业方向"},
                       {"code": "GD", "title": "游戏设计", "aos_type": "辅修"}],
    "containers": [{"title": "A 部分。基础课程", "credit_points": 42}, {"title": "E 部分。自由选修课程", "credit_points": 48}],
    "translation": {"machine": True, "reviewed": True, "stale": False},
    "source_url": "https://handbook.monash.edu/2026/courses/C2001",
}


def test_course_card():
    text = hub.format_course(COURSE_C2001, I18N).text
    order = ["🎓 C2001 · 计算机科学学士（BCompSci，2026 Handbook）", "本科（单一专业）｜144 学分｜3 年｜信息技术学院",
             "📍 校区：马来西亚校区、Clayton 校区", "不在 2027 年 Handbook 中", "📖 简介：",
             "🧭 本科专业方向：算法与软件、人工智能", "🧭 辅修：游戏设计", "🧱 课程结构：", "· A 部分。基础课程（42 学分）",
             "🔗 Handbook 官网：", "📘 Monash Hub：https://monashhub.secureview.tech/courses/C2001?year=2026"]
    positions = [text.index(x) for x in order]
    assert positions == sorted(positions)
    assert len(text.encode()) <= hub.COURSE_BUDGET


def test_codes_and_names():
    assert hub.course_codes("C2001 和 s3701 有什么区别") == ["C2001", "S3701"]
    assert hub.course_codes("FIT2004 和 2026") == []
    cases = {"编程范式有期末考试吗": "编程范式", "算法课的先修课是什么": "算法", "计算机科学学士要修多少学分": "计算机科学学士",
             "有机化学有考试吗": "有机化学", "Bachelor of Computer Science 有哪些专业方向": "Bachelor of Computer Science",
             "what is the prerequisite of algorithms": "algorithms", "数据结构那门课难吗": "数据结构", "算法课有考试吗": "算法"}
    for question, name in cases.items():
        assert hub.name_phrase(question) == name, question


def test_official_pages_put_malaysia_first_with_a_summary():
    data = {"answer_type": "official_search", "blocks": [{"type": "page_list", "items": [
        {"slug": "visa-au", "title": "延长你的停留", "applies_to": "australia", "url": "https://www.monash.edu/au",
         "summary": "澳洲的签证说明。"},
        {"slug": "pass-my", "title": "学生准证", "applies_to": "malaysia", "url": "https://www.monash.edu.my/pass",
         "summary": "马来西亚学生准证续签说明。", "translation": {"machine": True}}]}],
        "suggestions": ["学生准证怎么续签？"]}
    text = hub.format_answer(data, I18N).text
    assert text.index("学生准证（马来西亚校区）") < text.index("延长你的停留（澳洲校区）")
    assert "马来西亚学生准证续签说明。" in text and "澳洲的签证说明。" in text       # every page says what it is
    assert "📘 中文全文：https://monashhub.secureview.tech/guides/pass-my" in text
    assert "📘 中文全文：https://monashhub.secureview.tech/guides/visa-au" in text
    assert "💡 也可以问：「学生准证怎么续签？」" in text


UNITS = [{"unit_code": "FIT2102", "title": "编程范式"}, {"unit_code": "ETC5450", "title": "高级 R 编程"}]
ALGO = [{"unit_code": "FIT2115", "title": "数据结构及算法 1"}, {"unit_code": "FIT3155", "title": "高级数据结构与算法"}]


def _fake_hub2(down: bool = False):
    async def ask(request):
        if down:
            return web.json_response({}, status=502)
        body = await request.json()
        q = body["query"]
        if q.startswith("FIT2102"):
            return web.json_response({
                "answer_type": "handbook_assessment", "unit_code": "FIT2102", "title": "FIT2102 · Assessment (2027 Handbook)",
                "title_key": "answer.assessment.title", "title_params": {"code": "FIT2102", "year": 2027},
                "blocks": [{"type": "verdict", "key": "answer.assessment.noExam", "params": {"year": 2027}}]})
        if "退课" in q:
            return web.json_response({"answer_type": "official_faq", "title": "怎么退选一门课？",
                                      "blocks": [{"type": "text", "text": "在 WES 退选。"}]})
        return web.json_response({"answer_type": "official_search", "blocks": [{"type": "page_list", "items": [
            {"slug": "exams", "title": "期末考试", "applies_to": "all", "url": "https://www.monash.edu/exams"}]}]})

    async def units(request):
        q = request.query["q"]
        rows = UNITS if "编程" in q else ALGO if "算法" in q else []
        return web.json_response({"total": len(rows) if rows is not ALGO else 177, "results": rows})

    async def courses(request):
        year = int(request.query.get("year", 2027))
        if "计算机科学学士" in request.query["q"]:
            rows = [{"course_code": "C2001", "title": "计算机科学学士"}] if year == 2026 else \
                [{"course_code": "B2008", "title": "商学学士与计算机科学学士", "campuses": ["Clayton 校区"]}]
        else:
            rows = []
        return web.json_response({"total": len(rows), "academic_year": year, "results": rows})

    async def course(request):
        code = request.match_info["code"]
        if code == "B2026":             # a degree code whose digits look like a year
            return web.json_response(dict(COURSE_C2001, course_code="B2026", title="商业与贸易学士"))
        if code != "C2001":
            return web.json_response({}, status=404)
        year = request.query.get("year")
        if year:                        # the Hub answers an explicit year strictly
            return web.json_response(dict(COURSE_C2001, not_in_year=None)) if year == "2026" else \
                web.json_response({}, status=404)
        return web.json_response(COURSE_C2001)
    app = web.Application()
    app.router.add_post("/ask", ask)
    app.router.add_get("/units", units)
    app.router.add_get("/courses", courses)
    app.router.add_get("/courses/{code}", course)
    return app


def _run2(monkeypatch, question, down=False):
    async def go():
        async with TestServer(_fake_hub2(down)) as server:
            monkeypatch.setattr(config, "HUB_API", f"http://127.0.0.1:{server.port}")
            monkeypatch.setattr(hub, "_i18n", type("C", (), {"get": staticmethod(lambda: I18N)}))
            async with aiohttp.ClientSession() as session:
                return await hub.ask(session, question)
    return asyncio.run(go())


def test_unit_asked_by_name_is_answered_by_code(monkeypatch):
    answer = _run2(monkeypatch, "编程范式有期末考试吗")
    assert answer.strength == "strong" and answer.text.startswith("（按课程名找到：FIT2102 · 编程范式）")
    assert "没有列出期末考试" in answer.text


def test_ambiguous_unit_name_lists_candidates_after_pages(monkeypatch):
    answer = _run2(monkeypatch, "算法课有考试吗")
    assert answer.strength == "medium"
    assert answer.text.index("期末考试") < answer.text.index("按「算法」找到 177 门课程")
    assert "· FIT2115 数据结构及算法 1" in answer.text


def test_policy_faq_is_not_taken_for_a_unit_name(monkeypatch):
    answer = _run2(monkeypatch, "怎么退课")
    assert answer.answer_type == "official_faq"


def test_degree_by_code_and_by_name(monkeypatch):
    assert _run2(monkeypatch, "C2001 是什么学位").answer_type == "course_overview"
    by_name = _run2(monkeypatch, "计算机科学学士要修多少学分")          # found in the year before the default
    assert by_name.answer_type == "course_overview" and "144 学分" in by_name.text
    assert _run2(monkeypatch, "C9999 是什么").answer_type == "course_not_found"
    b2026 = _run2(monkeypatch, "B2026要学什么课")
    assert b2026.answer_type == "course_overview" and "B2026 · 商业与贸易学士" in b2026.text


def test_a_degree_is_read_from_the_year_asked_for(monkeypatch):
    asked = _run2(monkeypatch, "C2001 2026年要学什么")
    assert "（BCompSci，2026 Handbook）" in asked.text and "不在" not in asked.text
    # A year that does not list the degree: the Hub's default year, saying which year was asked for.
    older = _run2(monkeypatch, "C2001 2025年要学什么")
    assert "C2001 不在 2025 年 Handbook 中" in older.text and "以下是 2026 年 Handbook 的内容" in older.text
    monkeypatch.setattr(config, "HUB_YEAR", 2026)                 # WXBOT_HUB_YEAR, as on the VPS
    assert "不在" not in _run2(monkeypatch, "C2001 是什么学位").text


def test_hub_down_is_an_error_not_a_miss(monkeypatch):
    assert isinstance(_run2(monkeypatch, "学生签证怎么续签", down=True), hub.HubError)


def test_campus_suffix_is_not_doubled_and_crumbs_are_not_a_summary():
    data = {"answer_type": "official_search", "blocks": [{"type": "page_list", "items": [
        {"slug": "fees", "title": "费用和资金（马来西亚校区）", "applies_to": "malaysia", "url": "https://x/fees",
         "summary": "学位课程与课程信息 • Handbook • 团队领导 • 学院政策"},
        {"slug": "transfer", "title": "内部转学位课程", "applies_to": "all", "url": "https://x/t"}]}]}
    text = hub.format_answer(data, I18N).text
    assert "（马来西亚校区）（马来西亚校区）" not in text and "费用和资金（马来西亚校区）" in text
    assert "团队领导" not in text
    assert text.index("费用和资金") < text.index("内部转学位课程")          # Hub order kept


def test_teach_out_notice_keeps_the_faculty_wording():
    unit = {**UNIT_2102, "teach_out": {"entries": [{"change": "No longer offered", "course": "BCS, BSE",
                                                     "plan": "Replace with FIT3234 (S1 and S2)"}],
                                       "sources": {"it": {"url": "https://www.monash.edu/it/re-enrolment"}}}}
    text = hub.format_overview(unit, I18N).text
    assert "· No longer offered（BCS, BSE）：Replace with FIT3234 (S1 and S2)" in text
    assert "🔗 https://www.monash.edu/it/re-enrolment" in text
    assert len(text.encode()) <= hub.OVERVIEW_BUDGET


TEACH_OUT_SOURCES = {
    "it-au": {"url": "https://www.monash.edu/it/current-students/courses/re-enrolment/undergraduate", "applies_to": "australia"},
    "it-my": {"url": "https://www.monash.edu.my/it/current-students/Course-Offered/undergraduates/re-enrollment",
              "applies_to": "malaysia"}}


def test_teach_out_notice_is_the_malaysia_one_when_there_is_one():
    unit = {**UNIT_2102, "teach_out": {"entries": [
        {"change": "No longer offered", "course": "BCS, BSE", "plan": "Replace with FIT3234 (S1 and S2)",
         "source": "it-au", "applies_to": "australia"},
        {"change": "No longer offered", "course": "BCS, BCS in DS, BCS in AI, BSE", "plan": "Replace with FIT3234 (S1 and S2)",
         "source": "it-my", "applies_to": "malaysia"}], "sources": TEACH_OUT_SOURCES}}
    text = "\n".join(hub.teach_out_lines(I18N, unit))
    assert "（BCS, BCS in DS, BCS in AI, BSE）" in text and "（BCS, BSE）" not in text
    assert "monash.edu.my/it/" in text and "www.monash.edu/it/" not in text and "澳洲" not in text


def test_teach_out_notice_only_on_the_australian_page_says_so():
    unit = {**UNIT_2102, "teach_out": {"entries": [
        {"change": "Final offering S2 2027", "course": "ALL", "plan": "Replace with FIT2119 from 2028 (S1 and S2)",
         "source": "it-au", "applies_to": "australia"}], "sources": {"it-au": TEACH_OUT_SOURCES["it-au"]}}}
    text = "\n".join(hub.teach_out_lines(I18N, unit))
    assert "只有澳洲校区的页面写了" in text and "Replace with FIT2119" in text and "www.monash.edu/it/" in text


def test_area_of_study_card():
    assert hub.aos_codes("MMEDCHEM01介绍") == ["MMEDCHEM01"] and hub.aos_codes("FIT2102") == []
    aos = {"aos_code": "MMEDCHEM01", "title": "药物化学", "aos_type": "主修", "study_level": "本科", "credit_points": 48,
           "faculty": "马来西亚校区理学院", "academic_year": 2026, "not_in_year": 2027,
           "source_url": "https://handbook.monash.edu/2026/aos/MMEDCHEM01",
           "containers": [{"title": "核心课程", "credit_points": 42,
                           "items": [{"code": "CHM2922", "name": "Spectroscopy"}, {"code": "PHA3801", "name": "x"}]}],
           "units": {"CHM2922": {"title": "光谱学与分析化学"}}}
    text = hub.format_aos(aos, I18N).text
    assert text.startswith("🧭 MMEDCHEM01 · 药物化学（主修，2026 Handbook）")
    assert "· 核心课程（42 学分）：CHM2922 光谱学与分析化学、PHA3801 x" in text
    assert "不在 2027 年 Handbook 中" in text and "/courses/aos/MMEDCHEM01?year=2026" in text


def test_faq_links_its_guide_page_on_monash_hub_once():
    data = {"answer_type": "official_faq", "title": "怎么退选一门课？", "page_slug": "discontinue-units",
            "unit_code": "FIT2102", "blocks": [{"type": "text", "text": "在 WES 退选。"},
                                               {"type": "link", "to": "/units/FIT2102", "label": "FIT2102"}],
            "sources": [{"kind": "official", "url": "https://www.monash.edu/discontinue"}]}
    text = hub.format_answer(data, I18N).text
    assert "📘 Monash Hub 中文全文：https://monashhub.secureview.tech/guides/discontinue-units" in text
    assert text.count("https://monashhub.secureview.tech/units/FIT2102") == 1


def test_search_link_is_encoded():
    assert hub.search_link("怎么 退课") == "https://monashhub.secureview.tech/search?q=%E6%80%8E%E4%B9%88%20%E9%80%80%E8%AF%BE"


def test_official_links_get_their_hub_page(monkeypatch):
    monkeypatch.setattr(hub.guides, "by_url", {hub._url_key("https://www.monash.edu.my/student-services"): "my-services",
                                               hub._url_key("https://www.monash.edu/exams"): "exams"})
    text = hub.with_guides("看这里\n   🔗 http://monash.edu.my/student-services/?x=1\n🔗 https://example.com/other")
    assert text == ("看这里\n   🔗 http://monash.edu.my/student-services/?x=1\n"
                    "   📘 Monash Hub 中文全文：https://monashhub.secureview.tech/guides/my-services\n"
                    "🔗 https://example.com/other")
    already = "🔗 https://www.monash.edu/exams\n📘 中文全文：https://monashhub.secureview.tech/guides/exams"
    assert hub.with_guides(already) == already


def test_guide_index_reads_every_page(monkeypatch):
    pages = [{"slug": f"p{i}", "url": f"https://www.monash.edu/p{i}"} for i in range(3)]

    async def fake_call(session, method, path, budget, params=None):
        return 200, {"total": 3, "results": pages[params["offset"]:params["offset"] + 2]}
    monkeypatch.setattr(hub, "_call", fake_call)
    index = hub.GuideIndex()
    asyncio.run(index._load(None))
    assert index.link("https://monash.edu/p2/") == "https://monashhub.secureview.tech/guides/p2"


def test_missing_i18n_files_are_reported_once(tmp_path, caplog):
    from wxbot.hub_i18n import Cached
    cached = Cached(tmp_path)
    with caplog.at_level("WARNING", logger="wxbot.hub_i18n"):
        assert cached.get().t("answer.col.type") is None
        cached.get()
    assert sum("i18n files unavailable" in r.getMessage() for r in caplog.records) == 1
