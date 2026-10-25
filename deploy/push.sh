#!/bin/sh
# From a laptop checkout: sync code to the VPS and reinstall. Never touches venv/ or data/ there.
set -eu
cd "$(dirname "$0")/.."
rsync -a --delete --exclude /venv --exclude /data --exclude /.env --exclude .venv --exclude .scratch \
  --exclude .git --exclude __pycache__ --exclude .pytest_cache ./ mcs21-vps:/opt/wechat-bot/
ssh mcs21-vps 'sh /opt/wechat-bot/deploy/install.sh && systemctl restart wechat-bot && systemctl is-active wechat-bot'
