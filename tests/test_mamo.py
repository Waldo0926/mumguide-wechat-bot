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


def test_parse_mamo_ts():
    posts = parse_mamo_ts(TS)
    assert [p["url"] for p in posts] == ["https://mp.weixin.qq.com/s/abc", "https://mp.weixin.qq.com/s/def", ""]
    assert posts[1]["title"] == '马莫同学专访｜"在意大利上3周课"'
    assert posts[1]["summary"] == "第一段第二段 it's"


def test_canonical_url():
    assert canonical_url("https://mp.weixin.qq.com/s?__biz=X&amp;mid=1&amp;idx=1&amp;sn=Y&amp;chksm=Z#rd") == \
        "https://mp.weixin.qq.com/s?__biz=X&mid=1&idx=1&sn=Y"
    assert canonical_url("https://mp.weixin.qq.com/s/abc#wechat_redirect") == "https://mp.weixin.qq.com/s/abc"
