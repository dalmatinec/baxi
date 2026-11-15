#!/usr/bin/env bash
# Восстановление базы Бакси из бэкапа.
#   bash /opt/linkhub/deploy/restore.sh                 # последняя копия с сервера
#   bash /opt/linkhub/deploy/restore.sh /путь/baxi-...  # конкретный файл (.db.gz или .db.gz.enc)
# Текущая база сохраняется рядом как bot.db.before-restore-<время>.
set -euo pipefail
ROOT=/opt/linkhub
DATA=$ROOT/data
FILE="${1:-$(ls -1t $DATA/backups/baxi-*.db.gz* 2>/dev/null | head -1 || true)}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "Нет файла бэкапа. Укажи путь: bash $0 /путь/к/файлу"; exit 1; }
echo "Восстанавливаю из: $FILE"

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
SRC="$FILE"
if [[ "$FILE" == *.enc ]]; then
    PASS=$(grep -E '^BACKUP_PASSWORD=' $ROOT/.env | head -1 | cut -d= -f2- | tr -d ' "'"'"'' || true)
    [ -n "$PASS" ] || read -rsp "Пароль бэкапа (BACKUP_PASSWORD): " PASS && echo
    BKPASS="$PASS" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BKPASS -in "$FILE" -out "$WORK/x.db.gz"
    SRC="$WORK/x.db.gz"
fi
if [[ "$SRC" == *.gz ]]; then gunzip -c "$SRC" > "$WORK/x.db"; else cp "$SRC" "$WORK/x.db"; fi

python3 - "$WORK/x.db" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
ok = con.execute("PRAGMA integrity_check").fetchone()[0]
n = con.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
print(f"Проверка: {ok}, чатов в копии: {n}")
sys.exit(0 if ok == "ok" else 1)
PY

systemctl stop linkhub
[ -f $DATA/bot.db ] && cp $DATA/bot.db "$DATA/bot.db.before-restore-$(date +%s)"
rm -f $DATA/bot.db-wal $DATA/bot.db-shm
cp "$WORK/x.db" $DATA/bot.db
chown --reference=$DATA $DATA/bot.db 2>/dev/null || true
systemctl start linkhub
sleep 3
systemctl --no-pager --lines=5 status linkhub || true
echo "Готово. Бот работает с восстановленной базой."
