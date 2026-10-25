"""The knowledge base: Q&A pairs Waldo teaches, 马莫百科 articles, and the bot's own state.

Matching is deliberately model-free: jieba words plus CJK character bigrams, weighted by IDF,
scored as the overlap between the question and each stored phrasing. No tokens are spent and
every answer can be traced back to the row it came from.
"""
from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import jieba

jieba.setLogLevel(60)

SCHEMA = """
CREATE TABLE IF NOT EXISTS qa (
    id INTEGER PRIMARY KEY,
    answer TEXT NOT NULL,
    url TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0
);
-- Every way of asking a qa row. The first one added is the "main" question.
CREATE TABLE IF NOT EXISTS qa_phrase (
    id INTEGER PRIMARY KEY,
    qa_id INTEGER NOT NULL REFERENCES qa(id) ON DELETE CASCADE,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS article (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    digest TEXT,
    content TEXT,
    published_at REAL,
    fetched_at REAL NOT NULL
);
-- Questions the bot could not answer, waiting for Waldo.
CREATE TABLE IF NOT EXISTS pending (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    created_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',   -- open | answered | ignored
    qa_id INTEGER,
    -- Misses a person sends close together are one question (several lines), sent to Waldo as one note.
    updated_at REAL,                       -- when the last line was added
    parts INTEGER NOT NULL DEFAULT 1,      -- lines in question
    noted INTEGER NOT NULL DEFAULT 1       -- lines in the last note Waldo was sent; parts > noted: note due
);
CREATE TABLE IF NOT EXISTS contact (
    user_id TEXT PRIMARY KEY,
    context_token TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
-- Messages for people we cannot push to (公众号 users): shown with the reply to their next message.
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL,
    delivered_at REAL
);
CREATE TABLE IF NOT EXISTS log (
    id INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    route TEXT NOT NULL,          -- qa | hub | article | miss | command
    detail TEXT
);
-- take_outbox runs on every 公众号 message, open_pending on every miss; the log only grows.
CREATE INDEX IF NOT EXISTS outbox_by_user ON outbox(user_id, delivered_at);
CREATE INDEX IF NOT EXISTS pending_by_status ON pending(status);
CREATE INDEX IF NOT EXISTS log_by_time ON log(at);
CREATE INDEX IF NOT EXISTS phrase_by_qa ON qa_phrase(qa_id);
"""

STOPWORDS = set(
    "的 了 吗 呢 啊 呀 吧 嘛 哦 哈 是 在 我 你 他 她 它 我们 你们 他们 这 那 这个 那个 这些 那些 "
    "怎么 怎么样 怎样 如何 什么 啥 哪 哪里 哪儿 哪个 哪些 为什么 为啥 多少 几 请问 请 问 问下 问一下 一下 "
    "有 没有 有没有 可以 能 能不能 可不可以 要 需要 会 想 想问 知道 大家 谁 就 都 也 还 和 与 及 或 或者 "
    "吗? 嗯 呃 麻烦 谢谢 感谢 一个 一些 是不是 应该 得 地 着 过 被 把 给 对 从 到 跟 "
    # Parents ask for their child and open politely: "您好，请问孩子怎么交学费" is "怎么交学费".
    "您 您好 你好 老师 老师好 打扰 打扰了 孩子 小孩 我家 家长 女儿 儿子 "
    "a an the is are was were do does did i you we to of in on for and or how what when where which "
    "can could should would will my me it this that there any".split()
)

_CJK = re.compile(r"[一-鿿]+")
_WORD = re.compile(r"[a-z0-9]+|[一-鿿]+")
_UNIT = re.compile(r"\b([a-z]{3}\d{4})\b")
# Multi-character stopwords cut a CJK run before bigrams are taken, so 怎么申请 does not leave 么申
# behind: that bigram made "怎么申请宿舍" look like "怎么申请交换".
_STOP_RUN = re.compile("|".join(sorted((w for w in STOPWORDS if len(w) > 1 and _CJK.fullmatch(w)),
                                       key=len, reverse=True)))


