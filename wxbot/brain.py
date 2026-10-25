"""What the bot says. Pure logic: no WeChat I/O here, so it can be exercised from the CLI and tests."""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp

from . import config, hub, mamo
from .kb import KB, Match, clear_lead

if TYPE_CHECKING:
    from .rag import Rag

# Monash Hub lists every 马莫百科 post by topic (选课, 签证, 交换...), which also works outside the 公众号.
MAMO_ARCHIVE = f"📚 马莫百科往期文章（按主题分类）：{config.HUB_SITE}/mamo"
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


# Greetings that come in pairs or with a 请问 and nothing else ("你好在吗", "老师您好，请问") still get the
# introduction instead of going to the owner as a question.
_GREETING_RUN = re.compile(r"^(?:" + "|".join(sorted(map(re.escape, GREETINGS | {
    "老师", "老师好", "学长", "学长好", "学姐", "学姐好", "同学", "打扰了", "打扰一下", "请问", "早上好", "下午好", "晚上好", "哈啰", "嗨嗨"}), key=len, reverse=True))
    + r"|[\s,，、!！.。~?？呀啊呢嘛哦])+$")


# "好的谢谢学长", "看到了", "拜拜", "没事了我去问问": the end of a conversation, not a question for the owner
# (owner, 2026-10-24: forwarding these is annoying). A thank-you gets "不客气", a goodbye "拜拜", the rest a short line.
_THANKS = ("谢谢", "谢啦", "谢了", "多谢", "感谢", "感激不尽", "感激", "感恩", "辛苦了", "辛苦", "蟹蟹", "thanks", "thank you", "thankyou",
           "thx", "ty", "3q", "tks")
_BYES = ("拜拜", "再见", "晚安", "回见", "下次见", "下次再问", "改天再问", "byebye", "bye", "886", "88", "good night", "night")
_ACKS = ("好的", "好滴", "好嘞", "好哒", "好吧", "好呢", "好啊", "好", "行吧", "行", "ok", "okay", "okk", "欧克", "嗯嗯", "嗯", "收到",
         "看到了", "看到啦", "看到", "知道了", "知道啦", "知道", "明白了", "明白啦", "明白", "懂了", "了解了", "了解", "可以",
         "没问题", "没事了", "没事", "不用了", "算了", "没有了", "没了", "解决了", "搞定了", "搞定", "清楚了", "原来如此",
         "这样啊", "这样", "哈哈哈", "哈哈", "666", "牛", "厉害", "太好了", "好耶", "棒", "nice", "great", "cool", "got it",
         "试试", "看看", "问问", "再说", "等等", "等你", "等回复", "等消息", "进去了", "真的", "一样", "不重要")
_FILLERS = ("你", "您", "学长", "学姐", "老师", "同学", "小助手", "助手", "机器人", "大佬", "哥", "姐", "宝", "啦", "了", "呀",
            "啊", "哦", "噢", "喔", "呢", "哈", "嘿", "非常", "太", "很", "超", "真的", "那", "那就", "就", "先", "们", "我",
            "我们", "去", "再", "一下", "回复", "消息", "的", "啦啦", "so much", "very much", "much", "a lot", "lot", "you",
            "u", "all", "guys", "哇", "诶", "欸", "耶", "ww", "w")
_SIGN_OFF = re.compile(r"^(?:" + "|".join(sorted({re.escape(w.replace(" ", "")) for w in _THANKS + _BYES + _ACKS + _FILLERS},
                                                  key=len, reverse=True)) + r")+$")
_HELLO = re.compile(r"(你|您|大家|老师|学长|学姐|早上|上午|中午|下午|晚上)好")
_WX_EMOJI = re.compile(r"\[[^\[\]]{1,4}\]")       # WeChat's own emoji arrive as "[抱拳]", "[强]"
SIGN_OFF_REPLY = {"thanks": "不客气 😊 还有问题随时问我。", "bye": "拜拜 👋 有问题随时来问我。",
                  "ok": "好的 😊 还有问题随时问我。"}


