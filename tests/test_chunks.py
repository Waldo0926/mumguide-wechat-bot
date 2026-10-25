"""The chunk index (wxbot/chunks.py) and hybrid search (wxbot/retrieve.py), with a fake Monash Hub and a
fake embedder: no model is downloaded and nothing leaves the machine."""
import asyncio
import sys

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from wxbot import __main__ as cli, chunks, config, embed
from wxbot.chunks import MAX_CHARS, OVERLAP, build, guide_text, split_text
from wxbot.kb import KB
from wxbot.retrieve import Retriever

# Words that mean one thing to the fake model: a question and a passage that share a group are close,
# however they are written. That is what a real model adds over the word overlap.
CONCEPTS = [("签证", "visa", "续签", "emgs"), ("学费", "缴费", "fees", "交钱"), ("宿舍", "住宿", "accommodation"),
            ("延期", "extension", "特殊考虑")]


class FakeEmbedder:
    name = "fake-v1"

    def __init__(self):
        self.calls = 0

    def _vec(self, text):
        t = text.lower()
        v = np.array([1.0 if any(w in t for w in g) else 0.0 for g in CONCEPTS] + [0.1], dtype=np.float32)
        return v / np.linalg.norm(v)

    def passages(self, texts):
        self.calls += len(texts)
        return np.vstack([self._vec(t) for t in texts])

    def query(self, text):
        return self._vec(text)


GUIDES = {
    "student-visa-renewal": {"translation": {"locale": "zh", "machine": True, "reviewed": False, "stale": False},
                             "last_changed": "2026-10-01", "url": "https://www.monash.edu.my/visa-renewal",
                             "title": "学生签证续签",
                             "blocks": [{"type": "heading", "text": "学生签证续签"},
                                        {"type": "paragraph", "spans": [{"text": "签证到期前三个月在 EMGS 网站提交续签申请。"}]},
                                        {"type": "paragraph", "spans": [{"text": "Bring your passport to the office."}]},
                                        {"type": "list", "items": [[{"text": "护照"}], [{"text": "EMGS"}]]}]},
    "english-only": {"translation": None, "last_changed": "2026-10-01", "url": "https://www.monash.edu/x",
                     "title": "English only", "blocks": [{"type": "paragraph", "spans": [{"text": "x" * 200}]}]},
    "staff-only": {"translation": {"locale": "zh"}, "requires_sign_in": True, "last_changed": "2026-10-01",
                   "url": "https://www.monash.edu/y", "title": "需要登录", "blocks": []},
}
FAQ = [{"slug": "pay-fees", "question": "学费怎么交？", "answer": "在 WES 里用 Flywire 或银行转账缴费。",
        "official_url": "https://www.monash.edu.my/fees"},
       {"slug": "english", "question": "What is WAM?", "answer": "Weighted average mark.", "official_url": None}]


def fake_hub(guides, faq, details):
    async def listing(request):
        offset, limit = int(request.query.get("offset", 0)), int(request.query.get("limit", 50))
        rows = [{"slug": s, **{k: v for k, v in g.items() if k != "blocks"}} for s, g in guides.items()]
        return web.json_response({"total": len(rows), "results": rows[offset:offset + limit]})

    async def detail(request):
        slug = request.match_info["slug"]
        details.append(slug)
        g = guides[slug]
        return web.json_response({"slug": slug, **g})

    async def faq_list(request):
        return web.json_response({"total": len(faq), "results": faq})

    app = web.Application()
    app.router.add_get("/guides", listing)
    app.router.add_get("/guides/{slug}", detail)
    app.router.add_get("/faq", faq_list)
    return app


@pytest.fixture
def kb(tmp_path):
    kb = KB(tmp_path / "kb.sqlite")
    qa = kb.add_qa("学费怎么交", "在 WES 的 Fees 页面缴费，截止日期见官网。", "https://www.monash.edu.my/fees")
    kb.add_phrase(qa, "交学费")
    kb.add_qa("宿舍怎么申请", "去 Sunway 或 Monash Residence 官网申请住宿。")
    body = "\n".join(f"第{i}段：新生报到要带护照、录取信和证件照片，先在 WES 完成选课再去报到。" * 3 for i in range(8))
    kb.upsert_article("https://mp.weixin.qq.com/s/arrive", "新生报到指南", "报到流程", body, None)
    return kb


