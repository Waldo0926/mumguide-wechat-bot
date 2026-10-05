"""What the bot says. Pure logic: no WeChat I/O here, so it can be exercised from the CLI and tests."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import aiohttp

from . import config, hub, mamo
from .kb import KB, Match

GREETINGS = {"你好", "您好", "hi", "hello", "在吗", "在不在", "帮助", "help", "菜单", "你是谁", "?", "？", "嗨", "哈喽"}
_UNIT_CODE = re.compile(r"(?<![A-Za-z])([A-Za-z]{3,4})\s?-?\s?(\d{4})(?!\d)")
# Words that look like a unit prefix in front of a year: "Nov 2026", "Sem 2026", "Year 2027". Monash
# Hub checks prefixes against its database; we cannot, and a false code would make answer() ignore
# a taught Q&A ("Nov 2026 什么时候考试").
NOT_PREFIXES = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC",
                "JUNE", "JULY", "YEAR", "TERM", "SEM", "WEEK", "DAY", "PAGE", "ROOM", "TEL", "FAX", "CODE",
                "PIN", "WIN", "MAC", "IOS", "TOP", "FROM", "TILL", "SINCE", "INTO", "ONTO", "AND", "THE", "FOR"}


# Questions about the bot itself ("你能干什么", "你是什么大模型"): the answer is the introduction, not a
# question for the owner. Short questions only, so "你能帮我查 FIT2102 吗" still goes to the knowledge.
_YOU = r"(你|您|机器人|小助手|助手|bot)"
_ABOUT_ME = re.compile(
    _YOU + r"(都|还)?(能|会|可以)(干|做|帮|回答|答|查|问)?(些)?(什么|啥|哪些)"
    r"|" + _YOU + r"(是|叫)(谁|什么|啥|哪个)|" + _YOU + r"是(不是)?(真人|人|ai|机器人|大模型|gpt|chatgpt)"
    r"|" + _YOU + r"(有)?(什么|哪些)功能|什么(大)?模型", re.I)
# A bare "怎么用" / "能问什么" with nothing else in it is about the bot too.
_ABOUT_SHORT = re.compile(r"^(怎么用|如何使用|使用说明|能问什么|可以问什么|问什么|有什么功能|有哪些功能|功能介绍|能干嘛|能干什么)$")


def is_greeting(text: str) -> bool:
    low = text.lower().strip(" !！。.~?？")
    return low in GREETINGS or len(low) < 2


def is_about_me(text: str) -> bool:
    low = text.lower().strip(" !！。.~?？")
    return len(low) <= 16 and not codes_in(low) and bool(_ABOUT_ME.search(low) or _ABOUT_SHORT.match(low))


def unit_codes(text: str) -> set[str]:
    return {f"{a.upper()}{b}" for a, b in _UNIT_CODE.findall(text) if a.upper() not in NOT_PREFIXES}


def codes_in(text: str) -> set[str]:
    """Unit and degree codes: what a question is specifically about."""
    return unit_codes(text) | set(hub.course_codes(text)) | set(hub.aos_codes(text))


HUMAN = {"人工", "转人工", "找waldo", "找 waldo"}
HUB_DOWN = "查询服务暂时连不上 🙏 请过几分钟再发一次这个问题。"


@dataclass
class Out:
    to: str
    text: str
    mention_owner: bool = False  # also @ the owner, on channels that support it
    note: str = ""  # the 待答 note to send him privately


def intro() -> str:
    how = "直接把问题发给我就行，比如："
    return (
        "你好，我是 Monash 问答小助手 🤖\n"
        f"{how}\n"
        "· 课程：FIT2102 有期末考试吗 / 编程范式学什么 / FIT1045 的先修课\n"
        "· 学位：C2001 要修多少学分 / 计算机科学学士有哪些专业方向\n"
        "· 政策：怎么申请延期交作业 / 怎么退课 / WAM 怎么算 / 学生签证怎么续签\n"
        "· “马莫百科”公众号写过的内容\n"
        "我不是聊天大模型，不会编答案：回答都来自 Monash 官网、Handbook 和“马莫百科”公众号，并附上链接方便你核实。"
        f"答不上来的我会转给 {config.OWNER_NAME} 人工回复。\n"
        f"📘 课程、学位和官网政策的中文版都在 Monash Hub：{config.HUB_SITE}"
    )


def intro_short() -> str:
    """Tacked onto a custom 关注语, which already invites questions - just show what to ask."""
    return ("🤖 自动问答已开启，可以直接问，比如：\n"
            "· FIT2102 有期末考试吗\n"
            "· 学生签证怎么续签\n"
            f"答不上来的会转给 {config.OWNER_NAME} 人工回复。\n"
            f"📘 Monash Hub：{config.HUB_SITE}")


ADMIN_HELP = """管理命令（只有你能用）：
教 问题 | 答案 [| 链接]  —— 新增问答
也问 编号 另一种问法    —— 给问答加同义问法
改 编号 新答案 [| 链接]  —— 修改答案
删 编号 / 看 编号        —— 删除 / 查看问答
查 关键词              —— 看知识库里会匹配到什么
试 问题                —— 模拟回答并显示命中来源
待答                  —— 没答上来的问题
答 编号 答案 [| 链接]    —— 回复提问人，并把这组问答记住
                        （也可以直接发「编号 答案」，或引用待答通知直接写答案）
