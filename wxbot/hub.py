"""Ask Monash Hub's model-free /ask endpoint and turn its answer into a Chinese WeChat message.

We ask with ?locale=zh. Official FAQ answers and page titles then come back in Chinese already
(with a ``translation`` marker saying how they were translated); Handbook answers come back as
English plus translation keys, which hub_i18n renders the way the website does. The official
link always goes with the answer, so the English original is one tap away.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp
import jieba

from . import config
from .hub_i18n import Cached, HubI18n

log = logging.getLogger(__name__)

# How much we trust each Monash Hub answer type.
#   strong - answered from parsed Handbook fields for a named unit.
#   medium - the closest curated FAQ; can be the wrong FAQ, so it is framed as "closest".
#   weak   - a list of possibly relevant official pages.
STRENGTH = {
    "handbook_requisite": "strong",
    "handbook_assessment": "strong",
    "handbook_offering": "strong",
    "handbook_workload": "strong",
    "handbook_overview": "strong",
    "handbook_outcomes": "strong",
    "subjective": "strong",
    "official_faq": "medium",
    "official_search": "weak",
}
MAX_TEXT = 300
MAX_ROWS = 6
# The bot's readers are Monash Malaysia students (马莫百科): Australia-only pages go last. Malaysia and
# all-campus pages keep the Hub's relevance order - ranking every Malaysia page first put a pharmacy
# page above "internal course transfer" for 转专业.
CAMPUS_RANK = {"malaysia": 0, "all": 0, "australia": 2}


@dataclass
class HubError:
    """Monash Hub could not be asked (down, deploying, timed out) - not the same as "no answer"."""
    reason: str

# Monash Hub's wording for what a translation is (TranslationNotice.vue), shortened for a chat.
TRANSLATION_LABEL = {"machine": "translation.label.machine", "mixed": "translation.label.mixed",
                     "human": "translation.label.human"}
AUSTRALIA_NOTE = "📍 以上内容取自 Monash 澳大利亚校区网站，马来西亚校区的规定可能不同，请以 monash.edu.my 为准。"

_i18n = Cached(config.HUB_I18N_DIR)


@dataclass
class HubAnswer:
    strength: str      # strong | medium | weak
    text: str
    answer_type: str


def search_link(question: str) -> str:
    """Monash Hub's search page for a question: the same answer card the bot read, plus the units,
    degrees and official pages that match. For replies that have no page of their own on the Hub."""
    q = " ".join((question or "").split())[:40]
    return f"{config.HUB_SITE}/search?q={quote(q)}"


def _clip(text: str, n: int = MAX_TEXT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


_HOURS = re.compile(r"^(\d+(?:\.\d+)?) hours?$")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _cell(i18n: HubI18n, block: dict[str, Any], row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    kind = (block.get("terms") or {}).get(key)
    text = i18n.term(kind, str(value)) if kind else str(value)
    m = _HOURS.match(text)
    return f"{m.group(1)} 小时" if m else text


def _table(i18n: HubI18n, block: dict[str, Any]) -> list[str]:
    keys = block.get("keys") or []
    col_keys = block.get("column_keys") or []
    headers = [i18n.t(k) or c for k, c in zip(col_keys, block.get("columns") or [])] if col_keys else []
    lines = []
    # "#" columns carry no meaning in a chat list; the other headers say what the cells are.
    shown = [(k, h) for k, h in zip(keys, headers or keys) if h not in ("#",)]
    if headers:
        lines.append("（" + "｜".join(h for _, h in shown) + "）")
    for row in (block.get("rows") or [])[:MAX_ROWS]:
        cells = [_cell(i18n, block, row, k) or "—" for k, _ in shown]
        lines.append("· " + "｜".join(cells))
    extra = len(block.get("rows") or []) - MAX_ROWS
    if extra > 0:
        lines.append(f"· …还有 {extra} 项")
    caption = i18n.say(block.get("caption_key"), block.get("caption"), block.get("caption_params"))
    if caption:
        lines.append(caption)
    return lines


def _requisites(i18n: HubI18n, block: dict[str, Any]) -> list[str]:
    kind = i18n.term("requisiteType", block.get("requisite_type") or "")
    parts = []
    for g in block.get("groups") or []:
        joiner = f" {i18n.term('connector', g.get('connector') or 'AND')} "
        items = [str(i.get("code") or i.get("unit_code") or i.get("label") or "") if isinstance(i, dict) else str(i)
                 for i in g.get("items") or []]
        items = [i for i in items if i]
        if items:
            parts.append(joiner.join(items))
        elif g.get("description"):
            parts.append(_clip(g["description"], 200))
    return [f"{kind}：" + "；".join(parts)] if parts else []


def _blocks(i18n: HubI18n, blocks: list[dict[str, Any]], handbook: bool = False) -> list[str]:
    out: list[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "verdict":
            out.append(i18n.say(b.get("key"), b.get("text"), b.get("params"), b.get("terms")))
        elif t == "text":
            title = i18n.say(b.get("title_key"), b.get("title"))
            body = b.get("text") or ""
            if handbook and not _CJK.search(body):
                # Handbook prose has no reviewed Chinese, and the website never machine-translates
                # it. A paragraph of English in a Chinese chat reads as noise; point to it instead.
                out.append(f"【{title or 'Handbook 说明'}】英文原文见下方 Handbook 官网链接")
                continue
            if title:
                out.append(f"【{title}】")
            out.append(_clip(body))
        elif t == "table":
            out.extend(_table(i18n, b))
        elif t == "requisite_group":
            out.extend(_requisites(i18n, b))
        elif t == "list":
            for item in (b.get("items") or [])[:MAX_ROWS]:
                out.append("· " + _clip(item if isinstance(item, str) else str(item.get("text") or item), 150))
    return [line for line in out if line]


def _translation_note(i18n: HubI18n, tr: dict[str, Any] | None) -> str | None:
    if not tr:
        return None
    kind = "mixed" if tr.get("machine") and tr.get("reviewed") else "machine" if tr.get("machine") else "human"
    label = i18n.t(TRANSLATION_LABEL[kind]) or ""
    note = f"ℹ️ 中文为{label.rstrip('。')}，以官网英文原文为准。" if label else "ℹ️ 中文为翻译，以官网英文原文为准。"
    if tr.get("stale"):
        note += (i18n.t("translation.stale") or "")
    return note


def year_notice(code: str, missing: int | None, year: int | None) -> str | None:
    """When the default Handbook dropped a unit and we read an earlier one (the site says the same)."""
    if not (missing and year and missing != year):
        return None
    return (f"ℹ️ {code} 不在 {missing} 年 Handbook 中（可能已改课程代码或撤课），以下是 {year} 年 Handbook 的内容；"
            f"规划明年选课前请向学院确认。")


def format_answer(data: dict[str, Any], i18n: HubI18n | None = None, notice: str | None = None) -> HubAnswer | None:
    i18n = i18n or _i18n.get()
    atype = data.get("answer_type") or ""
    strength = STRENGTH.get(atype)
    if not strength:
        return None
    lines: list[str] = []

    if atype == "official_search":
        items = []
        for b in data.get("blocks") or []:
            if b.get("type") == "page_list":
                items = b.get("items") or []
        # sorted() is stable, so the Hub's relevance order holds within each campus group.
        items = sorted(items, key=lambda p: CAMPUS_RANK.get(p.get("applies_to") or "", 1))[:3]
        if not items:
            return None
        lines.append("Monash Hub 里找到这些相关的官方页面：")
        machine = None
        for n, p in enumerate(items, 1):
            title = p.get("title") or ""
            where = {"australia": "（澳洲校区）", "malaysia": "（马来西亚校区）"}.get(p.get("applies_to") or "", "")
            # Monash Hub now puts the campus in the title itself ("费用和资金（马来西亚校区）").
            if where and (where.strip("（）") in title or ("澳大利亚" in title and "澳洲" in where)):
                where = ""
            lines.append(f"{n}. {title}{where}")
            if _useful_summary(p.get("summary")):
                # The page's own summary (the Hub's translation of it), so every hit says something
                # before anyone taps. The top hit gets the longest one.
                lines.append("   " + _brief(p["summary"], 90 if n == 1 else 60))
            if p.get("slug"):
                # Every page has a Chinese version on Monash Hub, not only the top hit.
                lines.append(f"   📘 中文全文：{config.HUB_SITE}/guides/{p['slug']}")
            lines.append(f"   🔗 {p.get('url')}")
            machine = machine or p.get("translation")
        if machine:
            lines.append("ℹ️ 标题和摘要为翻译，以官网英文原文为准。")
        lines.extend(_suggestions(data))
        return HubAnswer(strength, "\n".join(lines), atype)

    title = i18n.say(data.get("title_key"), data.get("title"), data.get("title_params"))
    lines.append(f"最接近的官方说明：{title}" if atype == "official_faq" else title)
    if notice:
        lines.append(notice)
    lines.extend(_blocks(i18n, data.get("blocks") or [], handbook=bool(data.get("unit_code"))))
    caveat = i18n.say(data.get("caveat_key"), data.get("caveat"))
    if caveat:
        lines.append(f"⚠️ {_clip(caveat, 200)}")
    note = _translation_note(i18n, data.get("translation"))
    if note:
        lines.append(note)
    if data.get("applies_to") == "australia":
        lines.append(AUSTRALIA_NOTE)

    for s in data.get("sources") or []:
        if s.get("url"):
            label = "Handbook 官网" if s.get("kind") == "handbook" else "官网原文"
            lines.append(f"🔗 {label}：{s['url']}")
    lines.extend(_hub_links(data))
    if atype == "official_faq":
        lines.extend(_suggestions(data))
    return HubAnswer(strength, "\n".join(lines), atype)


def _hub_links(data: dict[str, Any]) -> list[str]:
    """Where the answer is on Monash Hub: the guide page an FAQ comes from (it shows the FAQ with the
    whole page in Chinese), the unit, and any page the answer links to. Each URL once."""
    links: dict[str, str] = {}
    if data.get("page_slug"):
        links[f"{config.HUB_SITE}/guides/{data['page_slug']}"] = "📘 Monash Hub 中文全文"
    if data.get("unit_code"):
        links.setdefault(f"{config.HUB_SITE}/units/{data['unit_code']}", "📘 Monash Hub")
    for b in data.get("blocks") or []:
        to = b.get("to") if b.get("type") == "link" else None
        if isinstance(to, str) and to.startswith("/"):
            links.setdefault(config.HUB_SITE + to, "📘 Monash Hub")
    return [f"{label}：{url}" for url, label in links.items()]


def _useful_summary(text: str | None) -> bool:
    """A Chinese sentence, not navigation crumbs ("学位课程与课程信息 • Handbook • 团队领导 …")."""
    return _zh(text) and (text or "").count("•") < 2


def teach_out_lines(i18n: HubI18n, unit: dict[str, Any] | None) -> list[str]:
    """The faculty's notice that a unit is being taught out and what replaces it. The wording is the
    faculty's and stays in English, as on the Hub's unit page (TeachOutNotice.vue)."""
    notice = (unit or {}).get("teach_out") or {}
    entries = [e for e in notice.get("entries") or [] if e.get("change") or e.get("plan")]
    if not entries:
        return []
    lines = ["📌 " + (i18n.t("teachOut.title") or "学院通知：这门课有变动")]
    for e in entries[:3]:
        who = f"（{e['course']}）" if e.get("course") else ""
        lines.append("· " + "：".join(x for x in (f"{e.get('change') or ''}{who}", e.get("plan") or "") if x))
    sources = notice.get("sources") or {}
    url = next((v.get("url") for v in sources.values() if isinstance(v, dict) and v.get("url")), None)
    lines.append("学院原文照录，请向学院确认是否适用于你的校区和入学年份。" + (f"\n🔗 {url}" if url else ""))
    return lines


def _suggestions(data: dict[str, Any]) -> list[str]:
    """The Hub's related curated questions - phrased so that sending one back gets its answer."""
    asks = [s for s in data.get("suggestions") or [] if isinstance(s, str) and _zh(s)][:2]
    return ["💡 也可以问：" + "　".join(f"「{s}」" for s in asks)] if asks else []


