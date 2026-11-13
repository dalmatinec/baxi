#!/usr/bin/env bash
# Обновить бота (и все копии white label) до свежей версии из GitHub:
#   bash /opt/linkhub/deploy/update.sh
set -euo pipefail
cd /opt/linkhub
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
cp deploy/linkhub.service /etc/systemd/system/linkhub.service
cp deploy/linkhub@.service /etc/systemd/system/linkhub@.service
systemctl daemon-reload
systemctl restart linkhub
# копии клиентов работают на том же коде, перезапускаем и их
for unit in $(systemctl list-units --type=service --state=running --no-legend 'linkhub@*' | awk '{print $1}'); do
    systemctl restart "$unit"
done
sleep 2
systemctl --no-pager --lines=5 status linkhub || true