忽略 编号              —— 跳过一个待答问题
收录 公众号文章链接      —— 把马莫百科文章加进知识库（直接发链接也行）
删文 编号              —— 移除一篇文章
关注语 [新内容]         —— 查看 / 设置公众号的关注自动回复
统计                  —— 知识库和使用情况"""

_CMD = re.compile(r"^[/#]?(教|也问|改|删|看|查|试|待答|答|忽略|收录|删文|关注语|统计|管理|管理帮助)(?:\s+|$|(?=#?\d))(.*)$", re.S)
_ID = re.compile(r"^#?(\d+)\s*(.*)$", re.S)
_PENDING_NOTE = re.compile(r"待答\s*#(\d+)")


def _split_answer(rest: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in re.split(r"\s*[|｜]\s*", rest)]
    if len(parts) >= 2 and re.match(r"https?://", parts[-1]):
        return " | ".join(parts[:-1]).strip(), parts[-1]
    return rest.strip(), None


def _short(user_id: str) -> str:
    if user_id.startswith("mp:"):
        return "公众号用户 " + user_id[3:11]
    return user_id.split("@")[0][:10]


def _can_push(user_id: str) -> bool:
    """A personal 订阅号 can only answer inside the 5s window of a user's own message."""
    return not user_id.startswith("mp:")


