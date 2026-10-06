# MUMGuide 微信问答机器人 — 马莫百科

[![类型](https://img.shields.io/badge/%E7%B1%BB%E5%9E%8B-%E6%97%A0%E5%A4%A7%E6%A8%A1%E5%9E%8B%E5%BE%AE%E4%BF%A1%E6%9C%BA%E5%99%A8%E4%BA%BA-2563eb?style=for-the-badge)](#它怎么回答)
[![技术](https://img.shields.io/badge/%E6%8A%80%E6%9C%AF-Python_3.12_%C2%B7_aiohttp_%C2%B7_SQLite-7c3aed?style=for-the-badge)](#目录结构)
[![测试](https://img.shields.io/badge/%E6%B5%8B%E8%AF%95-pytest_%C2%B7_%E7%A6%BB%E7%BA%BF-16a34a?style=for-the-badge)](#)
[![许可证](https://img.shields.io/badge/%E8%AE%B8%E5%8F%AF%E8%AF%81-%E4%BF%9D%E7%95%99%E6%89%80%E6%9C%89%E6%9D%83%E5%88%A9-dc2626?style=for-the-badge)](LICENSE)

[English](README.md) · **中文**

「马莫百科」公众号（服务 Monash University Malaysia 的同学）的微信问答机器人。同学关注公众号后直接用中文提问，机器人从三个来源回答，**不用大模型、不花 token**，每条回答都附上来源链接，方便同学核对。答不上来的问题会转给作者，作者的回复会发回给提问人，并被机器人记住。

> 学生个人项目，与 Monash University 无官方隶属关系。涉及选课、毕业、签证的决定请以学校官方页面为准。

## 它怎么回答

每条消息按顺序尝试三个来源：

1. **作者教过的问答**（`教 问题 | 答案`）：模糊匹配，可以给同一个答案补多种问法（`也问`）。
2. **[Monash Hub](https://monashhub.secureview.tech)**（姊妹项目，`POST /api/v1/ask` 接口）：课程的 Handbook 信息（考核、先修、开课、工作量、课程简介与学习目标）、学位和专业方向卡片、官方 FAQ 和官方页面，用网站自己校对过的中文术语渲染。
3. **马莫百科文章**：对公众号自己文章的标题、摘要和正文做匹配，回复文章链接。

都匹配不上时，机器人告诉提问人"已转给作者"，同时作者在私人微信对话里收到一条"待答 #N"，回复 `答 N 你的答案` 即可。答案会发给提问人，并存成新的问答，下次同样的问题机器人自己就能答。

```text
同学 ──► 马莫百科公众号 ──► 消息回调（nginx）──► 机器人（aiohttp）
                                                   │
                  ┌─────────────────┬──────────────┴──────┬──────────────────┐
                  ▼                 ▼                     ▼                  ▼
              教过的问答       Monash Hub API         马莫百科文章        待发回复 / 待答
              （SQLite）     （/ask、/guides）        （SQLite）          （SQLite）

作者 ◄──► 私人「ClawBot」对话（腾讯 iLink 长轮询）：管理后台与告警
```

用两个官方微信通道，是因为各自只能做一部分事：

| 通道 | 谁用 | 原因 |
|---|---|---|
| 公众号（订阅号）消息回调 | 所有同学 | 对外入口。未认证的个人订阅号只能被动回复：5 秒内、2048 字节内、每条消息回一条。 |
| iLink「ClawBot」（腾讯官方个人机器人接口） | 只有作者 | 只属于扫码的那个号，所以用作管理后台和告警渠道。 |

## 为什么不用 AI

Monash Hub 有意不使用生成式 AI，这个机器人也一样：匹配靠 jieba 分词加中文双字组的 IDF 加权重叠（`wxbot/kb.py`），每条回答都能追溯到一条问答、一个 Handbook 字段、一个官方页面或一篇文章。这样关于规则和截止日期的回答可以核对、每条消息零成本，也能稳稳落在微信 5 秒的回复时限内。

## 功能

- **按课程代码或课名查课。** "FIT2102学什么"返回课程简介、学习目标、考核、开课和先修；"编程范式有期末考试吗"会按课名找到 FIT2102；课名有歧义时列出候选课程，请对方回复课程代码。
- **学位与专业方向。** 问学位代码或名称（C2001、"计算机科学学士要修多少学分"）或专业方向代码，返回包含学分、结构、校区和链接的卡片。
- **学院停开通知。** 即将停开或被替代的课程，原文照录学院的通知并附链接。
- **年份回退。** 默认年份的 Handbook 里没有某门课或某个学位时，读取最近收录它的年份，并说明这一点。
- **中文优先，不贴机翻。** 使用 Monash Hub 校对过的中文；没有校对中文的内容给链接而不是贴英文长段落；每个官网链接都配上 Monash Hub 对应的中文全文页。
- **马来西亚校区优先。** 马来西亚和全校通用的页面排在澳洲专用页面前面，其余保持 Monash Hub 的相关度排序。
- **适配微信的限制。** 一个问题的所有 Monash Hub 请求共用 3.4 秒总时限，回复不会在 5 秒处被截断；Monash Hub 暂时不可用时提示稍后再问，而不是把问题都转给作者。
- **在微信里管理：** 教、改、答、统计、查看（见下表）；出问题时自动推送到作者的对话，同类问题限频，不用盯日志。

### 作者命令（发给 ClawBot 对话）

| 命令 | 含义 |
|---|---|
| `教 问题 \| 答案 [\| 链接]` | 新增问答 |
| `也问 编号 另一种问法` | 给问答补一种问法 |
| `改 编号 新答案 [\| 链接]` · `删 编号` · `看 编号` | 修改 / 删除 / 查看 |
| `查 关键词` · `试 问题` | 看会匹配到什么 / 模拟完整回答并显示来源 |
| `待答` · `答 编号 答案` · `忽略 编号` | 待答问题；回答 / 跳过 |
| `收录 <mp.weixin.qq.com 链接>` · `删文 编号` | 收录 / 移除马莫百科文章 |
| `关注语 [新内容]` | 查看 / 设置欢迎语 |
| `统计` · `管理` | 使用情况 / 命令列表 |

## 需要知道的限制

- 个人订阅号不能主动推送，作者对转人工问题的回答，要等提问人下一次给公众号发消息时才显示；公众号认证后可以解决。
- ClawBot 只属于扫码的那个号，不能分享，也不能拉进群。
- iLink 会话会过期，需要重新扫码（`python -m wxbot login`）。

## 快速开始（开发）

需要 Python 3.12。

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # 离线测试：模拟 Monash Hub、模拟公众号请求
WXBOT_HOME=.scratch WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1 \
  .venv/bin/python -m wxbot ask "FIT2102学什么"
```

命令行：`python -m wxbot {login,run,ask,teach,mamo-add,mamo-sync,mamo-sync-api,status}`。

要让 Handbook 回答显示中文，把 Monash Hub 的 `frontend/i18n/index.ts` 和 `frontend/i18n/handbook-terms.ts` 复制到 `$WXBOT_HOME/data/hub-i18n/`；没有这两个文件时答案保持英文。

## 配置（环境变量）

| 变量 | 默认值 | 含义 |
|---|---|---|
| `WXBOT_HOME` | 仓库根目录 | `data/` 所在位置 |
| `WXBOT_HUB_API` | 本机 Monash Hub | Monash Hub API 地址 |
| `WXBOT_MP_TOKEN` | — | 填在公众号后台的 Token；不设置则不启动回调服务 |
| `WXBOT_MP_PORT` | `8102` | 回调服务的本地端口 |
| `WXBOT_OWNER_NAME` | `Waldo` | "转给 …" 回复里的名字 |
| `WXBOT_MAMO_TS`、`WXBOT_HUB_I18N_DIR` | `data/` 下 | Monash Hub 文件的副本，由同步任务更新 |
| `WXBOT_QA_STRONG` / `WXBOT_QA_WEAK` | `0.6` / `0.42` | 教过的问答阈值（直接回答 / "你问的是不是…"） |
| `WXBOT_ARTICLE_MIN` / `WXBOT_ARTICLE_LEAD` | `0.5` / `0.7` | 文章匹配阈值 |

见 [.env.example](.env.example)。密钥（Token 和 iLink 账号文件）绝不进 git。

## 目录结构

```text
wxbot/
  bot.py       运行时：扫码登录、iLink 长轮询、消息发送
  mp.py        公众号消息服务（验签、重试去重、欢迎语、待发回复）
  brain.py     回答逻辑和作者命令（纯逻辑，不直接碰微信）
  kb.py        SQLite 存储与匹配索引（问答、文章、待答、待发回复、日志）
  hub.py       Monash Hub 客户端和消息排版（课程、学位、年份回退）
  hub_i18n.py  从网站的 TypeScript 里读取中文界面文案和 Handbook 术语表
  ilink.py     腾讯 iLink Bot API 客户端
  mamo.py      马莫百科文章抓取与文章列表同步
  alerts.py    把问题推送到作者对话的日志处理器
tests/         pytest，完全离线
```

## 关于这个仓库

这是私有开发仓库的公开快照。部署脚本、服务器配置和运维手册保留在私有仓库中。线上环境里，机器人作为沙箱化的 systemd 服务运行在 nginx 之后，和 Monash Hub 部署在同一台服务器上。

## 许可

Copyright © 2026 Shuoxun Wen，保留所有权利。源代码公开仅用于作品集展示和代码审阅，详见 [LICENSE](LICENSE)。
