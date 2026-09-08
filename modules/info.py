import os
import sys
import time
import psutil
import platform
from pathlib import Path
from telethon import events
from telethon.utils import get_display_name
import core
from config import BOT_VERSION, BASE_DIR

BANNER_FILE = BASE_DIR / "1.jpeg"

def get_banner_path() -> Path | None:
    """Возвращает путь к файлу изображения 1.jpeg (или альтернативным)."""
    if BANNER_FILE.exists():
        return BANNER_FILE
    
    # Резервные варианты
    for alt_name in ["1.jpg", "1.png", "banner.jpg", "i.webp"]:
        alt_path = BASE_DIR / alt_name
        if alt_path.exists():
            return alt_path
    return None

def get_os_name() -> str:
    """Определяет имя операционной системы."""
    system = platform.system()
    if system == "Linux":
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=")[1].strip().strip('"')
        except Exception:
            pass
        return f"Linux ({platform.release()})"
    elif system == "Windows":
        return f"Windows {platform.release()}"
    elif system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return f"{system} {platform.release()}"

def format_detailed_uptime() -> str:
    """Форматирует аптайм в виде: X day(s), HH:MM:SS"""
    delta = int(time.time() - core.START_TIME)
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{days} day(s), {hours:02d}:{minutes:02d}:{seconds:02d}"

@core.command("info", description="Show detailed system and bot info with banner", usage=".info")
async def info_cmd(event: events.NewMessage.Event):
    """Выводит информацию о юзерботе в виде полноценного фото 1.jpeg с текстом-подписью."""
    start_time = time.perf_counter_ns()
    
    client = event.client
    me = await client.get_me()
    
    user_name = get_display_name(me) or "User"
    user_id = me.id
    profile_link = f"[{user_name}](tg://user?id={user_id})"

    # RAM процесса
    try:
        process = psutil.Process(os.getpid())
        ram_usage = process.memory_info().rss / (1024 * 1024)
    except Exception:
        ram_usage = 0.0

    # CPU
    try:
        cpu_phys = psutil.cpu_count(logical=False) or 1
        cpu_total = psutil.cpu_count(logical=True) or 1
        cpu_percent = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_phys, cpu_total, cpu_percent = 1, 1, 0.0

    ping_ms = round((time.perf_counter_ns() - start_time) / 10**6, 2)
    uptime_str = format_detailed_uptime()
    os_name = get_os_name()

    text = (
        f"{profile_link}\n\n"
        f"🏷 **Ver :** `{BOT_VERSION}`\n"
        f"⏳ **Up :** `{uptime_str}`\n"
        f"💾 **RAM :** `{ram_usage:.1f} MB`\n"
        f"⚡ **CPU :** `{cpu_phys} ({cpu_total}) core(-s); {cpu_percent:.1f}% total`\n"
        f"🪐 **Ping :** `{ping_ms} ms`\n"
        f"💻 **OS :** `{os_name}`\n\n"
        f"✨ **Up-to-date**\n"
        f"✧◝(⁰▿⁰)◜✧"
    )

    banner_path = get_banner_path()
    
    # Отправляем фото 1.jpeg с текстом-подписью и удаляем команду
    if banner_path and banner_path.exists():
        try:
            reply_to = event.reply_to_msg_id
            await client.send_file(
                event.chat_id,
                file=str(banner_path),
                caption=text,
                reply_to=reply_to
            )
            await event.delete()
            return
        except Exception:
            pass

    await event.edit(text, link_preview=False)