OVERVIEW_BUDGET = 1500      # bytes; a 订阅号 reply is capped at 2048 and may carry a welcome as well
# (overview chars, learning-outcome chars, outcomes shown) - tried in order until the reply fits.
PROFILES = [(170, 60, 4), (130, 46, 4), (100, 36, 4), (80, 28, 3), (60, 24, 3)]


def _brief(text: str, n: int) -> str:
    """At most n characters, ending on a sentence when there is one."""
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n]
    end = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("."))
    return cut[: end + 1] if end >= n // 2 else cut.rstrip("，、 ") + "…"


def _zh(text: str | None) -> bool:
    return bool(text and _CJK.search(text))


def _requisite_lines(i18n: HubI18n, unit: dict[str, Any]) -> list[str]:
    out = []
    for r in unit.get("requisites") or []:
        codes = [str(i.get("code")) for i in r.get("items") or [] if isinstance(i, dict) and i.get("code")]
        kind = i18n.term("requisiteType", r.get("requisite_type") or "") or "要求"
        if codes:
            out.append(f"{kind}：" + f" {i18n.term('connector', r.get('connector') or 'AND')} ".join(codes))
        elif _zh(r.get("description")):
            out.append(f"{kind}：" + _brief(r["description"], 60))
    return out


def _offering_line(i18n: HubI18n, unit: dict[str, Any]) -> str | None:
    by_campus: dict[str, list[str]] = {}
    for o in unit.get("offerings") or []:
        campus = o.get("campus")
        if campus:
            by_campus.setdefault(campus, [])
            if o.get("teaching_period") and o["teaching_period"] not in by_campus[campus]:
                by_campus[campus].append(o["teaching_period"])
    if not by_campus:
        return None
    # The reader is a Monash Malaysia student: their campus first.
    order = sorted(by_campus, key=lambda c: (not c.startswith("马来西亚") and not c.startswith("Malaysia"), c))
    return "📍 开课：" + "；".join(f"{c}（{'、'.join(by_campus[c])}）" if by_campus[c] else c for c in order[:3])


