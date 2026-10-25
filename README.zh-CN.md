# MUMGuide WeChat Bot：马莫百科问答机器人

[![Tests](https://github.com/Waldo0926/mumguide-wechat-bot/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Waldo0926/mumguide-wechat-bot/actions/workflows/tests.yml)
[![在线率](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FWaldo0926%2Fuptime%2FHEAD%2Fapi%2Fmumguide-bot%2Fuptime.json)](https://waldo0926.github.io/uptime/history/mumguide-bot)
[![License](https://img.shields.io/badge/License-All_Rights_Reserved-dc2626)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![aiohttp](https://img.shields.io/badge/aiohttp-3.9%2B-2C5BB4?logo=aiohttp&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![WeChat](https://img.shields.io/badge/WeChat-%E5%85%AC%E4%BC%97%E5%8F%B7%20%2B%20iLink-07C160?logo=wechat&logoColor=white)
![大模型：可选，只摘原文](https://img.shields.io/badge/%E5%A4%A7%E6%A8%A1%E5%9E%8B-%E5%8F%AF%E9%80%89%EF%BC%8C%E5%8F%AA%E6%91%98%E5%8E%9F%E6%96%87-lightgrey)
[![文档](https://img.shields.io/badge/%E6%96%87%E6%A1%A3-docs.secureview.tech-1e5eff)](https://docs.secureview.tech/zh-cn/wechat-bot/)

中文 · [English](README.md)

「马莫百科」公众号（服务 Monash University Malaysia 的同学）的微信问答机器人。同学关注公众号后直接发问，机器人用中文回答，**主路径靠规则，不用大模型、不花 token**，并且总是附上官网链接，方便同学核对英文原文。答不上来的问题会转给作者，作者的回复会发回给提问人，并被机器人记住。另有一个可选的 RAG 模式（代码里默认关闭，线上从 2026-10-24 起打开）：规则答不上时，让免费的大模型从同样的资料里摘出能回答问题的原句，程序逐字核对后才发。

> 学生个人项目，与 Monash University 无官方隶属关系。涉及选课、毕业、签证的决定请以学校官方页面为准。

## 怎么用

1. 微信搜公众号 **马莫百科**，关注。
2. 像平时聊天一样用中文发问题，比如 `FIT2004 的先修课是什么`、`怎么申请 special consideration`。问题短一点、具体一点最好，带课号更准。
3. 几秒内回复，附官网链接，可以去核对英文原文。
4. 答不上时会告诉你已转给作者。作者的回复要等你下一次给公众号发消息时才能看到，因为订阅号不能主动发消息。

给同学看的使用说明：[docs.secureview.tech/zh-cn/wechat-bot](https://docs.secureview.tech/zh-cn/wechat-bot/)。

## 它怎么回答

每条消息按顺序尝试三个来源：

1. **作者教过的问答**（`教 问题 | 答案`）：模糊匹配，可以给同一个答案补多种问法（`也问`）。
2. **[Monash Hub](https://monashhub.secureview.tech)**（姊妹项目，`POST /api/v1/ask?locale=zh`）：课程代码对应的 Handbook 信息（考核、先修、开课、工作量，以及课程简介和学习目标）、官方 FAQ 和官方页面。用网站自己的中文和术语表渲染。Hub 社区里相关的帖子会附在答案下面，注明是学生经验。
3. **马莫百科文章**：对公众号文章的标题、摘要和正文做匹配，回复文章链接。同学常打的词会换成文章里的说法（Moodle → 学习平台、Allocate → 课表系统、学费 → 缴费）。

都匹配不上时，机器人告诉提问人"已转给作者"，同时作者在自己的微信里收到一条"待答 #N"，回复 `答 N 你的答案` 即可。答案会发给提问人（见"限制"），并存成新的问答，下次同样的问题机器人自己就能答。这条回复还会附上 Monash Hub 上按主题整理的马莫百科往期文章（`/mamo`）。很多人会把一个问题拆成好几句发，所以待答通知会等提问人 `WXBOT_PENDING_QUIET_S`（90）秒没再发新的，再把这段时间里机器人答不上来的几句合成一条发给作者，附上同一时间问过的其他问题；提问人也只收到一次"已转给作者"。问题还没处理时又补充的，追加到同一条，作为补充再发一次。几句合起来的回答不存成问答。

```
同学 ──► 马莫百科 公众号 ──► https://wxbot.secureview.tech/mp（nginx）──► wxbot（aiohttp，127.0.0.1:8102）
                                                                              │
                                          ┌──────────────┬───────────────┬────┴────────────┐
                                          ▼              ▼               ▼                 ▼
                                    教过的问答       Monash Hub API    马莫百科文章     待发回复 / 待答
                                    （SQLite）     （127.0.0.1:8100）   （SQLite）        （SQLite）
作者 ◄──► 微信里的「WeChat ClawBot」对话（腾讯 iLink 长轮询；管理后台 + 告警）◄─────────────────┘
```

用两个微信通道，是因为各自只能做一部分事：

| 通道 | 谁用 | 原因 |
|---|---|---|
| 公众号消息回调 | 所有人 | 对外入口；未认证的个人订阅号只能被动回复（5 秒内、2048 字节内、每条消息回一条） |
| iLink「ClawBot」（腾讯官方个人机器人接口） | 只有作者 | 只属于扫码的那个号，别人加不了、也拉不进群，所以用作管理后台和告警渠道 |
| MonashGuide 个人号，通过 jwping/wxbot（`wxbot/pcwx.py`） | 群聊、私聊 | 在群里被 @ 时回答；非官方方案，所以用单独的小号（封号风险作者已知晓）。设置 `WXBOT_OWNER_WXID` 后，待答通知通过它发到作者微信，ClawBot 掉线时告警也改走它 |

## 为什么只许摘原句，不做普通的 RAG 机器人

微信上的聊天机器人大多让大模型自己写回复。最有名的开源项目 [CowAgent](https://github.com/zhayujie/CowAgent)（原 chatgpt-on-wechat）在 README 里写的流程是：Agent 结合记忆、知识库和工具推理，再由模型生成回复。给生成的回复附上来源，也挡不住来源里没有的句子：一项对四个生成式搜索引擎的人工核查（[Liu、Zhang、Liang，EMNLP 2023 Findings](https://aclanthology.org/2023.findings-emnlp.467/)）发现，生成的句子只有 51.5% 能被它引用的来源完全支持。

学生和家长问的是签证、选课、毕业，多编一步比不回答更糟。所以这个机器人先按规则答；要用模型时，模型只能指出原文里的句子，程序逐句对照原文，对上了才发。

| | 让模型写回复 | 这个机器人 |
| --- | --- | --- |
| 回复从哪来 | 模型生成，附上来源 | 教过的问答、Handbook 字段、公众号文章，或从原文里原样摘的句子 |
| 来源里没有的句子 | 可能发出去 | 逐字核对时删掉 |
| 什么都对不上 | 看提示词怎么写 | 转给人工 |
| 每条消息的成本 | 调一次模型 | 规则不花钱；可选的模型用免费额度 |

核对起了多大作用，数字来自 [docs/EVAL.md](docs/EVAL.md) 最近两次运行（50 题，2026-10-25，`rule-r8` 和 `rag-qwen3.8-27b-r8`）：

| | 只用规则 | 规则 + 只许摘原句的模型 |
| --- | --- | --- |
| 资料里没有答案的题，没有乱答、转给人工 | 7 题里 1 题 | 7 题里 6 题 |
| 程序删掉了至少一句摘句的模型调用 | - | 29 次里 8 次 |
| 摘句一句都不能发、转给人工的模型调用 | - | 29 次里 2 次 |
| 超过公众号 4 秒限制的回复 | 50 题里 0 题 | 50 题里 0 题 |

EVAL.md 里“回答正确”一栏是裁判模型打的分，看不出多编的步骤，所以这里不引用。

## 规则优先，大模型只是可选

Monash Hub 有意不使用生成式 AI，这个机器人的主路径也一样：匹配靠 jieba 分词 + 中文双字组 + IDF 加权重叠（`wxbot/kb.py`），每条回答都能追溯到一条问答、一个 Handbook 字段或一个文章链接。

**RAG 模式**（`WXBOT_RAG=1`，默认关闭；线上打开，用 Groq 免费的 `qwen/qwen3.8-27b`）只在规则没命中或只有弱命中时才用，带课程或学位代码的问题不用：

1. 在片段索引上混合检索：词语重叠加本地 bge-small-zh 向量，用 RRF 合并，取前 5 段。
2. 把问题和编号的片段发给免费的 OpenAI 兼容模型（默认智谱 `glm-4-flash`）。模型不自己写回答，只能从片段里原样摘最多 4 句，写成 `[编号] 原句`，没有能回答的句子就说“这个我不确定”。
3. 程序逐字核对每一句是不是在它标的那段资料里（忽略空格），对不上的不发。摘句按它所在的整句发出；离开上下文会看错的句子不发，比如条件下面的列表项（“如果你没有满足上述任何一项要求：”）、以“；并且”或“：”结尾的、以“此流程”或前面没有问题的“不，”开头的。已教问答能回答时，不再混入别的句子；Hub FAQ 旁边只保留马来西亚页面的句子。讲澳洲的内容（澳洲校区页面，或带“在澳”、CoE、OSHC 等词的句子）放在最后，单独标“澳洲校区”，因为签证、保险这些规定两个国家不一样。发出的句子下面列出页面和链接，并注明是原文摘录。模型说资料里没有答案，或者摘的句子都不能用时，规则的弱匹配答案也不发，问题转给作者。作者 2026-10-24 定的原则是宁可说不知道，也不能说错流程；之前让免费模型用自己的话回答时，它会补出资料里没有的步骤。
4. 公众号上，规则已经有答案的问题只等 4 秒预算里剩下的时间。超时或出错时（Groq 免费额度在同时来好几个问题时会返回 429），公众号文章和 Hub FAQ 的答案照常发，但弱匹配的问答和一串相关性不高的官方页面不发，因为没有经过核对，问题转给作者。超时的调用会在后台跑完并缓存 7 天，再问一次就是秒回。

打开后，问题原文（不含用户 id）会发给模型服务商。和规则比效果如何，见 [docs/EVAL.md](docs/EVAL.md)：`python -m wxbot eval --mode rule|rag [--judge]` 跑 `eval/questions.jsonl` 里的 50 道题，报告检索命中@5、回答带正确链接、固定裁判模型打分的正确率、不该答的没乱答、摘句对不上原文的比例、超时和 P50/P95 耗时，每次运行一行。裁判只对照参考要点打分，看不出多补的步骤，所以回答还要逐条人工对照原文核对。最新结果见 [docs/EVAL.md](docs/EVAL.md)。

## 功能

- 用 Monash Hub 自己的中文翻译回答；没有校对过的中文就不贴英文长段落，改给 Handbook 链接，机器翻译会注明。
- "FIT2102学什么" → 课程简介、学习目标、考核、开课、先修、官网链接（≤ 1500 字节）。
- 默认年份的 Handbook 里没有这门课时（FIT2004 不在 2027 年），退回最近收录它的年份，并说明。
- 问"FIT2102 2026"（或 2026版、今年、明年）就查那一年的 Handbook；每条课程回答都会说明还有哪些年份、怎么问。`WXBOT_HUB_YEAR` 可以把默认年份先钉在今年，同学还在上今年的课时用。
- 答案下面附 Monash Hub 社区里已解决的相关帖子（最多两条，注明是学生经验、非官方）；官方内容都对不上但社区有帖子时，就回帖子，不再转给作者。
- 新关注的人第一次发消息，会先收到**关注语**，再收到答案，合在一条回复里。
- 作者在微信里管理：教、改、答、统计、查看（见下表）。
- 匹配是关键词式的，所以要让作者看得到没答上的：`未命中` 列出近一周没答上和差一点命中的问题，附上可以直接发的 `也问`；每周一早上自动发一份小结；`同义词` 把同学混用的词（签证 / visa / EMGS）算成一个词。`tests/test_qa_files.py` 是调阈值用的标注集。
- 出问题时机器人自己把提醒推到作者的 ClawBot（同类问题限频），ClawBot 掉线时改走 MonashGuide，不用盯日志。等了超过一天的待答问题每天提醒一次；`GET /health`（作者收不到消息时回 503）给外部监控用。
- 可选 RAG 模式用的片段索引：教过的问答、马莫百科推文、Monash Hub 的中文指南和 FAQ 切成短片段，用词语重叠加本地向量模型（onnxruntime 跑 bge-small-zh，只用 CPU）检索，再用倒数排名融合（RRF）合并。`python -m wxbot index` 建索引，`python -m wxbot search 问题` 显示前 5 条。见[运维手册](docs/OPERATIONS.zh-CN.md)第 10 节。
- 每晚自动备份知识库；可以单独导出教过的问答（不含用户数据）。
- 同学的提问保留 `WXBOT_LOG_DAYS`（90）天后删除，任何人发「删除我的数据」都能删掉自己的全部记录（介绍里不提，作者决定不需要告诉用户）。

### 作者命令（发给 ClawBot 对话，或者用作者自己的微信发给 MonashGuide）

| 命令 | 含义 |
|---|---|
| `教 问题 \| 答案 [\| 链接]` | 新增问答 |
| `也问 编号 另一种问法` | 给问答补一种问法 |
| `不问 编号 问法` | 去掉一种问法（第一种不能去） |
| `改 编号 新答案 [\| 链接]` · `删 编号` · `看 编号` | 修改 / 删除 / 查看 |
| `删数据 编号` | 删掉待答 #编号 那位提问人的全部记录（对方要求时用） |
| `列表 [页码]` | 所有问答，每页 20 组，带命中次数 |
| `查 关键词` · `试 问题` | 看会匹配到什么 / 模拟完整回答并显示来源 |
| `待答` · `答 编号 答案` · `忽略 编号` | 待答问题（显示等了多久）；回答（也可发「编号 答案」，或引用待答通知；再答一次就是更正）/ 跳过 |
| `收录 <mp.weixin.qq.com 链接>` · `删文 编号` | 收录 / 移除马莫百科文章（直接发链接也行） |
| `关注语 [新内容]` | 查看 / 设置欢迎语 |
| `未命中 [天数]` | 近几天（默认 7 天）没答上的问题，附差一点命中的问答和可以直接发的 `也问`；以及回了"你问的是不是…"的问题 |
| `同义词 [词=词=词]` | 查看 / 添加匹配时算同一个词的词（`同义词 签证=visa=EMGS`）；`同义词 删 visa` 移除一个词 |
| `管理员` · `管理员 配对` · `管理员 删 序号` | 查看管理员 / 给新管理员一个一次性配对码 / 删掉配对加入的管理员 |
| `统计` · `管理` | 使用情况 / 命令列表 |

## 需要知道的限制

- 个人订阅号不能主动推送：作者对转人工问题的回答，要等提问人下一次给公众号发消息时才显示。公众号认证后可以解决。
- ClawBot 只属于扫码的那个号，进不了群。群聊走 MonashGuide，这是非官方方案，有封号风险。
- 提问人一直不再发消息的话，待发回复 `WXBOT_OUTBOX_DAYS`（30）天后作废；超过 3 天的会注明是哪天的回复。
- iLink 会话会过期，需要重新扫码 `python -m wxbot login`（见 [docs/OPERATIONS.zh-CN.md](docs/OPERATIONS.zh-CN.md)）。

## 快速开始（开发）

需要 Python 3.12。

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                          # 80 多个测试，不需要联网
WXBOT_HOME=.scratch WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1 \
  .venv/bin/python -m wxbot ask "FIT2102学什么"          # 在终端里问一个问题
```

命令行：`python -m wxbot {login,run,ask,teach,mamo-add,mamo-sync,mamo-sync-api,status,backup,purge,export-qa,import-qa,index,search,eval}`。

要让 Handbook 回答显示中文，把 Monash Hub 的 `frontend/i18n/index.ts` 和 `frontend/i18n/handbook-terms.ts` 复制到 `$WXBOT_HOME/data/hub-i18n/`（没有这两个文件时答案保持英文；线上部署由同步定时器自动更新）。

## 配置（环境变量）

| 变量 | 默认值 | 含义 |
|---|---|---|
| `WXBOT_HOME` | 仓库根目录 | `data/` 所在位置 |
| `WXBOT_HUB_API` | `http://127.0.0.1:8100/api/v1` | Monash Hub API 地址 |
| `WXBOT_HUB_YEAR` | 无（用 Hub 的默认年份） | 查哪一年的 Handbook；问题里写了年份以问题为准 |
| `WXBOT_HUB_CAMPUS` | `malaysia` | Hub 优先给哪个校区的官网页面；留空就不传 |
| `WXBOT_MP_TOKEN` | 无 | 填在公众号后台的 Token；不设置则不启动 `/mp` 服务 |
| `WXBOT_MP_PORT` | `8102` | `/mp` 服务的本地端口 |
| `WXBOT_OWNER_NAME` | `Waldo` | "转给 …" 回复里的名字 |
| `WXBOT_MAMO_TS`、`WXBOT_HUB_I18N_DIR` | `data/` 下 | Monash Hub 文件的副本，由同步定时器更新 |
| `WXBOT_HUB_FILES_URL` | 无 | Hub 仓库的原始文件地址前缀；Hub 不在这台机器上时设置，`mamo-sync` 会去下载那些文件 |
| `WXBOT_QA_STRONG` / `WXBOT_QA_WEAK` | `0.6` / `0.42` | 教过的问答阈值（直接回答 / "你问的是不是…"） |
| `WXBOT_QA_NEAR` | `0.3` | 没答上的问题分数到这里就算"差一点命中"，在 `未命中` 里显示 |
| `WXBOT_QA_MARGIN` | `0.03` | 第二接近的问答分数要低这么多，强匹配才直接回答 |
| `WXBOT_ARTICLE_MIN` / `WXBOT_ARTICLE_LEAD` | `0.5` / `0.7` | 文章匹配阈值 |
| `WXBOT_OUTBOX_DAYS` | `30` | 超过这个天数的公众号待发回复不再显示；已送出的过了这个天数就删除 |
| `WXBOT_LOG_DAYS` | `90` | 同学的提问、已处理的待答和没送出的回复，过了这个天数就删除 |
| `WXBOT_PENDING_QUIET_S` / `WXBOT_PENDING_MERGE_S` | `90` / `1800` | 提问人这么久没再发，才发待答通知；离上一句答不上来的这么近，就追加到同一条待答 |
| `WXBOT_PCWX_API`、`WXBOT_PCWX_SECRET` | 无 | MonashGuide（jwping/wxbot）的 API 地址和回调密钥；都为空则关闭 |
| `WXBOT_PCWX_LISTEN` | `172.17.0.1:8112` | MonashGuide 回调监听地址（docker 网桥） |
| `WXBOT_PCWX_NAMES` | `马莫百科,MonashGuide` | 手打的"@名字"也算 @ 了机器人 |
| `WXBOT_OWNER_WXID` | 无 | 作者的 wxid：待答通知和备用告警通过 MonashGuide 发到这里 |
| `WXBOT_MP_APPID`、`WXBOT_MP_SECRET` | 无 | 仅用于没在用的 `mamo-sync-api` |
| `WXBOT_EMBED_MODEL` | `BAAI/bge-small-zh-v1.5` | 片段索引用的本地向量模型；`off`（或没装 onnxruntime）就只用词语重叠 |
| `WXBOT_MODELS_DIR` | `data/models` | 向量模型下载到哪 |
| `WXBOT_RAG_LEX_MIN` / `WXBOT_RAG_VEC_MIN` | `0.3` / `0.45` | 低于这两个分数的片段不算检索结果（词语覆盖率 / 余弦相似度） |
| `WXBOT_RAG` | `0` | `1` 打开 RAG 回答（需要先建索引、配 key） |
| `WXBOT_LLM_BASE` / `WXBOT_LLM_MODEL` | 智谱 `https://open.bigmodel.cn/api/paas/v4` / `glm-4-flash` | 任意 OpenAI 兼容的接口和模型 |
| `WXBOT_LLM_KEY` | 无 | 服务商的 API key（密钥，只放 `.env`） |
| `WXBOT_LLM_EXTRA` | 无 | 请求里额外加的 JSON，比如 Groq 的 gpt-oss 用 `'{"reasoning_effort": "low"}'`（要加单引号） |
| `WXBOT_LLM_TIMEOUT` | `8` | 规则答不上的问题最多等模型几秒 |
| `WXBOT_RAG_CACHE_DAYS` | `7` | 同一个问题的回答缓存几天 |

见 [.env.example](.env.example)。密钥（Token、`data/account.json`）绝不进 git。

## 目录结构

```
wxbot/
  bot.py        运行时：扫码登录、iLink 长轮询、把各部分接起来
  mp.py         公众号消息服务（验签、重试去重、欢迎语、待发回复）
  brain.py      回答逻辑和作者命令（纯逻辑，不直接碰微信）
  kb.py         SQLite 存储 + 匹配索引（问答、文章、待答、待发回复、日志）
  hub.py        Monash Hub 客户端和消息排版（课程简介、年份回退）
  hub_i18n.py   从网站的 TypeScript 里读中文界面文案和 Handbook 术语表
  ilink.py      腾讯 iLink Bot API 客户端
  pcwx.py       MonashGuide 个人号（群聊），通过 jwping/wxbot
  mamo.py       马莫百科文章抓取和文章列表同步
  chunks.py     RAG 模式的片段索引：切分、增量更新、Monash Hub 指南和 FAQ
  embed.py      本地句向量（onnxruntime，可选）
  retrieve.py   片段的混合检索（词语重叠 + 向量，RRF 融合）
  llm.py        OpenAI 兼容的聊天接口客户端（直接用 aiohttp）
  rag.py        RAG 回答：提示词、引用检查、缓存、超时
  evaluate.py   `eval`：在 eval/questions.jsonl 上比较规则和 RAG 回答，生成报告
eval/           评测题目（和可选的人工标注）
  alerts.py     把问题推送到作者 ClawBot 的日志处理器（ClawBot 不通时走 MonashGuide）
  tasks.py      spawn()：启动后台任务并保留引用，保证跑完
deploy/         systemd 单元、nginx 站点、安装/部署脚本
qa/             根据马莫百科推文写的问答，用 `import-qa` 导入（作者先审过）
tests/          pytest（模拟 Monash Hub、模拟 iLink 服务器、模拟公众号请求）
docs/           运维手册（中文 / English）
```

## 部署

和 Monash Hub 在同一台 VPS，目录 `/opt/wechat-bot`，运行用户 `wxbot`，用 `./deploy/push.sh` 部署。首次安装、nginx、证书、公众号设置、扫码登录、故障排查，全部在 [docs/OPERATIONS.zh-CN.md](docs/OPERATIONS.zh-CN.md)（[English](docs/OPERATIONS.md)）。

## 项目状态

见 [CHANGELOG.md](CHANGELOG.md)。这个仓库是部署用的私有仓库的公开副本，更新日志里的 issue 和 PR 编号指的是私有仓库。

## 许可证

Copyright (c) 2026 Waldo (github.com/Waldo0926)，保留所有权利。源码公开只供作品展示和代码查看，见 [LICENSE](LICENSE)。
