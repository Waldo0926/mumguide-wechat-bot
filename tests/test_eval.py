"""`python -m wxbot eval` (wxbot/evaluate.py). In CI only the rules and the retrieval run on real data: the
Q&A in qa/mamo-topics.json, indexed by word overlap. The RAG run and the judge use a fake model."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from wxbot import chunks, config, evaluate, hub
from wxbot.kb import KB

QA_FILE = Path(__file__).resolve().parent.parent / "qa" / "mamo-topics.json"


@pytest.fixture
def kb(tmp_path, monkeypatch):
    async def no_hub(http, q, **kw):
        return None

    async def nothing(http):
        return None
    monkeypatch.setattr(hub, "ask", no_hub)
    monkeypatch.setattr(hub.guides, "refresh_soon", lambda http: None)
    monkeypatch.setattr(hub.guides, "load_now", nothing)
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "kb.sqlite")
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "EMBED_MODEL", "off")
    kb = KB(config.DB_FILE)
    kb.import_qa(json.loads(QA_FILE.read_text(encoding="utf-8")))
    asyncio.run(chunks.build(kb, None, None, sources=("qa",)))
    return kb


def test_the_question_file_is_well_formed():
    qs = evaluate.load_questions()
    assert len(qs) >= 50 and len({q["id"] for q in qs}) == len(qs)
    for q in qs:
        assert q["question"] and isinstance(q["tags"], list)
        if q["answerable"]:
            assert q["expected_urls"] and q["expected_points"]
            assert all(u.startswith("https://") for u in q["expected_urls"])
        else:
            assert not q["expected_urls"]


def test_rule_run_finds_the_taught_answers_and_writes_the_report(kb, tmp_path):
    out = tmp_path / "EVAL.md"
    s = asyncio.run(evaluate.main("rule", False, None, False, out))
    rows = json.loads((tmp_path / "eval" / "results.json").read_text(encoding="utf-8"))["rule"]["rows"]
    # Questions whose answer is a taught Q&A in the repository: retrieval must keep finding them.
    taught = {hub._url_key(x["url"]) for x in json.loads(QA_FILE.read_text(encoding="utf-8")) if x.get("url")}
    qs = {q["id"]: q for q in evaluate.load_questions()}
    covered = [r for r in rows if evaluate._keys(qs[r["id"]]["expected_urls"]) & taught]
    assert len(covered) >= 20
    assert sum(r["retrieval_hit"] for r in covered) >= 0.8 * len(covered)
    assert all(r["rag"] == "-" for r in rows)
    text = out.read_text(encoding="utf-8")
    assert "| rule | " in text and s["correct"] == "未评"


class FakeModel:
    """Answers every RAG prompt with the start of passage 1, word for word, and every judge prompt with 1."""
    def app(self):
        async def completions(request):
            body = await request.json()
            system = body["messages"][0]["content"]
            if system.startswith("你是评分员"):
                content = "1"
            else:
                passage = body["messages"][1]["content"].split("\n\n[1] ", 1)[1].split("\n", 1)[1]
                content = f"[1] {passage[:20]}"
            return web.json_response({"choices": [{"message": {"content": content}}], "usage": {}})
        app = web.Application()
        app.router.add_post("/v1/chat/completions", completions)
        return app


def test_rag_run_with_the_judge_and_the_human_labels(kb, tmp_path, monkeypatch):
    out = tmp_path / "EVAL.md"

    async def go():
        async with TestServer(FakeModel().app()) as server:
            base = f"http://127.0.0.1:{server.port}/v1"
            monkeypatch.setattr(config, "LLM_BASE", base)
            monkeypatch.setattr(config, "LLM_KEY", "k")
            monkeypatch.setattr(evaluate, "JUDGE_BASE", base)
            monkeypatch.setattr(evaluate, "JUDGE_KEY", "k")
            await evaluate.main("rule", False, None, True, out, gap=5)
            return await evaluate.main("rag glm-4-flash", True, "glm-4-flash", True, out, gap=5)
    waits = []

    async def wait(seconds):
        waits.append(seconds)
    monkeypatch.setattr(evaluate, "asyncio", SimpleNamespace(sleep=wait))
    s = asyncio.run(go())
    assert s["correct"] != "未评" and s["timeout"].startswith("0%")
    results = json.loads((tmp_path / "eval" / "results.json").read_text(encoding="utf-8"))
    assert set(results) == {"rule", "rag glm-4-flash"}
    rag_rows = results["rag glm-4-flash"]["rows"]
    assert any(r["route"] == "rag" for r in rag_rows)
    # --gap waits only after the questions that called the model, never in the rule run.
    assert waits and set(waits) == {5} and len(waits) == sum(r["rag"] not in ("-", "skipped", "cached", "no chunks") for r in rag_rows)
    text = out.read_text(encoding="utf-8")
    assert "| rule | " in text and "| rag glm-4-flash | " in text

    labels = tmp_path / "labels.jsonl"
    first = next(r for r in rag_rows if r["answerable"])
    labels.write_text(json.dumps({"id": first["id"], "run": "rag glm-4-flash", "correct": first["correct"]}) + "\n")
    assert evaluate.agreement(results, labels) == "100%（1/1）"


def test_rag_status_reads_the_log_detail():
    assert evaluate.rag_status("rag", "chunks 1,2 ok 300t 1.2s") == "ok"
    assert evaluate.rag_status("miss", " | rag chunks 1 timeout 8.0s") == "timeout"
    assert evaluate.rag_status("qa", "qa#2 0.43 (weak) | rag chunks 3 uncited 200t 1.0s") == "uncited"
    assert evaluate.rag_status("hub", "official_faq") == "-"
    assert evaluate.rag_status("rag", "chunks 1,2 ok cut 1 500t 1.5s") == "cut"
    assert evaluate.rag_status("miss", " | rag chunks 1 unsupported 500t 1.5s") == "unsupported"
