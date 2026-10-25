"""The chunk index behind the optional RAG mode: everything the bot can cite, cut into short passages.

Sources: each taught Q&A (all its phrasings + the answer), 马莫百科 articles cut by paragraph, and Monash
Hub's Chinese guide pages and FAQ. Every chunk keeps the link it came from, so an answer built on it can
point there. `python -m wxbot index` builds it; after that, mamo-sync and import-qa keep it current.

Updating is incremental: a chunk whose text did not change keeps its vector, so a rerun only embeds
what is new. The RAG answer (wxbot/rag.py) reads it when WXBOT_RAG=1; `python -m wxbot search` shows
what a question would find.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from . import hub
from .embed import Embedder
from .kb import KB

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunk (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,          -- qa | article | hub_guide | hub_faq
    ref_id TEXT NOT NULL,          -- qa id, article id, guide or FAQ slug
    part INTEGER NOT NULL,
    url TEXT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    sha1 TEXT NOT NULL,
    stamp TEXT,                    -- hub_guide: the page's last_changed, so unchanged pages are not fetched
    vec BLOB,                      -- float32, unit length; NULL until embedded
    model TEXT,                    -- which model made vec
    updated_at REAL NOT NULL,
    UNIQUE(source, ref_id, part)
);
CREATE INDEX IF NOT EXISTS chunk_by_source ON chunk(source, ref_id);
"""

SOURCES = ("qa", "article", "hub_guide", "hub_faq")

MAX_CHARS = 500     # a chunk closes before it would pass this
OVERLAP = 80        # the next chunk starts with the last characters of the one before
_SENTENCE_END = re.compile(r"[。！？；!?;]|\.(?=\s)")
_CJK = re.compile(r"[一-鿿]")


@dataclass
class Doc:
    source: str
    ref_id: str
    part: int
    url: str | None
    title: str
    text: str
    stamp: str | None = None


# -- cutting text ---------------------------------------------------------------------------------

def _cut(p: str) -> int:
    """Where to cut a paragraph longer than MAX_CHARS: after the last sentence end that fits."""
    ends = [m.end() for m in _SENTENCE_END.finditer(p, 0, MAX_CHARS)]
    return ends[-1] if ends and ends[-1] >= MAX_CHARS // 3 else MAX_CHARS


def split_text(title: str, text: str) -> list[str]:
    """Paragraphs packed into chunks of up to MAX_CHARS, each starting with the title (a paragraph alone
    often does not say what it is about) and overlapping the previous chunk by OVERLAP characters."""
    pieces = []
    for p in (line.strip() for line in text.split("\n")):
        while len(p) > MAX_CHARS:
            at = _cut(p)
            pieces.append(p[:at])
            p = p[at:].lstrip()
        if p:
            pieces.append(p)
    chunks, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + 1 + len(piece) > MAX_CHARS:
            chunks.append(cur)
            cur = cur[-OVERLAP:] + "\n" + piece
        else:
            cur = f"{cur}\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return [f"{title}\n{c}" for c in chunks]


def _docs(source: str, ref_id: str, url: str | None, title: str, text: str, stamp: str | None = None) -> list[Doc]:
    return [Doc(source, ref_id, i, url, title, t, stamp) for i, t in enumerate(split_text(title, text))]


# -- the sources ----------------------------------------------------------------------------------

def qa_docs(kb: KB) -> list[Doc]:
    out = []
    for r in kb.db.execute("SELECT id, answer, url FROM qa ORDER BY id").fetchall():
        phrases = kb.phrases(r["id"])
        if not phrases:
            continue
        # One chunk per pair even when long: the answer is one unit the owner wrote.
        text = "问：" + " / ".join(phrases) + "\n答：" + r["answer"]
        out.append(Doc("qa", str(r["id"]), 0, r["url"], phrases[0], text))
    return out


def article_docs(kb: KB) -> list[Doc]:
    out = []
    for r in kb.db.execute("SELECT id, url, title, digest, content FROM article ORDER BY id").fetchall():
        body = r["content"] or r["digest"] or ""
        out.extend(_docs("article", str(r["id"]), r["url"], r["title"], body))
    return out