def split_tokens(text: str) -> tuple[set[str], set[str]]:
    """(words, bigrams). Words come from jieba; bigrams are CJK character pairs, which catch
    phrasings jieba cuts differently (延期交 / 延期提交) but also produce junk across word
    boundaries (去意 in 想去意大利), so the index only counts a query bigram it has seen."""
    text = text.lower()
    words: set[str] = set()
    for w in jieba.lcut_for_search(text):
        w = w.strip()
        if not w or w in STOPWORDS or not _WORD.fullmatch(w):
            continue
        if len(w) == 1 and not _CJK.fullmatch(w):
            continue
        words.add(w)
    grams: set[str] = set()
    for run in _CJK.findall(_STOP_RUN.sub(" ", text)):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg[0] not in STOPWORDS and bg[1] not in STOPWORDS and bg not in STOPWORDS:
                grams.add(bg)
    return words, grams - words


def tokens(text: str) -> set[str]:
    words, grams = split_tokens(text)
    return words | grams


# What students type for the topics 马莫百科 writes about, mapped to the words its titles and summaries
# use: the systems guide calls Moodle 学习平台 and Allocate+ 课表系统, and nobody types 缴费 for 学费.
# Only article matching uses this; a taught answer learns other phrasings through 也问.
ARTICLE_SYNONYMS = {
    "moodle": "学习平台", "作业": "学习平台", "assignment": "学习平台",
    "allocate": "课表系统 排课", "课表": "课表系统 排课", "上课时间": "课表系统 排课", "timetable": "课表系统 排课",
    "学费": "缴费", "交钱": "缴费", "付款": "缴费", "fees": "缴费",
    "注册": "报到", "入学": "报到", "开学": "报到",
    "台湾": "入台证 赴台",
    "exchange": "交换",
    "visa": "签证",
    "wes": "选课", "enrol": "选课", "enrolment": "选课",
    "邮箱": "学生邮箱", "email": "学生邮箱",
    "学位": "毕业", "毕业典礼": "毕业",
}

# Words that say little about which article fits ("我是学生"), so they never match one on their own.
_GENERIC = {"学生", "同学", "学校", "大学", "课程", "monash", "马莫", "百科", "指南"}

# jieba cuts 报到 into 报 + 到, and 到 is a stopword, so neither the title nor "怎么报到" kept the word.
jieba.add_word("报到")


def expand_for_articles(question: str) -> str:
    """The question in the articles' own words: each synonym replaces what the student typed, so the
    word they used does not count as a miss against the article."""
    text = question.lower()
    for k, v in ARTICLE_SYNONYMS.items():
        text = text.replace(k, f" {v} ") if _CJK.fullmatch(k) else re.sub(rf"(?<![a-z0-9]){k}(?![a-z0-9])", f" {v} ", text)
    return text


@dataclass
class Match:
    kind: str          # qa | article
    id: int
    score: float
    phrase: str        # the stored phrasing (or article title) that matched


def clear_lead(matches: list[Match], margin: float) -> bool:
    """True unless another pair scores within margin of the best one. 期末考试在哪考 is about as close
    to 期末考试什么时候 as to 期末考试能推迟吗: the shared rare words decide both scores, so neither
    answer is a sure one."""
    return len(matches) < 2 or matches[0].score - matches[1].score >= margin


def synonym_rewriter(groups: list[list[str]]) -> Callable[[str], str] | None:
    """A function that writes every word of a synonym group as the group's first word, in the text
    itself (签证=visa=emgs: "visa怎么续签" becomes "签证怎么续签"), so the question and the stored
    phrasings are tokenised in the same words. Latin words match whole words only; Chinese anywhere.
    Longer words are replaced first, so 学生签证 is not cut to 学生 + 签证's replacement."""
    first: dict[str, str] = {}
    for g in groups:
        for w in g[1:]:
            first.setdefault(w, g[0])
    if not first:
        return None
    parts = []
    for w in sorted(first, key=len, reverse=True):
        parts.append(re.escape(w) if _CJK.fullmatch(w) else rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])")
    pattern = re.compile("|".join(parts))
    return lambda text: pattern.sub(lambda m: f" {first[m.group(0)]} ", text.lower())


