# MUMGuide WeChat Bot: 马莫百科 Q&A bot

[![Tests](https://github.com/Waldo0926/mumguide-wechat-bot/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Waldo0926/mumguide-wechat-bot/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/License-All_Rights_Reserved-dc2626)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![aiohttp](https://img.shields.io/badge/aiohttp-3.9%2B-2C5BB4?logo=aiohttp&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)
![WeChat](https://img.shields.io/badge/WeChat-%E5%85%AC%E4%BC%97%E5%8F%B7%20%2B%20iLink-07C160?logo=wechat&logoColor=white)
![LLM: optional, quote-only](https://img.shields.io/badge/LLM-optional%2C%20quote--only-lightgrey)

[中文](README.zh-CN.md) · English

A WeChat question-answering bot for the **马莫百科** (MUMGuide) official account, which serves students of
Monash University Malaysia. A student follows the account and asks a question; the bot answers in Chinese
from three sources by rules, **with no language model and no token cost**, and always attaches the official link so
the student can check the English original. An optional RAG mode (off by default in the code, on in production since 2026-10-24) lets a free chat model pick sentences
from the same sources, checked word for word in code, when the rules find nothing. Anything it cannot answer is forwarded to the owner, whose reply
is sent back and remembered.

> Independent student project. Not affiliated with Monash University. Answers about enrolment, graduation or
> visas must be confirmed against the university's official pages.

## How it answers

For each message the bot tries, in order:

1. **Answers the owner taught it** (`教 问题 | 答案`): fuzzy-matched, with extra phrasings (`也问`).
2. **[Monash Hub](https://monashhub.secureview.tech)** (the sister project, `POST /api/v1/ask?locale=zh`):
   Handbook facts for a unit code (assessment, prerequisites, offerings, workload, and a summary with learning
   outcomes), curated official FAQs and official pages. Rendered with the website's own Chinese vocabulary.
   Related posts from the Hub's community go under the answer, labelled as student experience.
3. **马莫百科 articles**: title + digest + body of the account's posts, answered with the post link. Common words
   students type are mapped to the articles' own (Moodle → 学习平台, Allocate → 课表系统, 学费 → 缴费).

If nothing matches, the student is told the question has been forwarded; the owner gets a "待答 #N" note in
their own WeChat chat and replies `答 N <answer>`. The answer is sent to the asker (see *Constraints*) and stored
as a new Q&A, so the same question is answered automatically next time. The reply also links the list of all
马莫百科 posts by topic on Monash Hub (`/mamo`). People often split one question into several short messages, so
the note waits until the asker has sent nothing new for `WXBOT_PENDING_QUIET_S` (90 s): every line the bot could not
answer goes in one note, with what else they asked then, and the asker is told "forwarded" once. A line added
later, while the question is still open, joins it and is sent as a supplement. An answer to several lines is not
stored as a Q&A.

```
Student ──► 马莫百科 公众号 ──► https://wxbot.secureview.tech/mp (nginx) ──► wxbot (aiohttp, 127.0.0.1:8102)
                                                                               │
                                           ┌──────────────┬───────────────┬────┴─────────────┐
                                           ▼              ▼               ▼                  ▼
                                   taught Q&A       Monash Hub API   马莫百科 articles   outbox / pending
                                   (SQLite)       (127.0.0.1:8100)     (SQLite)          (SQLite)
Owner ◄──► "WeChat ClawBot" chat (Tencent iLink long-poll, admin console + alerts) ◄─────────────┘
```

Two WeChat channels, because each can do only part of the job:

| Channel | Who uses it | Why |
|---|---|---|
| 公众号 (official account) message callback | everyone | public front door; an unverified personal 订阅号 can only reply passively (≤ 5 s, ≤ 2048 bytes, one reply per message) |
| iLink "ClawBot" (Tencent's official personal-bot API) | the owner only | private to the account that scanned the QR code; cannot be shared or join groups, so it is the admin console and the alert channel |
| MonashGuide personal account via jwping/wxbot (`wxbot/pcwx.py`) | group chats, private chats | answers when @-ed in a group; unofficial, so it is a separate small account (ban risk accepted by the owner). With `WXBOT_OWNER_WXID` set, 待答 notes go to the owner's WeChat through it, and alerts fall back to it when ClawBot is down |

## Rules first, a model only as an option

Monash Hub is deliberately generative-AI-free, and so is this bot's main path: matching is jieba words + CJK character
bigrams with IDF-weighted overlap (`wxbot/kb.py`), and every answer can be traced to a Q&A row, a Handbook
field, or an article link.

The **RAG mode** (`WXBOT_RAG=1`; off by default, on in production with Groq's free `qwen/qwen3.8-27b`) is asked only when those rules found nothing or only a weak match, and
never for a unit or degree code:

1. Hybrid search over the chunk index: word overlap plus local bge-small-zh vectors, fused with RRF, top 5 passages.
2. A free OpenAI-compatible model (default Zhipu `glm-4-flash`) gets the question and the numbered passages. It does not
   write an answer: it may only pick up to 4 sentences from them, word for word, as `[n] sentence`, or say "这个我不确定".
3. The code checks that each quote is in the passage it names (spaces ignored) and drops the ones that are not. A
   quote is sent as the whole sentence it is in, and not at all when it cannot be read right alone: a list item under
   a condition ("如果你没有满足上述任何一项要求："), a line ending in "；并且" or "：", or one starting with "此流程"
   or a "不，" with no question in front of it. When a taught Q&A answers, nothing else is mixed in; next to the Hub's
   FAQ only Malaysia pages are. What is about Australia (an Australian campus page, or a sentence with "在澳", CoE,
   OSHC and the like) goes last under its own heading, since the visa and insurance rules differ by country.
   The sentences are sent with their pages and links under them and a line saying they are excerpts. When the model
   says the passages do not answer the question, or none of its quotes can be sent, a weak rule match is not sent either:
   the question goes to the owner. The owner's rule (2026-10-24) is better "不知道" than a wrong procedure, and free
   models asked to answer in their own words added steps no passage has.
4. On the 公众号 a question the rules did answer waits only for what is left of the 4 s budget. On a timeout or an
   error (Groq's free tier answers 429 when several questions come at once), an article or the Hub's FAQ is still sent,
   but a weak Q&A match or a list of loosely related pages is not, since nothing checked it: the question goes to the
   owner. A call that ran late still finishes and is cached (7 days), so asking again is instant.

Turning it on sends the question text (no user id) to the model's provider. How well it does against the rules is
measured in [docs/EVAL.md](docs/EVAL.md): `python -m wxbot eval --mode rule|rag [--judge]` runs the 50 questions in
`eval/questions.jsonl` and reports retrieval hit@5, replies with the right link, correctness marked by a fixed judge
model, unanswerable questions left alone, quotes not found in their passages, timeouts and P50/P95 time, one row per
run. The judge only compares a reply with the expected points, so it does not catch an added step; replies are also
read by hand against their passages. The current numbers are in [docs/EVAL.md](docs/EVAL.md).

## Features

- Chinese answers using Monash Hub's own translations; text with no reviewed Chinese is never pasted in English;
  the Handbook link is given instead, and machine translations are labelled as such.
- "FIT2102学什么" → summary, learning outcomes, assessment, offerings, prerequisites, links (≤ 1500 bytes).
- Falls back to the latest Handbook year that lists a unit when the default year dropped it (FIT2004 is not in 2027).
- "FIT2102 2026" (or 2026版, 今年, 明年) asks for that Handbook year; every unit answer says which other years exist
  and how to ask for one. `WXBOT_HUB_YEAR` pins the default year while students still sit this year's units.
- Solved community posts from Monash Hub are offered under an answer (at most two, marked as student experience,
  not official); when nothing official matches but posts do, they are the reply instead of a forward to the owner.
- First message from a new follower gets the **关注语** (welcome) followed by the answer, in one reply.
- Owner console in WeChat: teach, edit, answer, rank, inspect (see below).
- Matching is keyword-based, so the owner can see what it missed: `未命中` lists the week's unanswered and near-miss
  questions with the phrasing to add, a digest of them arrives every Monday morning, and `同义词` makes words students
  use interchangeably (签证 / visa / EMGS) count as one. `tests/test_qa_files.py` is the labelled set the thresholds are
  tuned against.
- Problems are reported to the owner's ClawBot chat (rate-limited per kind), or through MonashGuide when ClawBot is
  down, so nobody has to watch logs. Questions waiting over a day are brought up once a day, and `GET /health`
  (503 when the owner cannot be reached) is there for an outside uptime check.
- A chunk index for the optional RAG mode: taught Q&A, 马莫百科
  articles and Monash Hub's Chinese guides and FAQ cut into short passages, searched by word overlap plus a local
  vector model (bge-small-zh on onnxruntime, CPU only), merged with reciprocal rank fusion. `python -m wxbot index`
  builds it, `python -m wxbot search 问题` shows the top 5. See [docs/OPERATIONS.md](docs/OPERATIONS.md) §10.
- Nightly backup of the knowledge base, and an export of the taught answers that leaves out user data.
- Students' questions are kept for `WXBOT_LOG_DAYS` (90) and then deleted, and anyone can send `删除我的数据` to delete
  everything stored about them (the introduction does not mention it; the owner decided users need not be told).

### Owner commands (sent to the ClawBot chat, or to MonashGuide from the owner's WeChat)

| Command | Meaning |
|---|---|
| `教 问题 \| 答案 [\| 链接]` | add a Q&A |
| `也问 编号 另一种问法` | add a phrasing to a Q&A |
| `不问 编号 问法` | remove a phrasing (not the first) |
| `改 编号 新答案 [\| 链接]` · `删 编号` · `看 编号` | edit / delete / show |
| `删数据 编号` | delete everything stored about the person who asked 待答 #编号 (when they ask for it) |
| `列表 [页码]` | every Q&A, 20 per page, with its hit count |
| `查 关键词` · `试 问题` | what would match / simulate the full answer with its source |
| `待答` · `答 编号 答案` · `忽略 编号` | pending questions with how long they waited; answer (also `编号 答案`, or quote the note; again to correct it) / skip |
| `收录 <mp.weixin.qq.com 链接>` · `删文 编号` | add / remove a 马莫百科 article (a bare link also works) |
| `关注语 [新内容]` | show / set the welcome message |
| `未命中 [天数]` | questions nobody could answer in the last days (default 7), with the Q&A each almost hit and the `也问` to send; and questions answered with "你问的是不是…" |
| `同义词 [词=词=词]` | show / add words that count as one for matching (`同义词 签证=visa=EMGS`); `同义词 删 visa` removes a word |
| `管理员` · `管理员 配对` · `管理员 删 序号` | list admins / give a new admin a one-time code / remove one added that way |
| `统计` · `管理` | usage summary / this list |

## Constraints worth knowing

- A personal 订阅号 cannot push: the owner's answer to a forwarded question is shown the next time that person
  messages the account. Verifying the account would lift this.
- The ClawBot channel is private to whoever scanned its QR code and cannot join groups. Group chats go through MonashGuide, which is unofficial
  and can be banned.
- A queued reply is dropped after `WXBOT_OUTBOX_DAYS` (30) if the person never writes again; after 3 days it shows the
  day it was written.
- iLink sessions expire; re-scan with `python -m wxbot login` (see [docs/OPERATIONS.md](docs/OPERATIONS.md)).

## Quick start (development)

Requires Python 3.12.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                          # 80+ tests, no network needed
WXBOT_HOME=.scratch WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1 \
  .venv/bin/python -m wxbot ask "FIT2102学什么"          # answer a question from the terminal
```

CLI: `python -m wxbot {login,run,ask,teach,mamo-add,mamo-sync,mamo-sync-api,status,backup,purge,export-qa,import-qa,index,search,eval}`.

For fuller Chinese rendering of Handbook answers, put copies of the Monash Hub files
`frontend/i18n/index.ts` and `frontend/i18n/handbook-terms.ts` in `$WXBOT_HOME/data/hub-i18n/`
(without them answers stay in English; the deployment keeps them in sync automatically).

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `WXBOT_HOME` | repo root | where `data/` lives |
| `WXBOT_HUB_API` | `http://127.0.0.1:8100/api/v1` | Monash Hub API base |
| `WXBOT_HUB_YEAR` | none (the Hub's default) | Handbook year to answer from; a year typed in the question wins |
| `WXBOT_HUB_CAMPUS` | `malaysia` | campus whose official pages the Hub ranks first; empty sends none |
| `WXBOT_MP_TOKEN` | none | token typed into the 公众号 backend; the `/mp` server is off without it |
| `WXBOT_MP_PORT` | `8102` | local port of the `/mp` server |
| `WXBOT_OWNER_NAME` | `Waldo` | name used in "转给 …" replies |
| `WXBOT_MAMO_TS`, `WXBOT_HUB_I18N_DIR` | under `data/` | copies of Monash Hub files, refreshed by the sync timer |
| `WXBOT_HUB_FILES_URL` | none | raw-file root of the Hub's repository; set it when the Hub is not on this machine and `mamo-sync` downloads those files |
| `WXBOT_QA_STRONG` / `WXBOT_QA_WEAK` | `0.6` / `0.42` | taught-answer thresholds (direct / "你问的是不是…") |
| `WXBOT_QA_NEAR` | `0.3` | from this score a miss counts as "almost hit" in `未命中` |
| `WXBOT_QA_MARGIN` | `0.03` | a strong match answers directly only when the next taught answer scores at least this much lower |
| `WXBOT_ARTICLE_MIN` / `WXBOT_ARTICLE_LEAD` | `0.5` / `0.7` | article match thresholds |
| `WXBOT_OUTBOX_DAYS` | `30` | queued 公众号 replies older than this are not shown; delivered ones are deleted after it |
| `WXBOT_LOG_DAYS` | `90` | students' questions, closed 待答 questions and undelivered replies are deleted after this |
| `WXBOT_PENDING_QUIET_S` / `WXBOT_PENDING_MERGE_S` | `90` / `1800` | a 待答 note waits until the asker has been quiet this long; a miss this soon after their last one joins the same open question |
| `WXBOT_PCWX_API`, `WXBOT_PCWX_SECRET` | none | MonashGuide (jwping/wxbot) API and callback secret; both empty = off |
| `WXBOT_PCWX_LISTEN` | `172.17.0.1:8112` | where the MonashGuide callback listens (the docker bridge) |
| `WXBOT_PCWX_NAMES` | `马莫百科,MonashGuide` | names that count as a typed @-mention |
| `WXBOT_OWNER_WXID` | none | the owner's wxid: 待答 notes and backup alerts go there through MonashGuide |
| `WXBOT_MP_APPID`, `WXBOT_MP_SECRET` | none | only for the unused `mamo-sync-api` |
| `WXBOT_EMBED_MODEL` | `BAAI/bge-small-zh-v1.5` | local vector model for the chunk index; `off` (or no onnxruntime) = word overlap only |
| `WXBOT_MODELS_DIR` | `data/models` | where the vector model is downloaded to |
| `WXBOT_RAG_LEX_MIN` / `WXBOT_RAG_VEC_MIN` | `0.3` / `0.45` | below these a chunk is not a search result (word coverage / cosine) |
| `WXBOT_RAG` | `0` | `1` turns on the RAG answer (needs the index and a key) |
| `WXBOT_LLM_BASE` / `WXBOT_LLM_MODEL` | Zhipu's `https://open.bigmodel.cn/api/paas/v4` / `glm-4-flash` | any OpenAI-compatible endpoint and model |
| `WXBOT_LLM_KEY` | none | the provider's API key (secret, only in `.env`) |
| `WXBOT_LLM_EXTRA` | none | extra JSON for the request body, e.g. `'{"reasoning_effort": "low"}'` for Groq's gpt-oss (in single quotes) |
| `WXBOT_LLM_TIMEOUT` | `8` | seconds a question with no rule answer may wait for the model |
| `WXBOT_RAG_CACHE_DAYS` | `7` | how long an answer is reused for the same question |

See [.env.example](.env.example). Secrets (the token, `data/account.json`) never go in git.

## Project layout

```
wxbot/
  bot.py        runtime: QR login, iLink long-poll loop, wiring of everything
  mp.py         公众号 message server (signature check, retries, welcome, outbox)
  brain.py      the answering logic and the owner's commands (pure, no I/O to WeChat)
  kb.py         SQLite store + the matching index (taught Q&A, articles, pending, outbox, log)
  hub.py        Monash Hub client and message formatting (unit summary, year fallback)
  hub_i18n.py   reads the website's Chinese strings and Handbook vocabulary from its TypeScript
  ilink.py      Tencent iLink Bot API client
  pcwx.py       MonashGuide personal account (group chats) through jwping/wxbot
  mamo.py       马莫百科 article fetching and the post-list sync
  chunks.py     the chunk index for the RAG mode: cutting, incremental updates, Monash Hub guides and FAQ
  embed.py      local sentence vectors (onnxruntime, optional)
  retrieve.py   hybrid search over the chunks (word overlap + vectors, RRF)
  llm.py        OpenAI-compatible chat client (plain aiohttp)
  rag.py        the RAG answer: prompt, citation check, cache, timeout
  evaluate.py   `eval`: rules against the RAG answer on eval/questions.jsonl, writes the report
eval/           the evaluation questions (and optional human labels)
  alerts.py     logging handler that reports problems to the owner's ClawBot chat (MonashGuide as backup)
  tasks.py      spawn(): background tasks that are kept alive until they finish
deploy/         systemd units, nginx site, install/push scripts
qa/             Q&A written from the 马莫百科 posts, for `import-qa` (reviewed by the owner first)
tests/          pytest (fake Monash Hub, fake iLink server, fake 公众号 requests)
docs/           operations runbook (EN / 中文)
```

## Deployment

Runs on the same VPS as Monash Hub under `/opt/wechat-bot` as user `wxbot`; deploy with `./deploy/push.sh`.
Everything else (first install, nginx, certificate, 公众号 setup, QR login, troubleshooting) is in
[docs/OPERATIONS.md](docs/OPERATIONS.md) ([中文](docs/OPERATIONS.zh-CN.md)).

## Project status

See [CHANGELOG.md](CHANGELOG.md). This repository is a public copy of the private one the bot is deployed from,
so the issue and pull request numbers in the changelog refer to that repository.

## License

Copyright (c) 2026 Shuoxun Wen. All rights reserved. The source is public for portfolio review and code
inspection only; see [LICENSE](LICENSE).
