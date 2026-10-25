"""Hybrid search over the chunk index: the Q&A matcher's words, plus local sentence vectors.

The two rankings are merged with reciprocal rank fusion (RRF): a chunk scores 1 / (k + rank) in each
list it appears in. Ranks, not raw scores, so an IDF overlap and a cosine never have to be put on one
scale. Either list alone still works: without onnxruntime the vector list is simply empty.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from .chunks import SCHEMA
from .embed import Embedder
from .kb import KB, _Index, synonym_rewriter, tokens

RRF_K = 60
CANDIDATES = 20     # from each list, before fusing
PER_URL = 2         # one long page must not fill all five places
# Below these a chunk is not a candidate at all, so a question about nothing in the index gets nothing
# back (and the RAG mode then does not call the model). Tuned with `python -m wxbot eval`.
LEX_MIN = float(os.environ.get("WXBOT_RAG_LEX_MIN", "0.3"))
VEC_MIN = float(os.environ.get("WXBOT_RAG_VEC_MIN", "0.45"))


@dataclass
class Hit:
    id: int
    source: str
    ref_id: str
    url: str | None
    title: str
    text: str
    score: float                # RRF
    lex: float | None = None    # IDF coverage of the question, when in the lexical list
    cos: float | None = None    # cosine, when in the vector list


class Retriever:
    def __init__(self, kb: KB, embedder: Embedder | None = None):
        self.kb = kb
        kb.db.executescript(SCHEMA)
        self.embedder = embedder
        self._lock = threading.Lock()
        self._sig: tuple | None = None
        self._rows: dict[int, dict] = {}
        self._lex: _Index | None = None
        self._ids: list[int] = []
        self._mat = None
        self._toks: dict[int, tuple[str, set[str]]] = {}

    def _signature(self) -> tuple:
        n, last = self.kb.db.execute("SELECT COUNT(*), MAX(updated_at) FROM chunk").fetchone()
        model = self.embedder.name if self.embedder is not None else ""
        embedded = self.kb.db.execute("SELECT COUNT(*) FROM chunk WHERE vec IS NOT NULL AND model=?",
                                      (model,)).fetchone()[0]
        return n, last, embedded, self.kb.kv_get("synonyms")

    def _load(self) -> None:
        """Read the table again when it changed (another process ran `index`)."""
        sig = self._signature()
        if sig == self._sig:
            return
        rows = self.kb.db.execute("SELECT id, source, ref_id, url, title, text, sha1, vec, model FROM chunk").fetchall()
        rewrite = synonym_rewriter(self.kb.synonyms()) or (lambda text: text)
        if sig[3] != (self._sig or (None,) * 4)[3]:
            self._toks = {}
        # jieba takes seconds over a few thousand chunks; after a sync only the changed ones are cut again.
        toks = {}
        for r in rows:
            old = self._toks.get(r["id"])
            toks[r["id"]] = old if old and old[0] == r["sha1"] else (r["sha1"], tokens(rewrite(f"{r['title']} {r['text']}")))
        self._toks = toks
        self._rows = {r["id"]: dict(r) for r in rows}
        self._lex = _Index([(r["id"], r["title"], toks[r["id"]][1]) for r in rows], rewrite)
        self._ids, self._mat = [], None
        if self.embedder is not None:
            import numpy as np
            with_vec = [r for r in rows if r["vec"] is not None and r["model"] == self.embedder.name]
            if with_vec:
                self._ids = [r["id"] for r in with_vec]
                self._mat = np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in with_vec])
        self._sig = sig

    def search(self, question: str, limit: int = 5, per_url: int = PER_URL,
               sources: tuple[str, ...] | None = None) -> list[Hit]:
        with self._lock:
            self._load()
            lex_list: list[tuple[int, float]] = []
            if self._lex is not None:
                found = self._lex.search(self._lex.query(question), symmetric=False, limit=CANDIDATES * 3)
                lex_list = [(i, s) for i, s, _ in found if s >= LEX_MIN]
            vec_list: list[tuple[int, float]] = []
            if self._mat is not None:
                import numpy as np
                sims = self._mat @ self.embedder.query(question)
                order = np.argsort(-sims)[:CANDIDATES * 3]
                vec_list = [(self._ids[j], float(sims[j])) for j in order if sims[j] >= VEC_MIN]
            rows = self._rows
        if sources:
            lex_list = [x for x in lex_list if rows[x[0]]["source"] in sources]
            vec_list = [x for x in vec_list if rows[x[0]]["source"] in sources]
        fused: dict[int, Hit] = {}
        for rank, (cid, s) in enumerate(lex_list[:CANDIDATES], 1):
            fused[cid] = self._hit(rows[cid])
            fused[cid].score += 1 / (RRF_K + rank)
            fused[cid].lex = s
        for rank, (cid, s) in enumerate(vec_list[:CANDIDATES], 1):
            h = fused.setdefault(cid, self._hit(rows[cid]))
            h.score += 1 / (RRF_K + rank)
            h.cos = s
        out, per = [], {}
        for h in sorted(fused.values(), key=lambda h: -h.score):
            key = h.url or f"{h.source}#{h.ref_id}"
            if per.get(key, 0) >= per_url:
                continue
            per[key] = per.get(key, 0) + 1
            out.append(h)
            if len(out) == limit:
                break
        return out

    @staticmethod
    def _hit(r: dict) -> Hit:
        return Hit(r["id"], r["source"], r["ref_id"], r["url"], r["title"], r["text"], 0.0)
