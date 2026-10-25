"""The QR login against a fake iLink server (issue #13): the status machine, what gets written, and
the ways it gives up."""
import asyncio
import json
import os
import sys

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from wxbot import __main__ as cli, bot as bot_mod, config, ilink
from wxbot.kb import KB


def _fake_login(statuses: list[dict], qrcodes: list[dict], seen: list[str]):
    """get_bot_qrcode answers from `qrcodes` in order; get_qrcode_status from `statuses` (the last one
    repeats). Every request path is recorded in `seen`."""
    async def qrcode(request):
        seen.append(request.path_qs)
        return web.json_response(qrcodes.pop(0) if len(qrcodes) > 1 else qrcodes[0])

    async def status(request):
        seen.append(request.path_qs)
        return web.json_response(statuses.pop(0) if len(statuses) > 1 else statuses[0])

    app = web.Application()
    for prefix in ("", "/redirected"):
        app.router.add_get(f"{prefix}/ilink/bot/get_bot_qrcode", qrcode)
        app.router.add_get(f"{prefix}/ilink/bot/get_qrcode_status", status)
    return app


CONFIRMED = {"status": "confirmed", "ilink_bot_id": "bot@im.bot", "bot_token": "secret-token",
             "baseurl": "https://ilinkai.wechat.com", "ilink_user_id": "owner@im.wechat"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ACCOUNT_FILE", tmp_path / "data" / "account.json")
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "data" / "kb.sqlite")
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda s: real_sleep(min(s, 0.01)))   # the 1 s polls
    return tmp_path


def _login(monkeypatch, statuses, qrcodes=None, timeout_s=480):
    seen: list[str] = []
    qrcodes = qrcodes or [{"qrcode": "code-1", "qrcode_img_content": "https://liteapp/1"}]

    async def go():
        async with TestServer(_fake_login(list(statuses), list(qrcodes), seen)) as server:
            base = f"http://127.0.0.1:{server.port}"
            monkeypatch.setattr(ilink, "BASE_URL", base)
            # A redirect to "the host that serves this account" goes to a second prefix of the fake.
            for s in statuses:
                if s.get("redirect_host") == "REDIRECT":
                    s["redirect_host"] = f"{base}/redirected"
            await bot_mod.login(config.ACCOUNT_FILE.parent / "login-qr.png", timeout_s=timeout_s)
    asyncio.run(go())
    return seen


def test_login_follows_the_redirect_refreshes_an_expired_code_and_saves_the_account(home, monkeypatch, capsys):
    kb = KB(config.DB_FILE)
    kb.kv_set("sync_buf", "old-cursor")
    kb.kv_set("session_expired", "2026-10-01 10:00:00")
    seen = _login(monkeypatch, [
        {"status": "wait"},
        {"status": "scaned_but_redirect", "redirect_host": "REDIRECT"},
        {"status": "expired"},
        {"status": "scaned"},
        CONFIRMED,
    ], qrcodes=[{"qrcode": "code-1", "qrcode_img_content": "https://liteapp/1"},
                {"qrcode": "code-2", "qrcode_img_content": "https://liteapp/2"}])

    assert seen[0] == "/ilink/bot/get_bot_qrcode?bot_type=3"
    assert seen[1:3] == ["/ilink/bot/get_qrcode_status?qrcode=code-1"] * 2
    # After scaned_but_redirect the status polls go to the named host. A fresh code (the old one expired)
    # comes from the entry host, as the first one did, and is polled where the account lives.
    assert seen[3] == "/redirected/ilink/bot/get_qrcode_status?qrcode=code-1"
    assert seen[4] == "/ilink/bot/get_bot_qrcode?bot_type=3"
    assert seen[5:] == ["/redirected/ilink/bot/get_qrcode_status?qrcode=code-2"] * 2

    acct = json.loads(config.ACCOUNT_FILE.read_text())
    assert acct == {"account_id": "bot@im.bot", "token": "secret-token", "base_url": "https://ilinkai.wechat.com",
                    "user_id": "owner@im.wechat", "logged_in_at": acct["logged_in_at"]}
    assert oct(config.ACCOUNT_FILE.stat().st_mode & 0o777) == "0o600"          # the bot token is a secret
    assert not (config.ACCOUNT_FILE.parent / "login-qr.png").exists()           # nothing left to scan
    assert not list(config.ACCOUNT_FILE.parent.glob("*.tmp"))
    # A new identity starts a new update stream, and the old "expired" flag is cleared.
    assert kb.kv_get("sync_buf") == "" and kb.kv_get("session_expired") == ""
    assert bot_mod.admins_for(kb, acct) == {"owner@im.wechat"}                   # whoever scanned is the admin
    out = capsys.readouterr().out
    assert "QR written to" in out and "QR refreshed (1/10)" in out and "logged in: bot=bot@im.bot" in out


def test_qr_png_is_written_for_the_liteapp_url(home, monkeypatch):
    seen = _login(monkeypatch, [CONFIRMED])
    assert seen == ["/ilink/bot/get_bot_qrcode?bot_type=3", "/ilink/bot/get_qrcode_status?qrcode=code-1"]
    # The PNG is removed after a confirmed login; write it again the way login does and check it is a real image.
    png = home / "qr.png"
    bot_mod._write_qr("https://liteapp/1", png)
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_login_gives_up_without_a_code_or_with_incomplete_credentials_or_on_timeout(home, monkeypatch):
    with pytest.raises(SystemExit, match="拿不到二维码"):
        _login(monkeypatch, [CONFIRMED], qrcodes=[{}])
    assert not config.ACCOUNT_FILE.exists()
    with pytest.raises(SystemExit, match="credentials incomplete"):
        _login(monkeypatch, [{"status": "confirmed", "ilink_bot_id": "bot@im.bot"}])
    assert not config.ACCOUNT_FILE.exists()
    with pytest.raises(SystemExit, match="登录超时"):
        _login(monkeypatch, [{"status": "wait"}], timeout_s=0.05)
    with pytest.raises(SystemExit, match="二维码多次过期"):
        _login(monkeypatch, [{"status": "expired"}])


def test_status_reports_the_login_and_the_last_poll(home, monkeypatch, capsys):
    kb = KB(config.DB_FILE)
    monkeypatch.setattr(sys, "argv", ["wxbot", "status"])
    cli.main()
    first = json.loads(capsys.readouterr().out)
    assert first["logged_in"] is False and first["last_poll_age_s"] is None and first["pending"] == 0
    _login(monkeypatch, [CONFIRMED])
    kb.kv_set("last_poll", str(int(__import__("time").time()) - 30))
    kb.add_pending("mp:openid1", "食堂几点开")
    capsys.readouterr()
    cli.main()
    second = json.loads(capsys.readouterr().out)
    assert second["logged_in"] is True and second["bot"] == "bot@im.bot" and second["session_expired"] is None
    assert 30 <= second["last_poll_age_s"] <= 35 and second["pending"] == 1
    assert os.path.exists(config.ACCOUNT_FILE)
