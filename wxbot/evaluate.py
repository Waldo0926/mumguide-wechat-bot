"""`python -m wxbot eval`: the rules against the RAG answer on a fixed question set (eval/questions.jsonl).

Each run is stored under a name in data/eval/results.json, and docs/EVAL.md is written again from every
stored run, so models tried on different days end up in one table. What is measured:

- retrieval hit@5: one of the question's expected links is among the top 5 chunks (the same for every run);
- link in reply: the reply contains an expected link;
- answered / correct: a reply at all, and one a judge model marks as covering the expected points
  (`--judge`; the judge is fixed by WXBOT_JUDGE_* so that runs with different models are comparable);
- for questions nothing answers: the share left unanswered (a miss is the right outcome there);
- for the RAG answer: replies dropped for citing nothing or saying "不确定", timeouts, errors;
- time per question P50 / P95, and the share over 4 s (a 公众号 reply over 4 s arrives with the next message).

Optional human labels in eval/labels.jsonl ({"id", "run", "correct"}) give the judge's agreement with them.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import asyncio

import aiohttp

from . import config, embed, hub, llm
from .brain import MP_BUDGET_S, Brain
from .kb import KB
from .rag import Rag
from .retrieve import Retriever

QUESTIONS = Path(__file__).resolve().parent.parent / "eval" / "questions.jsonl"
LABELS = QUESTIONS.parent / "labels.jsonl"
OVER_S = 4.0

JUDGE_BASE = os.environ.get("WXBOT_JUDGE_BASE", "") or config.LLM_BASE
JUDGE_KEY = os.environ.get("WXBOT_JUDGE_KEY", "") or config.LLM_KEY
JUDGE_MODEL = os.environ.get("WXBOT_JUDGE_MODEL", "glm-4-flash")
JUDGE_SYSTEM = (
    "你是评分员，判断一个问答机器人的回答对不对。给你问题、参考要点和机器人的回答。"
    "回答说出了参考要点的意思，并且没有和要点矛盾的错误内容，就算正确；只给链接、没说出要点，算不正确。"
    "只输出一个数字：1 表示正确，0 表示不正确。"
)


@dataclass
class Row:
    id: str
    question: str
    answerable: bool
    route: str
    detail: str
    reply: str | None
    seconds: float
    retrieval_hit: bool
    link_in_reply: bool
    rag: str                    # ok | cut | uncited | unsure | unsupported | fragment | timeout | error | no chunks | cached | skipped | - (not asked)
    correct: int | None = None  # the judge's 0/1, None when not judged


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _keys(urls: list[str]) -> set[str]:
    return {hub._url_key(u) for u in urls}


def links_in(text: str | None) -> set[str]:
    return {hub._url_key(u) for u in hub._URL.findall(text or "")}


def rag_status(route: str, detail: str) -> str:
    if route == "rag":
        return "cached" if detail.endswith("cached") else "cut" if " ok cut " in detail else "ok"
    m = re.search(r"\| rag (.*)$", detail)
    if not m:
        return "-"
    for word in ("timeout", "uncited", "unsure", "unsupported", "fragment", "error", "no chunks", "skipped"):
        if word in m.group(1):
            return word
    return m.group(1)


async def judge(http: aiohttp.ClientSession, q: dict, reply: str) -> int | None:
    points = "\n".join(f"- {p}" for p in q["expected_points"])
    try:
        got = await llm.chat(http, [{"role": "system", "content": JUDGE_SYSTEM},
                                    {"role": "user", "content": f"问题：{q['question']}\n参考要点：\n{points}\n\n"
                                                                f"机器人的回答：\n{reply[:1500]}"}],
                             timeout=30, model=JUDGE_MODEL, max_tokens=5, base=JUDGE_BASE, key=JUDGE_KEY, extra={})
    except (llm.LLMError, TimeoutError):
        return None
    m = re.search(r"[01]", got.text)
    return int(m.group(0)) if m else None


async def run(kb: KB, http: aiohttp.ClientSession, questions: list[dict], *, use_rag: bool,
              model: str | None = None, with_judge: bool = False, gap: float = 0.0) -> list[Row]:
    retriever = Retriever(kb, embed.load())
    rag = Rag(kb, http, retriever, model, cache=False) if use_rag else None
    brain = Brain(kb, http, set(), rag)
    rows = []
    for q in questions:
        hits = retriever.search(q["question"])
        start = time.monotonic()
        # As on the 公众号: a question the rules answered may only wait for what is left of the reply budget.
        reply, route, detail = await brain.answer(q["question"], MP_BUDGET_S)
        seconds = time.monotonic() - start
        want = _keys(q["expected_urls"])
        row = Row(q["id"], q["question"], q["answerable"], route, detail, reply, round(seconds, 2),
                  bool(want & {hub._url_key(h.url) for h in hits if h.url}), bool(want & links_in(reply)),
                  rag_status(route, detail))
        if with_judge and q["answerable"]:
            row.correct = await judge(http, q, reply) if reply else 0
        rows.append(row)
        if gap and row.rag not in ("-", "skipped", "cached", "no chunks"):
            # A free tier's tokens-per-minute limit would otherwise turn most of a run into 429 errors,
            # which measures the limit, not the model.
            await asyncio.sleep(gap)
    return rows


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%（{n}/{d}）" if d else "-"


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def summary(rows: list[dict]) -> dict[str, Any]:
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    judged = [r for r in ans if r.get("correct") is not None]
    asked = [r for r in rows if r["rag"] not in ("-", "skipped")]
    times = [r["seconds"] for r in rows]
    return {
        "retrieval": _pct(sum(r["retrieval_hit"] for r in ans), len(ans)),
        "link": _pct(sum(r["link_in_reply"] for r in ans), len(ans)),
        "answered": _pct(sum(r["reply"] is not None for r in ans), len(ans)),
        "correct": _pct(sum(r["correct"] for r in judged), len(judged)) if judged else "未评",
        "abstain": _pct(sum(r["reply"] is None for r in unans), len(unans)),
        "uncited": _pct(sum(r["rag"] == "uncited" for r in asked), len(asked)) if asked else "-",
        "unsure": _pct(sum(r["rag"] == "unsure" for r in asked), len(asked)) if asked else "-",
        "cut": _pct(sum(r["rag"] == "cut" for r in asked), len(asked)) if asked else "-",
        "unsupported": _pct(sum(r["rag"] in ("unsupported", "fragment") for r in asked), len(asked)) if asked else "-",
        "timeout": _pct(sum(r["rag"] in ("timeout", "error") for r in asked), len(asked)) if asked else "-",
        "p50": f"{statistics.median(times):.1f}s" if times else "-",
        "p95": f"{_p(times, 0.95):.1f}s",
        "over4": _pct(sum(t > OVER_S for t in times), len(times)),
    }


def agreement(results: dict[str, dict], labels_path: Path = LABELS) -> str | None:
    if not labels_path.exists():
        return None
    labels = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    same = total = 0
    for lab in labels:
        run_rows = {r["id"]: r for r in (results.get(lab["run"]) or {}).get("rows", [])}
        r = run_rows.get(lab["id"])
        if r and r.get("correct") is not None:
            total += 1
            same += int(r["correct"] == int(lab["correct"]))
    return _pct(same, total) if total else None


def report(results: dict[str, dict], n_questions: int) -> str:
    lines = [
        "# Evaluation / 评测",
        "",
        "Generated by `python -m wxbot eval`; do not edit by hand. Questions: `eval/questions.jsonl`.",
        "由 `python -m wxbot eval` 生成，不要手改。题目在 `eval/questions.jsonl`。",
        "",
        f"{n_questions} questions: answerable ones have the links that answer them and 1–2 expected points; "
        "a few have no answer in any source, where the right outcome is no reply (the question goes to the owner).",
        "",
        "| 配置 run | 检索命中@5 | 回答带正确链接 | 答了 | 回答正确（裁判） | 不该答的没答 | 无引用被丢弃 | 说不确定 | 有摘句被删 | 摘句都不能用 | 超时/出错 | P50 | P95 | 超过 4 秒 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, res in results.items():
        s = summary(res["rows"])
        lines.append(f"| {name} | {s['retrieval']} | {s['link']} | {s['answered']} | {s['correct']} | {s['abstain']} | "
                     f"{s['uncited']} | {s['unsure']} | {s['cut']} | {s['unsupported']} | {s['timeout']} | {s['p50']} | {s['p95']} | {s['over4']} |")
    lines += ["", "Runs / 每次运行：", ""]
    for name, res in results.items():
        lines.append(f"- **{name}**: {res['mode']}, model `{res.get('model') or '-'}`, embedder `{res.get('embedder') or 'off'}`, "
                     f"judge `{res.get('judge') or '-'}`, {res['at']}, {res.get('chunks', 0)} chunks")
    agree = agreement(results)
    if agree:
        lines += ["", f"Judge agreement with the human labels in `eval/labels.jsonl` / 裁判和人工标注一致率：{agree}"]
    lines += [
        "",
        "How to read it / 怎么看：检索命中@5 是前 5 个片段里有没有期望的链接；回答正确由固定的裁判模型对照参考要点打 0/1；"
        "“不该答的没答”只看没有答案的题，没回答（转给作者）才算对；“无引用被丢弃”“说不确定”“有摘句被删”“摘句都不能用”“超时/出错”是 RAG 调用模型的结果占比（模型只能摘原句，程序逐字对照它标的资料，对不上的、或者离开上下文会看错的句子不发）；"
        "时间是每题从收到到出答案，按公众号的 4 秒预算算，超过 4 秒的回复会在下一条消息时送到。",
        "",
    ]
    return "\n".join(lines)


async def main(name: str, use_rag: bool, model: str | None, with_judge: bool, out: Path,
               questions_path: Path = QUESTIONS, gap: float = 0.0) -> dict[str, Any]:
    kb = KB(config.DB_FILE)
    questions = load_questions(questions_path)
    store = config.DATA / "eval" / "results.json"
    results = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    async with aiohttp.ClientSession() as http:
        await hub.guides.load_now(http)
        rows = await run(kb, http, questions, use_rag=use_rag, model=model, with_judge=with_judge, gap=gap)
    results[name] = {
        "mode": "rag" if use_rag else "rule", "model": (model or config.LLM_MODEL) if use_rag else None,
        "embedder": config.EMBED_MODEL if embed.load() else None, "judge": JUDGE_MODEL if with_judge else None,
        "at": time.strftime("%Y-%m-%d %H:%M"),
        "chunks": kb.db.execute("SELECT COUNT(*) FROM chunk").fetchone()[0],
        "rows": [asdict(r) for r in rows],
    }
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    out.write_text(report(results, len(questions)), encoding="utf-8")
    return summary(results[name]["rows"])