class _Index:
    """IDF-weighted overlap over a small in-memory corpus. Rebuilt whenever the DB changes."""

    def __init__(self, docs: list[tuple[int, str, set[str]]], rewrite: Callable[[str], str] | None = None):
        self.rewrite = rewrite
        self.docs = docs
        n = len(docs)
        df: dict[str, int] = {}
        for _, _, toks in docs:
            for t in toks:
                df[t] = df.get(t, 0) + 1
        self.df = df
        self.n = n
        self.unseen = math.log(n + 2) + 1.0

    def idf(self, t: str) -> float:
        d = self.df.get(t)
        return self.unseen if d is None else math.log((self.n + 1) / (d + 0.5)) + 1.0

    def query(self, text: str) -> set[str]:
        words, grams = split_tokens(self.rewrite(text) if self.rewrite else text)
        return words | {g for g in grams if g in self.df}

    def search(self, q: set[str], *, symmetric: bool, limit: int = 5) -> list[tuple[int, float, str]]:
        if not q or not self.docs:
            return []
        qw = {t: self.idf(t) for t in q}
        qsum = sum(qw.values())
        best: dict[int, tuple[float, str]] = {}
        for doc_id, phrase, toks in self.docs:
            common = q & toks
            if not common:
                continue
            hit = sum(qw[t] for t in common)
            qc = hit / qsum
            if symmetric:
                dsum = sum(self.idf(t) for t in toks)
                dc = hit / dsum if dsum else 0.0
                score = 2 * qc * dc / (qc + dc) if qc + dc else 0.0
                # A shared unit code (FIT2004) is a strong signal the question is about the same thing.
                if _UNIT.search(" ".join(common)):
                    score = min(1.0, score + 0.1)
            else:
                score = qc
            if score > best.get(doc_id, (0.0, ""))[0]:
                best[doc_id] = (score, phrase)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]
        return [(doc_id, s, p) for doc_id, (s, p) in ranked]


