#!/usr/bin/env bash
# Обновить бота до свежей версии из GitHub: bash /opt/linkhub/deploy/update.sh
set -euo pipefail
cd /opt/linkhub
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
systemctl restart linkhub
sleep 2
systemctl --no-pager --lines=5 status linkhub || true
