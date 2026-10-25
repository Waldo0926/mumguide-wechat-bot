# Operations runbook

[中文](OPERATIONS.zh-CN.md) · English

Production is one systemd service on the VPS reached as `ssh mcs21-vps` (the same box as Monash Hub).
Nothing here needs the model-based tooling: every step is a shell command.

## 1. What runs where

| Thing | Where |
|---|---|
| Code, venv | `/opt/wechat-bot/` (root-owned; the service cannot modify its own code) |
| Data | `/opt/wechat-bot/data/` (owner `wxbot`, mode 700): `kb.sqlite`, `account.json` (iLink token, mode 600), `mamo.ts`, `hub-i18n/` |
| Secrets | `/opt/wechat-bot/.env` (root, mode 600; `WXBOT_MP_TOKEN`) |
| Service | `wechat-bot.service`, one process: the `/mp` server on `127.0.0.1:8102` **and** the iLink long-poll loop |
| Sync job | `wechat-bot-mamo.timer` (every 6 h) → `wechat-bot-mamo.service`: copies Monash Hub's `frontend/data/mamo.ts` and `frontend/i18n/{index,handbook-terms}.ts` into `data/` (as root, because `/opt/monash-hub` is not readable by `wxbot`) and indexes new 马莫百科 posts |
| Backup | `wechat-bot-backup.timer` (03:30) → `wechat-bot-backup.service`: `python -m wxbot backup`, a copy of `kb.sqlite` in `data/backups/`, newest 14 kept (§8) |
| nginx | site `wxbot` (`/etc/nginx/sites-available/wxbot`, source `deploy/nginx-wxbot.conf`): only `location = /mp` is proxied; everything else is 404 |
| Certificate | Let's Encrypt via certbot webroot `/var/www/html`, renewed by the existing certbot timer |
| DNS | `wxbot.secureview.tech` A record → the VPS (set at name.com) |
| Monash Hub | `127.0.0.1:8100` (API), checkout `/opt/monash-hub/repo` |

Health: `systemctl is-active wechat-bot`, `journalctl -u wechat-bot -n 50`, and
`cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot status` (JSON: login state,
age of the last iLink poll, counts, pending questions). Normal operation needs no log-watching: problems are
pushed to the owner's ClawBot chat by `wxbot/alerts.py`. When ClawBot cannot deliver (expired login), alerts go to the
owner's own WeChat through MonashGuide, if `WXBOT_OWNER_WXID` is set. Questions that have waited over a day get the
owner one reminder a day ("⏰ 有 N 个问题等了超过一天还没回复") on the same channels.

For a check from outside the box, `GET /health` on the bot (`127.0.0.1:8102/health`) answers 200 while the owner can be
reached and 503 when the ClawBot session expired or its polling stopped for 15 minutes, with counts only
(`last_poll_age_s`, `session_expired`, `pending`). `deploy/nginx-wxbot.conf` has a `location = /health` block that
exposes it as `https://wxbot.secureview.tech/health`; install the updated file and `nginx -t && systemctl reload nginx`,
then point any free uptime monitor, or a cron `curl -fsS` on the home server, at it. Delete the block to keep it local.

## 2. Deploy a change

From a laptop checkout of this repo, with the `mcs21-vps` SSH alias working:

```bash
.venv/bin/python -m pytest -q && ./deploy/push.sh
```

`push.sh` rsyncs the code (excluding `venv/`, `data/`, `.env`), runs `deploy/install.sh` (creates the `wxbot` user and
venv if missing, installs requirements, installs the systemd units) and restarts the service. **Do not rsync by hand
with `--delete`**: that once removed the VPS venv. The iLink update cursor is stored in the database, so a restart
loses no messages.

## 3. First install on a fresh server

1. `rsync` the repo to `/opt/wechat-bot/` and run `sh /opt/wechat-bot/deploy/install.sh` as root.
2. `/opt/wechat-bot/.env` with a random `WXBOT_MP_TOKEN` (see `.env.example`), `chmod 600`.
3. DNS: an A record for the callback host (`wxbot.secureview.tech`) to the server.
4. nginx: install `deploy/nginx-wxbot.conf` as `/etc/nginx/sites-available/wxbot`, symlink into `sites-enabled`.
   Start with only the port-80 `server` block, run
   `certbot certonly --webroot -w /var/www/html -d <host>`, then install the full file and `nginx -t && systemctl reload nginx`.
