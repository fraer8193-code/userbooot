import os
import json
import re
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from telethon import events
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.errors import FloodWaitError
import core
from config import CMD_PREFIX, BASE_DIR

logger = logging.getLogger("Userbot.AutoTime")

SETTINGS_FILE = BASE_DIR / "autotime_settings.json"
MSK_TZ = timezone(timedelta(hours=3))

_task: asyncio.Task = None
_last_set_name: str = ""

def load_settings() -> dict:
    default_settings = {
        "enabled": True,
        "base_name": ""
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_settings.update(data)
        except Exception as e:
            logger.warning(f"Error loading autotime settings: {e}")
    return default_settings

def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.warning(f"Error saving autotime settings: {e}")

def get_msk_time_str() -> str:
    now = datetime.now(MSK_TZ)
    return now.strftime("%H:%M")

def clean_time_from_name(name: str) -> str:
    if not name:
        return "User"
    cleaned = re.sub(r"\s*\|\s*\d{1,2}:\d{2}.*$", "", name).strip()
    return cleaned if cleaned else "User"

async def update_profile_time(client, force: bool = False):
    global _last_set_name
    settings = load_settings()
    if not settings.get("enabled", True) and not force:
        return

    base_name = settings.get("base_name", "").strip()
    if not base_name:
        try:
            me = await client.get_me()
            base_name = clean_time_from_name(me.first_name)
            settings["base_name"] = base_name
            save_settings(settings)
        except Exception as e:
            logger.warning(f"Could not get current first_name: {e}")
            base_name = "User"

    # Telegram limit on first_name is 64 characters
    # " | HH:MM" takes 8 characters -> max base_name length is 55
    safe_base = base_name[:55]
    time_str = get_msk_time_str()
    new_name = f"{safe_base} | {time_str}"

    if new_name == _last_set_name and not force:
        return

    try:
        await client(UpdateProfileRequest(first_name=new_name))
        _last_set_name = new_name
        logger.info(f"Updated profile name to: {new_name}")
    except FloodWaitError as e:
        logger.warning(f"Flood wait during name update: wait {e.seconds}s")
        await asyncio.sleep(e.seconds + 2)
    except Exception as e:
        logger.warning(f"Failed to update profile name: {e}")

async def autotime_worker(client):
    while True:
        try:
            settings = load_settings()
            if settings.get("enabled", True):
                await update_profile_time(client)
            
            # Спим ровно до следующей минуты, чтобы обновлять время вовремя
            now = datetime.now(MSK_TZ)
            seconds_left = 60 - now.second + 0.5
            await asyncio.sleep(max(1.0, seconds_left))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception(f"Error in autotime loop: {e}")
            await asyncio.sleep(15)

def on_load(mgr):
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = asyncio.create_task(autotime_worker(mgr.client))
    logger.info("AutoTime worker started.")

def on_unload(mgr):
    global _task, _last_set_name
    if _task and not _task.done():
        _task.cancel()
        _task = None
    _last_set_name = ""

    # Восстанавливаем оригинальное имя без суффикса времени при выгрузке модуля
    settings = load_settings()
    base_name = settings.get("base_name", "").strip()
    if base_name and mgr.client:
        async def restore():
            try:
                await mgr.client(UpdateProfileRequest(first_name=base_name))
                logger.info(f"Restored profile name to: {base_name}")
            except Exception as e:
                logger.warning(f"Could not restore base name on unload: {e}")
        asyncio.create_task(restore())

@core.command("autotime", description="Manage auto-time in profile name", usage=f"{CMD_PREFIX}autotime [on|off|name <имя>|sync]")
async def autotime_cmd(event: events.NewMessage.Event):
    """Управление отображением времени по МСК в нике."""
    args = event.raw_text.split(maxsplit=2)
    sub = args[1].lower() if len(args) > 1 else ""

    settings = load_settings()

    if sub == "on":
        settings["enabled"] = True
        save_settings(settings)
        await event.edit("⏳ **Включение авто-времени...**")
        client = event.client
        await update_profile_time(client, force=True)
        time_str = get_msk_time_str()
        base = settings.get("base_name") or "User"
        await event.edit(
            f"✅ **Авто-время включено!**\n"
            f"👤 Ник: `{base} | {time_str}`\n"
            f"🕒 Часовой пояс: **МСК (UTC+3)**"
        )
        return

    elif sub == "off":
        settings["enabled"] = False
        save_settings(settings)
        base = settings.get("base_name", "").strip()
        client = event.client
        if not base:
            me = await client.get_me()
            base = clean_time_from_name(me.first_name)
            settings["base_name"] = base
            save_settings(settings)
        try:
            await client(UpdateProfileRequest(first_name=base))
        except Exception as e:
            logger.warning(f"Failed to reset profile name: {e}")
        await event.edit(
            f"⏸ **Авто-время выключено.**\n"
            f"👤 Ник возвращен к: `{base}`"
        )
        return

    elif sub == "name":
        if len(args) < 3 or not args[2].strip():
            await event.edit(f"💡 **Использование:** `{CMD_PREFIX}autotime name <Ваше имя>`")
            return
        new_name = clean_time_from_name(args[2].strip())
        settings["base_name"] = new_name
        save_settings(settings)
        client = event.client
        if settings.get("enabled", True):
            await update_profile_time(client, force=True)
            time_str = get_msk_time_str()
            await event.edit(
                f"✅ **Базовое имя обновлено!**\n"
                f"👤 Новый ник: `{new_name} | {time_str}`"
            )
        else:
            await event.edit(
                f"✅ **Базовое имя сохранено:** `{new_name}`\n"
                f"💡 Включите авто-время командой `{CMD_PREFIX}autotime on`"
            )
        return

    elif sub in ("sync", "update"):
        await event.edit("🔄 **Синхронизация времени...**")
        client = event.client
        await update_profile_time(client, force=True)
        time_str = get_msk_time_str()
        base = settings.get("base_name") or "User"
        await event.edit(f"✅ **Время обновлено:** `{base} | {time_str}` (МСК)")
        return

    # Если без параметров - показываем текущий статус
    is_enabled = settings.get("enabled", True)
    base_name = settings.get("base_name", "")
    if not base_name:
        try:
            me = await event.client.get_me()
            base_name = clean_time_from_name(me.first_name)
            settings["base_name"] = base_name
            save_settings(settings)
        except Exception:
            base_name = "Не определено"

    time_str = get_msk_time_str()
    status_emoji = "🟢 Включено" if is_enabled else "🔴 Выключено"
    preview = f"{base_name} | {time_str}" if is_enabled else base_name

    text = (
        f"🕐 **Настройки авто-времени в нике**\n\n"
        f"• **Статус:** {status_emoji}\n"
        f"• **Базовый ник:** `{base_name}`\n"
        f"• **Текущее время (МСК):** `{time_str}`\n"
        f"• **Текущий ник в профиле:** `{preview}`\n\n"
        f"💡 **Команды управления:**\n"
        f"  `{CMD_PREFIX}autotime on` — включить авто-время\n"
        f"  `{CMD_PREFIX}autotime off` — выключить и вернуть старый ник\n"
        f"  `{CMD_PREFIX}autotime name <имя>` — изменить базовый ник\n"
        f"  `{CMD_PREFIX}autotime sync` — синхронизировать прямо сейчас"
    )
    await event.edit(text)
