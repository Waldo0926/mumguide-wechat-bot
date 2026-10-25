# 运维手册

中文 · [English](OPERATIONS.md)

线上是 VPS 上的一个 systemd 服务，用 `ssh mcs21-vps` 登录（和 Monash Hub 同一台）。所有步骤都是普通 shell 命令。

## 1. 什么东西在哪

| 内容 | 位置 |
|---|---|
| 代码、venv | `/opt/wechat-bot/`（root 所有，服务本身改不了自己的代码） |
| 数据 | `/opt/wechat-bot/data/`（属主 `wxbot`，权限 700）：`kb.sqlite`、`account.json`（iLink 令牌，权限 600）、`mamo.ts`、`hub-i18n/` |
| 密钥 | `/opt/wechat-bot/.env`（root，权限 600；`WXBOT_MP_TOKEN`） |
| 服务 | `wechat-bot.service`：一个进程，同时跑 `127.0.0.1:8102` 上的 `/mp` 服务**和** iLink 长轮询 |
| 同步任务 | `wechat-bot-mamo.timer`（每 6 小时）→ `wechat-bot-mamo.service`：把 Monash Hub 的 `frontend/data/mamo.ts` 和 `frontend/i18n/{index,handbook-terms}.ts` 复制到 `data/`（用 root 身份，因为 `wxbot` 读不了 `/opt/monash-hub`），并收录新的马莫百科文章 |
| 备份 | `wechat-bot-backup.timer`（03:30）→ `wechat-bot-backup.service`：`python -m wxbot backup`，把 `kb.sqlite` 备份到 `data/backups/`，保留最新 14 份（见第 8 节） |
| nginx | 站点 `wxbot`（`/etc/nginx/sites-available/wxbot`，源文件 `deploy/nginx-wxbot.conf`）：只转发 `location = /mp`，其余一律 404 |
| 证书 | Let's Encrypt，certbot webroot `/var/www/html`，由现有 certbot 定时器续期 |
| DNS | `wxbot.secureview.tech` 的 A 记录指向 VPS（在 name.com 设置） |
| Monash Hub | `127.0.0.1:8100`（API），代码目录 `/opt/monash-hub/repo` |

健康检查：`systemctl is-active wechat-bot`、`journalctl -u wechat-bot -n 50`，以及 `cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot status`（JSON：登录状态、最近一次 iLink 轮询距今多久、各类计数、待答数）。平时不需要盯日志：出问题时 `wxbot/alerts.py` 会把提醒推到作者的 ClawBot 对话。ClawBot 自己发不出去时（比如登录过期），如果配置了 `WXBOT_OWNER_WXID`，提醒会通过 MonashGuide 发到作者自己的微信。等了超过一天没回的待答问题，每天在同样的渠道提醒作者一次（"⏰ 有 N 个问题等了超过一天还没回复"）。

要从机器外面检查，机器人有 `GET /health`（`127.0.0.1:8102/health`）：作者能收到消息时回 200，ClawBot 登录过期或 15 分钟没轮询时回 503，只给计数（`last_poll_age_s`、`session_expired`、`pending`）。`deploy/nginx-wxbot.conf` 里有一段 `location = /health`，把它暴露成 `https://wxbot.secureview.tech/health`；装上新的配置文件后 `nginx -t && systemctl reload nginx`，再让任何免费的网站监控、或者家里服务器上的 cron `curl -fsS` 去访问它。不想暴露就删掉那一段。

## 2. 部署改动

在本机的仓库里，确认 `mcs21-vps` 这个 SSH 别名可用：

```bash
.venv/bin/python -m pytest -q && ./deploy/push.sh
```

`push.sh` 会 rsync 代码（排除 `venv/`、`data/`、`.env`），运行 `deploy/install.sh`（没有就创建 `wxbot` 用户和 venv、安装依赖和 systemd 单元），然后重启服务。**不要手写带 `--delete` 的 rsync**：曾经因此删掉过 VPS 上的 venv。iLink 的更新游标存在数据库里，所以重启不会丢消息。

## 3. 在新服务器上首次安装

