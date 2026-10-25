"""python -m wxbot {login,run,ask,teach,mamo-add,mamo-sync,mamo-sync-api,status,backup,purge,export-qa,import-qa,
index,search,eval}"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

import aiohttp

from . import bot, chunks, config, embed, hub, mamo
from .brain import Brain
from .kb import KB


async def _ask(question: str, use_rag: bool) -> None:
    from . import rag
    kb = KB(config.DB_FILE)
    async with aiohttp.ClientSession() as http:
        await hub.guides.load_now(http)
        brain = Brain(kb, http, set(), rag.make(kb, http, force=use_rag))
        if use_rag and brain.rag is None:
            print("(RAG is not available: see the warning above)")
        reply, route, detail = await brain.answer(question)
    print(f"[{route} {detail}]\n{reply or '(miss -> 转给 Waldo)'}")


async def _mamo(args: argparse.Namespace) -> None:
    kb = KB(config.DB_FILE)
    async with aiohttp.ClientSession() as http:
        if args.cmd == "mamo-sync":
            if config.HUB_FILES_URL:
                fetched = await mamo.fetch_hub_files(http, config.HUB_FILES_URL, config.DATA)
                print(f"fetched from {config.HUB_FILES_URL}: {', '.join(fetched) or 'no change'}")
            changed, total = await mamo.sync_from_hub(http, kb, config.MAMO_TS)
            print(f"mamo.ts lists {total} posts; {changed} new or changed")
            if chunks.built(kb):
                # The same 6-hour timer keeps the RAG index current: new posts, Hub pages, taught Q&A.
                print(f"index: {await chunks.build(kb, http, embed.load())}")
        elif args.cmd == "mamo-sync-api":
            print(f"synced {await mamo.sync_official(http, kb)} articles")
        else:
            for url in args.urls:
                try:
                    art_id, title = await mamo.add_by_url(http, kb, url)
                    print(f"#{art_id} {title}")
                except Exception as exc:
                    print(f"FAILED {url}: {exc}")


async def _index(full: bool, hub_too: bool) -> None:
    kb = KB(config.DB_FILE)
    sources = chunks.SOURCES if hub_too else ("qa", "article")
    async with aiohttp.ClientSession() as http:
        report = await chunks.build(kb, http, embed.load(), sources=sources, full=full)
    for k, v in report.items():
        print(f"{k}: {v}")


def _search(question: str, limit: int) -> None:
    from .retrieve import Retriever
    kb = KB(config.DB_FILE)
    if not chunks.built(kb):
        print("the index is empty: run `python -m wxbot index` first")
        return
    for i, h in enumerate(Retriever(kb, embed.load()).search(question, limit=limit), 1):
        lex = f"{h.lex:.2f}" if h.lex is not None else "-"
        cos = f"{h.cos:.2f}" if h.cos is not None else "-"
        print(f"{i}. [{h.source} {h.ref_id}] rrf {h.score:.4f} lex {lex} cos {cos}  {h.title}\n   {h.url or ''}\n"
              f"   {h.text[:120].replace(chr(10), ' ')}")


def _status() -> None:
    kb = KB(config.DB_FILE)
    acct = json.loads(config.ACCOUNT_FILE.read_text()) if config.ACCOUNT_FILE.exists() else {}
    last = kb.kv_get("last_poll")
    print(json.dumps({
        "logged_in": bool(acct), "bot": acct.get("account_id"), "logged_in_at": acct.get("logged_in_at"),
        "last_poll_age_s": int(time.time() - int(last)) if last else None,
        "session_expired": kb.kv_get("session_expired") or None,
        "group_events_seen": int(kb.kv_get("group_events", "0")),
        "qa": kb.count("qa"), "articles": kb.count("article"), "contacts": kb.count("contact"),
        "pending": len(kb.open_pending(999)),
    }, ensure_ascii=False, indent=1))


def _backup(directory: Path, keep: int) -> None:
    """kb-YYYYmmdd-HHMMSS.sqlite in directory, keeping the newest `keep` (issue #1)."""
    dest = directory / time.strftime("kb-%Y%m%d-%H%M%S.sqlite")
    KB(config.DB_FILE).backup(dest)
    old = sorted(directory.glob("kb-*.sqlite"))[:-keep] if keep > 0 else []
    for f in old:
        f.unlink()
    print(f"backed up to {dest} ({dest.stat().st_size} bytes); removed {len(old)} old")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="wxbot")
    sub = p.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("login")
    lg.add_argument("--png", default=str(config.DATA / "login-qr.png"))
    sub.add_parser("run")
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--rag", action="store_true", help="also try the RAG answer, even with WXBOT_RAG=0")
    t = sub.add_parser("teach")
    t.add_argument("question")
    t.add_argument("answer")
    t.add_argument("--url")
    ma = sub.add_parser("mamo-add")
    ma.add_argument("urls", nargs="+")
    sub.add_parser("mamo-sync")
    sub.add_parser("mamo-sync-api")
    sub.add_parser("status")
    bk = sub.add_parser("backup")
    bk.add_argument("--dir", default=str(config.DATA / "backups"))
    bk.add_argument("--keep", type=int, default=14)
    sub.add_parser("purge", help="delete questions and replies past WXBOT_LOG_DAYS now (the bot also does it daily)")
    sub.add_parser("export-qa")
    im = sub.add_parser("import-qa")
    im.add_argument("file")
    im.add_argument("--replace", action="store_true", help="give pairs with the same first phrasing the file's answer")
    ix = sub.add_parser("index", help="build or update the chunk index for the RAG mode")
    ix.add_argument("--full", action="store_true", help="fetch every Monash Hub page again, not only changed ones")
    ix.add_argument("--no-hub", action="store_true", help="only taught Q&A and articles")
    se = sub.add_parser("search", help="show the top chunks the RAG mode would read for a question")
    se.add_argument("question")
    se.add_argument("--limit", type=int, default=5)
    ev = sub.add_parser("eval", help="score the rules or the RAG answer on eval/questions.jsonl")
    ev.add_argument("--mode", choices=["rule", "rag"], default="rule")
    ev.add_argument("--model", help="chat model for --mode rag (default WXBOT_LLM_MODEL)")
    ev.add_argument("--name", help="name of this run in the report (default: mode and model)")
    ev.add_argument("--judge", action="store_true", help="mark answers 0/1 with the judge model (WXBOT_JUDGE_*)")
    ev.add_argument("--gap", type=float, default=0.0,
                    help="seconds to wait after each model call (free tiers limit tokens per minute; Groq: 15)")
    ev.add_argument("--questions", default=None, help="question file (default eval/questions.jsonl)")
    ev.add_argument("--out", default=str(config.DATA / "eval" / "EVAL.md"),
                    help="report file; copy it to docs/EVAL.md in the repository")
    args = p.parse_args()

    if args.cmd == "login":
        asyncio.run(bot.login(Path(args.png)))
    elif args.cmd == "run":
        asyncio.run(bot.run())
    elif args.cmd == "ask":
        asyncio.run(_ask(args.question, args.rag))
    elif args.cmd == "teach":
        print(f"#{KB(config.DB_FILE).add_qa(args.question, args.answer, args.url)}")
    elif args.cmd in ("mamo-add", "mamo-sync", "mamo-sync-api"):
        asyncio.run(_mamo(args))
    elif args.cmd == "status":
        _status()
    elif args.cmd == "backup":
        _backup(Path(args.dir), args.keep)
    elif args.cmd == "purge":
        removed = KB(config.DB_FILE).purge(config.LOG_DAYS, config.OUTBOX_DAYS)
        print(f"removed {removed} (keeping {config.LOG_DAYS:g} days)")
    elif args.cmd == "export-qa":
        print(json.dumps(KB(config.DB_FILE).export_qa(), ensure_ascii=False, indent=1))
    elif args.cmd == "import-qa":
        items = json.loads(Path(args.file).read_text(encoding="utf-8"))
        kb = KB(config.DB_FILE)
        added, phrases, replaced = kb.import_qa(items, replace=args.replace)
        print(f"added {added} of {len(items)}, {phrases} new phrasings for pairs already there"
              + (f", {replaced} answers replaced" if args.replace else ""))
        if chunks.built(kb):
            print(f"index: {asyncio.run(chunks.build(kb, None, embed.load(), sources=('qa',)))['qa']}")
    elif args.cmd == "index":
        asyncio.run(_index(args.full, not args.no_hub))
    elif args.cmd == "search":
        _search(args.question, args.limit)
    elif args.cmd == "eval":
        from . import evaluate
        model = args.model or (config.LLM_MODEL if args.mode == "rag" else None)
        name = args.name or (f"rag {model}" if args.mode == "rag" else "rule")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        qs = Path(args.questions) if args.questions else evaluate.QUESTIONS
        s = asyncio.run(evaluate.main(name, args.mode == "rag", model, args.judge, out, qs, args.gap))
        print(f"{name}: " + ", ".join(f"{k} {v}" for k, v in s.items()) + f"\nreport: {out}")


if __name__ == "__main__":
    main()