def run_build(kb, monkeypatch, guides=GUIDES, faq=FAQ, embedder=None, **kw):
    details = []

    async def go():
        async with TestServer(fake_hub(guides, faq, details)) as server:
            monkeypatch.setattr(config, "HUB_API", f"http://127.0.0.1:{server.port}")
            import aiohttp
            async with aiohttp.ClientSession() as http:
                return await build(kb, http, embedder, **kw)
    return asyncio.run(go()), details


def test_split_text_packs_paragraphs_with_the_title_and_an_overlap():
    text = "\n".join("这是一段关于选课的说明，句子不长。" * 6 for _ in range(10))
    parts = split_text("选课指南", text)
    assert len(parts) > 1
    for p in parts:
        title, body = p.split("\n", 1)
        assert title == "选课指南" and len(body) <= MAX_CHARS + OVERLAP + 1
    for a, b in zip(parts, parts[1:]):
        assert b.split("\n", 1)[1].startswith(a.split("\n", 1)[1][-OVERLAP:])
    # A paragraph longer than a chunk is cut after a sentence, not in the middle of one.
    long = split_text("t", "很长的一句话。" * 200)
    assert all(p.endswith("。") for p in long[:-1])


def test_guide_text_leaves_out_english_the_hub_has_no_chinese_for():
    text = guide_text(GUIDES["student-visa-renewal"]["blocks"])
    assert "EMGS 网站提交续签申请" in text and "· 护照" in text and "· EMGS" in text
    assert "passport" not in text


def test_build_indexes_every_source_and_embeds_once(kb, monkeypatch):
    emb = FakeEmbedder()
    report, details = run_build(kb, monkeypatch, embedder=emb)
    total = report["total"]
    assert total["qa"] == 2 and total["article"] >= 2
    assert total["hub_guide"] == 1          # untranslated and sign-in pages are not cited
    assert total["hub_faq"] == 1            # the English-only answer is not either
    assert details == ["student-visa-renewal"]
    assert report["embedded"] == emb.calls == sum(total.values())
    qa_text = kb.db.execute("SELECT text FROM chunk WHERE source='qa' AND ref_id='1'").fetchone()[0]
    assert qa_text.startswith("问：学费怎么交 / 交学费\n答：")

    # Nothing changed: no page is fetched again and nothing is embedded again.
    report, details = run_build(kb, monkeypatch, embedder=emb)
    assert details == [] and report["embedded"] == 0
    assert report["qa"] == {"added": 0, "changed": 0, "removed": 0}

    # A changed answer is embedded again; a deleted article leaves the index.
    kb.update_qa(1, "在 WES 里缴费。")
    kb.delete_article(1)
    report, _ = run_build(kb, monkeypatch, embedder=emb)
    assert report["qa"]["changed"] == 1 and report["embedded"] == 1
    assert report["article"]["removed"] >= 2 and report["total"]["article"] == 0


def test_a_changed_hub_page_is_fetched_again_and_a_full_run_fetches_all(kb, monkeypatch):
    run_build(kb, monkeypatch)
    guides = {**GUIDES, "student-visa-renewal": {**GUIDES["student-visa-renewal"], "last_changed": "2026-10-20"}}
    _, details = run_build(kb, monkeypatch, guides=guides)
    assert details == ["student-visa-renewal"]
    _, details = run_build(kb, monkeypatch, guides=guides, full=True)
    assert details == ["student-visa-renewal"]


def test_hub_down_keeps_the_hub_chunks(kb, monkeypatch):
    run_build(kb, monkeypatch)
    monkeypatch.setattr(config, "HUB_API", "http://127.0.0.1:9")

    async def go():
        import aiohttp
        async with aiohttp.ClientSession() as http:
            return await build(kb, http, None)
    report = asyncio.run(go())
    assert report["hub_guide"] == "hub unreachable, kept" and report["total"]["hub_guide"] == 1
    assert report["total"]["hub_faq"] == 1


def test_hybrid_search_finds_by_meaning_what_the_words_miss(kb, monkeypatch):
    run_build(kb, monkeypatch, embedder=FakeEmbedder())
    question = "visa 快过期了"
    lexical = Retriever(kb).search(question)
    assert not any(h.source == "hub_guide" for h in lexical)
    hits = Retriever(kb, FakeEmbedder()).search(question)
    assert hits[0].source == "hub_guide" and hits[0].url == "https://www.monash.edu.my/visa-renewal"
    assert hits[0].cos > 0.9 and hits[0].lex is None


