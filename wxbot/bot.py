"""Runtime: QR login, the long-poll loop, and delivery."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from . import config, ilink, mp, pcwx, rag
from .alerts import AlertHandler
from .brain import Brain, Out
from .kb import KB
from .tasks import spawn

log = logging.getLogger("wxbot")

MAX_FAILURES, RETRY_DELAY, BACKOFF_DELAY = 3, 2, 30
DEDUP_TTL = 300
TEXT_DEDUP_TTL = 15
DIGEST_WEEKDAY, DIGEST_HOUR = 0, 9          # Monday 09:00, server time (the backup timer also uses server time)
DIGEST_CHECK_S = 1800
NUDGE_AFTER_S = 24 * 3600                   # a question waiting this long gets the owner a daily reminder
NUDGE_CHECK_S = 3600
NOTE_CHECK_S = 15                           # how often the held 待答 notes are looked at (Brain.due_notes)
RETENTION_CHECK_S = 3600


def _poll_level(failures: int) -> int:
    """The iLink CDN fails a single long poll now and then (HTTP 522 every hour or two) and the retry two
    seconds later works, so only a run of MAX_FAILURES in a row is worth an alert (WARNING and up)."""
    return logging.ERROR if failures >= MAX_FAILURES else logging.INFO


def load_account() -> dict[str, str] | None:
    if not config.ACCOUNT_FILE.exists():
        return None
    return json.loads(config.ACCOUNT_FILE.read_text())


def admins_for(kb: KB, account: dict[str, str] | None) -> set[str]:
    admins = {a for a in kb.kv_get("admins").split(",") if a}
    if account and account.get("user_id"):
        admins.add(account["user_id"])   # whoever scanned the QR code owns the bot
    return admins


# -- login ------------------------------------------------------------------------------------------

def _write_qr(content: str, png: Path) -> None:
    import qrcode
    png.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(content).save(str(png))


async def login(png: Path, timeout_s: int = 480) -> None:
    async with aiohttp.ClientSession() as http:
        async def fetch() -> tuple[str, str]:
            r = await ilink.api_get(http, ilink.BASE_URL, "ilink/bot/get_bot_qrcode?bot_type=3")
            return str(r.get("qrcode") or ""), str(r.get("qrcode_img_content") or "")

        code, content = await fetch()
        if not code:
            raise SystemExit("拿不到二维码")
        # WeChat must scan the liteapp URL, not the bare code.
        _write_qr(content or code, png)
        print(f"QR written to {png}\n{content}", flush=True)

        base, refreshes, deadline, last = ilink.BASE_URL, 0, time.monotonic() + timeout_s, ""
        while time.monotonic() < deadline:
            try:
                st = await ilink.api_get(http, base, f"ilink/bot/get_qrcode_status?qrcode={code}")
            except Exception as exc:
                if not isinstance(exc, asyncio.TimeoutError):
                    log.warning("QR poll: %s", exc)
                await asyncio.sleep(1)
                continue
            status = str(st.get("status") or "wait")
            if status != last:
                print(f"status: {status}", flush=True)
                last = status
            if status == "scaned_but_redirect" and st.get("redirect_host"):
                # iLink names the host that serves this account (ilinkai.wechat.com for accounts outside
                # mainland China); the rest of the login, and the bot, talk to it.
                host = str(st["redirect_host"])
                base = host if "://" in host else f"https://{host}"
            elif status == "expired":
                refreshes += 1
                if refreshes > 10:
                    raise SystemExit("二维码多次过期")
                code, content = await fetch()
                _write_qr(content or code, png)
                print(f"QR refreshed ({refreshes}/10)\n{content}", flush=True)
            elif status == "confirmed":
                acct = {
                    "account_id": str(st.get("ilink_bot_id") or ""),
                    "token": str(st.get("bot_token") or ""),
                    "base_url": str(st.get("baseurl") or ilink.BASE_URL),
                    "user_id": str(st.get("ilink_user_id") or ""),
                    "logged_in_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                if not acct["account_id"] or not acct["token"]:
                    raise SystemExit(f"confirmed but credentials incomplete: {sorted(st)}")
                config.ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = config.ACCOUNT_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(acct, indent=1))
                os.chmod(tmp, 0o600)
                tmp.replace(config.ACCOUNT_FILE)
                kb = KB(config.DB_FILE)
                kb.kv_set("sync_buf", "")          # a new bot identity starts a new update stream
                kb.kv_set("session_expired", "")
                png.unlink(missing_ok=True)
                print(f"logged in: bot={acct['account_id']} owner={acct['user_id']}", flush=True)
                return
            await asyncio.sleep(1)
        raise SystemExit("登录超时")


# -- the weekly digest (issue #8) ---------------------------------------------------------------------

def digest_due(now: float, last_sent: str) -> bool:
    """Monday from 09:00 on, once a week: the last one went out more than six days ago (or never)."""
    t = time.localtime(now)
    if t.tm_wday != DIGEST_WEEKDAY or t.tm_hour < DIGEST_HOUR:
        return False
    return not last_sent.isdigit() or now - int(last_sent) > 6 * 86400


async def weekly_digest(brain: Brain, deliver: Callable[[list[Out]], Awaitable[None]]) -> None:
    """Once a week, the questions the bot could not answer go to the owner, so phrasings and synonyms
    get added without anyone reading the log. Nothing is sent for a week with no misses."""
    while True:
        await asyncio.sleep(DIGEST_CHECK_S)
        try:
            if not digest_due(time.time(), brain.kb.kv_get("digest_sent")):
                continue
            brain.kb.kv_set("digest_sent", str(int(time.time())))
            text = brain.near_misses(7)
            if text:
                await deliver([Out(a, "📊 本周小结\n" + text) for a in brain.note_targets()])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("weekly digest failed: %s", exc)


# -- waiting questions (issue #3) ----------------------------------------------------------------------

def nudge_text(kb: KB, now: float | None = None) -> str | None:
    """"N questions have waited over a day", with the oldest first, or None when nothing has."""
    now = now or time.time()
    old = [p for p in kb.open_pending(999) if now - p["created_at"] >= NUDGE_AFTER_S]
    if not old:
        return None
    head = f"⏰ 有 {len(old)} 个问题等了超过一天还没回复："
    rows = [f"#{p['id']}（{int((now - p['created_at']) // 86400)} 天）{p['question'].replace(chr(10), ' / ')[:40]}"
            for p in old[:5]]
    if len(old) > 5:
        rows.append(f"…还有 {len(old) - 5} 个，发「待答」查看")
    return "\n".join([head, *rows, "回复「答 编号 答案」或「忽略 编号」。"])


async def pending_nudge(brain: Brain, deliver: Callable[[list[Out]], Awaitable[None]]) -> None:
    """Once a day while any question has waited over 24 h: the 待答 note may have been missed, or sent
    while ClawBot was down, and 公众号 users cannot ask again in a way that reaches the owner."""
    while True:
        await asyncio.sleep(NUDGE_CHECK_S)
        try:
            last = brain.kb.kv_get("pending_nudged")
            if last.isdigit() and time.time() - int(last) < NUDGE_AFTER_S:
                continue
            text = nudge_text(brain.kb)
            if text:
                brain.kb.kv_set("pending_nudged", str(int(time.time())))
                await deliver([Out(a, text) for a in brain.note_targets()])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("pending reminder failed: %s", exc)


async def pending_notes(brain: Brain, deliver: Callable[[list[Out]], Awaitable[None]]) -> None:
    """Send the 待答 notes held back so that several messages from one person go as one note."""
    while True:
        await asyncio.sleep(NOTE_CHECK_S)
        try:
            outs = brain.due_notes()
            if outs:
                await deliver(outs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("sending 待答 notes failed: %s", exc)


# -- retention (issue #10) ---------------------------------------------------------------------------

async def retention(kb: KB) -> None:
    """Once a day, delete students' questions and replies older than WXBOT_LOG_DAYS (KB.purge)."""
    while True:
        await asyncio.sleep(RETENTION_CHECK_S)
        try:
            last = kb.kv_get("purged_at")
            if last.isdigit() and time.time() - int(last) < 86400:
                continue
            kb.kv_set("purged_at", str(int(time.time())))
            removed = kb.purge(config.LOG_DAYS, config.OUTBOX_DAYS)
            if any(removed.values()):
                log.info("retention: removed %s", removed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("retention purge failed: %s", exc)


# -- run ----------------------------------------------------------------------------------------------

async def deliver_pc(pc: "pcwx.PCWeChat | None", o: Out) -> None:
    if not pc:
        log.warning("pcwx disabled; dropped message for %s", o.to[:16])
        return
    try:
        await pc.deliver(o)
    except Exception as exc:
        log.error("pcwx send to %s failed: %s", o.to[:16], exc)


def alert_sender(ilink_bot: Bot | None, admins: set[str], pc: pcwx.PCWeChat | None,
                 owner_wxid: str) -> Callable[[str], Awaitable[None]] | None:
    """Where alerts go: the admins' ClawBot chat, and the owner's own WeChat through MonashGuide when
    ClawBot cannot deliver. The expired iLink session is the alert that matters most and the one
    ClawBot can never send, so the second channel is what makes it reach anyone (issue #3)."""
    backup = pc if pc and owner_wxid else None
    if not ilink_bot and not backup:
        return None

    async def send(text: str) -> None:
        if ilink_bot:
            try:
                # Only iLink ids are reachable in ClawBot; admins added by pairing sit on the other channels.
                for admin in sorted(a for a in admins if not a.startswith((mp.PREFIX, pcwx.PREFIX))):
                    await ilink_bot.client.send_text(admin, text, ilink_bot.kb.context_token(admin))
                return
            except Exception as exc:
                if not backup:
                    raise
                logging.getLogger("wxbot.alerts").info("ClawBot could not take the alert (%s); using MonashGuide", exc)
        await backup.send(pcwx.user_id(None, owner_wxid), text)
    return send


class Bot:
    """The iLink side: Waldo's own ClawBot chat, used as the admin console."""

    def __init__(self, http: aiohttp.ClientSession, kb: KB, account: dict[str, str], brain: Brain):
        self.kb = kb
        self.account_id = account["account_id"]
        self.client = ilink.Client(http, base_url=account["base_url"], token=account["token"])
        self.brain = brain
        self.seen: dict[str, float] = {}
        self.pc: pcwx.PCWeChat | None = None

    def _duplicate(self, key: str, ttl: float = DEDUP_TTL) -> bool:
        now = time.time()
        if len(self.seen) > 2000:
            self.seen = {k: t for k, t in self.seen.items() if now - t < DEDUP_TTL}
        if key in self.seen and now - self.seen[key] < ttl:
            return True
        self.seen[key] = now
        return False

    async def deliver(self, outs: list[Out]) -> None:
        for o in outs:
            if o.to.startswith(mp.PREFIX):
                self.kb.queue_outbox(o.to, o.text)
                continue
            if o.to.startswith(pcwx.PREFIX):
                await deliver_pc(self.pc, o)
                continue
            try:
                await self.client.send_text(o.to, o.text[:3800], self.kb.context_token(o.to))
            except Exception as exc:
                log.error("send to %s failed: %s", o.to[:10], exc)

    async def process(self, msg: dict[str, Any]) -> None:
        sender = str(msg.get("from_user_id") or "").strip()
        if not sender or sender == self.account_id or msg.get("message_type") == ilink.MSG_TYPE_BOT:
            return
        mid = str(msg.get("message_id") or msg.get("msg_id") or "")
        if mid and self._duplicate(f"id:{mid}"):
            return
        items = msg.get("item_list") or []
        text = ilink.extract_text(items)
        kind, chat = ilink.chat_kind(msg, self.account_id)
        # Logged for the experiment: what shapes of message iLink actually delivers.
        log.info("inbound kind=%s chat=%s from=%s items=%s group_id=%r session=%s", kind, chat[:14], sender[:14],
                 [i.get("type") for i in items], msg.get("group_id"), str(msg.get("session_id") or "")[:14])
        if kind == "group":
            self.kb.kv_set("group_events", str(int(self.kb.kv_get("group_events", "0")) + 1))
            return
        # iLink can redeliver one message under a new id within seconds; a person repeating a question
        # (or an admin re-running 「试」) a minute later must still get an answer.
        if text and self._duplicate(f"txt:{sender}:{hash(text)}", ttl=TEXT_DEDUP_TTL):
            return
        first = self.kb.touch_contact(sender, str(msg.get("context_token") or "") or None)
        if first:
            log.info("new contact %s", sender[:14])
        if not text:
            await self.deliver([Out(sender, "目前我只看得懂文字消息，把问题打字发给我吧 🙂")])
            return
        outs = await self.brain.handle(sender, text, quoted=ilink.extract_quote(items))
        await self.deliver(outs)

    async def run(self) -> None:
        sync_buf = self.kb.kv_get("sync_buf")
        timeout_ms, failures = ilink.LONG_POLL_TIMEOUT_MS, 0
        log.info("polling as %s, admins=%s", self.account_id, [a[:10] for a in self.brain.admins])
        while True:
            try:
                resp = await self.client.get_updates(sync_buf, timeout_ms)
                if isinstance(resp.get("longpolling_timeout_ms"), int) and resp["longpolling_timeout_ms"] > 0:
                    timeout_ms = resp["longpolling_timeout_ms"]
                if ilink.is_error(resp):
                    if ilink.is_session_expired(resp):
                        log.error("iLink session expired - needs a new QR login (python -m wxbot login)")
                        self.kb.kv_set("session_expired", time.strftime("%Y-%m-%d %H:%M:%S"))
                        await asyncio.sleep(600)
                        continue
                    failures += 1
                    log.log(_poll_level(failures), "getupdates error %s (%d/%d)", resp, failures, MAX_FAILURES)
                    await asyncio.sleep(BACKOFF_DELAY if failures >= MAX_FAILURES else RETRY_DELAY)
                    failures %= MAX_FAILURES
                    continue
                failures = 0
                self.kb.kv_set("session_expired", "")
                if resp.get("get_updates_buf"):
                    sync_buf = str(resp["get_updates_buf"])
                    self.kb.kv_set("sync_buf", sync_buf)
                self.kb.kv_set("last_poll", str(int(time.time())))
                for msg in resp.get("msgs") or []:
                    spawn(self._safe(msg))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                log.log(_poll_level(failures), "poll error (%d/%d): %s", failures, MAX_FAILURES, exc)
                await asyncio.sleep(BACKOFF_DELAY if failures >= MAX_FAILURES else RETRY_DELAY)
                failures %= MAX_FAILURES

    async def _safe(self, msg: dict[str, Any]) -> None:
        try:
            await self.process(msg)
        except Exception:
            log.exception("handling message failed")


async def run() -> None:
    account = load_account()
    kb = KB(config.DB_FILE)
    if not account and not config.MP_TOKEN:
        raise SystemExit("nothing to run: no iLink login (python -m wxbot login) and no WXBOT_MP_TOKEN")
    async with aiohttp.ClientSession() as http:
        brain = Brain(kb, http, admins_for(kb, account), rag.make(kb, http))
        if brain.rag:
            log.info("rag: on, model %s", brain.rag.model)
            spawn(brain.rag.warm())
        ilink_bot = Bot(http, kb, account, brain) if account else None
        pc: pcwx.PCWeChat | None = None

        async def forward(outs: list[Out]) -> None:
            if ilink_bot:
                await ilink_bot.deliver(outs)
                return
            for o in outs:
                if o.to.startswith(mp.PREFIX):
                    kb.queue_outbox(o.to, o.text)
                elif o.to.startswith(pcwx.PREFIX):
                    await deliver_pc(pc, o)
                else:
                    log.warning("no iLink login; dropped message for %s: %s", o.to[:10], o.text[:60])

        pc_runner = None
        if config.PCWX_API and config.PCWX_SECRET:
            pc = pcwx.PCWeChat(http, kb, brain, forward)
            if ilink_bot:
                ilink_bot.pc = pc
            pc_runner = await pcwx.start(pc)
        else:
            log.info("WXBOT_PCWX_API/SECRET not set; personal-account (group chat) channel disabled")

        send_alert = alert_sender(ilink_bot, brain.admins, pc, config.OWNER_WXID)
        if send_alert:
            logging.getLogger().addHandler(AlertHandler(send_alert, asyncio.get_running_loop()))

        runner = None
        if config.MP_TOKEN:
            runner = await mp.start(mp.MPServer(brain, kb, forward))
        else:
            log.info("WXBOT_MP_TOKEN not set; 公众号 server disabled")
        spawn(retention(kb))
        spawn(pending_notes(brain, forward))
        if brain.note_targets():
            spawn(weekly_digest(brain, forward))
            spawn(pending_nudge(brain, forward))
        try:
            if ilink_bot:
                await ilink_bot.run()
            else:
                log.warning("no iLink login; running the 公众号 server only (admin notifications are dropped)")
                await asyncio.Event().wait()
        finally:
            for r in (runner, pc_runner):
                if r:
                    await r.cleanup()