1. 把仓库 `rsync` 到 `/opt/wechat-bot/`，用 root 运行 `sh /opt/wechat-bot/deploy/install.sh`。
2. 写 `/opt/wechat-bot/.env`，放一个随机的 `WXBOT_MP_TOKEN`（见 `.env.example`），`chmod 600`。
3. DNS：给回调域名（`wxbot.secureview.tech`）加指向服务器的 A 记录。
4. nginx：把 `deploy/nginx-wxbot.conf` 装成 `/etc/nginx/sites-available/wxbot`，软链到 `sites-enabled`。先只放 80 端口那个 `server` 块，运行 `certbot certonly --webroot -w /var/www/html -d <域名>`，再换成完整文件，`nginx -t && systemctl reload nginx`。
5. Monash Hub 在同一台机器上时，同步任务原样可用；否则在 `.env` 里设 `WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1` 和 `WXBOT_HUB_FILES_URL=https://raw.githubusercontent.com/Waldo0926/monash-hub/main`，`mamo-sync` 就会从 Hub 的仓库下载 `mamo.ts` 和中文文件，不再从 `/opt/monash-hub` 复制（见第 9 节）。
6. `systemctl enable --now wechat-bot-mamo.timer wechat-bot-backup.timer wechat-bot.service`。
7. 登录（§4）并配置公众号（§5）。

## 4. iLink（ClawBot）登录：首次，以及会话过期时

会话过期的表现：作者的对话不再回复；`status` 里有 `session_expired`；日志里有 `iLink session expired`。（公众号这一边照常工作。）

```bash
ssh mcs21-vps 'systemctl stop wechat-bot-login 2>/dev/null; systemd-run --unit=wechat-bot-login --uid=wxbot --gid=wxbot \
  -p WorkingDirectory=/opt/wechat-bot -E WXBOT_HOME=/opt/wechat-bot \
  /opt/wechat-bot/venv/bin/python -m wxbot login'
scp mcs21-vps:/opt/wechat-bot/data/login-qr.png .     # 打开图片，用手机微信扫码
```

- 二维码约 2 分钟有效，最多自动刷新 10 次（`journalctl -u wechat-bot-login` 能看到状态）；刷新后要重新拷一次 `login-qr.png`。
- **谁扫码，谁就是管理员**，所以请用应该收到"待答"通知的那个微信扫。手机上提示"是否接入 OpenClaw"选"是"，就会出现一个叫「WeChat ClawBot」的对话；机器人的 iLink 身份是 `…@im.bot`。
- 中国大陆以外的账号会被分到 `ilinkai.wechat.com`，它前面的 CDN 在约 15 秒后用 HTTP 524 断开长轮询。客户端把 524/504 当作"暂时没有消息"（`ilink.EMPTY_POLL_STATUSES`）。
- 登录完成后：`systemctl restart wechat-bot`。

## 5. 公众号设置

微信开发者平台（developers.weixin.qq.com）→ 公众号 → 基础信息 → **域名与消息推送配置 → 消息推送 → 启用**：

| 字段 | 值 |
|---|---|
| URL | `https://wxbot.secureview.tech/mp` |
| Token | `/opt/wechat-bot/.env` 里 `WXBOT_MP_TOKEN` 的值 |
| EncodingAESKey | 点"随机生成"（明文模式用不到） |
| 消息加解密方式 | **明文模式**，数据格式 **XML** |

腾讯会立刻用带签名的 `GET` 请求这个地址，机器人返回 200 和 `echostr` 即通过。注意：

- 启用服务器配置后，后台自己的自动回复（包括关注欢迎语）全部失效。欢迎语由机器人发：在作者对话里用 `关注语 <内容>` 设置。
- 关掉"位置上报"（用户每次进入公众号都会上报位置，机器人忽略它）。
- 未认证的个人公众号不能用客服消息主动推送，所以只能被动回复（5 秒内、2048 字节内）。
- 改 Token 时，`.env` 和后台要同时改成同一个值，然后 `systemctl restart wechat-bot`。