5. If Monash Hub is on the same box, the sync job works as is. Otherwise set `WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1`
   and `WXBOT_HUB_FILES_URL=https://raw.githubusercontent.com/Waldo0926/monash-hub/main` in `.env`: `mamo-sync` then downloads
   `mamo.ts` and the i18n files from the Hub's repository instead of copying them from `/opt/monash-hub` (§9).
6. `systemctl enable --now wechat-bot-mamo.timer wechat-bot-backup.timer wechat-bot.service`.
7. Log in (§4) and configure the 公众号 (§5).

## 4. iLink (ClawBot) login: first time, and whenever the session expires

Symptoms of an expired session: the owner's chat stops answering; `status` shows `session_expired`; the log says
`iLink session expired`. (The 公众号 side keeps working.)

```bash
ssh mcs21-vps 'systemctl stop wechat-bot-login 2>/dev/null; systemd-run --unit=wechat-bot-login --uid=wxbot --gid=wxbot \
  -p WorkingDirectory=/opt/wechat-bot -E WXBOT_HOME=/opt/wechat-bot \
  /opt/wechat-bot/venv/bin/python -m wxbot login'
scp mcs21-vps:/opt/wechat-bot/data/login-qr.png .     # open it and scan with WeChat on the phone
```

- The QR code lasts about 2 minutes and is refreshed up to 10 times (`journalctl -u wechat-bot-login` shows the status);
  re-copy `login-qr.png` after a refresh.
- **Whoever scans becomes the owner/admin**, so scan with the account that should receive "待答" notes. In WeChat answer
  "接入 OpenClaw: 是" and a chat named "WeChat ClawBot" appears; the bot's iLink identity is `…@im.bot`.
- Accounts outside mainland China are served from `ilinkai.wechat.com`, which sits behind a CDN that ends long polls with
  HTTP 524 after ~15 s. The client treats 524/504 as "no messages yet" (`ilink.EMPTY_POLL_STATUSES`).
- Afterwards: `systemctl restart wechat-bot`.

## 5. 公众号 (official account) setup

微信开发者平台 (developers.weixin.qq.com) → 公众号 → 基础信息 → **域名与消息推送配置 → 消息推送 → 启用**:

| Field | Value |
|---|---|
| URL | `https://wxbot.secureview.tech/mp` |
| Token | the value of `WXBOT_MP_TOKEN` in `/opt/wechat-bot/.env` |
| EncodingAESKey | "random generate" (unused in plaintext mode) |
| Message encryption | **明文模式 (plaintext)**, data format **XML** |

Tencent immediately calls the URL with a signed `GET`; the bot answers it (HTTP 200 with the `echostr`). Notes:

- Enabling the server configuration switches off the backend's own auto-replies, including the welcome message.
  The bot sends the welcome itself: set it from the owner chat with `关注语 <text>`.