class KB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        # Deleted rows are overwritten, not just unlinked: a purged question must not stay readable in the
        # free pages of the file and of every backup taken from it (issue #10).
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript(SCHEMA)
        self._migrate()
        self._lock = threading.Lock()
        self._qa_index: _Index | None = None
        self._data_version = self._current_data_version()
        self._art_index: _Index | None = None

    def _migrate(self) -> None:
        """Columns added after a database was created. Rows already there were sent to Waldo (noted 1)."""
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(pending)")}
        for name, kind in (("updated_at", "REAL"), ("parts", "INTEGER NOT NULL DEFAULT 1"),
                           ("noted", "INTEGER NOT NULL DEFAULT 1")):
            if name not in have:
                self.db.execute(f"ALTER TABLE pending ADD COLUMN {name} {kind}")

    # -- indexes ---------------------------------------------------------------------------
    def _current_data_version(self) -> int:
        return self.db.execute("PRAGMA data_version").fetchone()[0]

    def _refresh_if_changed(self) -> None:
        """PRAGMA data_version moves when *another* connection commits (the CLI, the mamo sync
        timer). Our own writes invalidate directly."""
        v = self._current_data_version()
        if v != self._data_version:
            self._data_version = v
            self._invalidate()

    def _invalidate(self) -> None:
        self._qa_index = None
        self._art_index = None

    def _qa(self) -> _Index:
        self._refresh_if_changed()
        if self._qa_index is None:
            rewrite = synonym_rewriter(self.synonyms()) or (lambda text: text)
            rows = self.db.execute("SELECT qa_id, text FROM qa_phrase").fetchall()
            self._qa_index = _Index([(r["qa_id"], r["text"], tokens(rewrite(r["text"]))) for r in rows], rewrite)
        return self._qa_index

    # -- synonyms (issue #8) -----------------------------------------------------------------------
    # Groups of words that mean the same thing to a student (签证=visa=EMGS), kept in kv as one line per
    # group. Matching replaces each by the group's first word, so a taught answer phrased with 签证 is found
    # by a question that says visa. Model-free, like the rest of the matching.
    def synonyms(self) -> list[list[str]]:
        return [line.split("=") for line in self.kv_get("synonyms").split("\n") if "=" in line]

    def _save_synonyms(self, groups: list[list[str]]) -> None:
        self.kv_set("synonyms", "\n".join("=".join(g) for g in groups if len(g) > 1))
        self._invalidate()

    def add_synonyms(self, words: list[str]) -> list[str]:
        """Make words one term. Joins any group that already holds one of them. Returns the group."""
        new = []
        for w in (w.strip().lower() for w in words):
            if w and w not in new:
                new.append(w)
        if len(new) < 2:
            return new
        groups, group = [], new
        for g in self.synonyms():
            if set(g) & set(group):
                group = g + [w for w in group if w not in g]
            else:
                groups.append(g)
        with self._lock:
            self._save_synonyms(groups + [group])
        return group

    def remove_synonym(self, word: str) -> bool:
        word = word.strip().lower()
        groups = self.synonyms()
        if not any(word in g for g in groups):
            return False
        with self._lock:
            self._save_synonyms([[w for w in g if w != word] for g in groups])
        return True

    def rewrite(self, text: str) -> str:
        """The text in the synonyms' first words (what 「查」 and the tests see)."""
        fn = synonym_rewriter(self.synonyms())
        return fn(text) if fn else text

    def _art(self) -> tuple[_Index, _Index]:
        """Two indexes over the same articles: title + digest, and the full text."""
        self._refresh_if_changed()
        if self._art_index is None:
            rows = self.db.execute("SELECT id, title, digest, content FROM article").fetchall()
            heads = [(r["id"], r["title"], tokens(f"{r['title']} {r['digest'] or ''}")) for r in rows]
            full = [(r["id"], r["title"], tokens(f"{r['title']} {r['digest'] or ''} {(r['content'] or '')[:6000]}"))
                    for r in rows]
            self._art_index = (_Index(heads), _Index(full))
        return self._art_index

    def match_qa(self, question: str, limit: int = 3) -> list[Match]:
        with self._lock:
            idx = self._qa()
            hits = idx.search(idx.query(question), symmetric=True, limit=limit)
        return [Match("qa", i, s, p) for i, s, p in hits]

    def match_articles(self, question: str, limit: int = 3) -> list[Match]:
        """Score = 0.6 x coverage by title/digest + 0.4 x coverage by full text. The title is what
        the article is about; the body mentions many things in passing (签证 in a travel guide)."""
        with self._lock:
            heads, full = self._art()
            # Single characters (选, 交, 用 in 怎么选课/学费怎么交/怎么用) carry no topic and only dilute
            # coverage; a taught answer still sees them.
            q = {t for t in full.query(expand_for_articles(question)) if len(t) >= 2}
            head_scores = {i: s for i, s, _ in heads.search(q, symmetric=False, limit=len(heads.docs))}
            head_toks = {d: t for d, _, t in heads.docs}
            out = []
            for i, s, title in full.search(q, symmetric=False, limit=len(full.docs)):
                toks = next(t for d, _, t in full.docs if d == i)
                matched = {t for t in q & toks if len(t) >= 2}
                # At least two distinct matched terms, so one common word in a body can't pull in an article.
                # One is enough when it is what this article's title or summary is about and few others
                # share it: "怎么选课" is a fair question, while 指南 or monash is in every title.
                if len(matched) < 2 and not (matched and all(
                        t in head_toks[i] and t not in _GENERIC and heads.df.get(t, 0) <= max(1, heads.n // 2)
                        for t in matched)):
                    continue
                out.append(Match("article", i, 0.6 * head_scores.get(i, 0.0) + 0.4 * s, title))
        out.sort(key=lambda m: -m.score)
        return out[:limit]

    # -- qa ----------------------------------------------------------------------------------
    def add_qa(self, question: str, answer: str, url: str | None = None) -> int:
        now = time.time()
        with self._lock:
            cur = self.db.execute("INSERT INTO qa(answer, url, created_at, updated_at) VALUES (?,?,?,?)",
                                  (answer, url, now, now))
            qa_id = cur.lastrowid
            self.db.execute("INSERT INTO qa_phrase(qa_id, text) VALUES (?,?)", (qa_id, question))
            self._invalidate()
        return qa_id

    def add_phrase(self, qa_id: int, text: str) -> bool:
        with self._lock:
            if not self.db.execute("SELECT 1 FROM qa WHERE id=?", (qa_id,)).fetchone():
                return False
            self.db.execute("INSERT INTO qa_phrase(qa_id, text) VALUES (?,?)", (qa_id, text))
            self._invalidate()
        return True

    def delete_phrase(self, qa_id: int, text: str) -> bool:
        """Drop one phrasing. The first one stays, since import-qa uses it to recognise the pair."""
        with self._lock:
            ids = [r["id"] for r in self.db.execute(
                "SELECT id FROM qa_phrase WHERE qa_id=? ORDER BY id", (qa_id,))]
            hit = self.db.execute("SELECT id FROM qa_phrase WHERE qa_id=? AND text=?", (qa_id, text)).fetchone()
            if not hit or hit["id"] == ids[0]:
                return False
            self.db.execute("DELETE FROM qa_phrase WHERE id=?", (hit["id"],))
            self._invalidate()
        return True

    def update_qa(self, qa_id: int, answer: str, url: str | None = None) -> bool:
        with self._lock:
            cur = self.db.execute("UPDATE qa SET answer=?, url=COALESCE(?, url), updated_at=? WHERE id=?",
                                  (answer, url, time.time(), qa_id))
        return cur.rowcount > 0

    def delete_qa(self, qa_id: int) -> bool:
        with self._lock:
            cur = self.db.execute("DELETE FROM qa WHERE id=?", (qa_id,))
            self._invalidate()
        return cur.rowcount > 0

    def get_qa(self, qa_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM qa WHERE id=?", (qa_id,)).fetchone()

    def phrases(self, qa_id: int) -> list[str]:
        return [r["text"] for r in self.db.execute("SELECT text FROM qa_phrase WHERE qa_id=? ORDER BY id", (qa_id,))]

    def hit(self, qa_id: int) -> None:
        self.db.execute("UPDATE qa SET hits=hits+1 WHERE id=?", (qa_id,))

    def count(self, table: str) -> int:
        assert table in {"qa", "qa_phrase", "article", "contact"}
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    # -- articles -----------------------------------------------------------------------------
    def upsert_article(self, url: str, title: str, digest: str | None, content: str | None,
                       published_at: float | None) -> int:
        with self._lock:
            self.db.execute(
                "INSERT INTO article(url, title, digest, content, published_at, fetched_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(url) DO UPDATE SET title=excluded.title, digest=excluded.digest, "
                "content=excluded.content, published_at=COALESCE(excluded.published_at, published_at), "
                "fetched_at=excluded.fetched_at",
                (url, title, digest, content, published_at, time.time()))
            self._invalidate()
            return self.db.execute("SELECT id FROM article WHERE url=?", (url,)).fetchone()[0]

    def get_article(self, art_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM article WHERE id=?", (art_id,)).fetchone()

    def delete_article(self, art_id: int) -> bool:
        with self._lock:
            cur = self.db.execute("DELETE FROM article WHERE id=?", (art_id,))
            self._invalidate()
        return cur.rowcount > 0

    # -- pending ------------------------------------------------------------------------------
    def add_pending(self, user_id: str, question: str, noted: bool = True) -> int:
        """noted=False: the note to Waldo is sent later (due_pending), so lines that follow can join it."""
        now = time.time()
        cur = self.db.execute("INSERT INTO pending(user_id, question, created_at, updated_at, noted) VALUES (?,?,?,?,?)",
                              (user_id, question, now, now, 1 if noted else 0))
        return cur.lastrowid

    def recent_pending(self, user_id: str, within_s: float) -> sqlite3.Row | None:
        """This person's open question that a line was added to in the last within_s seconds."""
        return self.db.execute("SELECT * FROM pending WHERE status='open' AND user_id=? AND COALESCE(updated_at, created_at)>=?"
                               " ORDER BY id DESC LIMIT 1", (user_id, time.time() - within_s)).fetchone()

    def append_pending(self, pid: int, line: str) -> None:
        self.db.execute("UPDATE pending SET question=question || char(10) || ?, parts=parts+1, updated_at=? WHERE id=?",
                        (line, time.time(), pid))

    def due_pending(self, quiet_s: float, now: float | None = None) -> list[sqlite3.Row]:
        """Open questions with lines Waldo has not been sent, and nothing added for quiet_s seconds."""
        return self.db.execute("SELECT * FROM pending WHERE status='open' AND parts>noted AND COALESCE(updated_at, created_at)<=?"
                               " ORDER BY id", ((now or time.time()) - quiet_s,)).fetchall()

    def mark_noted(self, pid: int, parts: int) -> None:
        self.db.execute("UPDATE pending SET noted=? WHERE id=?", (parts, pid))

    def said_between(self, user_id: str, start: float, end: float) -> list[str]:
        """What a person asked between two times, oldest first (commands, thanks and goodbyes left out)."""
        return [r[0] for r in self.db.execute("SELECT question FROM log WHERE user_id=? AND at>=? AND at<=?"
                                              " AND route NOT IN ('command', 'chat')"
                                              " ORDER BY at", (user_id, start, end))]

    def open_pending(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM pending WHERE status='open' ORDER BY id LIMIT ?", (limit,)).fetchall()

    def get_pending(self, pid: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM pending WHERE id=?", (pid,)).fetchone()

    def close_pending(self, pid: int, status: str, qa_id: int | None = None) -> None:
        self.db.execute("UPDATE pending SET status=?, qa_id=? WHERE id=?", (status, qa_id, pid))

    # -- outbox -------------------------------------------------------------------------------------
    def queue_outbox(self, user_id: str, text: str) -> None:
        self.db.execute("INSERT INTO outbox(user_id, text, created_at) VALUES (?,?,?)", (user_id, text, time.time()))

    def take_outbox(self, user_id: str, max_age_s: float | None = None) -> list[tuple[float, str]]:
        """(queued at, text) of everything waiting for user_id, marked delivered. Rows older than
        max_age_s are left out and stay undelivered: after a month the asker has moved on, and a
        reply out of nowhere reads as spam (issue #5)."""
        since = time.time() - max_age_s if max_age_s else 0
        rows = self.db.execute("SELECT id, text, created_at FROM outbox WHERE user_id=? AND delivered_at IS NULL "
                               "AND created_at>=? ORDER BY id", (user_id, since)).fetchall()
        if rows:
            self.db.executemany("UPDATE outbox SET delivered_at=? WHERE id=?", [(time.time(), r["id"]) for r in rows])
        return [(r["created_at"], r["text"]) for r in rows]

    def expired_outbox(self, max_age_s: float) -> int:
        return self.db.execute("SELECT COUNT(*) FROM outbox WHERE delivered_at IS NULL AND created_at<?",
                               (time.time() - max_age_s,)).fetchone()[0]

    # -- contacts / kv / log --------------------------------------------------------------------
    def touch_contact(self, user_id: str, context_token: str | None) -> bool:
        """Record a message from user_id. Returns True the first time we see them."""
        now = time.time()
        row = self.db.execute("SELECT 1 FROM contact WHERE user_id=?", (user_id,)).fetchone()
        if row:
            self.db.execute("UPDATE contact SET context_token=COALESCE(?, context_token), last_seen=?, "
                            "messages=messages+1 WHERE user_id=?", (context_token, now, user_id))
            return False
        self.db.execute("INSERT INTO contact(user_id, context_token, first_seen, last_seen, messages) "
                        "VALUES (?,?,?,?,1)", (user_id, context_token, now, now))
        return True

    def context_token(self, user_id: str) -> str | None:
        row = self.db.execute("SELECT context_token FROM contact WHERE user_id=?", (user_id,)).fetchone()
        return row["context_token"] if row else None

    def kv_get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO kv(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))

    def log(self, user_id: str, question: str, route: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO log(at, user_id, question, route, detail) VALUES (?,?,?,?,?)",
                        (time.time(), user_id, question, route, detail))

    # -- retention (issue #10) ---------------------------------------------------------------------------
    def purge(self, keep_days: float, delivered_days: float, now: float | None = None) -> dict[str, int]:
        """Delete what users said once it is no longer useful: the log after keep_days, replies
        delivered more than delivered_days ago (and undelivered ones after keep_days), and closed
        待答 questions after keep_days. Taught Q&A, open questions and contacts stay."""
        now = now or time.time()
        old, sent = now - keep_days * 86400, now - delivered_days * 86400
        return {
            "log": self.db.execute("DELETE FROM log WHERE at<?", (old,)).rowcount,
            "outbox": self.db.execute("DELETE FROM outbox WHERE (delivered_at IS NOT NULL AND delivered_at<?) "
                                      "OR created_at<?", (sent, old)).rowcount,
            "pending": self.db.execute("DELETE FROM pending WHERE status!='open' AND created_at<?", (old,)).rowcount,
        }

    def forget_user(self, user_id: str) -> int:
        """Everything stored about one person: their questions, replies waiting for them, their
        待答 questions and the contact row. Q&A taught from their question stay (they are the owner's)."""
        return sum(self.db.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,)).rowcount
                   for table in ("log", "outbox", "pending", "contact"))

    # -- what went unanswered (issue #8) ----------------------------------------------------------------
    def misses(self, days: float, limit: int = 10) -> list[tuple[str, int]]:
        """(question, times asked) for questions nobody could answer in the last `days`, most asked first."""
        rows = self.db.execute(
            "SELECT question, COUNT(*) AS n FROM log WHERE at>? AND route='miss' "
            "GROUP BY question ORDER BY n DESC, MAX(at) DESC LIMIT ?", (time.time() - days * 86400, limit)).fetchall()
        return [(r["question"], r["n"]) for r in rows]

    def unsure_hits(self, days: float, limit: int = 10) -> list[tuple[str, int, int, float]]:
        """(question, times, qa id, score) for questions answered with "你问的是不是…" in the last `days`."""
        rows = self.db.execute("SELECT question, detail FROM log WHERE at>? AND route='qa' AND detail LIKE '%(weak)'",
                               (time.time() - days * 86400,)).fetchall()
        seen: dict[str, list] = {}
        for r in rows:
            m = re.match(r"qa#(\d+) ([0-9.]+)", r["detail"] or "")
            if m:
                hit = seen.setdefault(r["question"], [0, int(m.group(1)), float(m.group(2))])
                hit[0] += 1
        return sorted(((q, n, i, s) for q, (n, i, s) in seen.items()), key=lambda x: -x[1])[:limit]

    # -- listing, backup and export -------------------------------------------------------------------
    def list_qa(self, offset: int = 0, limit: int = 20) -> list[sqlite3.Row]:
        """Q&A pairs in id order, with the first phrasing (the "main" question) of each."""
        return self.db.execute(
            "SELECT qa.id, qa.hits, (SELECT text FROM qa_phrase WHERE qa_id=qa.id ORDER BY id LIMIT 1) AS question "
            "FROM qa ORDER BY qa.id LIMIT ? OFFSET ?", (limit, offset)).fetchall()

    def backup(self, dest: Path) -> None:
        """A consistent copy while the bot keeps running (SQLite's online backup, not a file copy,
        which can catch the WAL halfway)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        out = sqlite3.connect(str(tmp))
        try:
            with self._lock:
                self.db.backup(out)
        finally:
            out.close()
        tmp.replace(dest)

    def export_qa(self) -> list[dict]:
        """What the owner taught, without anyone's questions or ids: safe to keep in git (issue #1, #10)."""
        return [{"phrases": self.phrases(r["id"]), "answer": r["answer"], "url": r["url"], "hits": r["hits"]}
                for r in self.db.execute("SELECT id, answer, url, hits FROM qa ORDER BY id").fetchall()]

    def import_qa(self, items: list[dict], replace: bool = False) -> tuple[int, int, int]:
        """Add exported pairs. One whose first phrasing and answer are already here is not added again,
        but phrasings it is missing are added to it, so a file can grow new phrasings for pairs that are
        live. With replace, a pair here with the same first phrasing but another answer gets the file's
        answer and link (it keeps its number and hits) instead of a second copy. Importing the same file
        twice changes nothing. Returns (pairs added, phrasings added, answers replaced)."""
        known, by_first = {}, {}
        for r in self.db.execute("SELECT id, answer FROM qa ORDER BY id").fetchall():
            first = (self.phrases(r["id"])[:1] or [""])[0]
            known.setdefault(first + "\0" + r["answer"], r["id"])
            by_first.setdefault(first, r["id"])
        added = new_phrases = replaced = 0
        for item in items:
            phrases = [p for p in item.get("phrases") or [] if p.strip()]
            if not phrases or not item.get("answer"):
                continue
            key = phrases[0] + "\0" + item["answer"]
            if key not in known and replace and phrases[0] in by_first:
                self.update_qa(by_first[phrases[0]], item["answer"], item.get("url"))
                known[key] = by_first[phrases[0]]
                replaced += 1
            if key in known:
                have = set(self.phrases(known[key]))
                for p in phrases[1:]:
                    if p not in have and self.add_phrase(known[key], p):
                        have.add(p)
                        new_phrases += 1
                continue
            qa_id = self.add_qa(phrases[0], item["answer"], item.get("url"))
            for p in phrases[1:]:
                self.add_phrase(qa_id, p)
            known[key] = qa_id
            added += 1
        return added, new_phrases, replaced