def _spans(spans: list[dict[str, Any]]) -> str:
    return "".join(s.get("text") or "" for s in spans).strip()


def guide_text(blocks: list[dict[str, Any]]) -> str:
    """A guide page's blocks as plain lines. Lines the Hub has no Chinese for are left out: the bot does
    not paste or translate English Handbook prose, so it must not cite it either. A line of
    up to three words (a name, a code, WES) stays."""
    lines = []
    for b in blocks:
        kind = b.get("type")
        if kind == "heading":
            lines.append(b.get("text") or "")
        elif kind == "paragraph":
            lines.append(_spans(b.get("spans") or []))
        elif kind == "list":
            lines.extend("· " + _spans(item) for item in b.get("items") or [])
        elif kind == "table":
            for row in [b.get("columns") or []] + (b.get("rows") or []):
                lines.append(" | ".join(str(c) for c in row if c))
    return "\n".join(line for line in (x.strip() for x in lines) if line and (_CJK.search(line) or len(line.split()) <= 3))


def _stamp(page: dict[str, Any]) -> str:
    tr = page.get("translation") or {}
    return f"{page.get('last_changed')}|{tr.get('stale')}|{tr.get('reviewed')}|{tr.get('machine')}"


async def hub_guide_docs(http: aiohttp.ClientSession, known: dict[str, str], full: bool = False
                         ) -> tuple[list[Doc], set[str]] | None:
    """(new or changed chunks, slugs whose chunks stay as they are), or None when the Hub did not answer.
    Only pages the Hub has in Chinese. `known` is slug -> stamp of what is indexed already."""
    pages, offset = [], 0
    while True:
        status, body = await hub._call(http, "GET", "/guides", 20.0,
                                       params={"limit": 500, "offset": offset, "locale": "zh"})
        results = (body or {}).get("results")
        if results is None:
            return None
        pages.extend(results)
        offset += len(results)
        if not results or offset >= (body.get("total") or 0):
            break
    keep, todo = set(), []
    for p in pages:
        if not p.get("slug") or not p.get("translation") or p.get("requires_sign_in"):
            continue
        if not full and known.get(p["slug"]) == _stamp(p):
            keep.add(p["slug"])
        else:
            todo.append(p)
    sem = asyncio.Semaphore(4)

    async def one(p: dict[str, Any]) -> list[Doc]:
        async with sem:
            status, page = await hub._call(http, "GET", f"/guides/{p['slug']}", 20.0, params={"locale": "zh"})
        if not page:
            if p["slug"] in known:
                keep.add(p["slug"])     # a passing failure: keep the old chunks rather than drop them
            return []
        text = guide_text(page.get("blocks") or [])
        if len(text) < 40:
            return []
        return _docs("hub_guide", p["slug"], page.get("url") or p.get("url"), page.get("title") or p["slug"],
                     text, _stamp(p))

    docs = [d for part in await asyncio.gather(*(one(p) for p in todo)) for d in part]
    return docs, keep


async def hub_faq_docs(http: aiohttp.ClientSession) -> list[Doc] | None:
    status, body = await hub._call(http, "GET", "/faq", 20.0, params={"limit": 200, "locale": "zh"})
    results = (body or {}).get("results")
    if results is None:
        return None
    out = []
    for f in results:
        q, a = (f.get("question") or "").strip(), (f.get("answer") or "").strip()
        if f.get("slug") and q and _CJK.search(a):
            out.extend(_docs("hub_faq", f["slug"], f.get("official_url"), q, "答：" + a))
    return out


# -- the table ------------------------------------------------------------------------------------

def _sha1(doc: Doc) -> str:
    return hashlib.sha1(f"{doc.url}\0{doc.title}\0{doc.text}".encode()).hexdigest()


