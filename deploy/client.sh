#!/usr/bin/env bash
# Копии бота для клиентов (white label). Запускать от root:
#   bash /opt/linkhub/deploy/client.sh add vasya      # новый клиент (спросит токен, ID, ключ нейросети)
#   bash /opt/linkhub/deploy/client.sh list           # все копии и их состояние
#   bash /opt/linkhub/deploy/client.sh logs vasya     # логи копии
#   bash /opt/linkhub/deploy/client.sh restart vasya
#   bash /opt/linkhub/deploy/client.sh edit vasya     # поменять токен, ключ нейросети и т.п. (.env) и перезапустить
#   bash /opt/linkhub/deploy/client.sh backup vasya   # копия базы клиента прямо сейчас
#   bash /opt/linkhub/deploy/client.sh remove vasya   # остановить и убрать (папка уйдёт в архив)
# Обновление кода у всех копий сразу: bash /opt/linkhub/deploy/update.sh
# Каждая копия ест около 100-150 МБ памяти. На сервере с 2 ГБ спокойно живут 6-8 копий плюс основной бот.
# Продлевать оплату и ставить на паузу удобнее из бота: /admin → Клиенты.
set -euo pipefail
DIR=/opt/linkhub
BASE=$DIR/instances
CMD="${1:-}"; NAME="${2:-}"

need_name() {
    [[ "$NAME" =~ ^[a-z0-9_-]{2,32}$ ]] || { echo "Имя: латиница, цифры, - или _, от 2 до 32 символов"; exit 1; }
}

case "$CMD" in
add)
    need_name
    [ -d "$BASE/$NAME" ] && { echo "Клиент $NAME уже есть"; exit 1; }
    cp "$DIR/deploy/linkhub@.service" /etc/systemd/system/linkhub@.service
    systemctl daemon-reload
    AVAIL=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
    if [ "${AVAIL:-0}" -lt 250 ]; then
        echo "⚠️  Свободно всего ${AVAIL} МБ памяти. Сначала добавь подкачку: bash $DIR/deploy/swap.sh"
        read -rp "Всё равно продолжить? [y/N]: " GO; [ "$GO" = "y" ] || exit 1
    fi
    read -rp "Токен бота клиента (от @BotFather): " TOKEN
    if ! curl -fsS --max-time 10 "https://api.telegram.org/bot${TOKEN}/getMe" | grep -q '"ok":true'; then
        echo "Telegram не принял этот токен. Проверь, что скопировал его целиком."; exit 1
    fi
    for other in "$BASE"/*/.env; do
        [ -f "$other" ] && grep -q "^BOT_TOKEN=${TOKEN}$" "$other" && { echo "Этот токен уже стоит у $(basename "$(dirname "$other")")"; exit 1; }
    done
    read -rp "Telegram ID клиента (он будет админом): " OWNER
    read -rp "Ключ нейросети клиента (можно пусто, тогда без ИИ): " AIKEY
    read -rp "Оплачено дней [30]: " DAYS; DAYS="${DAYS:-30}"
    read -rp "Лимит чатов (0 = без лимита) [3]: " LIMIT; LIMIT="${LIMIT:-3}"
    mkdir -p "$BASE/$NAME/data"
    cat > "$BASE/$NAME/.env" <<ENV
BOT_TOKEN=$TOKEN
OWNER_IDS=$OWNER
AI_API_KEY=$AIKEY
EDITION=client
INSTANCE_NAME=$NAME
DATA_DIR=$BASE/$NAME/data
DAILY_LIMIT_USD=1
CREATOR=0
ENV
    UNTIL=$(( $(date +%s) + DAYS * 86400 ))
    echo "{\"paid_until\": $UNTIL, \"max_chats\": $LIMIT, \"active\": true}" > "$BASE/$NAME/license.json"
    chown -R linkhub:linkhub "$BASE"
    chmod 600 "$BASE/$NAME/.env"
    systemctl enable --now "linkhub@$NAME" >/dev/null
    sleep 3
    systemctl --no-pager --lines=5 status "linkhub@$NAME" || true
    echo; echo "Готово. Клиент пишет своему боту /admin. Продлевать: в основном боте /admin → Клиенты."
    ;;
list)
    [ -d "$BASE" ] || { echo "Клиентов пока нет"; exit 0; }
    for d in "$BASE"/*/; do
        n=$(basename "$d"); [ -f "$d/.env" ] || continue
        printf "%-20s %-10s %s\n" "$n" "$(systemctl is-active "linkhub@$n" || true)" "$(cat "$d/license.json" 2>/dev/null)"
    done
    free -h | head -2
    ;;
logs) need_name; journalctl -u "linkhub@$NAME" -n 100 --no-pager ;;
restart) need_name; systemctl restart "linkhub@$NAME"; systemctl --no-pager --lines=5 status "linkhub@$NAME" || true ;;
edit)
    need_name
    [ -f "$BASE/$NAME/.env" ] || { echo "Клиента $NAME нет"; exit 1; }
    ${EDITOR:-nano} "$BASE/$NAME/.env"
    systemctl restart "linkhub@$NAME"; sleep 3
    systemctl --no-pager --lines=5 status "linkhub@$NAME" || true
    ;;
backup)
    need_name
    DB="$BASE/$NAME/data/bot.db"; [ -f "$DB" ] || { echo "Базы у $NAME пока нет"; exit 1; }
    OUT="$BASE/$NAME/data/backups/manual-$(date +%Y%m%d-%H%M).db"
    mkdir -p "$(dirname "$OUT")"
    "$DIR/.venv/bin/python" -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$DB" "$OUT"
    gzip -f "$OUT"; chown -R linkhub:linkhub "$BASE/$NAME/data/backups"
    echo "Готово: $OUT.gz"
    ;;
remove)
    need_name
    systemctl disable --now "linkhub@$NAME" 2>/dev/null || true
    mkdir -p "$BASE/.archive"
    mv "$BASE/$NAME" "$BASE/.archive/$NAME-$(date +%Y%m%d%H%M)"
    echo "Клиент $NAME остановлен, папка в $BASE/.archive"
    ;;
*) sed -n 2,14p "$0"; exit 1 ;;
esac
