"""python -m wxbot {login,run,ask,teach,mamo-add,mamo-sync,mamo-sync-api,status}"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

import aiohttp

from . import bot, config, mamo
from .brain import Brain
from .kb import KB


async def _ask(question: str) -> None:
    kb = KB(config.DB_FILE)
    async with aiohttp.ClientSession() as http:
        reply, route, detail = await Brain(kb, http, set()).answer(question)
    print(f"[{route} {detail}]\n{reply or '(miss -> 转给 Waldo)'}")


async def _mamo(args: argparse.Namespace) -> None:
    kb = KB(config.DB_FILE)
    async with aiohttp.ClientSession() as http:
        if args.cmd == "mamo-sync":
            changed, total = await mamo.sync_from_hub(http, kb, config.MAMO_TS)
            print(f"mamo.ts lists {total} posts; {changed} new or changed")
        elif args.cmd == "mamo-sync-api":
            print(f"synced {await mamo.sync_official(http, kb)} articles")
        else:
            for url in args.urls:
                try:
                    art_id, title = await mamo.add_by_url(http, kb, url)
                    print(f"#{art_id} {title}")
                except Exception as exc:
                    print(f"FAILED {url}: {exc}")


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
    t = sub.add_parser("teach")
    t.add_argument("question")
    t.add_argument("answer")
    t.add_argument("--url")
    ma = sub.add_parser("mamo-add")
    ma.add_argument("urls", nargs="+")
    sub.add_parser("mamo-sync")
    sub.add_parser("mamo-sync-api")
    sub.add_parser("status")
    args = p.parse_args()

    if args.cmd == "login":
        asyncio.run(bot.login(Path(args.png)))
    elif args.cmd == "run":
        asyncio.run(bot.run())
    elif args.cmd == "ask":
        asyncio.run(_ask(args.question))
    elif args.cmd == "teach":
        print(f"#{KB(config.DB_FILE).add_qa(args.question, args.answer, args.url)}")
    elif args.cmd in ("mamo-add", "mamo-sync", "mamo-sync-api"):
        asyncio.run(_mamo(args))
    elif args.cmd == "status":
        _status()


if __name__ == "__main__":
    main()
