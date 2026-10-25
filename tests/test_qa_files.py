import json
import re
from pathlib import Path

import pytest

from wxbot import config
from wxbot.kb import KB, clear_lead

QA_DIR = Path(__file__).resolve().parent.parent / "qa"


@pytest.fixture
def kb(tmp_path):
    kb = KB(tmp_path / "kb.sqlite")
    items = json.loads((QA_DIR / "mamo-topics.json").read_text(encoding="utf-8"))
    assert kb.import_qa(items) == (len(items), 0, 0) and kb.import_qa(items) == (0, 0, 0)
    return kb


def _answer(kb, q):
    m = kb.match_qa(q)
    sure = m and m[0].score >= config.QA_STRONG and clear_lead(m, config.QA_MARGIN)
    return kb.get_qa(m[0].id)["answer"] if sure else None


def test_a_rule_for_australia_is_labelled_as_such():
    # The owner (2026-10-25): visa, insurance and the like differ by country, so an answer that gives the
    # Australian rule says so, next to the Malaysia one.
    for item in json.loads((QA_DIR / "mamo-topics.json").read_text(encoding="utf-8")):
        if re.search(r"(?<![A-Za-z])(?:CoE|OSHC|ESOS|subclass 500|Allianz)(?![A-Za-z])", item["answer"]):
            assert "【澳洲校区" in item["answer"] and "马来西亚校区" in item["answer"], item["phrases"][0]


def test_no_answer_sends_students_to_ask_mira(kb):
    # Ask Mira was switched off in October 2026; MoVA and Monash Connect replaced it.
    for item in json.loads((QA_DIR / "mamo-topics.json").read_text(encoding="utf-8")):
        answer = item["answer"].lower().replace(" ", "")
        assert "askmira.monash" not in answer and "student hub 或" not in answer, item["phrases"][0]


def test_every_link_is_a_source(kb):
    # An answer Waldo gave from his own experience (where the printers are) can have no link.
    for item in json.loads((QA_DIR / "mamo-topics.json").read_text(encoding="utf-8")):
        assert item.get("url", "https://www.monash.edu/").startswith((
            "https://mp.weixin.qq.com/s/", "https://www.monash.edu.my/", "https://www.monash.edu/",
            "https://sors.monash.edu.my", "https://monashhub.secureview.tech/")), item["phrases"][0]


