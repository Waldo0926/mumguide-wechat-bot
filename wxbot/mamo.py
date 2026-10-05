"""马莫百科 articles: fetch one by its mp.weixin.qq.com link, or sync all of them through the 公众号 API.

Only title, digest and plain text are kept, for matching. Replies point readers to the article link
rather than reposting it.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from . import config
from .kb import KB

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")
ARTICLE_URL = re.compile(r"https?://mp\.weixin\.qq\.com/s[/?][^\s]+")


def canonical_url(url: str) -> str:
    url = html.unescape(url.strip())
    # Short links (/s/xxxx) are stable. Long links keep only the params that identify the article.
    m = re.match(r"(https?://mp\.weixin\.qq\.com/s)\?(.*)", url)
    if m:
        keep = [p for p in m.group(2).split("&") if p.split("=")[0] in {"__biz", "mid", "idx", "sn"}]
        return f"{m.group(1)}?{'&'.join(keep)}"
    return url.split("#")[0]


def _meta(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return (tag.get("content") or "").strip() if tag else ""


def parse_article(page: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(page, "html.parser")
    title = _meta(soup, "og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    body = soup.find(id="js_content")
    if not title or body is None:
        return None
    content = "\n".join(s.strip() for s in body.get_text("\n").splitlines() if s.strip())
    digest = _meta(soup, "og:description") or _meta(soup, "description")
    m = re.search(r'var\s+ct\s*=\s*"(\d+)"', page)
    return {"title": title, "digest": digest, "content": content, "published_at": float(m.group(1)) if m else None}


async def fetch_article(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    async with session.get(url, headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        page = await resp.text()
    art = parse_article(page)
    if not art:
        if "环境异常" in page or "verify" in page.lower():
            raise RuntimeError("微信要求验证，暂时抓不到这篇，过一会儿再试")
        raise RuntimeError("没从页面里找到正文，确认一下是公众号文章链接")
    return art


async def add_by_url(session: aiohttp.ClientSession, kb: KB, url: str) -> tuple[int, str]:
    url = canonical_url(url)
    art = await fetch_article(session, url)
    art_id = kb.upsert_article(url, art["title"], art["digest"], art["content"], art["published_at"])
    return art_id, art["title"]


# -- Monash Hub's copy of the post list -----------------------------------------------------------
# frontend/data/mamo.ts in the monash-hub repo lists every post (url, date, title, summary); the
# VPS checkout is updated on each deploy. We parse it rather than scrape the rendered site.

_FIELD = re.compile(r"(\w+):\s*((?:'(?:[^'\\]|\\.)*'\s*\+?\s*)+)")
_QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")


def parse_mamo_ts(source: str) -> list[dict[str, str]]:
    start = source.find("MAMO_POSTS")
    if start < 0:
        raise ValueError("MAMO_POSTS not found")
    body = source[source.index("[", start) + 1:]
    posts = []
    for chunk in re.split(r"\n\s*\},?", body):
        fields = {k: "".join(p.replace("\\'", "'") for p in _QUOTED.findall(v)) for k, v in _FIELD.findall(chunk)}
        if fields.get("title"):
            posts.append(fields)
    return posts


async def sync_from_hub(session: aiohttp.ClientSession, kb: KB, ts_path: str) -> tuple[int, int]:
    """Add posts listed in Monash Hub's mamo.ts. Returns (new or changed, total listed)."""
    with open(ts_path, encoding="utf-8") as f:
        posts = parse_mamo_ts(f.read())
    changed = 0
    for post in posts:
        url = canonical_url(post.get("url") or "")
        if not url:
            continue
        row = kb.db.execute("SELECT title, content FROM article WHERE url=?", (url,)).fetchone()
        if row and row["content"] and row["title"] == post["title"]:
            continue
        published = time.mktime(time.strptime(post["date"], "%Y-%m-%d")) if post.get("date") else None
        try:
            art = await fetch_article(session, url)
            content, digest = art["content"], art["digest"] or post.get("summary")
        except Exception as exc:
            log.warning("fetch %s failed (%s); indexing title and summary only", url, exc)
            content, digest = None, post.get("summary")
        kb.upsert_article(url, post["title"], digest, content, published)
        changed += 1
        await asyncio.sleep(2)   # be gentle with mp.weixin.qq.com
    return changed, len(posts)


# -- 公众号 API (freepublish/batchget) -----------------------------------------------------------

async def _access_token(session: aiohttp.ClientSession) -> str:
    async with session.post("https://api.weixin.qq.com/cgi-bin/stable_token",
                            json={"grant_type": "client_credential", "appid": config.MP_APPID,
                                  "secret": config.MP_SECRET}) as resp:
        data = await resp.json(content_type=None)
    if "access_token" not in data:
        raise RuntimeError(f"stable_token: {data}")
    return data["access_token"]


async def sync_official(session: aiohttp.ClientSession, kb: KB) -> int:
    """Pull every published article through the 公众号 API. Needs AppID/AppSecret and the VPS IP
    on the account's IP allowlist."""
    if not (config.MP_APPID and config.MP_SECRET):
        raise RuntimeError("WXBOT_MP_APPID / WXBOT_MP_SECRET not set")
    token = await _access_token(session)
    offset, total, stored = 0, None, 0
    while total is None or offset < total:
        async with session.post(f"https://api.weixin.qq.com/cgi-bin/freepublish/batchget?access_token={token}",
                                json={"offset": offset, "count": 20, "no_content": 0}) as resp:
            data = await resp.json(content_type=None)
        if data.get("errcode"):
            raise RuntimeError(f"freepublish/batchget: {data}")
        total = int(data.get("total_count") or 0)
        items = data.get("item") or []
        if not items:
            break
        for item in items:
            published = float(item.get("update_time") or 0) or None
            for news in (item.get("content") or {}).get("news_item") or []:
                if news.get("is_deleted"):
                    continue
                text = BeautifulSoup(news.get("content") or "", "html.parser").get_text("\n")
                text = "\n".join(s.strip() for s in text.splitlines() if s.strip())
                kb.upsert_article(canonical_url(news["url"]), news.get("title") or "", news.get("digest"),
                                  text, published)
                stored += 1
        offset += len(items)
        time.sleep(0.3)
    return stored
