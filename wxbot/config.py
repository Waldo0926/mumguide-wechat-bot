from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("WXBOT_HOME", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
ACCOUNT_FILE = DATA / "account.json"
DB_FILE = DATA / "kb.sqlite"

HUB_API = os.environ.get("WXBOT_HUB_API", "http://127.0.0.1:8100/api/v1")
HUB_SITE = "https://monashhub.secureview.tech"
# Handbook year to ask Monash Hub for. Empty: the Hub's own default (CURRENT_ACADEMIC_YEAR, which moves to
# next year in October). Set it to this year while students still sit this year's units (issue #6); a year
# typed in the question ("FIT2102 2026") always wins.
HUB_YEAR = int(os.environ.get("WXBOT_HUB_YEAR", "0") or 0) or None
# The campus whose pages the Hub ranks first (/ask "campus"); the bot is for Monash Malaysia students. Empty: none.
HUB_CAMPUS = os.environ.get("WXBOT_HUB_CAMPUS", "malaysia").strip()

OWNER_NAME = os.environ.get("WXBOT_OWNER_NAME", "Waldo")
# The owner's personal WeChat wxid (as MonashGuide sees it). Set: 待答 notes go to him through MonashGuide,
# and in a group he is @-ed instead. Empty: notes go to the ClawBot admins.
OWNER_WXID = os.environ.get("WXBOT_OWNER_WXID", "")

# Monash Hub's list of 马莫百科 posts (copied here by wechat-bot-mamo.service before each sync).
MAMO_TS = os.environ.get("WXBOT_MAMO_TS", str(DATA / "mamo.ts"))
# Where mamo-sync downloads that file and the i18n files from when Monash Hub is not on this machine
# (issue #2): the raw-file root of the Hub's public repository, e.g.
# https://raw.githubusercontent.com/Waldo0926/monash-hub/main . Empty: use the copies already in data/.
HUB_FILES_URL = os.environ.get("WXBOT_HUB_FILES_URL", "").rstrip("/")

# Copies of Monash Hub's frontend/i18n/{index.ts,handbook-terms.ts}, refreshed with mamo.ts, so
# Handbook answers read in the same Chinese as the website.
HUB_I18N_DIR = Path(os.environ.get("WXBOT_HUB_I18N_DIR", str(DATA / "hub-i18n")))

# 公众号 message server (developer mode, plaintext). The token is the one entered in the
# 公众号 backend under 设置与开发 → 基本配置 → 服务器配置.
MP_TOKEN = os.environ.get("WXBOT_MP_TOKEN", "")
MP_PORT = int(os.environ.get("WXBOT_MP_PORT", "8102"))

# 公众号 API (optional). Only used by `python -m wxbot mamo-sync-api`.
MP_APPID = os.environ.get("WXBOT_MP_APPID", "")
MP_SECRET = os.environ.get("WXBOT_MP_SECRET", "")

# Match thresholds (0..1): overlap scores from kb._Index.search.
QA_STRONG = float(os.environ.get("WXBOT_QA_STRONG", "0.6"))
QA_WEAK = float(os.environ.get("WXBOT_QA_WEAK", "0.42"))
QA_NEAR = float(os.environ.get("WXBOT_QA_NEAR", "0.3"))       # 未命中 report: "almost hit" starts here
# A strong match only counts when the next pair is at least this far behind; otherwise "你问的是不是…".
QA_MARGIN = float(os.environ.get("WXBOT_QA_MARGIN", "0.03"))
ARTICLE_MIN = float(os.environ.get("WXBOT_ARTICLE_MIN", "0.5"))
ARTICLE_LEAD = float(os.environ.get("WXBOT_ARTICLE_LEAD", "0.7"))   # above this, articles go before a hub FAQ

# A 公众号 user sees a queued reply with their next message. After this many days it is dropped
# (still in the table, counted in 统计); after OUTBOX_DATED_DAYS it says which day it was written.
OUTBOX_DAYS = float(os.environ.get("WXBOT_OUTBOX_DAYS", "30"))
OUTBOX_DATED_DAYS = 3
# Students' questions are kept this long (issue #10): enough for 未命中 and the weekly digest, which look back
# a week, and for spotting what keeps coming up over a semester. Delivered replies go after OUTBOX_DAYS.
LOG_DAYS = float(os.environ.get("WXBOT_LOG_DAYS", "90"))
# People often send one question as several short messages. Questions the bot cannot answer are sent to
# Waldo once nothing has been added for PENDING_QUIET_S seconds, all in one note; a miss within
# PENDING_MERGE_S of the last one, while it is still open, is added to the same question.
PENDING_QUIET_S = float(os.environ.get("WXBOT_PENDING_QUIET_S", "90"))
PENDING_MERGE_S = float(os.environ.get("WXBOT_PENDING_MERGE_S", "1800"))

# The MonashGuide personal account through jwping/wxbot (container wxbot-wechat). Empty API = off.
# The callback listens on the docker bridge so only the container (and the host) can reach it; the
# secret is the last path segment of the URL registered with wxbot.
PCWX_API = os.environ.get("WXBOT_PCWX_API", "")
PCWX_LISTEN = os.environ.get("WXBOT_PCWX_LISTEN", "172.17.0.1:8112")
PCWX_SECRET = os.environ.get("WXBOT_PCWX_SECRET", "")
# The account's display names; "@<name>" typed by hand (no real mention) also addresses the bot.
PCWX_NAMES = [n.strip() for n in os.environ.get("WXBOT_PCWX_NAMES", "马莫百科,MonashGuide").split(",") if n.strip()]

# Chunk index for the optional RAG mode (wxbot/chunks.py, docs/OPERATIONS.md §10). The vector model runs
# locally on the CPU with onnxruntime (requirements-rag.txt) and downloads once into MODELS_DIR. "off", or
# onnxruntime not installed, leaves the index lexical only: the same jieba + bigram matching as the Q&A.
EMBED_MODEL = os.environ.get("WXBOT_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
MODELS_DIR = Path(os.environ.get("WXBOT_MODELS_DIR", str(DATA / "models")))

# RAG mode (wxbot/rag.py): when the rules find nothing or only a weak match, a chat model answers from the chunks
# above and must cite them. Off unless WXBOT_RAG=1; the rules stay the main path and the fallback. Any
# OpenAI-compatible endpoint works; the default is Zhipu's free glm-4-flash.
RAG = os.environ.get("WXBOT_RAG", "0") == "1"
LLM_BASE = os.environ.get("WXBOT_LLM_BASE", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
LLM_KEY = os.environ.get("WXBOT_LLM_KEY", "")
LLM_MODEL = os.environ.get("WXBOT_LLM_MODEL", "glm-4-flash")
# Extra JSON fields for the request body, for what one provider needs and another rejects, e.g. turning off
# "thinking": {"reasoning_effort": "none"} on Groq's qwen3, {"thinking": {"type": "disabled"}} on GLM-4.7-Flash.
LLM_EXTRA = os.environ.get("WXBOT_LLM_EXTRA", "")
# How long a question with nothing else to answer it may wait for the model. On the 公众号 a wait over 4 s turns
# into "我还在查" and the answer comes with the next message (mp.LATE); a question the rules did answer only waits
# for what is left of the 4 s.
LLM_TIMEOUT = float(os.environ.get("WXBOT_LLM_TIMEOUT", "8"))
RAG_CACHE_DAYS = float(os.environ.get("WXBOT_RAG_CACHE_DAYS", "7"))