@pytest.mark.parametrize("question, expected", [
    ("怎么选课", "my.monash.edu/wes"), ("WES怎么提交", "my.monash.edu/wes"), ("怎么退课", "my.monash.edu/wes"),
    ("学费怎么交", "fee-payment-methods"), ("支付宝交学费", "留学缴费"),
    ("Moodle怎么用", "learning.monash.edu"), ("怎么交作业", "确认提交"), ("作业提交", "确认提交"),
    ("怎么报到", "Lepak Place"), ("怎么选上课时间", "my-timetable"), ("tutorial满了怎么办", "EMO"),
    ("交换", "WAM 至少 60%"), ("交换生", "WAM 至少 60%"), ("入台证", "coa.immigration.gov.tw"),
    ("去台湾", "coa.immigration.gov.tw"), ("续签", "Student Pass Renewal"), ("签证快到期了", "Student Pass Renewal"),
    ("签到", "Attendance Code"), ("怎么毕业", "按月自动授予学位"), ("学生邮箱", "mail.google.com"),
    ("MPU是什么", "MPU3172"), ("通识课", "MPU3172"), ("general studies", "MPU3172"), ("研究生要修通识课吗", "研究生不用修"),
    ("26S2入学要修哪些MPU", "MPU3172"), ("2025年入学要修哪些MPU", "MPU3193"),
    ("本地生要修哪些通识课", "MPU3182"), ("本地生MPU", "MPU3182"), ("MPU3212是什么", "SPM"),
    ("MPU有什么变化", "从 4 门变成 6 门"), ("通识课有变化吗", "从 4 门变成 6 门"),
    ("马来西亚学生要修哪些通识课", "MPU3182"), ("MPU3172是什么", "MPU3172"), ("26S1入学MPU", "Monash Malaysia Connect"),
    ("学校地址", "Jalan Lagoon Selatan"), ("从机场怎么去学校", "SunU-Monash"), ("校车几点", "22:15"),
    ("教室在哪", "Monash Study app"), ("学校地图", "Monash Study app"),
    ("GPA怎么算", "Σ(等级分 × 学分)"), ("WAM怎么算", "wam/calculator"), ("绩点", "HD 4.0"), ("MPU算WAM吗", "不算进"),
    ("巴士", "22:15"), ("公交", "SunU-Monash"), ("LT在哪", "Monash Study app"), ("GS是什么", "MPU3172"),
    ("马来语课要修吗", "MPU3143"),
    ("什么是hurdle", "2026 年 12 月 31 日"), ("hurdle改了什么", "additional assessment"),
    ("hurdle有啥变化", "additional assessment"), ("hurdle没过", "NH"), ("成绩是NH", "NH"),
    ("hurdle啥意思", "2026 年 12 月 31 日"), ("还有45分门槛吗", "2026 年 12 月 31 日"),
    ("我的课有没有hurdle", "Handbook"), ("期末要过45分吗", "45%"),
    ("额外考核是什么", "additional assessment"), ("hurdle有几次机会", "additional assessment"),
    ("NGO是什么", "NGO"), ("NH影响GPA吗", "0.3"), ("总分够了为什么还挂", "NH"),
    ("hurdle没过还能supp吗", "NS"),
    ("挂科了怎么办", "45 到 49"), ("补考怎么申请", "不能申请"), ("补考过了给几分", "50 分"),
    ("孩子成绩显示NH是什么意思", "Hurdle Fail"), ("孩子挂科了怎么办", "45 到 49"),
    ("学生卡丢了怎么办", "RM100"), ("M-Pass怎么申请", "Let's Begin"), ("学生证怎么办", "M-Pass"),
    # How parents ask: polite openers and "孩子" do not get in the way.
    ("您好，请问孩子怎么交学费", "fee-payment-methods"), ("我家孩子刚到马来西亚，需要怎么报到", "Lepak Place"),
    ("老师好，孩子想申请交换", "WAM 至少 60%"), ("孩子要修通识课吗", "MPU3172"),
    # Taught 2026-10-24 from questions the bot could not answer.
    ("提交之后只显示一门成功", "Monash Connect"), ("课满了怎么办", "Monash Connect"),
    ("补课课撞了咋办", "同一门课其他时间"), ("下周一放假吗", "雪兰莪州"), ("公共假期要上课吗", "雪兰莪州"),
    ("minor和elective有什么区别", "Free Elective"), ("可供elective的课有哪些", "Free Elective"),
    ("学校打印机怎么用", "图书馆一楼"), ("面对面咨询服务", "取号"), ("作业会发到哪里", "learning.monash.edu"),
    ("问问学生mdac那个离开时间怎么填呀", "自行上网查找"), ("maybank开户", "International Student Letter"), ("银行卡怎么办", "International Student Letter"),
    ("plenary在哪里", "Monash Study app"), ("马莫plenary在哪", "Monash Study app"), ("Handbook2027有啥变化", "monashhub.secureview.tech/units"),
    ("期末考试什么时候", "Assessment"), ("期末考试时间", "Assessment"), ("期末考试在哪考", "时间和地点"), ("考场在哪", "时间和地点"),
    ("签证过期了怎么办", "ISP 柜台"), ("签证过期了还能留在马来西亚吗", "ISP 柜台"), ("学生签证过期了", "ISP 柜台"),
    ("Student Pass过期了", "ISP 柜台"),
    ("转专业是符合转的要求就可以还是择优录取啊", "internal-course-transfer"), ("马莫怎么转专业", "Internal Course Transfer"),
    ("换专业", "Internal Course Transfer"), ("转专业会影响签证吗", "Student Pass"), ("怎么换课", "my.monash.edu/wes"),
    ("AskMira用不了", "MoVA"), ("MoVA是什么", "MoVA"), ("面对面咨询服务", "Building 3"),
    ("Monash Connect在哪", "Building 3"), ("Allocate显示Full", "MoVA"), ("签到码漏填了", "MoVA"),
    ("期末考试那天有事能推迟考吗", "deferred-and-rescheduled-assessments"), ("期末考试挂了怎么办", "45 到 49"),
    ("国际生有没有保险", "Generali"), ("看病保险怎么报销", "MiCare"), ("这学期什么时候放假", "Principal Dates"),
    ("什么时候放假", "Principal Dates"), ("不想上这门课了怎么退", "census date"), ("census date之后还能退课吗", "WD-LATE"),
    ("考试能带什么进考场", "M-Pass"), ("期末考试要带什么", "M-Pass"),
    ("休学会影响学生签证吗", "注销 Student Pass"), ("休学会影响学生签证吗", "compassionate or compelling"),
    ("能打工吗", "每周不超过 20 小时"), ("一周能打工多少小时", "48 小时"), ("转学去别的大学", "release"),
    ("转去其他大学", "注销 Student Pass"), ("签证怎么续签", "subclass 500"), ("国际生有没有保险", "OSHC"),
    ("不想上这门课了怎么退", "18 学分"),
    ("毕业可以推迟吗", "最长到课程完成后 12 个月"), ("国际学生减课会影响签证吗", "18 学分"), ("underload怎么申请", "SORS"), ("underload在哪申请", "underload-application"), ("可以只修三门课吗", "mum.student.visa@monash.edu"), ("overload怎么申请", "overload-semester-enrolment"), ("一学期能修五门课吗", "60%"), ("一学期修几门课", "4 门课、24 学分"), ("选课是一学期一学期选吗", "一整年"), ("莫纳什的选课是一学期一学期的选吗", "优先确定 S1"), ("可以只选一个学期的课吗", "一整年"), ("交换需要消签吗", "保留马来西亚学生签证"), ("交换要注销学生签证吗", "赶不上开学"), ("去交换学生签证怎么办", "目的地国家"), ("毕业要销签吗", "Course Completion / Discontinuation Form"), ("毕业了学生签证要注销吗", "Course Completion / Discontinuation Form"), ("全日制要修多少学分", "overload怎么申请"), ("选几门课", "underload怎么申请"), ("GIP是什么", "Semester in Australia"), ("SIA", "GIP"), ("毕业延期", "最多 3 个月"), ("学生签证过期了怎么办", "【澳洲校区】"), ("休学要回国吗", "eVAL"), ("学生签证过期了", "ISP 柜台"), ("eExam要带什么", "HB/2B"), ("学费交晚了成绩会被扣住吗", "encumbrance"),
    ("学费没交会怎么样", "encumbrance"), ("学校有校车吗", "Sunway Shuttle Bus"), ("shuttle bus", "Sunway Shuttle Bus"),
    ("PTPTN是什么", "马来西亚公民"), ("作业交完要注意什么", "确认提交"), ("student pass什么时候可以续", "Student Pass Renewal"),
    ("学校在哪里", "Jalan Lagoon Selatan"), ("公共假期要上课吗", "雪兰莪州"),
])
def test_topics_get_their_answer(kb, question, expected):
    assert expected in (_answer(kb, question) or ""), question


@pytest.mark.parametrize("question", ["食堂哪家好吃", "图书馆几点关门", "租房", "我是学生",
                                      "FIT2004考试难吗", "怎么申请奖学金", "银行卡丢了怎么办",
                                      # 期末考试 decides these scores, so no single answer is sure.
                                      "期末考试考什么",
                                      "多少分及格",
                                      "2026下半年入学要准备什么"])
def test_other_questions_are_left_alone(kb, question):
    assert _answer(kb, question) is None