- Turn off 位置上报 (users' location is sent on every visit and ignored).
- Unverified personal accounts cannot use the customer-service push API, so replies are passive only (≤ 5 s, ≤ 2048 bytes).
- Changing the token needs the same value in `.env` and the backend, then `systemctl restart wechat-bot`.

## 5b. MonashGuide personal account (group chats)

Students @ the **MonashGuide** WeChat account (nickname 马莫百科) in group chats, or message it privately. It is a
separate small account logged in to PC WeChat 3.9.8.25 inside the unofficial
[jwping/wxbot](https://github.com/jwping/wxbot) Docker image, which hooks the client. **The account can be banned**;
never log the owner's main account in here. The image is closed-source, so it runs isolated with only a loopback port.

| Thing | Value |
|---|---|
| Container | `wxbot-wechat` (`--restart unless-stopped`, volume `wxbot-wechat-home`, 3 GB memory cap) |
| wxbot API | `127.0.0.1:8110` (no auth; it also returns the account's database key - keep it on loopback) |
| Our callback | `http://172.17.0.1:8112/pcwx/<WXBOT_PCWX_SECRET>` on the docker bridge; registered by the bot on start |
| `.env` | `WXBOT_PCWX_API=http://127.0.0.1:8110`, `WXBOT_PCWX_SECRET=<random>` |
| Owner | `WXBOT_OWNER_WXID=<owner's wxid>`: misses in a group @ him there (his reply @-ing the asker is learned); other misses are sent to his WeChat, where admin commands work |

Only group messages that @ the account and private messages are handled; everything else said in a group is dropped
unread. Replies in a group @ the asker; a forwarded question answered with 「答」 goes back to that group.

First run / re-login: `docker run -d --name wxbot-wechat --restart unless-stopped --security-opt seccomp=unconfined
-p 127.0.0.1:8110:8080 -v wxbot-wechat-home:/home/wxbot --memory 3g -e WXBOT_ARGS="-w -b"
registry.cn-shanghai.aliyuncs.com/jwping/wxbot:v1.10.1-9-3.9.8.25`, wait 3-5 min, then
`docker logs --tail 3 wxbot-wechat` shows `Not logged in, please login http://weixin.qq.com/x/...`: turn that URL into a QR
code (`python -c "import qrcode,sys;qrcode.make(sys.argv[1]).save('qr.png')" URL`) and scan it with MonashGuide's phone.
It expires in a few minutes. After a container restart `-b` clicks "log in" and the phone only has to confirm.
Check: `curl -s 127.0.0.1:8110/api/checklogin` → `"status":1`. The bot checks this every 10 minutes and alerts the
owner's ClawBot chat when the account has been logged out for 10 minutes (logged out on the phone, or `wxbot-wechat`
restarted, for example by a Docker restart or prune); `docker restart wxbot-wechat` and confirm on the MonashGuide
phone. It picks the account up again by itself, no bot restart needed. Known risk: Tencent may refuse 3.9.8.25 ("版本太低").

## 6. Everyday administration

All from the owner's ClawBot chat (list: `管理`). Typical flow: a "❓ 待答 #12" note arrives → reply
`答 12 <answer> | <link>` (or just `12 <answer>`; or quote the note and write the answer). The asker sees the answer on their next
message and the pair is stored as a new Q&A; add other ways to ask it with `也问 <id> <phrasing>`. `试 <question>` shows what
a stranger would get and which route produced it.

Once a week (Monday from 09:00 server time) the owner gets "📊 本周小结": the questions nobody answered, each with the
Q&A it almost hit and the `也问` to send, and the questions answered with "你问的是不是…". `未命中 [days]` shows the same
at any time. When students use another word for a taught topic (visa for 签证), `同义词 签证=visa=EMGS` makes them one
word for matching; `同义词` lists the groups and `同义词 删 visa` removes a word. The thresholds (`WXBOT_QA_STRONG`,
`WXBOT_QA_WEAK`, `WXBOT_QA_NEAR`) are checked against the labelled questions in `tests/test_qa_files.py`.

A second admin: send `管理员 配对`, which gives a six-digit code valid for 10 minutes. The new admin sends `配对 <code>`
from their own WeChat, privately to MonashGuide or to the 公众号 (not in a group), and the owner is told who joined. Five wrong
codes void it, and a restart does too. `管理员` lists everyone with a number and `管理员 删 <number>` removes an admin
added this way; the QR scanner and `WXBOT_OWNER_WXID` are fixed. Admins on the 公众号 can use every command but get no
待答 notes or alerts, because a personal 订阅号 cannot push to them; alerts only go to ClawBot (and MonashGuide as fallback).

From the server (e.g. before the owner chat is logged in again). Run them from `/opt/wechat-bot`: `wxbot` is not
installed into the venv, so Python only finds it in that folder ("No module named wxbot" otherwise).

```bash
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot teach "问题" "答案" --url https://...
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot ask "FIT2102学什么"
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot mamo-add https://mp.weixin.qq.com/s/...
```

The running service notices changes made by other processes (SQLite `PRAGMA data_version`), no restart needed.

`qa/mamo-topics.json` holds answers written from the 马莫百科 posts (选课, 缴费, Moodle, 交作业, 报到, Allocate,
交换, 入台证, 续签, 出勤, 毕业, 常用网站) and from monash.edu.my (General Studies / MPU, transport, campus map,
M-Pass, hurdles and supplementary assessment). After `deploy/push.sh` it is on the VPS; import it (again after it gains pairs):

```bash
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot import-qa /opt/wechat-bot/qa/mamo-topics.json
```

Importing again skips pairs already there, but adds any new phrasings the file has for them. When a post changes, edit the answer with `改 <编号>` in ClawBot. If you
edit an answer in the file instead, import with `--replace`: the pair with the same first phrasing gets the new answer
and keeps its number. Without it, an edited pair is imported as a second copy. Phrasings taken out of the file stay
live until you remove them with `不问 <编号> <问法>`.

## 7. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Owner chat silent, `session_expired` in `status` | iLink session expired → §4 |
| `getupdates HTTP 524` in the log | normal on the international host; handled as an empty poll. Only a problem if it also says `ret=`/`errcode` |
| `hub GET /units failed after 0.4s: TimeoutError` at INFO | one Hub call ran out of reply time; three timeouts in a row alert as "连不上 Monash Hub" |
| `poll error (1/3)` or `(2/3)` with HTTP 522 | the CDN dropped one poll; the retry fixes it, so it is logged at INFO. Three in a row (`3/3`) alerts the owner |
| Followers get no reply at all | `systemctl status wechat-bot`; nginx/cert (`curl -I https://wxbot.secureview.tech/mp` should be 403 for an unsigned request); token mismatch → `bad signature` warnings |
| "我还在查，稍等几秒再发一次" | the answer took > 4 s (usually Monash Hub slow); WeChat gives up at 5 s. The retry usually hits the finished answer |
| Handbook answers in English | `data/hub-i18n/*.ts` missing/stale → `systemctl start wechat-bot-mamo.service` and check it succeeded |
| New 马莫百科 post not found | wait for the 6-hour timer or `mamo-add <link>`; the post must be listed in Monash Hub's `mamo.ts` for the timer to see it |
| `FIT…` "不在 2027 Handbook" shown with a 2026 answer | intended: the unit was dropped from the default year. Students can ask for a year themselves ("FIT2102 2026"); to answer from this year's Handbook by default until the new year, set `WXBOT_HUB_YEAR=2026` in `.env` and restart |
| A question was forwarded though Monash Hub was down | fixed: the asker now gets "查询服务暂时连不上" and nothing is forwarded |

## 8. Backups, retention, end of life

- **Nightly backup.** `wechat-bot-backup.timer` (03:30) runs `python -m wxbot backup`, which writes a consistent copy
  (SQLite online backup) to `data/backups/kb-YYYYmmdd-HHMMSS.sqlite` and keeps the newest 14. Enable it once with
  `systemctl enable --now wechat-bot-backup.timer`. These copies are on the same disk: add `/opt/wechat-bot/data/backups`
  to the off-site / j1900 pull.
- **Restore:** `systemctl stop wechat-bot`, copy the chosen `kb-*.sqlite` over `data/kb.sqlite` (owner `wxbot`, delete
  `kb.sqlite-wal` and `kb.sqlite-shm` first), `systemctl start wechat-bot`.
- **Taught answers on their own:** `python -m wxbot export-qa > qa.json` writes every Q&A with its phrasings, answer and
  link, and nothing about users; `python -m wxbot import-qa qa.json` adds them to another database (pairs already there
  only get their missing phrasings). Handy for review, or for moving to a new server.
- Undelivered 公众号 replies older than `WXBOT_OUTBOX_DAYS` (30) are no longer shown; `统计` counts them.
- **Retention**. Once a day the bot deletes questions
  in `log`, closed 待答 questions and undelivered replies older than `WXBOT_LOG_DAYS` (90), and delivered replies older
  than `WXBOT_OUTBOX_DAYS` (30). `python -m wxbot purge` does the same at once. Taught Q&A, open 待答 questions and
  contacts are kept. The database runs with `secure_delete`, so deleted text is overwritten in the file; the nightly
  backups still hold it until they rotate out (14 days).
- **Deleting one person.** A user sends `删除我的数据` and everything stored under their id goes (questions, 待答,
  queued replies, contact row); the request itself is not logged. When someone asks the owner instead, `删数据 <待答编号>`
  does it for the person who asked that question. Q&A taught from their question stay.
- The VPS is paid until about February 2027; the move is planned in §9.

## 9. Moving to another host (before the VPS expires, about 2027-02)

Everything the bot needs is in `/opt/wechat-bot` plus one Docker volume, so the move is a copy and a DNS change. What is
specific to this VPS and how each part moves:

| On the VPS today | On the new host |
|---|---|
| Code and venv in `/opt/wechat-bot` | `rsync` the repo (as `push.sh` does, but to the new alias) and run `deploy/install.sh` |
| `data/kb.sqlite`, `data/account.json`, `data/hub-i18n/`, `data/mamo.ts` | copy `data/` as user `wxbot` (mode 700); take the database from a fresh `python -m wxbot backup` file, never the live file |
| `.env` | copy, then set `WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1` and `WXBOT_HUB_FILES_URL=https://raw.githubusercontent.com/Waldo0926/monash-hub/main` unless Monash Hub moves to the same machine |
| Monash Hub next door (`127.0.0.1:8100`, `/opt/monash-hub/repo`) | the public API; `mamo-sync` downloads the post list and the Chinese from the Hub's repository (the `install` steps in `wechat-bot-mamo.service` are allowed to fail) |
| nginx + Let's Encrypt on a public IP | a public IP again (same nginx file, new certificate), or a tunnel when the host is behind a home connection (below) |
| `wxbot-wechat` container (MonashGuide's PC WeChat, volume `wxbot-wechat-home`) | `docker run` the same image (§5b) and either copy the volume (`docker run --rm -v wxbot-wechat-home:/from -v $PWD:/to alpine tar czf /to/home.tgz -C /from .`) or log in again by QR; it needs about 3 GB of RAM on its own |
| Timers and nginx reload by root | `systemctl enable --now wechat-bot-mamo.timer wechat-bot-backup.timer wechat-bot.service` |

**Where to.** Two choices, both without new spending:

- **j1900 at home** (Debian, 3.7 GB RAM, dynamic IP). The bot alone needs under 200 MB; the MonashGuide container needs
  up to 3 GB, so run it there only if nothing else large runs, or skip the group-chat channel. The 公众号 callback needs a
  stable HTTPS URL, which a free **Cloudflare Tunnel** gives a host behind NAT: `cloudflared` runs on j1900, the hostname
  `wxbot.secureview.tech` is routed to `http://127.0.0.1:80` (keep nginx in front with only the `/mp` and `/health`
  locations; the tunnel terminates TLS, so the port-80 server block with those two locations is enough and certbot is not
  needed). The DNS zone `secureview.tech` must be on Cloudflare for that (free plan, change the nameservers at name.com;
  other records such as `monashhub` are imported as they are and can stay "DNS only").
- **Another small VPS**, if one is available anyway: the same steps as §3, nothing else changes.

If Monash Hub moves to the same machine, keep `WXBOT_HUB_API` local and leave `WXBOT_HUB_FILES_URL` empty; the sync job then
copies from the checkout as it does now.

**Order of the cutover.** The old host keeps running until the last step, so every step can be undone by pointing DNS back.

1. Prepare the new host completely (install, `.env`, nginx or tunnel, timers) with a copy of yesterday's backup, and test
   from the host itself: `python -m wxbot ask "FIT2102学什么"`, `curl -s 127.0.0.1:8102/health`, and the mamo sync
   (`systemctl start wechat-bot-mamo.service`; `data/hub-i18n/` must be filled).
2. On the old host: `systemctl stop wechat-bot` (two bots must not poll iLink with the same cursor), run
   `python -m wxbot backup`, and copy the new backup file, `account.json` and `.env` across.
3. Restore the backup on the new host (§8) and `systemctl start wechat-bot`. `python -m wxbot status` must show the login and,
   within a minute, a recent poll; `journalctl -u wechat-bot` must not say `session expired` (if it does, scan again, §4).
4. Switch DNS (the A record, or the tunnel route) for `wxbot.secureview.tech`. The 公众号 backend keeps the same URL and
   token, so nothing changes there; send the account a message and expect the reply from the new host.
5. Move or re-login MonashGuide (§5b) and check `docker logs` and a group @.
6. Watch `/health` and the alerts for a day, then shut the old host down. The off-site backup pull (§8) must point at the
   new host.

## 10. Chunk index for the RAG mode (optional)

The index is what the optional RAG mode will read: taught Q&A, 马莫百科 articles, and Monash Hub's Chinese guide pages
and FAQ, cut into passages of up to 500 characters (`chunk` table in `kb.sqlite`). Without these steps the bot
behaves exactly as before.

1. Add `WXBOT_RAG=0` to `/opt/wechat-bot/.env`. Any `WXBOT_RAG` line makes `deploy/install.sh` install
   `requirements-rag.txt` (onnxruntime, tokenizers and numpy, CPU only, no PyTorch), so deploy once more with `./deploy/push.sh`.
2. Build it once (the first run downloads the vector model, about 90 MB, into `data/models/`, and fetches every Chinese
   guide page from the Hub; a few minutes):
   ```bash
   cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot index
   ```
3. Check what a question finds: `... -m wxbot search "学生签证怎么续签"` prints the top 5 with the word score (`lex`),
   the cosine (`cos`) and the fused score.

After the first build it stays current on its own: `mamo-sync` (every 6 hours) and `import-qa` update it, and only
changed passages are embedded again. Hub pages are fetched again only when their `last_changed` moved;
`index --full` fetches them all. Q&A taught from WeChat (`教`, `改`) are picked up by the next sync. Without onnxruntime,
or with `WXBOT_EMBED_MODEL=off`, the index works on word overlap alone. Hub pages with no Chinese, and English lines
inside a page, are left out, for the same reason the bot never pastes English Handbook prose.

The model needs about 300 MB of memory while it runs. To remove everything: delete `data/models/`, take `WXBOT_RAG`
out of `.env`, and run `DELETE FROM chunk` in Python (the `sqlite3` CLI is not installed).

**Trying and turning on the RAG answer.** Put the model settings in `.env` (`WXBOT_LLM_KEY`, and `WXBOT_LLM_BASE`,
`WXBOT_LLM_MODEL`, `WXBOT_LLM_EXTRA` for anything but Zhipu's glm-4-flash; see `.env.example`). The `wxbot` user cannot
read `.env` (root, 600), so a command that needs the key runs through systemd, which reads the file for it:

```bash
systemd-run --quiet --pipe --wait --uid=wxbot --gid=wxbot -p WorkingDirectory=/opt/wechat-bot \
  -p EnvironmentFile=/opt/wechat-bot/.env -E WXBOT_HOME=/opt/wechat-bot \
  /opt/wechat-bot/venv/bin/python -m wxbot ask --rag "学生签证怎么续签"
```

`ask --rag` tries the RAG answer while `WXBOT_RAG` is still `0`, and prints the route (`rag`) with the chunk ids, the
tokens and the time. Once the evaluation ([docs/EVAL.md](EVAL.md)) looks right, set `WXBOT_RAG=1` and
`systemctl restart wechat-bot`; the log says `rag: on, model …`. The `log` table then has `route='rag'` rows, and a
rules answer that the RAG answer could not improve says why in `detail` (`| rag … timeout`, `uncited` (no quote
lines), `unsure`, `unsupported` (no quote found in its passage), `fragment` (quotes found, but none
reads right without what is around it), `error`, `no chunks`; `ok cut N` means N quotes were
left out, and the log has them with the reason). If it times out often or answers badly, set `WXBOT_RAG=0` and restart: the rules are not touched.

**Evaluating.** `eval` runs `eval/questions.jsonl` through the rules (`--mode rule`) or the rules plus the RAG answer
(`--mode rag`, any `--model`; the cache is off so every question calls the model; `--gap 15` waits after each call,
so that a free tier's tokens-per-minute limit does not turn the run into 429 errors), with the same 4 s budget as the
公众号. `--judge` marks each answer 0/1 against its expected points with a fixed judge (`WXBOT_JUDGE_MODEL`, default
glm-4-flash, and `WXBOT_JUDGE_BASE` / `WXBOT_JUDGE_KEY`, defaulting to the `WXBOT_LLM_*` ones), so runs with different
models are comparable. Every run is kept in `data/eval/results.json` under its `--name`, and the report with all runs is
written to `data/eval/EVAL.md` (the `wxbot` user cannot write `docs/`). Run it through `systemd-run` as above, e.g.
`... -m wxbot eval --mode rag --judge`, then copy the report into the repository from the laptop:
`scp mcs21-vps:/opt/wechat-bot/data/eval/EVAL.md docs/EVAL.md`. To try another provider for one run, put its three
`WXBOT_LLM_*` lines in a root-only file (say `/root/groq.env`, mode 600) and add `-p EnvironmentFile=/root/groq.env`
after the first one: the later file wins, `.env` stays as it is, and the key is not on the command line.
Human labels go in `eval/labels.jsonl` (`{"id": "q01", "run": "rag glm-4-flash", "correct": 1}` per line); the report
then shows how often the judge agrees.

The question text goes to the model's provider (no user id). Answers are cached in `rag_cache` by a hash of the question
for `WXBOT_RAG_CACHE_DAYS` (7); a call that ran past the reply still finishes in the background and fills the cache.