def sign_off(text: str) -> str | None:
    """"thanks", "bye" or "ok" for a message that only thanks, says goodbye or acknowledges; None otherwise."""
    if len(text) > 30 or "?" in text or "？" in text:
        return None
    core = re.sub(r"[\W_]+", "", _WX_EMOJI.sub("", text.lower()))
    if not core:
        return "ok" if text.strip() else None          # only emoji: 👍, [抱拳]
    if _HELLO.search(core) or not _SIGN_OFF.match(core):
        return None
    for kind, words in (("thanks", _THANKS), ("bye", _BYES), ("ok", _ACKS)):
        if any(w.replace(" ", "") in core for w in words):
            return kind
    return None


def is_greeting(text: str) -> bool:
    low = text.lower().strip(" !！。.~?？")
    return low in GREETINGS or len(low) < 2 or bool(_GREETING_RUN.match(low))


def is_about_me(text: str) -> bool:
    low = text.lower().strip(" !！。.~?？")
    return len(low) <= 16 and not codes_in(low) and bool(_ABOUT_ME.search(low) or _ABOUT_SHORT.match(low))


def unit_codes(text: str) -> set[str]:
    return {f"{a.upper()}{b}" for a, b in _UNIT_CODE.findall(text) if a.upper() not in NOT_PREFIXES}


def codes_in(text: str) -> set[str]:
    """Unit and degree codes: what a question is specifically about."""
    return unit_codes(text) | set(hub.course_codes(text)) | set(hub.aos_codes(text))


HUMAN = {"人工", "转人工", "找waldo", "找 waldo"}
FORGET = {"删除我的数据", "删除我的记录", "删掉我的数据", "删掉我的记录"}
HUB_DOWN = "查询服务暂时连不上 🙏 请过几分钟再发一次这个问题。"
# What a 公众号 reply may spend in Brain.answer when the rules already have something to say: mp.REPLY_BUDGET_S
# is 4 s and the rest is WeChat, the outbox and the XML.
MP_BUDGET_S = 3.5


@dataclass
class Out:
    to: str
    text: str
    mention_owner: bool = False     # in a WeChat group: also @ the owner (a question only he can answer)
    note: str = ""                  # the 待答 note to send him privately when he cannot be @-ed there


