# MUMGuide WeChat Bot — 马莫百科 Q&A bot

[![Type](https://img.shields.io/badge/Type-Zero--AI_WeChat_bot-2563eb?style=for-the-badge)](#how-it-answers)
[![Tech](https://img.shields.io/badge/Tech-Python_3.12_%C2%B7_aiohttp_%C2%B7_SQLite-7c3aed?style=for-the-badge)](#project-layout)
[![Tests](https://img.shields.io/badge/Tests-pytest_%C2%B7_offline-16a34a?style=for-the-badge)](#quick-start-development)
[![License](https://img.shields.io/badge/License-All_Rights_Reserved-dc2626?style=for-the-badge)](LICENSE)

**English** · [中文](README.zh-CN.md)

A WeChat question-answering bot for the **马莫百科 (MUMGuide)** official account, which serves students of Monash University Malaysia. A student follows the account and asks a question in Chinese; the bot answers from three sources **with no language model and no token cost**, and every answer carries a link to the source so the student can check it. Anything it cannot answer is forwarded to the owner, whose reply is sent back and remembered.

> Independent student project. Not affiliated with Monash University. Answers about enrolment, graduation or visas must be confirmed against the university's official pages.

## How it answers

For each message the bot tries, in order:

1. **Answers the owner taught it** (`教 问题 | 答案`), fuzzy-matched, with extra phrasings (`也问`).
2. **[Monash Hub](https://monashhub.secureview.tech)**, the sister project, through its `POST /api/v1/ask` endpoint: Handbook facts for a unit (assessment, prerequisites, offerings, workload, summary and learning outcomes), degree and area-of-study cards, curated official FAQs and official pages, rendered with the website's own reviewed Chinese vocabulary.
3. **马莫百科 articles**: title, digest and body of the account's own posts, answered with the post link.

If nothing matches, the student is told the question has been forwarded; the owner gets a "待答 #N" note in a private WeChat chat and replies `答 N <answer>`. The answer reaches the asker and is stored as a new Q&A, so the same question is answered automatically next time.

```text
Student ──► 马莫百科 official account ──► message callback (nginx) ──► bot (aiohttp)
                                                                        │
                       ┌──────────────────┬─────────────────────┬───────┴──────────┐
                       ▼                  ▼                     ▼                  ▼
                  taught Q&A        Monash Hub API      马莫百科 articles    outbox / pending
                   (SQLite)          (/ask, /guides)        (SQLite)            (SQLite)

Owner ◄──► private "ClawBot" chat (Tencent iLink long-poll): admin console and alerts
```

Two official WeChat channels are used, because each can do only part of the job:

| Channel | Used by | Why |
|---|---|---|
| Official account (订阅号) message callback | every student | The public front door. An unverified personal 订阅号 can only reply passively: within 5 seconds, at most 2048 bytes, one reply per message. |
| iLink "ClawBot" (Tencent's official personal-bot API) | the owner only | Private to the account that scanned its QR code, so it serves as the admin console and the alert channel. |

## Why no AI

Monash Hub is deliberately generative-AI-free, and so is this bot. Matching is jieba words plus CJK character bigrams with IDF-weighted overlap (`wxbot/kb.py`), and every answer can be traced to a Q&A row, a Handbook field, an official page or an article link. That makes answers about rules and deadlines checkable, costs nothing per message, and keeps the reply inside WeChat's 5-second window.

## Features

- **Units by code or by name.** "FIT2102学什么" returns the summary, learning outcomes, assessment, offerings and prerequisites; "编程范式有期末考试吗" finds FIT2102 by its title, and an ambiguous name lists the candidates and asks for the code.
- **Degrees and areas of study.** A degree code or name (C2001, "计算机科学学士要修多少学分") or an area-of-study code returns a card with credit points, structure, campuses and links.
- **Faculty teach-out notices.** Units that are closing or being replaced show the faculty's own wording and link.
- **Year fallback.** When the default Handbook year drops a unit or degree, the bot reads the latest year that lists it and says so.
- **Chinese first, never machine-pasted.** Answers use Monash Hub's reviewed translations; text without reviewed Chinese is linked rather than pasted in English, and every official link is paired with its Monash Hub Chinese page.
- **Malaysia-aware ordering.** Malaysia and all-campus pages come before Australia-only ones, while Monash Hub's relevance order is otherwise kept.
- **Fits WeChat's limits.** All Monash Hub calls for one question share a 3.4-second budget so a reply is never cut off at 5 seconds, and a Hub outage tells the student to try again instead of flooding the owner.
- **Owner console in WeChat:** teach, edit, answer, rank and inspect (below), with problems reported to the owner's chat and rate-limited per kind, so nobody has to watch logs.

### Owner commands (sent to the ClawBot chat)

| Command | Meaning |
|---|---|
| `教 问题 \| 答案 [\| 链接]` | add a Q&A |
| `也问 编号 另一种问法` | add a phrasing to a Q&A |
| `改 编号 新答案 [\| 链接]` · `删 编号` · `看 编号` | edit / delete / show |
| `查 关键词` · `试 问题` | what would match / simulate the full answer with its source |
| `待答` · `答 编号 答案` · `忽略 编号` | pending questions; answer / skip |
| `收录 <mp.weixin.qq.com 链接>` · `删文 编号` | add / remove a 马莫百科 article |
| `关注语 [新内容]` | show / set the welcome message |
| `统计` · `管理` | usage summary / this list |

## Constraints worth knowing

- A personal 订阅号 cannot push messages, so the owner's answer to a forwarded question is shown the next time that student messages the account. A verified account would lift this.
- The ClawBot channel is private to whoever scanned its QR code; it cannot be shared or added to group chats.
- iLink sessions expire and need a new QR scan (`python -m wxbot login`).

## Quick start (development)

Requires Python 3.12.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # offline tests: fake Monash Hub, fake official-account requests
WXBOT_HOME=.scratch WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1 \
  .venv/bin/python -m wxbot ask "FIT2102学什么"
```

CLI: `python -m wxbot {login,run,ask,teach,mamo-add,mamo-sync,mamo-sync-api,status}`.

For fuller Chinese rendering of Handbook answers, put copies of Monash Hub's `frontend/i18n/index.ts` and `frontend/i18n/handbook-terms.ts` in `$WXBOT_HOME/data/hub-i18n/`; without them answers stay in English.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `WXBOT_HOME` | repo root | where `data/` lives |
| `WXBOT_HUB_API` | local Monash Hub | Monash Hub API base URL |
| `WXBOT_MP_TOKEN` | — | token entered in the official-account backend; the callback server is off without it |
| `WXBOT_MP_PORT` | `8102` | local port of the callback server |
| `WXBOT_OWNER_NAME` | `Waldo` | name used in "转给 …" replies |
| `WXBOT_MAMO_TS`, `WXBOT_HUB_I18N_DIR` | under `data/` | copies of Monash Hub files, refreshed by a sync job |
| `WXBOT_QA_STRONG` / `WXBOT_QA_WEAK` | `0.6` / `0.42` | taught-answer thresholds (direct / "你问的是不是…") |
| `WXBOT_ARTICLE_MIN` / `WXBOT_ARTICLE_LEAD` | `0.5` / `0.7` | article match thresholds |

See [.env.example](.env.example). Secrets (the token and the iLink account file) never go in git.

## Project layout

```text
wxbot/
  bot.py       runtime: QR login, iLink long-poll loop, delivery
  mp.py        official-account message server (signature check, retries, welcome, outbox)
  brain.py     answering logic and owner commands (pure, no WeChat I/O)
  kb.py        SQLite store and matching index (taught Q&A, articles, pending, outbox, log)
  hub.py       Monash Hub client and message formatting (units, degrees, year fallback)
  hub_i18n.py  reads the website's Chinese strings and Handbook vocabulary from its TypeScript
  ilink.py     Tencent iLink Bot API client
  mamo.py      马莫百科 article fetching and post-list sync
  alerts.py    logging handler that reports problems to the owner's chat
tests/         pytest, fully offline
```

## About this repository

This is a public snapshot of a private working repository. Deployment scripts, server configuration and the operations runbook are kept private. In production the bot runs as a sandboxed systemd service behind nginx, next to Monash Hub.

## License

Copyright © 2026 Shuoxun Wen. All rights reserved. The source is published for portfolio presentation and code review only; see [LICENSE](LICENSE).
