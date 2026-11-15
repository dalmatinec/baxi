#!/usr/bin/env bash
# Сторож: раз в 5 минут (таймер linkhub-health.timer) проверяет бота и сервер.
#   • бот и копии клиентов: если процесс жив, но 15 минут не было пульса (data/heartbeat), значит завис, перезапуск
#   • сервис упал и не поднимается: запуск
#   • мало места на диске (< 1 ГБ) или памяти (< 150 МБ): пишет владельцу в Telegram (не чаще раза в 6 часов)
# Ручной запуск: bash /opt/linkhub/deploy/health.sh
set -uo pipefail
DIR=/opt/linkhub
STALE=900
NOW=$(date +%s)
ALERTS=()

check_unit() {   # $1 = имя сервиса, $2 = папка data
    local unit="$1" data="$2"
    if ! systemctl is-active --quiet "$unit"; then
        systemctl restart "$unit" && ALERTS+=("♻️ $unit был остановлен, запустил заново")
        return
    fi
    local beat=0
    [ -f "$data/heartbeat" ] && beat=$(cat "$data/heartbeat" 2>/dev/null || echo 0)
    local started
    started=$(date -d "$(systemctl show -p ActiveEnterTimestamp --value "$unit")" +%s 2>/dev/null || echo "$NOW")
    if [ $((NOW - started)) -gt $STALE ] && [ $((NOW - beat)) -gt $STALE ]; then
        systemctl restart "$unit"
        ALERTS+=("♻️ $unit завис (нет пульса $(( (NOW - beat) / 60 )) мин), перезапустил")
    fi
}

check_unit linkhub "$DIR/data"
for d in "$DIR"/instances/*/; do
    [ -f "$d/.env" ] || continue
    n=$(basename "$d")
    systemctl is-enabled --quiet "linkhub@$n" 2>/dev/null && check_unit "linkhub@$n" "$d/data"
done

FREE_MB=$(df -Pm "$DIR" | awk 'NR==2 {print $4}')
MEM_MB=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
WARN_FILE="$DIR/data/.health-warned"
if [ "${FREE_MB:-9999}" -lt 1024 ] || [ "${MEM_MB:-9999}" -lt 150 ]; then
    LAST=$(cat "$WARN_FILE" 2>/dev/null || echo 0)
    if [ $((NOW - LAST)) -gt 21600 ]; then
        ALERTS+=("⚠️ Сервер: свободно на диске ${FREE_MB} МБ, памяти ${MEM_MB} МБ. Почисти старые файлы или добавь swap.")
        echo "$NOW" > "$WARN_FILE"
    fi
fi

# сообщение владельцам через Telegram (токен и ID из .env основного бота)
if [ ${#ALERTS[@]} -gt 0 ] && [ -f "$DIR/.env" ]; then
    TOKEN=$(grep -E '^BOT_TOKEN=' "$DIR/.env" | cut -d= -f2-)
    OWNERS=$(grep -E '^OWNER_IDS=' "$DIR/.env" | cut -d= -f2- | tr ',' ' ')
    TEXT="🩺 Сторож сервера:"$'\n'"$(printf '%s\n' "${ALERTS[@]}")"
    for id in $OWNERS; do
        curl -fsS --max-time 10 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
            --data-urlencode "chat_id=${id}" --data-urlencode "text=${TEXT}" >/dev/null 2>&1 || true
    done
    printf '%s\n' "${ALERTS[@]}"
fi
exit 0
