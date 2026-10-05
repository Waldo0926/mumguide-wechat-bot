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
    qa_id INTEGER
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
"""

STOPWORDS = set(
    "的 了 吗 呢 啊 呀 吧 嘛 哦 哈 是 在 我 你 他 她 它 我们 你们 他们 这 那 这个 那个 这些 那些 "
    "怎么 怎么样 怎样 如何 什么 啥 哪 哪里 哪儿 哪个 哪些 为什么 为啥 多少 几 请问 请 问 问下 问一下 一下 "
    "有 没有 有没有 可以 能 能不能 可不可以 要 需要 会 想 想问 知道 大家 谁 就 都 也 还 和 与 及 或 或者 "
    "吗? 嗯 呃 麻烦 谢谢 感谢 一个 一些 是不是 应该 得 地 着 过 被 把 给 对 从 到 跟 "
    "a an the is are was were do does did i you we to of in on for and or how what when where which "
    "can could should would will my me it this that there any".split()
)

_CJK = re.compile(r"[一-鿿]+")
_WORD = re.compile(r"[a-z0-9]+|[一-鿿]+")
_UNIT = re.compile(r"\b([a-z]{3}\d{4})\b")


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
    for run in _CJK.findall(text):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg[0] not in STOPWORDS and bg[1] not in STOPWORDS and bg not in STOPWORDS:
                grams.add(bg)
    return words, grams - words


def tokens(text: str) -> set[str]:
    words, grams = split_tokens(text)
    return words | grams


@dataclass
class Match:
    kind: str          # qa | article
    id: int
    score: float
    phrase: str        # the stored phrasing (or article title) that matched


class _Index:
    """IDF-weighted overlap over a small in-memory corpus. Rebuilt whenever the DB changes."""

    def __init__(self, docs: list[tuple[int, str, set[str]]]):
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
        words, grams = split_tokens(text)
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
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._qa_index: _Index | None = None
        self._data_version = self._current_data_version()
        self._art_index: _Index | None = None

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
            rows = self.db.execute("SELECT qa_id, text FROM qa_phrase").fetchall()
            self._qa_index = _Index([(r["qa_id"], r["text"], tokens(r["text"])) for r in rows])
        return self._qa_index

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
            q = full.query(question)
            head_scores = {i: s for i, s, _ in heads.search(q, symmetric=False, limit=len(heads.docs))}
            out = []
            for i, s, title in full.search(q, symmetric=False, limit=len(full.docs)):
                toks = next(t for d, _, t in full.docs if d == i)
                # At least two distinct matched terms, so one common word can't pull in an article.
                if len({t for t in q & toks if len(t) >= 2}) < 2:
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
    def add_pending(self, user_id: str, question: str) -> int:
        cur = self.db.execute("INSERT INTO pending(user_id, question, created_at) VALUES (?,?,?)",
                              (user_id, question, time.time()))
        return cur.lastrowid

    def open_pending(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM pending WHERE status='open' ORDER BY id LIMIT ?", (limit,)).fetchall()

    def get_pending(self, pid: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM pending WHERE id=?", (pid,)).fetchone()

    def close_pending(self, pid: int, status: str, qa_id: int | None = None) -> None:
        self.db.execute("UPDATE pending SET status=?, qa_id=? WHERE id=?", (status, qa_id, pid))

    # -- outbox -------------------------------------------------------------------------------------
    def queue_outbox(self, user_id: str, text: str) -> None:
        self.db.execute("INSERT INTO outbox(user_id, text, created_at) VALUES (?,?,?)", (user_id, text, time.time()))

    def take_outbox(self, user_id: str) -> list[str]:
        rows = self.db.execute("SELECT id, text FROM outbox WHERE user_id=? AND delivered_at IS NULL ORDER BY id",
                               (user_id,)).fetchall()
        if rows:
            self.db.executemany("UPDATE outbox SET delivered_at=? WHERE id=?", [(time.time(), r["id"]) for r in rows])
        return [r["text"] for r in rows]

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