## 5b. MonashGuide 个人号（群聊）

同学在群里 @ **MonashGuide**（昵称 马莫百科），或者私聊它提问。它是一个单独的小号，登录在非官方项目 [jwping/wxbot](https://github.com/jwping/wxbot) 的 Docker 镜像里（Wine 跑 PC 微信 3.9.8.25 并挂钩子）。**这个号有被封的风险**，绝不要把主号登进来。镜像不开源，所以只开本机端口、隔离运行。

| 项目 | 值 |
|---|---|
| 容器 | `wxbot-wechat`（`--restart unless-stopped`，数据卷 `wxbot-wechat-home`，内存上限 3 GB） |
| wxbot 接口 | `127.0.0.1:8110`（无鉴权，还会返回数据库密钥，只能留在本机） |
| 我们的回调 | docker 网桥上的 `http://172.17.0.1:8112/pcwx/<WXBOT_PCWX_SECRET>`，机器人启动时自动注册 |
| `.env` | `WXBOT_PCWX_API=http://127.0.0.1:8110`、`WXBOT_PCWX_SECRET=<随机串>` |
| 作者 | `WXBOT_OWNER_WXID=<作者的 wxid>`：群里答不上来就在群里 @ 他（他 @ 提问人的回复会被记住）；其他答不上来的发到他的微信，在那里能用管理命令 |

只处理群里 @ 它的消息和私聊；群里其他聊天直接丢弃，不读不存。群里回复会 @ 提问人；转人工的问题用「答」回复后，会发回原来的群。

首次运行 / 重新登录：用上面英文版里的 `docker run` 命令，等 3–5 分钟，`docker logs --tail 3 wxbot-wechat` 会出现 `Not logged in, please login http://weixin.qq.com/x/...`，把链接转成二维码，用 MonashGuide 的手机扫码，几分钟内有效。容器重启后 `-b` 会自动点登录，手机上确认即可。检查：`curl -s 127.0.0.1:8110/api/checklogin` 返回 `"status":1`。机器人每 10 分钟检查一次，小号掉线超过 10 分钟（手机上退出了，或者 `wxbot-wechat` 被重启过，比如重启 Docker、跑 `docker system prune`）会推送提醒到作者的 ClawBot。处理办法：`docker restart wxbot-wechat`，再用 MonashGuide 的手机确认登录。登录上以后机器人会自动接上，不用重启。已知风险：腾讯可能拒绝 3.9.8.25（"版本太低"）。

## 6. 日常管理

都在作者的 ClawBot 对话里做（命令列表：发 `管理`）。典型流程：收到"❓ 待答 #12"→ 回复 `答 12 <答案> | <链接>`（或直接 `12 <答案>`；或引用那条通知，直接写答案）。提问人下次发消息时会看到答案，这组问答也存成新的问答；想让它认更多问法，用 `也问 <编号> <问法>`。`试 <问题>` 会显示陌生人会收到什么，以及是哪个来源给的答案。

每周一 09:00（服务器时间）以后作者会收到一条"📊 本周小结"：这周没人答上的问题，每条附差一点命中的问答和可以直接发的 `也问`，以及回了"你问的是不是…"的问题。随时发 `未命中 [天数]` 也能看。同学换了个词问教过的内容时（签证说成 visa），用 `同义词 签证=visa=EMGS` 把它们算成一个词；`同义词` 查看，`同义词 删 visa` 移除一个词。阈值（`WXBOT_QA_STRONG`、`WXBOT_QA_WEAK`、`WXBOT_QA_NEAR`）用 `tests/test_qa_files.py` 里标注好的问题核对。

加第二个管理员：发 `管理员 配对`，会得到一个 10 分钟内有效的六位配对码。新管理员用自己的微信私聊 MonashGuide 或者给公众号发 `配对 <配对码>`（群里不行），作者会收到是谁加入了。连续输错 5 次或者机器人重启，配对码就作废。`管理员` 列出所有管理员和序号，`管理员 删 <序号>` 删掉配对加入的管理员；扫码的主人和 `WXBOT_OWNER_WXID` 删不了。公众号上的管理员所有命令都能用，但收不到待答通知和告警，因为个人订阅号没法主动推送；告警只发 ClawBot（备用是 MonashGuide）。

在服务器上（比如作者对话还没重新登录时）。要在 `/opt/wechat-bot` 目录里运行：`wxbot` 没有装进 venv，只有在这个目录下 Python 才找得到它，否则会报 "No module named wxbot"。

```bash
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot teach "问题" "答案" --url https://...
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot ask "FIT2102学什么"
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot mamo-add https://mp.weixin.qq.com/s/...
```

运行中的服务能发现其他进程对数据库的修改（SQLite `PRAGMA data_version`），不用重启。

`qa/mamo-topics.json` 是根据马莫百科推文写的问答（选课、缴费、Moodle、交作业、报到、Allocate、交换、入台证、续签、出勤、毕业、常用网站），以及根据马莫官网写的问答（通识课 MPU、交通、校园地图、M-Pass 学生卡、hurdle、补考）。`deploy/push.sh` 之后它就在 VPS 上了，导入一次（文件加了新问答后再导一次）：

```bash
cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot import-qa /opt/wechat-bot/qa/mamo-topics.json
```

再导一次会跳过已有的问答，但文件里给它们新加的问法会补进去。推文更新后，在 ClawBot 里用 `改 <编号>` 改答案；如果改的是文件里的答案，导入时加 `--replace`，第一个问法相同的那组会换成新答案，编号不变。不加的话改过的会多导入一份。从文件里删掉的问法不会自动下线，用 `不问 <编号> <问法>` 去掉。

## 7. 故障排查

| 现象 | 可能原因 / 处理 |
|---|---|
| 作者对话没反应，`status` 里有 `session_expired` | iLink 会话过期 → §4 |
| 日志里有 `getupdates HTTP 524` | 国际节点上的正常现象，已按空轮询处理；只有同时出现 `ret=`/`errcode` 才是问题 |
| 日志里有普通级别的 `hub GET /units failed after 0.4s: TimeoutError` | 一次 Hub 调用超出了回复时间；连续 3 次超时才会提醒"连不上 Monash Hub" |
| 日志里有 HTTP 522 的 `poll error (1/3)` 或 `(2/3)` | CDN 丢了一次轮询，重试就好，只记普通日志；连续 3 次（`3/3`）才会提醒作者 |
| 关注者完全收不到回复 | `systemctl status wechat-bot`；nginx/证书（不带签名 `curl -I https://wxbot.secureview.tech/mp` 应为 403）；Token 不一致会有 `bad signature` 警告 |
| 回复"我还在查，稍等几秒再发一次" | 回答用了超过 4 秒（通常是 Monash Hub 慢）；微信 5 秒就放弃。重发通常能拿到已算好的答案 |
| Handbook 回答是英文 | `data/hub-i18n/*.ts` 缺失或过期 → `systemctl start wechat-bot-mamo.service` 并确认成功 |
| 新发的马莫百科文章搜不到 | 等 6 小时的定时器，或 `mamo-add <链接>`；定时器只会看到已列在 Monash Hub `mamo.ts` 里的文章 |
| "FIT… 不在 2027 Handbook" 但给了 2026 的答案 | 符合设计：默认年份已撤下这门课。同学可以自己指定年份（"FIT2102 2026"）；想在新学年开始前默认按今年的 Handbook 回答，在 `.env` 里设 `WXBOT_HUB_YEAR=2026` 并重启 |
| Monash Hub 挂了时问题被转给了作者 | 已修复：现在只提示对方稍后再问，不转人工 |

## 8. 备份、数据保留、到期

- **每晚备份。** `wechat-bot-backup.timer`（03:30）运行 `python -m wxbot backup`，用 SQLite 在线备份把一致的副本写到 `data/backups/kb-YYYYmmdd-HHMMSS.sqlite`，保留最新 14 份。首次启用：`systemctl enable --now wechat-bot-backup.timer`。这些副本和原文件在同一块盘上，还要把 `/opt/wechat-bot/data/backups` 加进异地备份或 j1900 的拉取。
- **恢复：** `systemctl stop wechat-bot`，先删掉 `kb.sqlite-wal` 和 `kb.sqlite-shm`，再用选好的 `kb-*.sqlite` 覆盖 `data/kb.sqlite`（属主 `wxbot`），然后 `systemctl start wechat-bot`。
- **单独导出教过的问答：** `python -m wxbot export-qa > qa.json` 导出所有问答（问法、答案、链接），不含任何用户信息；`python -m wxbot import-qa qa.json` 导入到另一个数据库（已有的问答只补上缺的问法）。适合审阅，或者迁移服务器。
- 超过 `WXBOT_OUTBOX_DAYS`（30）天还没送出的公众号回复不再显示，`统计` 里会显示条数。
- **数据保留**。机器人每天删一次：`log` 里超过 `WXBOT_LOG_DAYS`（90）天的提问、已处理的待答和没送出的回复，以及送出超过 `WXBOT_OUTBOX_DAYS`（30）天的回复。`python -m wxbot purge` 可以立刻删一次。教过的问答、还没处理的待答和联系人不删。数据库开了 `secure_delete`，删掉的内容在文件里会被覆盖；每晚的备份里还有，等 14 天后轮换掉。
- **删除某个人的数据。** 用户发「删除我的数据」，他的提问、待答、待发回复和联系人记录全部删除，这条请求本身也不记录。如果是找作者要求删除，用 `删数据 <待答编号>` 删掉提这个问题的人的数据。用他的问题教出来的问答保留。
- VPS 大约付费到 2027 年 2 月，迁移计划见第 9 节。

## 9. 迁到别的机器（VPS 大约 2027 年 2 月到期之前）

机器人需要的东西都在 `/opt/wechat-bot` 里，外加一个 Docker 卷，所以迁移就是复制加改 DNS。这台 VPS 上每样东西怎么搬：

| 现在在 VPS 上 | 到新机器上 |
|---|---|
| 代码和 venv，`/opt/wechat-bot` | 像 `push.sh` 那样 `rsync` 仓库（换成新机器的别名），然后跑 `deploy/install.sh` |
| `data/kb.sqlite`、`data/account.json`、`data/hub-i18n/`、`data/mamo.ts` | 以 `wxbot` 用户复制 `data/`（权限 700）；数据库用刚跑的 `python -m wxbot backup` 生成的文件，不要直接拷正在用的那个 |
| `.env` | 复制过去，然后加 `WXBOT_HUB_API=https://monashhub.secureview.tech/api/v1` 和 `WXBOT_HUB_FILES_URL=https://raw.githubusercontent.com/Waldo0926/monash-hub/main`（Monash Hub 也搬到同一台机器时不用改） |
| 隔壁的 Monash Hub（`127.0.0.1:8100`，`/opt/monash-hub/repo`） | 走公网 API；`mamo-sync` 从 Hub 的仓库下载推文列表和中文文件（`wechat-bot-mamo.service` 里的 `install` 步骤允许失败） |
| nginx + Let's Encrypt，有公网 IP | 还是公网 IP 的话同一份 nginx 配置、重新签证书；家里没有公网 IP 就走隧道（见下） |
| `wxbot-wechat` 容器（MonashGuide 的 PC 微信，卷 `wxbot-wechat-home`） | 用同一个镜像 `docker run`（第 5b 节），卷可以复制（`docker run --rm -v wxbot-wechat-home:/from -v $PWD:/to alpine tar czf /to/home.tgz -C /from .`），也可以重新扫码登录；它自己要约 3 GB 内存 |
| 定时器和 root 的 nginx reload | `systemctl enable --now wechat-bot-mamo.timer wechat-bot-backup.timer wechat-bot.service` |

**搬到哪。** 两种选择，都不用新花钱：

- **家里的 j1900**（Debian，3.7 GB 内存，动态 IP）。机器人本身不到 200 MB 内存；MonashGuide 容器要到 3 GB，所以只有机器上没别的大东西时才放它，不然就不要群聊这一路。公众号回调需要一个固定的 HTTPS 地址，没有公网 IP 的机器可以用免费的 **Cloudflare Tunnel**：j1900 上跑 `cloudflared`，把 `wxbot.secureview.tech` 指到 `http://127.0.0.1:80`（前面仍然放 nginx，只开 `/mp` 和 `/health` 两个 location；TLS 由隧道终结，所以只要 80 端口那个 server 块加这两个 location 就够了，不需要 certbot）。前提是 `secureview.tech` 这个域的 DNS 放到 Cloudflare（免费套餐，在 name.com 改 nameserver；`monashhub` 等其他记录原样导入，可以保持"仅 DNS"）。
- **另一台小 VPS**，如果反正有的话：按第 3 节的步骤装，别的都不变。

Monash Hub 也搬到同一台机器的话，`WXBOT_HUB_API` 保持本机地址，`WXBOT_HUB_FILES_URL` 留空，同步任务还是像现在一样从代码目录复制。

**切换顺序。** 旧机器一直跑到最后一步，所以每一步都能靠把 DNS 指回去来撤销。

1. 把新机器完整准备好（安装、`.env`、nginx 或隧道、定时器），用昨天的备份先跑起来，在机器上自测：`python -m wxbot ask "FIT2102学什么"`、`curl -s 127.0.0.1:8102/health`，以及同步任务（`systemctl start wechat-bot-mamo.service`，`data/hub-i18n/` 要有文件）。
2. 旧机器上 `systemctl stop wechat-bot`（两个机器人不能用同一个游标去轮询 iLink），跑 `python -m wxbot backup`，把新的备份文件、`account.json` 和 `.env` 拷过去。
3. 在新机器上恢复备份（第 8 节），`systemctl start wechat-bot`。`python -m wxbot status` 要显示已登录，一分钟内要有新的轮询；`journalctl -u wechat-bot` 不能出现 `session expired`（出现就重新扫码，第 4 节）。
4. 把 `wxbot.secureview.tech` 的 DNS（A 记录或隧道路由）切过去。公众号后台的 URL 和 Token 都不变，不用动；给公众号发条消息，回复应该来自新机器。
5. 搬或者重新登录 MonashGuide（第 5b 节），看 `docker logs` 和群里 @ 一下。
6. 看一天 `/health` 和提醒，没问题就关掉旧机器。异地备份的拉取（第 8 节）要改指向新机器。

## 10. RAG 模式的片段索引（可选）

可选的 RAG 模式会读这个索引：教过的问答、马莫百科推文、Monash Hub 的中文指南页和 FAQ，切成最多 500 字的片段（`kb.sqlite` 里的 `chunk` 表）。不做下面这几步，机器人和以前完全一样。

1. 在 `/opt/wechat-bot/.env` 里加一行 `WXBOT_RAG=0`。只要有 `WXBOT_RAG` 这一行，`deploy/install.sh` 就会装 `requirements-rag.txt`（onnxruntime、tokenizers 和 numpy，只用 CPU，不装 PyTorch），所以再用 `./deploy/push.sh` 部署一次。
2. 建一次索引（第一次会把向量模型下载到 `data/models/`，大约 90 MB，并从 Hub 取所有中文指南页，要几分钟）：
   ```bash
   cd /opt/wechat-bot && sudo -u wxbot WXBOT_HOME=/opt/wechat-bot venv/bin/python -m wxbot index
   ```
3. 看一个问题能找到什么：`... -m wxbot search "学生签证怎么续签"` 打印前 5 条，带词语分数（`lex`）、余弦相似度（`cos`）和融合后的分数。

建过一次以后它会自己保持更新：`mamo-sync`（每 6 小时）和 `import-qa` 都会更新索引，只有变了的片段才重新算向量。Hub 的页面只有 `last_changed` 变了才重新取，`index --full` 全部重取。在微信里 `教`、`改` 的问答，下一次同步时进索引。没装 onnxruntime 或设置 `WXBOT_EMBED_MODEL=off` 时，索引只用词语重叠。Hub 上没有中文的页面、页面里的英文句子都不收，和机器人从不贴英文 Handbook 段落是同一个原因。

模型运行时大约占 300 MB 内存。要全部去掉：删掉 `data/models/`，从 `.env` 里去掉 `WXBOT_RAG`，再用 Python 执行 `DELETE FROM chunk`（VPS 上没装 `sqlite3` 命令）。

**试用和打开 RAG 回答。** 把模型配置写进 `.env`（`WXBOT_LLM_KEY`；不用智谱 glm-4-flash 时还有 `WXBOT_LLM_BASE`、`WXBOT_LLM_MODEL`、`WXBOT_LLM_EXTRA`，见 `.env.example`）。`wxbot` 用户读不了 `.env`（root，600），所以要用 key 的命令通过 systemd 跑，由它替命令读这个文件：

```bash
systemd-run --quiet --pipe --wait --uid=wxbot --gid=wxbot -p WorkingDirectory=/opt/wechat-bot \
  -p EnvironmentFile=/opt/wechat-bot/.env -E WXBOT_HOME=/opt/wechat-bot \
  /opt/wechat-bot/venv/bin/python -m wxbot ask --rag "学生签证怎么续签"
```

`ask --rag` 在 `WXBOT_RAG` 还是 `0` 的时候也会试 RAG 回答，并打印来源（`rag`）、用到的片段编号、token 数和耗时。评测（[docs/EVAL.md](EVAL.md)）没问题后，设置 `WXBOT_RAG=1` 再 `systemctl restart wechat-bot`，日志里会有 `rag: on, model …`。之后 `log` 表里会有 `route='rag'` 的记录；RAG 没能替代规则答案时，`detail` 里写了原因（`| rag … timeout`、`uncited`（没有摘句）、`unsure`、`unsupported`（摘的句子在资料里都找不到）、`fragment`（找到了，但离开上下文都会看错）、`error`、`no chunks`；`ok cut N` 是有 N 句没发，日志里有这几句和原因）。如果经常超时或答得不好，改回 `WXBOT_RAG=0` 再重启，规则那边不受影响。

**评测。** `eval` 把 `eval/questions.jsonl` 交给规则（`--mode rule`）或规则加 RAG 回答（`--mode rag`，可以用 `--model` 换模型；缓存关掉，每道题都会调用模型；`--gap 15` 每次调用后等 15 秒，免得免费额度的每分钟 token 上限把一轮评测变成一串 429）回答，用和公众号一样的 4 秒预算。`--judge` 用固定的裁判模型对照参考要点给每个回答打 0/1（`WXBOT_JUDGE_MODEL`，默认 glm-4-flash；`WXBOT_JUDGE_BASE` / `WXBOT_JUDGE_KEY` 默认用 `WXBOT_LLM_*` 的），这样不同模型的结果可以放在一起比。每次运行按 `--name` 存在 `data/eval/results.json` 里，包含所有运行的报告写到 `data/eval/EVAL.md`（`wxbot` 用户写不了 `docs/`）。和上面一样用 `systemd-run` 跑，比如 `... -m wxbot eval --mode rag --judge`，然后在笔记本上把报告拷回仓库：`scp mcs21-vps:/opt/wechat-bot/data/eval/EVAL.md docs/EVAL.md`。只想用另一家模型跑一次，就把它的三行 `WXBOT_LLM_*` 写进一个只有 root 能读的文件（比如 `/root/groq.env`，权限 600），在 `systemd-run` 那行第一个 EnvironmentFile 后面再加 `-p EnvironmentFile=/root/groq.env`：后面的文件优先，`.env` 不用改，key 也不会出现在命令行里。人工标注写在 `eval/labels.jsonl`（每行 `{"id": "q01", "run": "rag glm-4-flash", "correct": 1}`），报告里会显示裁判和人工的一致率。

问题原文会发给模型服务商（不含用户 id）。回答按问题的哈希存在 `rag_cache` 里，缓存 `WXBOT_RAG_CACHE_DAYS`（7）天；超过回复时间的调用会在后台跑完并写进缓存。
