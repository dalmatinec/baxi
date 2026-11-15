#!/usr/bin/env bash
# Защита сервера от падений. Запускать от root, можно сколько угодно раз (повторно ничего не ломает):
#   bash /opt/linkhub/deploy/harden.sh
# Что делает:
#   1. swap (подкачка), если её нет: при нехватке памяти сервер не встаёт
#   2. логи не больше 300 МБ и не старше месяца: диск не забьётся
#   3. автозапуск бота и сайта после перезагрузки сервера
#   4. сторож раз в 5 минут: перезапускает зависшего бота, пишет тебе, если мало места или памяти
#   5. ежедневная чистка старых файлов (архивы копий клиентов старше 60 дней)
set -euo pipefail
DIR=/opt/linkhub
Q="${1:-}"
say() { [ "$Q" = "--quiet" ] || echo "$@"; }

if ! swapon --show --noheadings | grep -q .; then
    bash "$DIR/deploy/swap.sh" 4 >/dev/null && say "✅ Swap 4 ГБ включён"
else
    say "✅ Swap уже есть"
fi

mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/linkhub.conf <<CONF
[Journal]
SystemMaxUse=300M
MaxRetentionSec=1month
CONF
systemctl restart systemd-journald
say "✅ Логи ограничены: 300 МБ, месяц"

cp "$DIR/deploy/linkhub.service" /etc/systemd/system/linkhub.service
cp "$DIR/deploy/linkhub@.service" /etc/systemd/system/linkhub@.service
cp "$DIR/deploy/linkhub-health.service" "$DIR/deploy/linkhub-health.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable linkhub >/dev/null 2>&1
systemctl is-enabled --quiet caddy 2>/dev/null || { systemctl list-unit-files caddy.service >/dev/null 2>&1 && systemctl enable caddy >/dev/null 2>&1 || true; }
systemctl enable --now linkhub-health.timer >/dev/null 2>&1
say "✅ Автозапуск после перезагрузки и сторож раз в 5 минут включены"

cat > /etc/cron.daily/linkhub-cleanup <<CRON
#!/bin/sh
# старые архивы удалённых копий клиентов
find $DIR/instances/.archive -mindepth 1 -maxdepth 1 -mtime +60 -exec rm -rf {} + 2>/dev/null
exit 0
CRON
chmod +x /etc/cron.daily/linkhub-cleanup
say "✅ Ежедневная чистка старых файлов"

say ""
say "Сейчас: $(free -h | awk 'NR==2 {print "память " $3 " из " $2}'), диск свободно $(df -h "$DIR" | awk 'NR==2 {print $4}')"
say "Проверить сторожа вручную: bash $DIR/deploy/health.sh"