def intro(group: bool = False) -> str:
    how = "在群里 @我 加上你的问题就行，比如：" if group else "直接把问题发给我就行，比如："
    return (
        "你好，我是 Monash 问答小助手 🤖\n"
        f"{how}\n"
        "· 课程：FIT2102 有期末考试吗 / 编程范式学什么 / FIT1045 的先修课\n"
        "· 学位：C2001 要修多少学分 / 计算机科学学士有哪些专业方向\n"
        "· 政策：怎么申请延期交作业 / 怎么退课 / WAM 怎么算 / 学生签证怎么续签\n"
        "· 新生和家长：怎么报到 / 学费怎么交 / 从机场怎么去学校\n"
        "· “马莫百科”公众号写过的内容\n"
        + ("回答都来自 Monash 官网、Handbook 和“马莫百科”公众号，并附上链接方便你核实；"
           "有些回答是大模型从这些资料里原样摘出的句子，会标出处，不会改写或补充。"
           if config.RAG else
           "我不是聊天大模型，不会编答案：回答都来自 Monash 官网、Handbook 和“马莫百科”公众号，并附上链接方便你核实。") +
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
不问 编号 问法          —— 去掉一种问法（第一种不能去）
改 编号 新答案 [| 链接]  —— 修改答案
删 编号 / 看 编号        —— 删除 / 查看问答
删数据 编号            —— 删掉待答 #编号 那位提问人留下的所有记录（对方要求时用）
列表 [页码]             —— 所有问答，每页 20 组
查 关键词              —— 看知识库里会匹配到什么
试 问题                —— 模拟回答并显示命中来源
待答                  —— 没答上来的问题
答 编号 答案 [| 链接]    —— 回复提问人，并把这组问答记住
                        （也可以直接发「编号 答案」，或引用待答通知直接写答案）
忽略 编号              —— 跳过一个待答问题
收录 公众号文章链接      —— 把马莫百科文章加进知识库（直接发链接也行）
删文 编号              —— 移除一篇文章
关注语 [新内容]         —— 查看 / 设置公众号的关注自动回复
统计                  —— 知识库和使用情况
未命中 [天数]           —— 近几天没答上、差一点命中的问题（默认 7 天）
同义词 [词=词=词]       —— 查看 / 添加同义词（如 同义词 签证=visa=EMGS）；「同义词 删 visa」移除一个词
管理员                —— 查看管理员；「管理员 配对」给新管理员一个配对码，「管理员 删 序号」删掉一个"""

_CMD = re.compile(r"^[/#]?(教|也问|不问|改|删数据|删|看|查|试|待答|答|忽略|收录|删文|关注语|统计|列表|未命中|同义词|管理员|管理|管理帮助)"
                  r"(?:\s+|$|(?=#?\d))(.*)$", re.S)
_ID = re.compile(r"^#?(\d+)\s*(.*)$", re.S)
_PENDING_NOTE = re.compile(r"待答\s*#(\d+)")
# The bare "12 answer" shortcut needs a space after the number: "3门课挂了怎么办" is a question.
_ID_THEN_ANSWER = re.compile(r"^#?(\d+)\s+(\S.*)$", re.S)
# A new admin proves it with a code an admin asked for (issue #4): nobody has to read a user id out of the log.
_PAIR = re.compile(r"^配对\s*(\d{6})$")
PAIR_TTL_S = 600
PAIR_MAX_TRIES = 5


def _split_answer(rest: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in re.split(r"\s*[|｜]\s*", rest)]
    if len(parts) >= 2 and re.match(r"https?://", parts[-1]):
        return " | ".join(parts[:-1]).strip(), parts[-1]
    return rest.strip(), None


def _short(user_id: str) -> str:
    if user_id.startswith("mp:"):
        return "公众号用户 " + user_id[3:11]
    if user_id.startswith("pc:"):
        body = user_id[3:]
        return ("微信群 " + body.split("@")[0][-6:] + " 的 " + body.split("|", 1)[1][:12]) if "|" in body \
            else "MonashGuide 私聊 " + body[:12]
    return user_id.split("@")[0][:10]


def _waited(created_at: float, now: float | None = None) -> str:
    """How long a pending question has waited; over 3 days it is flagged (issue #5)."""
    days = int(((now or time.time()) - created_at) // 86400)
    return "今天" if days < 1 else f"{days} 天前" + (" ⏰" if days > 3 else "")


def saved_admins(kb: KB) -> list[str]:
    """Admins added with a pairing code (the kv row bot.admins_for also reads); the QR scanner is not in it."""
    return [a for a in kb.kv_get("admins").split(",") if a]


def _in_group(user_id: str) -> bool:
    return user_id.startswith("pc:") and "|" in user_id


def _can_push(user_id: str) -> bool:
    """A personal 订阅号 can only answer inside the 5s window of a user's own message."""
    return not user_id.startswith("mp:")


class Brain:
    def __init__(self, kb: KB, http: aiohttp.ClientSession, admins: set[str], rag: Rag | None = None):
        self.kb = kb
        self.http = http
        self.admins = admins
        self.rag = rag          # the optional RAG answer (WXBOT_RAG=1); None: rules only
        # The owner's own WeChat, reached through the MonashGuide account ("pc:<wxid>"). When set, it gets
        # the 待答 notes and can use the admin commands there; ClawBot is then only the alert channel.
        self.owner_pc = f"pc:{config.OWNER_WXID}" if config.OWNER_WXID else ""
        self.last_question: dict[str, tuple[float, str]] = {}
        self.recent: dict[str, list[float]] = {}
        self._deferred: list[Out] = []  # messages a command sends to someone else (「答」 replies to the asker)
        self._pairing: tuple[str, float] | None = None   # (code, expires at), kept in memory: a restart voids it
        self._pair_fails = 0

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

    async def answer(self, question: str, budget_s: float | None = None) -> tuple[str | None, str, str]:
        """(reply or None, route, detail). route is qa | hub | article | mixed | rag | miss.

        The rules go first. Only when they found nothing or only a weak match, and the question names no
        unit or degree (those are the Handbook's), the RAG mode is asked, if it is on. budget_s: how long a
        question the rules did answer may take in all (a 公众号 reply); one with no answer waits up to
        WXBOT_LLM_TIMEOUT either way."""
        start = time.monotonic()
        reply, route, detail, sure = await self._rules(question)
        if sure or self.rag is None or codes_in(question):
            return reply, route, detail
        has_answer = route not in ("miss", "hub_down")
        timeout = config.LLM_TIMEOUT
        if has_answer and budget_s is not None:
            timeout = min(timeout, budget_s - (time.monotonic() - start))
        if has_answer and timeout < 0.5:
            return reply, route, f"{detail} | rag skipped: no time".strip()
        got = await self.rag.answer(question, timeout)
        if got.text:
            # The Hub links go under the sources, never between the quotes (a quote may hold a link).
            quoted, sep, sources = got.text.partition("\n\n参考：\n")
            return quoted + sep + self._with_hub(sources, question), "rag", got.detail
        if got.unsure:
            # The owner's call (2026-10-24): when the model read the best passages and found no answer, a
            # weak rule match ("你问的是不是…", a list of loosely related pages) is likely off too, so the
            # question goes to the owner instead. A slow or failing model still falls back to the rules.
            return None, "miss", f"{detail} | rag {got.detail}".strip()
        return reply, route, f"{detail} | rag {got.detail}".strip()

    async def _rules(self, question: str) -> tuple[str | None, str, str, bool]:
        """The model-free answer: (reply or None, route, detail, sure). sure: a strong taught answer or
        a strong Monash Hub answer, which nothing else is asked to improve on."""
        hub.guides.refresh_soon(self.http)
        qa = self.kb.match_qa(question)
        top = qa[0] if qa else None
        # A question about a unit is for the Handbook, unless what Waldo taught names that unit:
        # "FIT2004 马来西亚开吗" must not be answered by a Q&A about where the Malaysia campus is.
        codes = codes_in(question)
        if top and codes and not codes & codes_in(top.phrase):
            top = None
        if top and top.score >= config.QA_STRONG and clear_lead(qa, config.QA_MARGIN):
            self.kb.hit(top.id)
            return self._with_hub(self._fmt_qa(top, unsure=False), question), "qa", f"qa#{top.id} {top.score:.2f}", True

        h = await hub.ask(self.http, question)
        hub_down = isinstance(h, hub.HubError)
        if hub_down:
            h = None
        if h and h.strength == "strong":
            return self._with_hub(h.text, question), "hub", h.answer_type, True

        arts = [m for m in self.kb.match_articles(question, limit=2) if m.score >= config.ARTICLE_MIN]
        arts = [m for m in arts if m.score >= 0.8 * arts[0].score]
        if top and top.score >= config.QA_WEAK:
            self.kb.hit(top.id)
            reply = self._fmt_qa(top, unsure=True)
            if arts:
                reply += "\n\n" + self._fmt_articles(arts)
            return self._with_hub(reply, question), "qa", f"qa#{top.id} {top.score:.2f} (weak)", False

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
                    "+".join(route), detail, False)
        if hub_down:
            # Monash Hub is restarting or unreachable: a passing outage, not a question for Waldo
            # (alerts.py already tells him the Hub is down).
            return HUB_DOWN, "hub_down", "", False
        return None, "miss", "", False

    # -- entry point ------------------------------------------------------------------------------
    def _as_answer(self, text: str, quoted: str) -> str | None:
        """Admin shortcuts for 「答」: quoting a 待答 notification, or "12 answer" where 12 is an
        open pending question. Returns the 「答」 arguments, or None."""
        m = _PENDING_NOTE.search(quoted or "")
        if m:
            return f"{m.group(1)} {text}"
        m = _ID_THEN_ANSWER.match(text)
        if m:
            p = self.kb.get_pending(int(m.group(1)))
            if p and p["status"] == "open":
                return text
        return None

    async def handle(self, user_id: str, text: str, quoted: str = "") -> list[Out]:
        text = text.strip()
        is_admin = user_id in self.admins or bool(self.owner_pc and user_id == self.owner_pc)

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
        m = _PAIR.match(text)
        if m and not _in_group(user_id):
            return self._pair(user_id, m.group(1), is_admin)
        low = text.lower().strip(" !！。.~")
        done = sign_off(text)
        if done:
            self.kb.log(user_id, text, "chat", done)
            return [Out(user_id, SIGN_OFF_REPLY[done])]
        if is_greeting(text) or is_about_me(text):
            return [Out(user_id, intro(group=_in_group(user_id)))]
        if low in HUMAN:
            return self._escalate(user_id, explicit=True)
        if low in FORGET:
            # Not logged: the point is that nothing about them is left.
            self.last_question.pop(user_id, None)
            n = self.kb.forget_user(user_id)
            return [Out(user_id, f"🗑 已经删掉你在这里留下的 {n} 条记录。以后再提问还会照常记录，用来改进回答。"
                        if n else "这里没有你的记录。")]

        self.last_question[user_id] = (time.time(), text)
        reply, route, detail = await self.answer(text, MP_BUDGET_S if user_id.startswith("mp:") else None)
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
        dup = next((p for p in self.kb.open_pending(200)
                    if p["user_id"] == user_id and question in p["question"].split("\n")), None)
        if dup:
            return [Out(user_id, f"已经转给 {config.OWNER_NAME} 了，他看到会回复你 🙏")]
        if not _in_group(user_id):
            # One question sent as several messages reaches Waldo as one note (due_notes), and the asker
            # is told it was passed on once.
            open_ = self.kb.recent_pending(user_id, config.PENDING_MERGE_S)
            if open_:
                self.kb.append_pending(open_["id"], question)
                if open_["noted"] == 0:
                    return [Out(user_id, f"好的，会和你前面的问题一起转给 {config.OWNER_NAME} 🙏")] if explicit else []
                return [Out(user_id, f"收到，已经补充给 {config.OWNER_NAME} 🙏")]
        pid = self.kb.add_pending(user_id, question, noted=_in_group(user_id) and bool(self.owner_pc))
        if _in_group(user_id) and self.owner_pc:
            # Asked in a group: the owner is asked right there (pcwx @-s him, at most once per group per
            # cooldown), and his reply @-ing the asker is learned as the answer (pcwx.owner_reply).
            return [Out(user_id, f"这个问题我还答不上来 🙏 可以先在 Monash Hub 搜搜看：{hub.search_link(question)}\n"
                                 f"{MAMO_ARCHIVE}\n"
                                 f"已经请 {config.OWNER_NAME} 来回答：", mention_owner=True,
                        note=self._note(pid, user_id, question))]
        later = ("他看到后会回复你" if _can_push(user_id) else "他补充答案后，你再给我发任意一条消息就能看到")
        outs = [Out(user_id, (f"好的，已经转给 {config.OWNER_NAME}，{later} 🙏" if explicit else
                              f"这个问题我还答不上来 🙏 已经转给 {config.OWNER_NAME}，{later}。\n"
                              f"等的时候可以先在 Monash Hub 搜搜看：{hub.search_link(question)}\n{MAMO_ARCHIVE}"))]
        return outs

    def due_notes(self, now: float | None = None) -> list[Out]:
        """The notes to Waldo for questions nothing has been added to for PENDING_QUIET_S seconds: each
        one has every line the person sent that the bot could not answer, and what else they said then."""
        now = now or time.time()
        outs = []
        for p in self.kb.due_pending(config.PENDING_QUIET_S, now):
            self.kb.mark_noted(p["id"], p["parts"])
            lines = p["question"].split("\n")
            around = [q for q in self.kb.said_between(p["user_id"], p["created_at"] - 300, now) if q not in lines]
            note = self._note(p["id"], p["user_id"], p["question"], around[-5:], again=p["noted"] > 0)
            outs.extend(Out(a, note) for a in self.note_targets())
        return outs

    @staticmethod
    def _note(pid: int, user_id: str, question: str, around: list[str] = (), again: bool = False) -> str:
        n = question.count("\n") + 1
        head = f"❓ 待答 #{pid}（来自 {_short(user_id)}" + ("，有补充" if again else "") + (f"，{n} 句" if n > 1 else "") + "）"
        said = ("\n\n同一时间还说了（机器人答过）：\n" + "\n".join(f"· {q}" for q in around)) if around else ""
        keep = "会发给对方（几句合起来的不记成问答）" if n > 1 else "会发给对方并记住这组问答"
        return f"{head}\n{question}{said}\n\n回复「答 {pid} 你的答案」{keep}；「忽略 {pid}」跳过。"

    def note_targets(self) -> list[str]:
        # An admin on the 公众号 can use the commands but cannot be pushed to; a note queued for them
        # would turn up in front of the answer to their next question.
        return [self.owner_pc] if self.owner_pc else sorted(a for a in self.admins if not a.startswith("mp:"))

    # -- admins (issue #4) ----------------------------------------------------------------------------
    def _pair(self, user_id: str, code: str, is_admin: bool) -> list[Out]:
        if not self._pairing:
            return [Out(user_id, "现在没有可用的配对码，请让管理员先发「管理员 配对」。")]
        code_now, expires = self._pairing
        if time.time() > expires:
            self._pairing = None
            return [Out(user_id, "配对码已经过期了，请让管理员重新发「管理员 配对」。")]
        if not secrets.compare_digest(code, code_now):
            self._pair_fails += 1
            if self._pair_fails >= PAIR_MAX_TRIES:
                self._pairing = None     # a six-digit code must not be guessable by trying
            return [Out(user_id, "配对码不对。")]
        self._pairing = None
        if is_admin:
            return [Out(user_id, "你已经是管理员了。")]
        others = self.note_targets()
        self.admins.add(user_id)
        self.kb.kv_set("admins", ",".join(saved_admins(self.kb) + [user_id]))
        self.kb.log(user_id, "配对", "command", "admin added")
        outs = [Out(user_id, "✅ 你现在是管理员了，发「管理」查看命令。")]
        outs.extend(Out(a, f"🔑 {_short(user_id)} 用配对码成为了管理员。不是你邀请的话，发「管理员」查看并删掉。")
                    for a in others)
        return outs

    def _admins_command(self, rest: str) -> str:
        saved = saved_admins(self.kb)
        if rest == "配对":
            self._pairing, self._pair_fails = (f"{secrets.randbelow(10 ** 6):06d}", time.time() + PAIR_TTL_S), 0
            return (f"🔑 配对码：{self._pairing[0]}（{PAIR_TTL_S // 60} 分钟内有效，只能用一次）\n"
                    f"让对方用自己的微信私聊 MonashGuide，或者给公众号发「配对 {self._pairing[0]}」。")
        everyone = sorted(self.admins | ({self.owner_pc} if self.owner_pc else set()))
        m = re.match(r"^删\s*(\d+)$", rest)
        if m:
            i = int(m.group(1))
            if not 1 <= i <= len(everyone):
                return f"没有第 {i} 个管理员，发「管理员」查看序号。"
            who = everyone[i - 1]
            if who not in saved:
                return "这个管理员不是配对加进来的（扫码的主人或 WXBOT_OWNER_WXID），不能在这里删。"
            self.kb.kv_set("admins", ",".join(a for a in saved if a != who))
            self.admins.discard(who)
            return f"🗑 已删除管理员 {_short(who)}"
        if rest:
            return "格式：管理员 / 管理员 配对 / 管理员 删 序号"
        lines = []
        for i, a in enumerate(everyone, 1):
            how = ("配对加入" if a in saved else "WXBOT_OWNER_WXID" if a == self.owner_pc else "扫码的主人")
            lines.append(f"{i}. {_short(a)}（{how}）")
        return "管理员：\n" + "\n".join(lines) + "\n\n「管理员 配对」加一个，「管理员 删 序号」删一个。"

    # -- what went unanswered (issue #8) ---------------------------------------------------------------
    def near_misses(self, days: int = 7) -> str | None:
        """The owner's view of what the matching could not do: questions nobody answered (with the Q&A
        each almost hit, and the 也问 to send), and questions answered with "你问的是不是…". None when
        there was nothing of the kind."""
        kb = self.kb
        lines = []
        misses = kb.misses(days)
        if misses:
            lines.append(f"近 {days} 天答不上来的问题（按次数）：")
            for question, n in misses:
                line = f"· {n}× {question}"
                top = (kb.match_qa(question, limit=1) or [None])[0]
                if top and top.score >= config.QA_STRONG:
                    line += f"，现在能答了（#{top.id}）"
                elif top and top.score >= config.QA_NEAR:
                    line += f"，差一点命中 #{top.id}「{top.phrase}」({top.score:.2f})，可以发「也问 {top.id} {question}」"
                lines.append(line)
        unsure = kb.unsure_hits(days)
        if unsure:
            lines.append("拿不准才回答的（回了“你问的是不是…”）：")
            lines.extend(f"· {n}× {q} → #{i}「{(kb.phrases(i) or [''])[0]}」({s:.2f})" for q, n, i, s in unsure)
        if not lines:
            return None
        lines.append("答得不对的，用「教」或「也问」补上；换个词就答不上的，用「同义词 词=词」。")
        return "\n".join(lines)

    def learn(self, asker: str, answer: str) -> int | None:
        """The owner answered an asker himself (in the group): close their latest open question and
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
            q, a = (re.split(r"\s*[|｜]\s*", rest, maxsplit=1) if re.search(r"[|｜]", rest) else rest.split("\n", 1))
            answer, url = _split_answer(a)
            if not q.strip() or not answer:
                return "问题和答案都不能为空。格式：教 问题 | 答案 [| 链接]"
            qa_id = kb.add_qa(q.strip(), answer, url)
            return f"✅ 记住了 #{qa_id}\n问：{q.strip()}\n答：{answer}" + (f"\n🔗 {url}" if url else "") + \
                f"\n\n换个说法也想命中，就发「也问 {qa_id} 另一种问法」。"

        if cmd in ("也问", "不问", "改", "删", "删数据", "看", "答", "忽略", "删文"):
            m = _ID.match(rest)
            if not m:
                return f"格式：{cmd} 编号 …"
            n, body = int(m.group(1)), m.group(2).strip()

            if cmd == "也问":
                if not body:
                    return "格式：也问 编号 另一种问法"
                return f"✅ #{n} 多了一种问法：{body}" if kb.add_phrase(n, body) else f"没有 #{n} 这组问答"
            if cmd == "不问":
                if not body:
                    return "格式：不问 编号 问法"
                return f"✅ #{n} 不再认「{body}」" if kb.delete_phrase(n, body) else \
                    f"#{n} 没有「{body}」这种问法（第一种问法不能去，发「看 {n}」查看）"
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
            if cmd == "删数据":
                p = kb.get_pending(n)
                if not p:
                    return f"没有待答 #{n}（只能按待答编号删，「待答」里能看到）"
                self.last_question.pop(p["user_id"], None)
                return f"🗑 已删除 {_short(p['user_id'])} 的 {kb.forget_user(p['user_id'])} 条记录"
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
                merged = "\n" in p["question"]
                if merged:
                    # Several messages are not one phrasing a later question would match.
                    qa_id = None
                    kb.close_pending(n, "answered")
                elif p["status"] == "answered" and p["qa_id"] and kb.update_qa(p["qa_id"], answer, url):
                    # Answering the same question again corrects the answer instead of adding a second Q&A.
                    qa_id = p["qa_id"]
                else:
                    qa_id = kb.add_qa(p["question"], answer, url)
                    kb.close_pending(n, "answered", qa_id)
                asked = p["question"].replace("\n", " / ")
                reply = f"关于你问的「{asked}」，{config.OWNER_NAME} 的回复：\n{answer}" + (f"\n🔗 {url}" if url else "")
                self._deferred.append(Out(p["user_id"], self._with_hub(reply, asked.replace(" / ", " "))))
                if merged:
                    return ("✅ 已回复提问人。这条是几句合起来的，没有记成问答；想让机器人以后会答，用「教 问题 | 答案」。"
                            if _can_push(p["user_id"]) else
                            "✅ 已记下回复。对方是公众号用户，没法主动推送，他下次发消息时会看到。这条是几句合起来的，没有记成问答。")
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
            return "\n".join(f"#{r['id']}（{_short(r['user_id'])}，{_waited(r['created_at'])}）{r['question'].replace(chr(10), ' / ')}"
                             for r in rows)

        if cmd == "列表":
            page = int(rest) if rest.isdigit() and int(rest) > 0 else 1
            total = kb.count("qa")
            rows = kb.list_qa(offset=(page - 1) * 20, limit=20)
            if not rows:
                return "还没有教过的问答" if not total else f"没有第 {page} 页（共 {total} 组）"
            pages = (total + 19) // 20
            lines = [f"#{r['id']}（命中 {r['hits']}）{r['question']}" for r in rows]
            more = f"\n发「列表 {page + 1}」看下一页" if page < pages else ""
            return f"问答第 {page}/{pages} 页，共 {total} 组：\n" + "\n".join(lines) + more

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

        if cmd == "未命中":
            days = int(rest) if rest.isdigit() and 0 < int(rest) <= 365 else 7
            return self.near_misses(days) or f"近 {days} 天每个问题都答上了 👍"

        if cmd == "同义词":
            if not rest:
                groups = kb.synonyms()
                return ("同义词：\n" + "\n".join("· " + " = ".join(g) for g in groups) if groups
                        else "还没有同义词。格式：同义词 签证=visa=EMGS")
            m = re.match(r"^删\s*(\S+)$", rest)
            if m:
                return f"🗑 已移除同义词 {m.group(1)}" if kb.remove_synonym(m.group(1)) else f"没有同义词 {m.group(1)}"
            group = kb.add_synonyms(re.split(r"\s*[=＝，,]\s*", rest))
            if len(group) < 2:
                return "格式：同义词 签证=visa=EMGS（至少两个词）"
            return "✅ 这些词现在算同一个词：" + " = ".join(group)

        if cmd == "管理员":
            return self._admins_command(rest)

        if cmd == "统计":
            day = time.time() - 86400
            routes = kb.db.execute("SELECT route, COUNT(*) FROM log WHERE at>? AND route!='command' GROUP BY route",
                                   (day,)).fetchall()
            r = "，".join(f"{a} {b}" for a, b in routes) or "无"
            expired = kb.expired_outbox(config.OUTBOX_DAYS * 86400)
            stale = f"\n超过 {config.OUTBOX_DAYS:g} 天没送出、已作废的回复：{expired} 条" if expired else ""
            return (f"问答 {kb.count('qa')} 组（{kb.count('qa_phrase')} 种问法），文章 {kb.count('article')} 篇，"
                    f"联系人 {kb.count('contact')} 个，待答 {len(kb.open_pending(999))} 个\n近 24 小时：{r}" + stale)

        return ADMIN_HELP
