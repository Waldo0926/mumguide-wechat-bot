from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("WXBOT_HOME", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
ACCOUNT_FILE = DATA / "account.json"
DB_FILE = DATA / "kb.sqlite"

HUB_API = os.environ.get("WXBOT_HUB_API", "http://127.0.0.1:8100/api/v1")
HUB_SITE = "https://monashhub.secureview.tech"

OWNER_NAME = os.environ.get("WXBOT_OWNER_NAME", "Waldo")

# Monash Hub's list of 马莫百科 posts (copied here by a scheduled sync job before each sync).
MAMO_TS = os.environ.get("WXBOT_MAMO_TS", str(DATA / "mamo.ts"))

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
ARTICLE_MIN = float(os.environ.get("WXBOT_ARTICLE_MIN", "0.5"))
ARTICLE_LEAD = float(os.environ.get("WXBOT_ARTICLE_LEAD", "0.7"))   # above this, articles go before a hub FAQ
