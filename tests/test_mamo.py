from wxbot import mamo
from wxbot.mamo import canonical_url, parse_mamo_ts

TS = """export const MAMO_POSTS: MamoPost[] = [
  {
    url: 'https://mp.weixin.qq.com/s/abc',
    date: '2026-09-01',
    title: '马莫百科｜赴台必看',
    summary: '入台证申请条件'
  },
  {
    url: 'https://mp.weixin.qq.com/s/def',
    date: '2026-08-26',
    title:
      '马莫同学专访｜"在意大利上3周课"',
    summary:
      '第一段' +
      '第二段 it\\'s'
  },
  {
    url: '',
    date: '2026-07-01',
    title: '没有链接的帖子'
  }
]
"""


def test_hub_files_are_fetched_whole_and_replaced_only_when_changed(tmp_path):
    import asyncio

    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    files = {
        "frontend/data/mamo.ts": "export const MAMO_POSTS = [\n  { url: 'https://mp.weixin.qq.com/s/a', date: '2026-10-01', title: 'A', summary: 's' },\n]\n",
        "frontend/i18n/index.ts": "const en: Messages = {}\nconst zh: Messages = { 'x': '一' }\n",
        "frontend/i18n/handbook-terms.ts": "const zhCampus: Dictionary = { 'Malaysia': '马来西亚' }\n",
    }

    async def serve(request):
        name = request.match_info["name"]
        if name == "broken/frontend/data/mamo.ts":
            return web.Response(text="<html>Not Found</html>")        # a wrong file, not the post list
        if name not in files:
            return web.Response(status=404)
        return web.Response(text=files[name])
    app = web.Application()
    app.router.add_get("/{name:.*}", serve)

    async def go():
        async with TestServer(app) as server, aiohttp.ClientSession() as http:
            base = f"http://127.0.0.1:{server.port}"
            first = await mamo.fetch_hub_files(http, base, tmp_path)
            second = await mamo.fetch_hub_files(http, base, tmp_path)
            files["frontend/data/mamo.ts"] += "// new post\n"
            third = await mamo.fetch_hub_files(http, base, tmp_path)
            try:
                await mamo.fetch_hub_files(http, f"{base}/broken", tmp_path)
            except RuntimeError as exc:
                failure = str(exc)
            return first, second, third, failure
    first, second, third, failure = asyncio.run(go())
    assert first == ["mamo.ts", "hub-i18n/index.ts", "hub-i18n/handbook-terms.ts"]
    assert second == [] and third == ["mamo.ts"]
    assert "MAMO_POSTS missing" in failure
    assert (tmp_path / "mamo.ts").read_text().endswith("// new post\n")        # the bad fetch changed nothing
    assert "const zh" in (tmp_path / "hub-i18n" / "index.ts").read_text()
    assert not list(tmp_path.rglob("*.tmp"))
    assert mamo.parse_mamo_ts((tmp_path / "mamo.ts").read_text())[0]["title"] == "A"


def test_parse_mamo_ts():
    posts = parse_mamo_ts(TS)
    assert [p["url"] for p in posts] == ["https://mp.weixin.qq.com/s/abc", "https://mp.weixin.qq.com/s/def", ""]
    assert posts[1]["title"] == '马莫同学专访｜"在意大利上3周课"'
    assert posts[1]["summary"] == "第一段第二段 it's"


def test_canonical_url():
    assert canonical_url("https://mp.weixin.qq.com/s?__biz=X&amp;mid=1&amp;idx=1&amp;sn=Y&amp;chksm=Z#rd") == \
        "https://mp.weixin.qq.com/s?__biz=X&mid=1&idx=1&sn=Y"
    assert canonical_url("https://mp.weixin.qq.com/s/abc#wechat_redirect") == "https://mp.weixin.qq.com/s/abc"
