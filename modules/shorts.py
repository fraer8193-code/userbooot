"""
YouTube Shorts Module v2.0 — Листание рекомендаций, поиск по темам и скачивание Shorts.

Возможности:
  .shorts / .sh            — Листать персональные рекомендации Shorts
  .shorts <тема/запрос>    — Найти и скачать Shorts по любой теме (мемы, игры, котики и т.д.)
  .shorts <ссылка>         — Скачать конкретный YouTube Short по ссылке
  .shorts login <куки>     — Привязать YouTube аккаунт для доступа к рекомендациям
  .shorts me               — Статус аккаунта
  .shorts logout           — Отвязать YouTube аккаунт
  .shorts help             — Справка
"""

import io
import os
import re
import json
import time
import random
import asyncio
from pathlib import Path
from telethon import events
import yt_dlp
import core

TEMP_DIR = Path("temp_media")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

COOKIES_FILE = Path("youtube_cookies.txt")
SESSION_FILE = Path("youtube_session.json")

# Кэш очереди рекомендаций
_shorts_queue = []
_seen_shorts_ids = set()

# ===================== УПРАВЛЕНИЕ АККАУНТОМ =====================

def load_session_info() -> dict:
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"is_logged_in": COOKIES_FILE.exists(), "last_login": 0}

def save_session_info(data: dict):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def extract_youtube_url(text: str) -> str | None:
    patterns = [
        r'(https?://(?:www\.)?youtube\.com/shorts/[\w-]+)',
        r'(https?://(?:www\.)?youtu\.be/[\w-]+)',
        r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+)'
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return None

def get_ydl_base_opts() -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best[ext=mp4][filesize<40M]/best[filesize<40M]/best',
        'socket_timeout': 20,
        'http_chunk_size': 10485760,
        'buffersize': 1048576,
        'remote_components': ['ejs:github'],
        'js_runtimes': {'node': {}},
        'match_filter': lambda info, *args: 'Video too long for Shorts' if info.get('duration') and info.get('duration') > 120 else None
    }
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 10:
        opts['cookiefile'] = str(COOKIES_FILE)
    return opts

# ===================== ЗАГРУЗКА И ПОИСК SHORTS =====================

async def fetch_shorts_by_query(query: str = "") -> list:
    """Извлекает список Shorts по поисковому запросу или из ленты трендов/рекомендаций."""
    opts = get_ydl_base_opts()
    opts['extract_flat'] = True

    if query:
        search_target = f"ytsearch10:{query} #shorts"
    else:
        feed_sources = [
            "https://www.youtube.com/hashtag/shorts",
            "https://www.youtube.com/hashtag/short",
            "https://www.youtube.com/hashtag/memes",
            "https://www.youtube.com/hashtag/funny"
        ]
        search_target = random.choice(feed_sources)

    items = []

    def _fetch():
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                res = ydl.extract_info(search_target, download=False)
                entries = res.get("entries", [])
                if entries:
                    for e in entries:
                        if e and e.get("id"):
                            items.append({
                                "id": e["id"],
                                "title": e.get("title", ""),
                                "url": f"https://www.youtube.com/shorts/{e['id']}",
                                "uploader": e.get("uploader", "YouTube"),
                                "duration": e.get("duration", 0)
                            })
            except Exception:
                pass

    await asyncio.to_thread(_fetch)
    return items

async def download_short_video(url: str) -> tuple[bytes | None, dict]:
    """Скачивает конкретный YouTube Short и возвращает байты и метаданные."""
    meta = {
        "title": "",
        "uploader": "",
        "duration": 0,
        "url": url,
        "id": ""
    }

    temp_path = TEMP_DIR / f"yt_{int(time.time())}_{random.randint(1000, 9999)}.mp4"
    opts = get_ydl_base_opts()
    opts['outtmpl'] = str(temp_path)
    opts['overwrites'] = True

    info = None
    def _run():
        nonlocal info
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

    try:
        await asyncio.to_thread(_run)
    except Exception:
        return None, meta

    # Поиск скачанного файла
    v_bytes = None
    for f in TEMP_DIR.glob(f"{temp_path.stem}*"):
        try:
            if f.stat().st_size > 5000:
                v_bytes = f.read_bytes()
                f.unlink()
                if info:
                    meta.update({
                        "title": str(info.get("title", ""))[:200],
                        "uploader": info.get("uploader", ""),
                        "duration": info.get("duration", 0),
                        "id": str(info.get("id", "")),
                        "url": f"https://www.youtube.com/shorts/{info.get('id')}" if info.get("id") else url
                    })
                return v_bytes, meta
            f.unlink()
        except Exception:
            pass

    return None, meta

