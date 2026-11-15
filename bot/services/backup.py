"""Бэкап базы раз в сутки: копия на сервере (7 дней и 4 недели) и файл в закрытый канал без звука.
Владельцу пишет, только если бэкап не получился.

Восстановление: переслать файл из канала боту в личку и нажать «Восстановить» (/admin → Настройки → Бэкап)
или на сервере: bash /opt/linkhub/deploy/restore.sh"""

import asyncio
import gzip
import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from bot import config, db, notify

log = logging.getLogger(__name__)

KEEP_DAILY, KEEP_WEEKLY, KEEP_IN_CHANNEL = 7, 4, 7
HOUR = int(os.getenv("BACKUP_HOUR", "4") or 4)       # во сколько делать бэкап (по времени из TZ)


def folder() -> Path:
    return config.DATA_DIR / "backups"


def _snapshot(dest: Path) -> None:
    """Копия базы на ходу, бот не останавливается (sqlite backup API)."""
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


async def make() -> Path:
    """Делает файл бэкапа и возвращает путь к нему."""
    folder().mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(config.TZ).strftime("%Y-%m-%d_%H%M")
    raw = folder() / f"tmp-{stamp}.db"
    await asyncio.to_thread(_snapshot, raw)
    gz = folder() / f"baxi-{stamp}.db.gz"
    await asyncio.to_thread(_gzip, raw, gz)
    raw.unlink()
    return gz


def _gzip(src: Path, dst: Path) -> None:
    with open(src, "rb") as f, gzip.open(dst, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)


def rotate() -> None:
    """Оставляет последние 7 копий и ещё по одной за 4 прошлые недели (воскресные)."""
    files = sorted(folder().glob("baxi-*.db.gz"), reverse=True)
    keep, weeks = set(files[:KEEP_DAILY]), set()
    for f in files[KEEP_DAILY:]:
        day = datetime.strptime(f.name[5:15], "%Y-%m-%d")
        week = day.isocalendar()[:2]
        if week not in weeks and len(weeks) < KEEP_WEEKLY:
            weeks.add(week)
            keep.add(f)
    for f in files:
        if f not in keep:
            f.unlink(missing_ok=True)


async def _send_to_channel(bot: Bot, path: Path) -> None:
    channel = os.getenv("BACKUP_CHANNEL", "").strip() or await db.kv_get("backup_channel")
    if not channel:
        return
    reach = await db.reach()
    size = path.stat().st_size / 1024 / 1024
    caption = (f"💾 Бэкап {datetime.now(config.TZ):%d.%m.%Y %H:%M}\n"
               f"{size:.1f} МБ · чатов {reach['chats']} · людей в личке {reach['dm']}\n"
               "Восстановить: переслать этот файл боту в личку")
    msg = await bot.send_document(int(channel), FSInputFile(path), caption=caption, disable_notification=True)
    # в канале держим только последние копии, старые удаляем
    ids = json.loads(await db.kv_get("backup_msgs", "[]"))
    ids.append(msg.message_id)
    for old in ids[:-KEEP_IN_CHANNEL]:
        try:
            await bot.delete_message(int(channel), old)
        except Exception:
            pass
    await db.kv_set("backup_msgs", json.dumps(ids[-KEEP_IN_CHANNEL:]))


async def run(bot: Bot) -> Path:
    path = await make()
    rotate()
    await _send_to_channel(bot, path)
    await db.kv_set("backup_last", str(int(time.time())))
    await db.kv_set("backup_size", str(path.stat().st_size))
    return path


async def tick(bot: Bot) -> None:
    """Раз в сутки в HOUR часов. Ошибку присылает владельцу, но не чаще раза в сутки."""
    now = datetime.now(config.TZ)
    if now.hour < HOUR or await db.kv_get("backup_day") == now.strftime("%Y-%m-%d"):
        return
    await db.kv_set("backup_day", now.strftime("%Y-%m-%d"))
    try:
        await run(bot)
    except Exception as exc:
        log.exception("Бэкап не получился")
        await notify.owners(bot, f"⚠️ Бэкап не получился: {str(exc)[:300]}\nПроверь /admin → Настройки → Бэкап.")


# ---------- восстановление из файла, присланного владельцем ----------

async def prepare_restore(src: Path) -> str:
    """Распаковывает файл, проверяет базу и кладёт её как data/restore.db.
    При следующем запуске бот подменит базу (старая сохранится рядом). Возвращает краткую сводку."""
    work = folder() / f"restore-{int(time.time())}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        gz = src
        raw = work / "x.db"
        if gz.name.endswith(".gz"):
            await asyncio.to_thread(_gunzip, gz, raw)
        else:
            shutil.copy2(gz, raw)
        con = sqlite3.connect(raw)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            chats = con.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
        finally:
            con.close()
        if ok != "ok":
            raise RuntimeError(f"база повреждена: {ok}")
        shutil.move(raw, config.DATA_DIR / "restore.db")
        return f"чатов в копии: {chats}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _gunzip(src: Path, dst: Path) -> None:
    with gzip.open(src, "rb") as g, open(dst, "wb") as f:
        shutil.copyfileobj(g, f)