def format_overview(unit: dict[str, Any], i18n: HubI18n | None = None, missing_year: int | None = None) -> HubAnswer:
    """What a student means by "FIT2102 学什么": the unit's summary, learning outcomes and assessment,
    from /units/{code}. The Chinese is the site's own (machine translated, partly reviewed - and it
    says so); text with no Chinese is not pasted, the Handbook link is the way to the original."""
    i18n = i18n or _i18n.get()
    code, year = unit.get("unit_code"), unit.get("academic_year")
    link_year = f"?year={year}" if missing_year else ""
    tail = []
    if unit.get("source_url"):
        tail.append(f"🔗 Handbook 官网：{unit['source_url']}")
    tail.append(f"📘 Monash Hub：{config.HUB_SITE}/units/{code}{link_year}")

    def build(profile: tuple[int, int, int], extras: bool) -> str:
        ov_n, out_n, out_k = profile
        lines = [f"{code} · {unit.get('title') or ''}（{year} Handbook）"]
        meta = [f"{unit['credit_points']} 学分" if unit.get("credit_points") else "", unit.get("level") or "",
                unit.get("faculty") or unit.get("school") or ""]
        lines.append("｜".join(m for m in meta if m))
        notice = year_notice(code, missing_year, year)
        if notice:
            lines.append(notice)
        lines.extend(teach_out_lines(i18n, unit))
        if _zh(unit.get("overview")):
            lines.append("📖 课程简介：" + _brief(unit["overview"], ov_n))
        outcomes = [o for o in unit.get("learning_outcomes") or [] if _zh(o.get("description"))]
        if outcomes:
            lines.append("🎯 学习目标：")
            lines.extend(f"{n}. {_brief(o['description'], out_n)}" for n, o in enumerate(outcomes[:out_k], 1))
            if len(outcomes) > out_k:
                lines.append(f"…共 {len(outcomes)} 条，全文见官网")
        elif unit.get("learning_outcomes") or unit.get("overview"):
            lines.append("📖 简介和学习目标暂无中文，英文原文见官网链接")
        assessments = unit.get("assessments") or []
        if assessments:
            exam = {True: "含考试", False: "Handbook 未列期末考试"}.get(unit.get("has_exam"), "")
            lines.append(f"📝 考核方式（{exam}）：" if exam else "📝 考核方式：")
            for a in assessments[:6]:
                weight = f"{a['weight']}%" if a.get("weight") not in (None, "") else ""
                hurdle = i18n.term("hurdle", a.get("hurdle")) if a.get("hurdle") else ""
                kind = i18n.term("assessmentType", a.get("type")) if a.get("type") else ""
                cells = [_brief(str(a.get("name") or "").strip(), 36), kind, weight + (f"（{hurdle}）" if hurdle else "")]
                lines.append("· " + "｜".join(c for c in cells if c))
        if extras:
            offering = _offering_line(i18n, unit)
            if offering:
                lines.append(offering)
            lines.extend(_requisite_lines(i18n, unit))
        note = _translation_note(i18n, unit.get("translation"))
        if note and (_zh(unit.get("overview")) or outcomes):
            lines.append(note)
        return "\n".join(lines + tail)

    text = build(PROFILES[0], True)
    for profile in PROFILES:
        text = build(profile, True)
        if len(text.encode()) <= OVERVIEW_BUDGET:
            break
    else:
        text = build(PROFILES[-1], False)
    return HubAnswer("strong", text, "handbook_overview")