async def get_next_short(query: str = "") -> tuple[bytes | None, dict]:
    """
    Возвращает следующее видео из очереди Shorts или по поисковому запросу.
    При сбое автоматически пробует следующее видео.
    """
    global _shorts_queue, _seen_shorts_ids

    candidates = []
    if query:
        candidates = await fetch_shorts_by_query(query)
    else:
        if not _shorts_queue:
            new_batch = await fetch_shorts_by_query()
            fresh = [v for v in new_batch if v["id"] not in _seen_shorts_ids]
            if not fresh:
                _seen_shorts_ids.clear()
                fresh = new_batch
            _shorts_queue.extend(fresh)
        candidates = _shorts_queue

    for candidate in candidates[:5]:
        v_id = candidate["id"]
        _seen_shorts_ids.add(v_id)
        if len(_seen_shorts_ids) > 500:
            _seen_shorts_ids.clear()

        if not query and candidate in _shorts_queue:
            _shorts_queue.remove(candidate)

        v_bytes, meta = await download_short_video(candidate["url"])
        if v_bytes and len(v_bytes) > 5000:
            if not meta.get("title"):
                meta.update(candidate)
            return v_bytes, meta

    return None, {}

def format_caption(meta: dict, elapsed: float, query: str = "") -> str:
    parts = []
    
    badge = f"🔍 **Shorts по запросу:** `{query}`" if query else "▶️ **YouTube Shorts**"
    if meta.get("uploader"):
        parts.append(f"{badge} • **{meta['uploader']}**")
    else:
        parts.append(badge)

    if meta.get("title"):
        title = meta["title"].strip()
        if len(title) > 160:
            title = title[:157] + "..."
        parts.append(f"\n📝 {title}")

    info_bits = []
    if meta.get("duration"):
        mins = int(meta["duration"]) // 60
        secs = int(meta["duration"]) % 60
        info_bits.append(f"⏱ {mins}:{secs:02d}" if mins else f"⏱ {secs}с")

    info_bits.append(f"⚡ {elapsed:.1f}s")
    if info_bits:
        parts.append("\n" + " • ".join(info_bits))

    if meta.get("url"):
        parts.append(f"\n🔗 [Смотреть на YouTube]({meta['url']})")

    return "\n".join(parts)

# ===================== КОМАНДЫ ЮЗЕРБОТА =====================

