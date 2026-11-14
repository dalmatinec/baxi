#!/usr/bin/env bash
# Сайт на своём домене с HTTPS (сертификат Let's Encrypt выпускается и продлевается сам).
# Перед запуском в DNS домена должны быть A-записи @ и www на IP этого сервера.
#   bash /opt/linkhub/deploy/site.sh satpaev.ceo [юзернейм_бота_Store] [юзернейм_канала]
# Юзернеймы запоминаются в /opt/linkhub/site.env, второй раз можно не писать.
set -euo pipefail
DOMAIN="${1:-satpaev.ceo}"
CONF=/opt/linkhub/site.env
[ -f "$CONF" ] && . "$CONF"
STORE_BOT="${2:-${STORE_BOT:-}}"; STORE_BOT="${STORE_BOT#@}"
CHANNEL="${3:-${CHANNEL:-newssatbox}}"; CHANNEL="${CHANNEL#@}"
printf 'STORE_BOT=%s\nCHANNEL=%s\n' "$STORE_BOT" "$CHANNEL" > "$CONF"
WEB=/var/www/site

if ! command -v caddy >/dev/null; then
    echo "Ставлю Caddy (веб-сервер с автоматическим HTTPS)..."
    apt-get update -q
    apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl gnupg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q
    apt-get install -y -q caddy
fi

mkdir -p "$WEB"
cp -r /opt/linkhub/site/. "$WEB/"

# юзернейм бота берём у самого Telegram по токену из .env: ссылки на сайте /bot, /add, /order ведут к нему
TOKEN=$(grep -E '^BOT_TOKEN=' /opt/linkhub/.env | head -1 | cut -d= -f2- | tr -d ' "'"'"'')
BOT=$(curl -fsS "https://api.telegram.org/bot${TOKEN}/getMe" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["username"])' || true)
if [ -z "$BOT" ]; then
    echo "Не смог узнать юзернейм бота (проверь BOT_TOKEN в /opt/linkhub/.env)"; exit 1
fi
echo "Бот: @$BOT · Store: ${STORE_BOT:+@$STORE_BOT}${STORE_BOT:-не указан} · канал: @$CHANNEL"
STORE_URL="https://t.me/${STORE_BOT:-$CHANNEL}"

cat > /etc/caddy/Caddyfile <<CADDY
# Сгенерировано deploy/site.sh. Сайт: $DOMAIN, www перекидывает на основной адрес.
www.$DOMAIN {
    redir https://$DOMAIN{uri} permanent
}

$DOMAIN {
    encode zstd gzip
    # короткие ссылки на бота: так юзернейм не зашит в страницы
    redir /bot   https://t.me/$BOT 302
    redir /add   https://t.me/$BOT?startgroup=true&admin=delete_messages+pin_messages+invite_users 302
    redir /order https://t.me/$BOT?start=order 302
    redir /my    https://t.me/$BOT?start=mychats 302
    redir /store $STORE_URL 302
    redir /news  https://t.me/$CHANNEL 302
    # живые цифры (сколько чатов и участников) бот пишет сам
    handle /stats.json {
        root * /opt/linkhub/data
        header Cache-Control "max-age=60"
        file_server
    }
    handle {
        root * $WEB
        try_files {path} {path}.html {path}/index.html =404
        file_server
    }
    handle_errors {
        root * $WEB
        rewrite * /404.html
        file_server
    }
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
CADDY

# если включён файрвол, открываем веб-порты
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
fi

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl enable --now caddy >/dev/null 2>&1 || true
systemctl reload caddy || systemctl restart caddy
sleep 3
echo
echo "Готово. Открой https://$DOMAIN (первый раз сертификат выпускается до минуты)."
echo "Если не открывается: journalctl -u caddy --no-pager -n 30"