class Chunks:
    def __init__(self, kb: KB):
        self.kb = kb
        self.db = kb.db
        self.db.executescript(SCHEMA)

    def count(self, source: str | None = None) -> int:
        if source:
            return self.db.execute("SELECT COUNT(*) FROM chunk WHERE source=?", (source,)).fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]

    def stamps(self, source: str) -> dict[str, str]:
        return {r[0]: r[1] or "" for r in self.db.execute(
            "SELECT ref_id, MIN(stamp) FROM chunk WHERE source=? GROUP BY ref_id", (source,))}

    def sync(self, source: str, docs: list[Doc], keep_refs: set[str] = frozenset()) -> dict[str, int]:
        """Make the table hold exactly `docs` for this source, plus whatever it has for keep_refs.
        A chunk whose text changed loses its vector; one that did not keeps it."""
        now = time.time()
        have = {(r["ref_id"], r["part"]): (r["id"], r["sha1"]) for r in self.db.execute(
            "SELECT id, ref_id, part, sha1 FROM chunk WHERE source=?", (source,))}
        added = changed = 0
        want = set()
        with self.kb._lock:
            self.db.execute("BEGIN")
            for d in docs:
                key, sha = (d.ref_id, d.part), _sha1(d)
                want.add(key)
                old = have.get(key)
                if old and old[1] == sha:
                    if d.stamp is not None:
                        self.db.execute("UPDATE chunk SET stamp=? WHERE id=?", (d.stamp, old[0]))
                    continue
                if old:
                    self.db.execute("UPDATE chunk SET url=?, title=?, text=?, sha1=?, stamp=?, vec=NULL, model=NULL, "
                                    "updated_at=? WHERE id=?", (d.url, d.title, d.text, sha, d.stamp, now, old[0]))
                    changed += 1
                else:
                    self.db.execute("INSERT INTO chunk(source, ref_id, part, url, title, text, sha1, stamp, updated_at) "
                                    "VALUES (?,?,?,?,?,?,?,?,?)",
                                    (source, d.ref_id, d.part, d.url, d.title, d.text, sha, d.stamp, now))
                    added += 1
            gone = [cid for (ref, part), (cid, _) in have.items() if (ref, part) not in want and ref not in keep_refs]
            self.db.executemany("DELETE FROM chunk WHERE id=?", [(c,) for c in gone])
            self.db.execute("COMMIT")
        return {"added": added, "changed": changed, "removed": len(gone)}

    def embed_missing(self, embedder: Embedder, batch: int = 64) -> int:
        """Vectors for every chunk that has none, or one from another model. Returns how many."""
        done = 0
        while True:
            rows = self.db.execute("SELECT id, title, text FROM chunk WHERE vec IS NULL OR model IS NOT ? "
                                   "ORDER BY id LIMIT ?", (embedder.name, batch)).fetchall()
            if not rows:
                return done
            vecs = embedder.passages([r["text"] for r in rows])
            with self.kb._lock:
                self.db.executemany("UPDATE chunk SET vec=?, model=? WHERE id=?",
                                    [(v.astype("float32").tobytes(), embedder.name, r["id"]) for r, v in zip(rows, vecs)])
            done += len(rows)


async def build(kb: KB, http: aiohttp.ClientSession | None, embedder: Embedder | None, *,
                sources: tuple[str, ...] = SOURCES, full: bool = False) -> dict[str, Any]:
    """Bring the index up to date. A source that could not be read (the Hub is down) keeps what it had."""
    store = Chunks(kb)
    report: dict[str, Any] = {}
    if "qa" in sources:
        report["qa"] = store.sync("qa", qa_docs(kb))
    if "article" in sources:
        report["article"] = store.sync("article", article_docs(kb))
    if http is not None and "hub_guide" in sources:
        got = await hub_guide_docs(http, store.stamps("hub_guide"), full)
        report["hub_guide"] = store.sync("hub_guide", *got) if got else "hub unreachable, kept"
    if http is not None and "hub_faq" in sources:
        faq = await hub_faq_docs(http)
        report["hub_faq"] = store.sync("hub_faq", faq) if faq is not None else "hub unreachable, kept"
    if embedder is not None:
        # Embedding a few thousand chunks takes minutes on a small CPU; keep the event loop free.
        report["embedded"] = await asyncio.get_running_loop().run_in_executor(None, store.embed_missing, embedder)
    report["total"] = {s: store.count(s) for s in SOURCES}
    return report


def built(kb: KB) -> bool:
    """Whether someone has run `index` here; until then the other commands leave the index alone."""
    return Chunks(kb).count() > 0