@core.command("shorts", description="Листать YouTube Shorts или скачать по ссылке/теме", usage=".shorts [ссылка/тема/login/me/help]")
async def shorts_cmd(event: events.NewMessage.Event):
    """
    Главная команда модуля YouTube Shorts.
    - .shorts            — Листать рекомендации Shorts
    - .shorts <тема>     — Найти Shorts по теме (например .shorts мемы)
    - .shorts <ссылка>   — Скачать Shorts видео в HD
    - .shorts login      — Привязать куки аккаунта YouTube
    - .shorts me         — Статус аккаунта
    - .shorts logout     — Выйти из аккаунта
    """
    raw = event.raw_text or ""
    parts = raw.split(maxsplit=1)
    subcmd = parts[1].strip() if len(parts) > 1 else ""

    t0 = time.time()

    # --- Подкоманда: HELP ---
    if subcmd.lower() in ("help", "помощь", "инфо"):
        is_acc = "✅ Авторизован" if COOKIES_FILE.exists() else "❌ Гостевой режим"
        help_text = (
            "🎬 **YOUTUBE SHORTS МОДУЛЬ**\n\n"
            f"👤 **Статус аккаунта:** `{is_acc}`\n\n"
            "✨ **Команды:**\n"
            "• `.shorts` (или `.sh`) — Листать персональные рекомендации Shorts\n"
            "• `.shorts <тема>` — Найти Shorts по теме (например `.shorts мемы`, `.shorts котики`, `.shorts игры`)\n"
            "• `.shorts <ссылка>` — Скачать Shorts видео в HD\n"
            "• `.shorts login <куки_текст>` — Привязать YouTube аккаунт\n"
            "• `.shorts me` — Проверить статус аккаунта\n"
            "• `.shorts logout` — Отвязать аккаунт\n"
        )
        await event.edit(help_text)
        return

    # --- Подкоманда: LOGIN ---
    if subcmd.lower().startswith("login "):
        cookie_content = subcmd.split(maxsplit=1)[1].strip()
        if len(cookie_content) < 20:
            await event.edit("❌ **Ошибка:** Слишком короткий текст куков.")
            return

        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write(cookie_content)

        save_session_info({"is_logged_in": True, "last_login": time.time()})
        _shorts_queue.clear()
        _seen_shorts_ids.clear()

        await event.edit("🎉 **YouTube аккаунт успешно привязан!**\nТеперь пиши `.shorts` для персональных рекомендаций.")
        return

    # --- Подкоманда: LOGOUT ---
    if subcmd.lower() in ("logout", "unlogin", "выйти"):
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()
        save_session_info({"is_logged_in": False, "last_login": 0})
        _shorts_queue.clear()
        _seen_shorts_ids.clear()
        await event.edit("🚪 **Аккаунт YouTube отвязан.**")
        return

    # --- Подкоманда: ME ---
    if subcmd.lower() in ("me", "account", "аккаунт"):
        has_c = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 10
        text = (
            "👤 **СТАТУС YOUTUBE АККАУНТА**\n\n"
            f"📊 **Статус:** `{'🟢 Авторизован' if has_c else '🔴 Гостевой режим'}`\n"
            f"📥 **В очереди Shorts:** `{len(_shorts_queue)}` шт.\n\n"
            "💡 *Команды: `.shorts` — листать, `.shorts мемы` — поиск по теме.*"
        )
        await event.edit(text)
        return

    # --- РЕЖИМ 1: СКАЧИВАНИЕ ПО ССЫЛКЕ ---
    yt_url = extract_youtube_url(subcmd)
    if not yt_url:
        try:
            reply = await event.get_reply_message()
            if reply and reply.raw_text:
                yt_url = extract_youtube_url(reply.raw_text)
        except Exception:
            pass

    if yt_url:
        await event.edit("📥 **Скачиваю YouTube Shorts...**")
        v_bytes, meta = await download_short_video(yt_url)
        elapsed = time.time() - t0

        if not v_bytes:
            await event.edit("❌ **Не удалось скачать видео.** Возможно, видео ограничено или приватное.")
            return

        caption = format_caption(meta, elapsed)
        v_file = io.BytesIO(v_bytes)
        v_file.name = f"shorts_{meta.get('id', 'video')}.mp4"

        try:
            await event.client.send_file(
                event.chat_id,
                v_file,
                caption=caption,
                reply_to=event.reply_to_msg_id,
                supports_streaming=True
            )
            await event.delete()
        except Exception as e:
            await event.edit(f"❌ **Ошибка отправки:** `{e}`")
        return

    # --- РЕЖИМ 2: ПОИСК ПО ТЕМЕ ИЛИ ЛИСТАНИЕ РЕКОМЕНДАЦИЙ ---
    search_query = subcmd if (subcmd and not subcmd.lower().startswith("rec")) else ""
    if search_query:
        status_msg = f"🔍 **Ищу Shorts по запросу:** `{search_query}`..."
    else:
        has_c = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 10
        status_msg = "📱 **Листаю рекомендации YouTube Shorts...**" if has_c else "🔥 **Ищу свежий YouTube Short...**"

    await event.edit(status_msg)

    v_bytes, meta = await get_next_short(query=search_query)
    elapsed = time.time() - t0

    if not v_bytes:
        await event.edit("⚠️ **Не удалось загрузить Short.** Попробуй еще раз через пару секунд.")
        return

    caption = format_caption(meta, elapsed, query=search_query)
    v_file = io.BytesIO(v_bytes)
    v_file.name = f"shorts_{meta.get('id', 'rec')}.mp4"

    try:
        await event.client.send_file(
            event.chat_id,
            v_file,
            caption=caption,
            reply_to=event.reply_to_msg_id,
            supports_streaming=True
        )
        await event.delete()
    except Exception as e:
        await event.edit(f"❌ **Ошибка отправки:** `{e}`")

@core.command("sh", description="Алиас для .shorts", usage=".sh")
async def sh_alias_cmd(event: events.NewMessage.Event):
    """Алиас для команды .shorts."""
    await shorts_cmd(event)
