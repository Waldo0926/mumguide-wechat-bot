#!/bin/sh
# Run on the VPS as root after rsyncing the repo to /opt/wechat-bot.
set -eu
cd /opt/wechat-bot
id wxbot >/dev/null 2>&1 || useradd --system --home-dir /opt/wechat-bot --shell /usr/sbin/nologin wxbot
[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
# The RAG mode's local vector model (onnxruntime), only on a host that opted in by putting WXBOT_RAG in .env.
if grep -qs '^WXBOT_RAG=' .env; then venv/bin/pip install -q -r requirements-rag.txt; fi
install -d -o wxbot -g wxbot -m 700 data
find . -path ./data -prune -o -exec chown root:root {} +
for u in wechat-bot.service wechat-bot-mamo.service wechat-bot-mamo.timer wechat-bot-backup.service wechat-bot-backup.timer; do install -m 644 deploy/$u /etc/systemd/system/$u; done
systemctl daemon-reload
echo "installed"