def not_found_answer(code: str) -> HubAnswer:
    return HubAnswer("strong", f"没有在已收录的各年 Handbook 里找到 {code}。请检查课程代码是否写对，"
                     f"或者到 Monash Hub 按课程名称搜索：\n📘 {config.HUB_SITE}/units", "unit_not_found")


# -- degrees (courses, in Monash's words) ------------------------------------------------------------

# Monash course codes are one faculty letter and four digits (C2001, B2000, S3701). Not the unit
# pattern: that needs three or four letters.
_COURSE_CODE = re.compile(r"(?<![A-Za-z0-9])([ABCDEFLMPSabcdeflmps])([0-9]{4})(?![A-Za-z0-9])")
COURSE_BUDGET = 1500


def course_codes(text: str) -> list[str]:
    seen: list[str] = []
    for letter, digits in _COURSE_CODE.findall(text or ""):
        code = f"{letter.upper()}{digits}"
        if code not in seen:
            seen.append(code)
    return seen


def _campus_order(campuses: list[str]) -> list[str]:
    return sorted(campuses, key=lambda c: (not c.startswith("马来西亚") and not c.startswith("Malaysia"), c))


def course_year_notice(code: str, missing: int | None, year: int | None) -> str | None:
    if not (missing and year and missing != year):
        return None
    return (f"ℹ️ {code} 不在 {missing} 年 Handbook 中（可能停招或改了代码），以下是 {year} 年 Handbook 的内容；"
            f"申请或转学位前请向学院确认。")


def format_course(course: dict[str, Any], i18n: HubI18n | None = None) -> HubAnswer:
    """What a student asking about a degree wants first: what it is, how long and how many credit
    points, where it is taught, its majors/minors and how the structure splits up - with links."""
    i18n = i18n or _i18n.get()
    code, year = course.get("course_code"), course.get("academic_year")
    missing = course.get("not_in_year")
    link_year = f"?year={year}" if missing else ""
    tail = []
    if course.get("source_url"):
        tail.append(f"🔗 Handbook 官网：{course['source_url']}")
    tail.append(f"📘 Monash Hub：{config.HUB_SITE}/courses/{code}{link_year}")

    def build(overview_n: int, parts_n: int) -> str:
        abbr = course.get("abbreviated_name")
        lines = [f"🎓 {code} · {course.get('title') or ''}（{abbr + '，' if abbr else ''}{year} Handbook）"]
        meta = [course.get("course_type") or "",
                f"{course['credit_points']} 学分" if course.get("credit_points") else "",
                f"{course['duration_years']:g} 年" if isinstance(course.get("duration_years"), (int, float)) else "",
                course.get("faculty") or ""]
        lines.append("｜".join(m for m in meta if m))
        if course.get("campuses"):
            lines.append("📍 校区：" + "、".join(_campus_order(list(course["campuses"]))))
        notice = course_year_notice(code, missing, year)
        if notice:
            lines.append(notice)
        if overview_n and _zh(course.get("overview")):
            lines.append("📖 简介：" + _brief(course["overview"], overview_n))
        majors: dict[str, list[str]] = {}
        for a in course.get("areas_of_study") or []:
            kind = a.get("aos_type") or "专业方向"
            if a.get("title") and a["title"] not in majors.setdefault(kind, []):
                majors[kind].append(a["title"])
        for kind, titles in majors.items():
            lines.append(f"🧭 {kind}：" + "、".join(titles[:8]) + ("等" if len(titles) > 8 else ""))
        parts = [c for c in course.get("containers") or [] if c.get("title")]
        if parts and parts_n:
            lines.append("🧱 课程结构：")
            for c in parts[:parts_n]:
                cp = f"（{c['credit_points']} 学分）" if c.get("credit_points") else ""
                lines.append(f"· {_brief(c['title'], 30)}{cp}")
            if len(parts) > parts_n:
                lines.append(f"· …共 {len(parts)} 部分，全部见下方链接")
        note = _translation_note(i18n, course.get("translation"))
        if note:
            lines.append(note)
        return "\n".join(lines + tail)

    for overview_n, parts_n in ((150, 6), (110, 5), (80, 4), (60, 3), (0, 3), (0, 0)):
        text = build(overview_n, parts_n)
        if len(text.encode()) <= COURSE_BUDGET:
            break
    return HubAnswer("strong", text, "course_overview")