def test_hybrid_search_ranks_what_both_lists_agree_on_first(kb, monkeypatch):
    run_build(kb, monkeypatch, embedder=FakeEmbedder())
    hits = Retriever(kb, FakeEmbedder()).search("学费怎么交")
    assert hits[0].lex is not None and hits[0].cos is not None
    assert {h.source for h in hits[:2]} == {"qa", "hub_faq"}


def test_one_page_gets_at_most_two_places(kb, monkeypatch):
    run_build(kb, monkeypatch)
    hits = Retriever(kb).search("新生报到要带护照和录取信", limit=5)
    assert sum(h.url == "https://mp.weixin.qq.com/s/arrive" for h in hits) == 2


def test_search_sees_a_new_index_without_a_restart(kb, monkeypatch):
    r = Retriever(kb)
    assert r.search("宿舍怎么申请") == []
    run_build(kb, monkeypatch)
    assert r.search("宿舍怎么申请")[0].source == "qa"


def test_cli_index_and_search(kb, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "kb.sqlite")
    monkeypatch.setattr(embed, "load", lambda name=None: None)
    monkeypatch.setattr(sys, "argv", ["wxbot", "search", "宿舍"])
    cli.main()
    assert "run `python -m wxbot index` first" in capsys.readouterr().out
    run_build(kb, monkeypatch)
    cli.main()
    out = capsys.readouterr().out
    assert out.startswith("1. [qa 2]") and "宿舍怎么申请" in out


def test_import_qa_updates_a_built_index(kb, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "kb.sqlite")
    monkeypatch.setattr(embed, "load", lambda name=None: None)
    f = tmp_path / "qa.json"
    f.write_text('[{"phrases": ["图书馆几点关门"], "answer": "晚上十点"}]', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["wxbot", "import-qa", str(f)])
    cli.main()
    assert "index:" not in capsys.readouterr().out      # not built yet: left alone
    run_build(kb, monkeypatch)
    f.write_text('[{"phrases": ["自习室在哪"], "answer": "图书馆二楼"}]', encoding="utf-8")
    cli.main()
    assert "index: {'added': 1" in capsys.readouterr().out
    assert chunks.Chunks(kb).count("qa") == 4


def test_onnx_embedder_pools_cls_adds_the_bge_query_instruction_and_normalises(monkeypatch, tmp_path):
    """onnxruntime, tokenizers and huggingface_hub replaced by stand-ins: the wiring, not the model."""
    import types
    seen = {}

    class Enc:
        def __init__(self, text):
            self.ids, self.attention_mask, self.type_ids = [len(text), 1], [1, 1], [0, 0]

    class Tokenizer:
        @staticmethod
        def from_file(path):
            seen["tokenizer"] = path
            return Tokenizer()

        def enable_truncation(self, n):
            seen["max"] = n

        def enable_padding(self):
            pass

        def encode_batch(self, texts):
            seen.setdefault("texts", []).extend(texts)
            return [Enc(t) for t in texts]

    class Session:
        def __init__(self, path, opts, providers):
            seen["model"] = path

        def get_inputs(self):
            return [types.SimpleNamespace(name="input_ids"), types.SimpleNamespace(name="attention_mask")]

        def run(self, outputs, feed):
            seen["feed"] = sorted(feed)
            n = feed["input_ids"].shape[0]
            # (batch, tokens, dim): the first token is [CLS]
            return [np.tile(np.array([[[3.0, 4.0], [9.0, 9.0]]], dtype=np.float32), (n, 1, 1))]

    def snapshot_download(repo, cache_dir, allow_patterns):
        seen["repo"], seen["files"] = repo, allow_patterns
        return str(tmp_path)

    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(
        SessionOptions=lambda: types.SimpleNamespace(), InferenceSession=Session))
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=snapshot_download))
    monkeypatch.setitem(sys.modules, "tokenizers", types.SimpleNamespace(Tokenizer=Tokenizer))
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(embed, "_cache", {})
    e = embed.load("BAAI/bge-small-zh-v1.5")
    assert seen["repo"] == "Qdrant/bge-small-zh-v1.5" and seen["files"] == ["model_optimized.onnx", "tokenizer.json"]
    assert np.allclose(e.query("签证"), [0.6, 0.8])
    assert seen["texts"][-1] == embed.BGE_ZH_QUERY + "签证"
    assert seen["feed"] == ["attention_mask", "input_ids"]      # only the inputs the model has
    assert e.passages(["a"] * 20).shape == (20, 2) and seen["max"] == 512
    assert embed.load("off") is None and embed.load("BAAI/bge-small-zh-v1.5") is e