class Brain:
    def __init__(self, kb: KB, http: aiohttp.ClientSession, admins: set[str]):
        self.kb = kb
        self.http = http
        self.admins = admins
        self.last_question: dict[str, tuple[float, str]] = {}
        self.recent: dict[str, list[float]] = {}
        self._deferred: list[Out] = []  # messages a command sends to someone else (「答」 replies to the asker)

    # -- answering ------------------------------------------------------------------------------
    @staticmethod
    def _with_hub(reply: str, question: str, sep: str = "\n") -> str:
        """Every answer points to Monash Hub: each official link gets the same page on the Hub under it,
        and a reply with no Hub page at all (an article, a taught answer without a link) gets the Hub's
        search for the question, which shows its answer and related pages."""
        reply = hub.with_guides(reply)
        if config.HUB_SITE in reply:
            return reply
        return reply + sep + "📘 Monash Hub 上查看更多：" + hub.search_link(question)

    def _fmt_qa(self, m: Match, *, unsure: bool) -> str:
        row = self.kb.get_qa(m.id)
        text = row["answer"]
        if unsure:
            text = f"你问的是不是「{m.phrase}」？\n{text}"
        if row["url"]:
            text += f"\n🔗 {row['url']}"
        return text

    def _fmt_articles(self, arts: list[Match]) -> str:
        lines = ["“马莫百科”公众号相关文章："]
        for i, m in enumerate(arts, 1):
            row = self.kb.get_article(m.id)
            lines.append(f"{i}. {row['title']}\n{row['url']}")
        return "\n".join(lines)

    async def answer(self, question: str) -> tuple[str | None, str, str]:
        """(reply or None, route, detail). route is qa | hub | article | mixed | miss."""
        hub.guides.refresh_soon(self.http)
        qa = self.kb.match_qa(question)
        top = qa[0] if qa else None
        # A question about a unit is for the Handbook, unless what Waldo taught names that unit:
        # "FIT2004 马来西亚开吗" must not be answered by a Q&A about where the Malaysia campus is.
        codes = codes_in(question)
        if top and codes and not codes & codes_in(top.phrase):
            top = None
        if top and top.score >= config.QA_STRONG:
            self.kb.hit(top.id)
            return self._with_hub(self._fmt_qa(top, unsure=False), question), "qa", f"qa#{top.id} {top.score:.2f}"

        h = await hub.ask(self.http, question)
        hub_down = isinstance(h, hub.HubError)
        if hub_down:
            h = None
        if h and h.strength == "strong":
            return self._with_hub(h.text, question), "hub", h.answer_type

        arts = [m for m in self.kb.match_articles(question, limit=2) if m.score >= config.ARTICLE_MIN]
        arts = [m for m in arts if m.score >= 0.8 * arts[0].score]
        if top and top.score >= config.QA_WEAK:
            self.kb.hit(top.id)
            reply = self._fmt_qa(top, unsure=True)
            if arts:
                reply += "\n\n" + self._fmt_articles(arts)
            return self._with_hub(reply, question), "qa", f"qa#{top.id} {top.score:.2f} (weak)"

        parts, route = [], []
        # A clearly matching 马莫百科 article is usually closer than Monash Hub's nearest FAQ,
        # which can be about something else entirely, so it goes first.
        arts_first = bool(arts) and arts[0].score >= config.ARTICLE_LEAD
        if arts_first:
            parts.append(self._fmt_articles(arts))
            route.append("article")
        if h and h.strength == "medium":
            parts.append(h.text)
            route.append("hub")
        if arts and not arts_first:
            parts.append(self._fmt_articles(arts))
            route.append("article")
        if h and h.strength == "weak":
            # The official pages go in after the articles too: their Chinese pages are on Monash Hub.
            parts.append(h.text)
            route.append("hub")
        if parts:
            body = self._with_hub("\n\n".join(parts), question, sep="\n\n")
            detail = " ".join(filter(None, [h.answer_type if h else "", f"{len(arts)} articles" if arts else ""]))
            return (body + "\n\n如果没解决你的问题，回复「人工」我帮你转给 " + config.OWNER_NAME + "。",
                    "+".join(route), detail)
        if hub_down:
            # Monash Hub is restarting or unreachable: a passing outage, not a question for Waldo
            # (alerts.py already tells him the Hub is down).
            return HUB_DOWN, "hub_down", ""
        return None, "miss", ""

    # -- entry point ------------------------------------------------------------------------------
    def _as_answer(self, text: str, quoted: str) -> str | None:
        """Admin shortcuts for 「答」: quoting a 待答 notification, or "12 answer" where 12 is an
        open pending question. Returns the 「答」 arguments, or None."""
        m = _PENDING_NOTE.search(quoted or "")
        if m:
            return f"{m.group(1)} {text}"
        m = _ID.match(text)
        if m and m.group(2).strip():
            p = self.kb.get_pending(int(m.group(1)))
            if p and p["status"] == "open":
                return text
        return None

    async def handle(self, user_id: str, text: str, quoted: str = "") -> list[Out]:
        text = text.strip()
        is_admin = user_id in self.admins

        if is_admin:
            cmd = _CMD.match(text)
            answer_args = None if cmd else self._as_answer(text, quoted)
            if cmd or answer_args:
                self.kb.log(user_id, text, "command")
                reply = (await self._command(cmd.group(1), cmd.group(2).strip()) if cmd
                         else await self._command("答", answer_args))
                outs, self._deferred = [Out(user_id, reply)] + self._deferred, []
                return outs
            if mamo.ARTICLE_URL.fullmatch(text):
                return [Out(user_id, await self._command("收录", text))]

        if not is_admin and self._rate_limited(user_id):
            return []
        low = text.lower().strip(" !！。.~")
        if is_greeting(text) or is_about_me(text):
            return [Out(user_id, intro())]
        if low in HUMAN:
            return self._escalate(user_id, explicit=True)

        self.last_question[user_id] = (time.time(), text)
        reply, route, detail = await self.answer(text)
        self.kb.log(user_id, text, route, detail)
        if reply:
            return [Out(user_id, reply)]
        if is_admin:
            return [Out(user_id, "（没命中任何知识。换成普通用户这里会转给你。可以用「教 问题 | 答案」教我。）")]
        return self._escalate(user_id, explicit=False)

    def _rate_limited(self, user_id: str) -> bool:
        now = time.time()
        stamps = [t for t in self.recent.get(user_id, []) if now - t < 60]
        stamps.append(now)
        self.recent[user_id] = stamps
        return len(stamps) > 8

    def _escalate(self, user_id: str, *, explicit: bool) -> list[Out]:
        last = self.last_question.get(user_id)
        if not last or time.time() - last[0] > 3600:
            return [Out(user_id, "把你的问题再发一遍吧，我转给 " + config.OWNER_NAME + "。")] if explicit else []
        question = last[1]
        dup = next((p for p in self.kb.open_pending(200) if p["user_id"] == user_id and p["question"] == question), None)
        if dup:
            return [Out(user_id, f"已经转给 {config.OWNER_NAME} 了，他看到会回复你 🙏")]
        pid = self.kb.add_pending(user_id, question)
        later = ("他看到后会回复你" if _can_push(user_id) else "他补充答案后，你再给我发任意一条消息就能看到")
        outs = [Out(user_id, (f"好的，已经转给 {config.OWNER_NAME}，{later} 🙏" if explicit else
                              f"这个问题我还答不上来 🙏 已经转给 {config.OWNER_NAME}，{later}。\n"
                              f"等的时候可以先在 Monash Hub 搜搜看：{hub.search_link(question)}"))]
        note = self._note(pid, user_id, question)
        outs.extend(Out(a, note) for a in self.note_targets())
        return outs

    @staticmethod
    def _note(pid: int, user_id: str, question: str) -> str:
        return (f"❓ 待答 #{pid}（来自 {_short(user_id)}）\n{question}\n\n"
                f"回复「答 {pid} 你的答案」会发给对方并记住这组问答；「忽略 {pid}」跳过。")

    def note_targets(self) -> list[str]:
        return sorted(self.admins)

    def learn(self, asker: str, answer: str) -> int | None:
        """The owner answered an asker himself: close their latest open question and
        remember the pair. Returns the new Q&A id, or None when the asker had nothing open."""
        p = next((r for r in reversed(self.kb.open_pending(500)) if r["user_id"] == asker), None)
        if not p or not answer.strip():
            return None
        qa_id = self.kb.add_qa(p["question"], answer.strip())
        self.kb.close_pending(p["id"], "answered", qa_id)
        self.kb.log(asker, p["question"], "learned", f"qa#{qa_id}")
        return qa_id

    # -- admin commands ---------------------------------------------------------------------------
    async def _command(self, cmd: str, rest: str) -> str:
        kb = self.kb
        if cmd in ("管理", "管理帮助"):
            return ADMIN_HELP

        if cmd == "教":
            if "|" not in rest and "｜" not in rest and "\n" not in rest:
                return "格式：教 问题 | 答案 [| 链接]"
            q, a = (re.split(r"\s*[|｜]\s*", rest, 1) if re.search(r"[|｜]", rest) else rest.split("\n", 1))
            answer, url = _split_answer(a)
            if not q.strip() or not answer:
                return "问题和答案都不能为空。格式：教 问题 | 答案 [| 链接]"
            qa_id = kb.add_qa(q.strip(), answer, url)
            return f"✅ 记住了 #{qa_id}\n问：{q.strip()}\n答：{answer}" + (f"\n🔗 {url}" if url else "") + \
                f"\n\n换个说法也想命中，就发「也问 {qa_id} 另一种问法」。"

        if cmd in ("也问", "改", "删", "看", "答", "忽略", "删文"):
            m = _ID.match(rest)
            if not m:
                return f"格式：{cmd} 编号 …"
            n, body = int(m.group(1)), m.group(2).strip()

            if cmd == "也问":
                if not body:
                    return "格式：也问 编号 另一种问法"
                return f"✅ #{n} 多了一种问法：{body}" if kb.add_phrase(n, body) else f"没有 #{n} 这组问答"
            if cmd == "改":
                answer, url = _split_answer(body)
                if not answer:
                    return "格式：改 编号 新答案 [| 链接]"
                return f"✅ #{n} 已更新" if kb.update_qa(n, answer, url) else f"没有 #{n} 这组问答"
            if cmd == "删":
                return f"🗑 #{n} 已删除" if kb.delete_qa(n) else f"没有 #{n} 这组问答"
            if cmd == "看":
                row = kb.get_qa(n)
                if not row:
                    return f"没有 #{n} 这组问答"
                phrases = "\n".join(f"· {p}" for p in kb.phrases(n))
                return f"#{n}（命中 {row['hits']} 次）\n问法：\n{phrases}\n答：{row['answer']}" + \
                    (f"\n🔗 {row['url']}" if row["url"] else "")
            if cmd == "删文":
                return f"🗑 文章 #{n} 已移除" if kb.delete_article(n) else f"没有文章 #{n}"
            if cmd == "忽略":
                p = kb.get_pending(n)
                if not p or p["status"] != "open":
                    return f"#{n} 不在待答列表里"
                kb.close_pending(n, "ignored")
                return f"已跳过 #{n}"
            if cmd == "答":
                p = kb.get_pending(n)
                if not p:
                    return f"没有待答 #{n}"
                answer, url = _split_answer(body)
                if not answer:
                    return "格式：答 编号 答案 [| 链接]"
                qa_id = kb.add_qa(p["question"], answer, url)
                kb.close_pending(n, "answered", qa_id)
                reply = f"关于你问的「{p['question']}」，{config.OWNER_NAME} 的回复：\n{answer}" + (f"\n🔗 {url}" if url else "")
                self._deferred.append(Out(p["user_id"], self._with_hub(reply, p["question"])))
                if _can_push(p["user_id"]):
                    return f"✅ 已回复提问人，并记为问答 #{qa_id}"
                return f"✅ 已记为问答 #{qa_id}。对方是公众号用户，没法主动推送，他下次发消息时会看到你的回复。"

        if cmd == "查":
            if not rest:
                return "格式：查 关键词"
            lines = []
            for m in kb.match_qa(rest, limit=5):
                lines.append(f"#{m.id} {m.score:.2f}  {m.phrase}")
            for m in kb.match_articles(rest, limit=3):
                lines.append(f"文章#{m.id} {m.score:.2f}  {m.phrase}")
            return "\n".join(lines) if lines else "知识库里没有相关内容"

        if cmd == "试":
            if not rest:
                return "格式：试 问题"
            reply, route, detail = await self.answer(rest)
            return f"[来源：{route} {detail}]\n{reply or '（答不上来 → 会转给你）'}"

        if cmd == "待答":
            rows = kb.open_pending()
            if not rows:
                return "没有待答问题 👍"
            return "\n".join(f"#{r['id']}（{_short(r['user_id'])}）{r['question']}" for r in rows)

        if cmd == "收录":
            url_m = mamo.ARTICLE_URL.search(rest)
            if not url_m:
                return "格式：收录 https://mp.weixin.qq.com/s/..."
            try:
                art_id, title = await mamo.add_by_url(self.http, kb, url_m.group(0))
            except Exception as exc:
                return f"收录失败：{exc}"
            return f"✅ 已收录文章 #{art_id}：{title}"

        if cmd == "关注语":
            if not rest:
                current = kb.kv_get("mp_welcome")
                return f"当前关注语：\n{current}" if current else "还没设置关注语。格式：关注语 欢迎关注马莫百科…"
            kb.kv_set("mp_welcome", rest)
            return "✅ 关注语已更新（新关注的人会先看到这段，再看到机器人的使用说明）"

        if cmd == "统计":
            day = time.time() - 86400
            routes = kb.db.execute("SELECT route, COUNT(*) FROM log WHERE at>? AND route!='command' GROUP BY route",
                                   (day,)).fetchall()
            r = "，".join(f"{a} {b}" for a, b in routes) or "无"
            return (f"问答 {kb.count('qa')} 组（{kb.count('qa_phrase')} 种问法），文章 {kb.count('article')} 篇，"
                    f"联系人 {kb.count('contact')} 个，待答 {len(kb.open_pending(999))} 个\n近 24 小时：{r}")

        return ADMIN_HELP
