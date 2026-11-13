#!/usr/bin/env bash
# Копии бота для клиентов (white label). Запускать от root:
#   bash /opt/linkhub/deploy/client.sh add vasya      # новый клиент (спросит токен, ID, ключ нейросети)
#   bash /opt/linkhub/deploy/client.sh list           # все копии и их состояние
#   bash /opt/linkhub/deploy/client.sh logs vasya     # логи копии
#   bash /opt/linkhub/deploy/client.sh restart vasya
#   bash /opt/linkhub/deploy/client.sh remove vasya   # остановить и убрать (папка уйдёт в архив)
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
    read -rp "Токен бота клиента (от @BotFather): " TOKEN
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
remove)
    need_name
    systemctl disable --now "linkhub@$NAME" 2>/dev/null || true
    mkdir -p "$BASE/.archive"
    mv "$BASE/$NAME" "$BASE/.archive/$NAME-$(date +%Y%m%d%H%M)"
    echo "Клиент $NAME остановлен, папка в $BASE/.archive"
    ;;
*) sed -n 2,9p "$0"; exit 1 ;;
esac