# Area of study (major/minor/specialisation) codes: letters then two digits (MMEDCHEM01, ALGSFTWR01).
_AOS_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{4,9}[0-9]{2})(?![A-Za-z0-9])")


def aos_codes(text: str) -> list[str]:
    return list(dict.fromkeys(c.upper() for c in _AOS_CODE.findall(text or "")))


def format_aos(aos: dict[str, Any], i18n: HubI18n | None = None) -> HubAnswer:
    i18n = i18n or _i18n.get()
    code, year, missing = aos.get("aos_code"), aos.get("academic_year"), aos.get("not_in_year")
    names = {c: (u or {}).get("title") for c, u in (aos.get("units") or {}).items()}
    tail = []
    if aos.get("source_url"):
        tail.append(f"🔗 Handbook 官网：{aos['source_url']}")
    tail.append(f"📘 Monash Hub：{config.HUB_SITE}/courses/aos/{code}" + (f"?year={year}" if missing else ""))

    def build(per_part: int, overview_n: int) -> str:
        kind = aos.get("aos_type") or "专业方向"
        lines = [f"🧭 {code} · {aos.get('title') or ''}（{kind}，{year} Handbook）"]
        meta = [aos.get("study_level") or "", f"{aos['credit_points']} 学分" if aos.get("credit_points") else "",
                aos.get("faculty") or ""]
        lines.append("｜".join(m for m in meta if m))
        if missing and year and missing != year:
            lines.append(f"ℹ️ {code} 不在 {missing} 年 Handbook 中，以下是 {year} 年 Handbook 的内容；选专业前请向学院确认。")
        if overview_n and _zh(aos.get("overview")):
            lines.append("📖 简介：" + _brief(aos["overview"], overview_n))
        parts = [c for c in aos.get("containers") or [] if c.get("title")]
        if parts:
            lines.append("🧱 结构：")
        for c in parts[:5]:
            cp = f"（{c['credit_points']} 学分）" if c.get("credit_points") else ""
            items = [i for i in c.get("items") or [] if i.get("code")]
            shown = "、".join(f"{i['code']} {names.get(i['code']) or i.get('name') or ''}".strip()
                             for i in items[:per_part])
            more = f" 等 {len(items)} 门" if len(items) > per_part else ""
            lines.append(f"· {_brief(c['title'], 24)}{cp}" + (f"：{shown}{more}" if shown else ""))
        note = _translation_note(i18n, aos.get("translation"))
        if note:
            lines.append(note)
        return "\n".join(lines + tail)

    for per_part, overview_n in ((8, 120), (5, 80), (3, 60), (2, 0), (0, 0)):
        text = build(per_part, overview_n)
        if len(text.encode()) <= COURSE_BUDGET:
            break
    return HubAnswer("strong", text, "aos_overview")


def course_not_found(code: str) -> HubAnswer:
    return HubAnswer("strong", f"没有在已收录的各年 Handbook 里找到学位 {code}。请检查代码是否写对，"
                     f"或者到 Monash Hub 按学位名称搜索：\n📘 {config.HUB_SITE}/courses", "course_not_found")


# -- finding a unit or degree by its name ------------------------------------------------------------

# What a question says *about* the unit or degree, as opposed to its name. Dropping these jieba
# tokens leaves the name: "编程范式有期末考试吗" -> 编程范式, "计算机科学学士要修多少学分" -> 计算机科学学士.
# Token-level, so a name that merely contains one of them (有机化学, 目的) stays whole.
_ASKING = set("""
有没有 有吗 是不是 是什么 是啥 什么 怎么样 怎么 如何 哪些 哪个 哪几个 多少 几个 几年 读几年 要读 要修 需要 可以 能不能
期末考试 期末 考试 考核 考不考 作业 占比 分数 先修课 先修 前置课 前置 预修 要求 条件 学分 开课 开不开 哪个 学期
学什么 讲什么 学 讲 内容 介绍 难不难 难吗 难 好过吗 好过 工作量 课程代码 代码 专业方向 方向 主修 辅修 校区 学位
马来西亚 马校 大马 澳洲 课程 这门课 那门课 这门 那门 一门 门 课 的 吗 呢 啊 呀 吧 了 有 是 在 不 要 修 开 读 几 个
请问 想问 问下 一下 我 你 这个 那个 哪 啥 还 都 么 能 会
workload exam exams final assessment assessments prerequisite prerequisites prereq prereqs credit credits points
what which is are the does do have has about unit units course courses degree how many much any
""".split())
_EDGE = {"of", "in", "for", "and", "&", "-", "·"}
# Asking-phrases jieba cuts across ("先修课" -> 先 / 修课), taken out before it sees them.
_GLUED = re.compile("先修课|先修|前置课|预修课|预修|期末考试|有没有|是什么|是不是|难不难|考不考|开不开|多少学分|几学分|专业方向")
_PUNCT = re.compile(r"[,，。.!！?？:：;；、“”\"'‘’()（）\[\]【】/|~～]+")
_CJK_CHAR = re.compile(r"[\u4e00-\u9fff]")

