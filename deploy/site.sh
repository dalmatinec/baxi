#!/usr/bin/env bash
# Сайт на своём домене с HTTPS (сертификат Let's Encrypt выпускается и продлевается сам).
# Перед запуском в DNS домена должны быть A-записи @ и www на IP этого сервера.
#   bash /opt/linkhub/deploy/site.sh satpaev.ceo
set -euo pipefail
DOMAIN="${1:-satpaev.ceo}"
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

cat > /etc/caddy/Caddyfile <<CADDY
# Сгенерировано deploy/site.sh. Сайт: $DOMAIN, www перекидывает на основной адрес.
www.$DOMAIN {
    redir https://$DOMAIN{uri} permanent
}

$DOMAIN {
    root * $WEB
    encode zstd gzip
    try_files {path} {path}.html {path}/ /index.html
    file_server
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
