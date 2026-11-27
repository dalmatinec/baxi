#!/usr/bin/env bash
# Установка или обновление бота на Ubuntu/Debian. Запускать от root:
#   bash /opt/linkhub/deploy/install.sh
# При первом запуске спросит токен, свой Telegram ID и ключ нейросети, запишет в /opt/linkhub/.env
set -euo pipefail
trap 'echo "❌ Остановился на строке $LINENO: $BASH_COMMAND"' ERR

DIR=/opt/linkhub
cd "$DIR" || { echo "Сначала: git clone https://github.com/dalmatinec/baxi $DIR"; exit 1; }

# swap 5 ГБ, если его ещё нет: на сервере с 2 ГБ памяти без него тесно
bash "$DIR/deploy/swap.sh" 5 >/dev/null && echo "Swap: $(swapon --show=SIZE --noheadings | head -1)"

if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3-venv
fi
id linkhub >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin linkhub

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    read -rsp "Токен бота от @BotFather (ввод скрыт): " TOKEN; echo
    read -rp "Твой Telegram ID (несколько через запятую): " OWNERS
    read -rsp "Ключ API нейросети DeepSeek, можно пусто (ввод скрыт): " AIKEY; echo
    sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$TOKEN|; s|^OWNER_IDS=.*|OWNER_IDS=$OWNERS|; s|^AI_API_KEY=.*|AI_API_KEY=$AIKEY|" .env
fi
mkdir -p data
chown -R linkhub:linkhub data
chown linkhub:linkhub .env && chmod 600 .env

cp deploy/linkhub.service /etc/systemd/system/linkhub.service
systemctl daemon-reload
systemctl enable linkhub >/dev/null
systemctl restart linkhub
bash "$DIR/deploy/harden.sh" --quiet || true
sleep 3
systemctl --no-pager --lines=8 status linkhub || true
echo
echo "Готово. Логи: journalctl -u linkhub -f   Настройки: nano $DIR/.env, потом systemctl restart linkhub"