UNIT_CUES = ("课", "考试", "期末", "考核", "先修", "前置", "学分", "开课", "学什么", "难不难", "难吗", "工作量",
             "exam", "assessment", "prereq", "unit", "workload")
DEGREE_CUES = ("学士", "硕士", "博士", "学位", "bachelor", "master", "degree", "diploma", "文凭")


def name_phrase(question: str) -> str | None:
    """The longest run of the question that is not asking-words: the likely unit/degree name."""
    chunks: list[list[str]] = [[]]
    for tok in jieba.lcut(_GLUED.sub("|", question or "")):
        if not tok.strip():
            chunks[-1].append(" ")
        elif tok.strip().lower() in _ASKING or _PUNCT.fullmatch(tok.strip()):
            chunks.append([])
        else:
            chunks[-1].append(tok.strip())
    names = []
    for c in chunks:
        words = "".join(c).split()
        while words and words[0].lower() in _EDGE:
            words.pop(0)
        while words and words[-1].lower() in _EDGE:
            words.pop()
        name = " ".join(words)
        # jieba glues particles onto the name ("算法课有考试" -> 算法 / 课有); 算法课, 实习课: the name is before 课.
        while len(name) > 2 and name[-1] in "有的是吗呢了啊呀吧课":
            name = name[:-1]
        if len(name) >= (2 if _CJK_CHAR.search(name) else 4):
            names.append(name)
    return max(names, key=len) if names else None


def has_cue(question: str, cues: tuple[str, ...]) -> bool:
    low = question.lower()
    return any(c in low for c in cues)


def _norm(s: str | None) -> str:
    return re.sub(r"[\s（）()·\-]", "", (s or "").lower())


def pick(results: list[dict[str, Any]], phrase: str, title_key: str = "title") -> dict[str, Any] | None:
    """The one result the phrase clearly names: an exact title, or the only result and its title starts
    with the phrase. Not just "the only result": 计算机科学学士 alone finds 商学学士与计算机科学学士."""
    exact = [r for r in results if _norm(r.get(title_key)) == _norm(phrase)]
    if len(exact) == 1:
        return exact[0]
    if len(results) == 1 and _norm(results[0].get(title_key)).startswith(_norm(phrase)):
        return results[0]
    return None


def unit_candidates(results: list[dict[str, Any]], total: int, phrase: str) -> HubAnswer:
    lines = [f"按「{phrase}」找到这些课程：" if total <= 5 else f"按「{phrase}」找到 {total} 门课程，最相关的几门："]
    for r in results[:5]:
        lines.append(f"· {r['unit_code']} {r.get('title') or ''}")
    lines.append("回复课程代码加问题，比如「" + results[0]["unit_code"] + " 有期末考试吗」。")
    lines.append(f"📘 更多：{config.HUB_SITE}/units")
    return HubAnswer("medium", "\n".join(lines), "unit_candidates")


def course_candidates(results: list[dict[str, Any]], total: int, phrase: str) -> HubAnswer:
    lines = [f"按「{phrase}」找到这些学位：" if total <= 5 else f"按「{phrase}」找到 {total} 个学位，最相关的几个："]
    for r in results[:5]:
        where = "、".join(_campus_order(list(r.get("campuses") or [])))
        lines.append(f"· {r['course_code']} {r.get('title') or ''}" + (f"（{where}）" if where else ""))
    lines.append("回复学位代码（比如「" + results[0]["course_code"] + "」）看学分、专业方向和课程结构。")
    lines.append(f"📘 更多：{config.HUB_SITE}/courses")
    return HubAnswer("medium", "\n".join(lines), "course_candidates")


# -- talking to Monash Hub ---------------------------------------------------------------------------

class _Budget:
    """WeChat waits 5 s for a 公众号 reply, and one question can take several Hub calls; every call
    gets what is left of one overall budget instead of its own 2.5 s."""

    def __init__(self, seconds: float, per_call: float):
        self.end = time.monotonic() + seconds
        self.per_call = per_call

    def left(self) -> float:
        return min(self.per_call, self.end - time.monotonic())


async def _call(session: aiohttp.ClientSession, method: str, path: str, budget: _Budget | float, **kw: Any
                ) -> tuple[int, Any]:
    """(HTTP status, JSON body); (0, None) when the hub cannot be reached in time."""
    timeout = budget.left() if isinstance(budget, _Budget) else budget
    if timeout < 0.2:
        return 0, None
    try:
        async with session.request(method, f"{config.HUB_API}{path}", timeout=aiohttp.ClientTimeout(total=timeout),
                                   **kw) as resp:
            body = await resp.json() if resp.status == 200 else None
            return resp.status, body
    except Exception as exc:
        log.warning("hub %s %s failed: %s", method, path, exc or type(exc).__name__)
        return 0, None


# -- official links -> their pages on Monash Hub --------------------------------------------------------

_URL = re.compile(r"https?://[^\s，。；）)」】]+")


def _url_key(url: str) -> str:
    """Two spellings of one official page match: no scheme, no www., no query or trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return (host + parts.path.rstrip("/")).lower()


class GuideIndex:
    """Official page URL -> the slug of its guide page on Monash Hub. With it, any official link the bot
    sends (a taught answer, the owner's reply, an FAQ's source) goes out with the Hub's Chinese page
    under it. /guides lists every indexed page (762 on 2026-10-04), read in the background so no
    answer waits for it, and again every REFRESH_S."""
    REFRESH_S = 6 * 3600
    RETRY_S = 300
    PAGE = 500

    def __init__(self) -> None:
        self.by_url: dict[str, str] = {}
        self.next_load = 0.0
        self._task: asyncio.Task[None] | None = None

    def refresh_soon(self, session: aiohttp.ClientSession | None) -> None:
        if session is None or time.monotonic() < self.next_load or (self._task and not self._task.done()):
            return
        self._task = asyncio.ensure_future(self._load(session))

    async def _load(self, session: aiohttp.ClientSession) -> None:
        by_url: dict[str, str] = {}
        offset = 0
        while True:
            status, body = await _call(session, "GET", "/guides", 20.0, params={"limit": self.PAGE, "offset": offset})
            results = (body or {}).get("results")
            if results is None:
                # Keep what we had and try again soon; a reply without the Hub page still has the search link.
                self.next_load = time.monotonic() + self.RETRY_S
                return
            for p in results:
                if p.get("url") and p.get("slug"):
                    by_url.setdefault(_url_key(p["url"]), p["slug"])
            offset += len(results)
            if not results or offset >= (body.get("total") or 0):
                break
        self.by_url = by_url
        self.next_load = time.monotonic() + self.REFRESH_S
        log.info("hub guides: %d official pages", len(by_url))

    def link(self, url: str) -> str | None:
        slug = self.by_url.get(_url_key(url))
        return f"{config.HUB_SITE}/guides/{slug}" if slug else None


guides = GuideIndex()


def with_guides(text: str) -> str:
    """Under every line with an official link, the same page on Monash Hub, unless the reply has it."""
    seen = set(_URL.findall(text))
    out = []
    for line in text.split("\n"):
        out.append(line)
        for url in _URL.findall(line):
            link = None if url.startswith(config.HUB_SITE) else guides.link(url)
            if link and link not in seen:
                seen.add(link)
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f"{indent}📘 Monash Hub 中文全文：{link}")
    return "\n".join(out)


def _down(status: int) -> bool:
    return status == 0 or status >= 500


async def ask_course(session: aiohttp.ClientSession, code: str, budget: _Budget | float = 2.5
                     ) -> HubAnswer | HubError:
    status, course = await _call(session, "GET", f"/courses/{code}", budget, params={"locale": "zh"})
    if status == 404:
        return course_not_found(code)
    if not course:
        return HubError(f"/courses/{code} {status}")
    return format_course(course)


async def find_unit(session: aiohttp.ClientSession, question: str, budget: _Budget | float
                    ) -> tuple[dict[str, Any] | None, HubAnswer | None]:
    """(the unit the question names, or None; a candidate list when the name is ambiguous)."""
    phrase = name_phrase(question)
    if not phrase:
        return None, None
    status, found = await _call(session, "GET", "/units", budget, params={"q": phrase, "locale": "zh", "limit": 8})
    results = (found or {}).get("results") or []
    if not results:
        return None, None
    chosen = pick(results, phrase)
    if chosen:
        return chosen, None
    # Only a list of units whose titles carry the words: "考试时间表" and "选课" are not unit names,
    # and the Hub's full-text matches for them are noise under the official pages.
    if _norm(phrase) not in _norm(results[0].get("title")):
        return None, None
    return None, unit_candidates(results, found.get("total") or len(results), phrase)


async def find_course(session: aiohttp.ClientSession, question: str, budget: _Budget | float
                      ) -> HubAnswer | None:
    phrase = name_phrase(question)
    if not phrase:
        return None
    status, found = await _call(session, "GET", "/courses", budget, params={"q": phrase, "locale": "zh", "limit": 8})
    results = (found or {}).get("results") or []
    chosen = pick(results, phrase) if results else None
    if not chosen and found and found.get("academic_year"):
        # The default year can drop a degree that is still being taught out (C2001 is not in 2027).
        status, older = await _call(session, "GET", "/courses", budget,
                                    params={"q": phrase, "locale": "zh", "limit": 8,
                                            "year": int(found["academic_year"]) - 1})
        chosen = pick((older or {}).get("results") or [], phrase)
    if chosen:
        answer = await ask_course(session, chosen["course_code"], budget)
        return answer if isinstance(answer, HubAnswer) else None
    if results:
        return course_candidates(results, found.get("total") or len(results), phrase)
    return None


async def ask(session: aiohttp.ClientSession, question: str, timeout: float = 2.5, budget_s: float = 3.4
              ) -> HubAnswer | HubError | None:
    """Monash Hub's answer, in Chinese, or HubError when the Hub could not be reached. On top of /ask:
    - a degree code (C2001) or a degree name ("计算机科学学士") gets the degree card from /courses;
    - an answer that is only a link ("FIT2102学什么") becomes the unit's summary, outcomes and assessment;
    - when the default Handbook year has dropped the unit (FIT2004 is gone from 2027), read the latest
      year that lists it, and say so;
    - a unit asked about by name ("编程范式有考试吗") is found by title and asked about by code."""
    budget = _Budget(budget_s, timeout)
    unit_like = bool(re.search(r"(?<![A-Za-z0-9])[A-Za-z]{3,4}\s?-?\s?[0-9]{4}(?![A-Za-z0-9])", question))
    courses = [] if unit_like else course_codes(question)
    if courses:
        return await ask_course(session, courses[0], budget)
    for code in ([] if unit_like else aos_codes(question)[:1]):
        status, aos = await _call(session, "GET", f"/courses/aos/{code}", budget, params={"locale": "zh"})
        if aos:
            return format_aos(aos)
        if _down(status):
            return HubError(f"/courses/aos/{code} {status}")
        # 404: letters and two digits that are not an area of study ("WEEK10"); ask as usual.

    answer = await _ask(session, question, budget)
    if isinstance(answer, HubError) or unit_like:
        return answer
    if answer and answer.strength == "strong":
        return answer
    if answer and answer.answer_type == "official_faq":
        return answer       # a curated answer to a policy question; the words were not a name

    found: HubAnswer | None = None
    if has_cue(question, DEGREE_CUES):
        found = await find_course(session, question, budget)
    elif has_cue(question, UNIT_CUES):
        unit, found = await find_unit(session, question, budget)
        if unit:
            by_code = await _ask(session, f"{unit['unit_code']} {question}", budget)
            if isinstance(by_code, HubAnswer) and by_code.strength == "strong":
                by_code.text = f"（按课程名找到：{unit['unit_code']} · {unit.get('title') or ''}）\n" + by_code.text
                return by_code
    if found and found.strength == "strong":
        return found
    if found and answer:
        # A list of candidate units/degrees, after the official pages the words also matched.
        return HubAnswer("medium", answer.text + "\n\n" + found.text, f"{answer.answer_type}+{found.answer_type}")
    return found or answer


async def _ask(session: aiohttp.ClientSession, question: str, budget: _Budget) -> HubAnswer | HubError | None:
    payload = {"query": question[:500]}
    status, data = await _call(session, "POST", "/ask", budget, params={"locale": "zh"}, json=payload)
    if not data:
        return HubError(f"/ask {status}") if _down(status) else None
    code, missing, year = data.get("unit_code"), None, None

    if data.get("answer_type") == "unit_not_found" and code:
        status, unit = await _call(session, "GET", f"/units/{code}", budget, params={"locale": "zh"})
        if status == 404:
            return not_found_answer(code)
        if not unit:
            return HubError(f"/units/{code} {status}")
        missing, year = unit.get("not_in_year") or (data.get("title_params") or {}).get("year"), unit.get("academic_year")
        status, data = await _call(session, "POST", "/ask", budget, params={"locale": "zh"},
                                   json={**payload, "year": year})
        if not data:
            return HubError(f"/ask {status}")

    if data.get("answer_type") in ("handbook_overview", "handbook_outcomes") and code:
        # Outcomes come back in English from /ask; the unit page has the site's Chinese for them.
        params = {"locale": "zh", **({"year": year} if year else {})}
        status, unit = await _call(session, "GET", f"/units/{code}", budget, params=params)
        if unit:
            return format_overview(unit, missing_year=missing)

    if data.get("answer_type") == "handbook_workload" and code:
        # /ask leaves the workload paragraph in English; the unit detail has the site's Chinese for it.
        english = [b for b in data.get("blocks") or [] if b.get("type") == "text" and not _zh(b.get("text"))]
        answer_year = (data.get("title_params") or {}).get("year") or year
        if english:
            params = {"locale": "zh", **({"year": answer_year} if answer_year else {})}
            status, unit = await _call(session, "GET", f"/units/{code}", budget, params=params)
            if unit and _zh(unit.get("workload_requirements")):
                english[0]["text"] = unit["workload_requirements"]

    notice = year_notice(code or "", missing, year)
    atype = data.get("answer_type") or ""
    if code and (atype.startswith("handbook_") or atype == "subjective"):
        # The faculty's teach-out notice ("No longer offered - replace with FIT3234") is on the unit
        # detail, not in /ask; a student asking about FIT2004's exam needs to see it too.
        answer_year = (data.get("title_params") or {}).get("year") or year
        params = {"locale": "zh", **({"year": answer_year} if answer_year else {})}
        status, unit = await _call(session, "GET", f"/units/{code}", budget, params=params)
        extra = teach_out_lines(_i18n.get(), unit)
        notice = "\n".join(x for x in [notice, *extra] if x) or None
    return format_answer(data, notice=notice)
