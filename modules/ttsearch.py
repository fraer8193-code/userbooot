"""
TikTok Search Module — поиск видео TikTok по названию или описанию.

Возможности:
  .ttsh <запрос>        — Найти видео по названию/описанию и отправить первое
  .ttsh <запрос> [N]    — Отправить N-й результат из найденных (1-5)
  .ttsh #хештег         — Поиск по хештегу: найдет видео с указанным # в описании

Поиск работает через публичный API TikWM: находит видео по тексту в названии,
описании и хештегах, затем скачивает ролик без водяного знака.
"""

import io
import re
import time
import aiohttp
from telethon import events
import core

# ===================== КОНФИГУРАЦИЯ =====================

TIKWM_SEARCH_BASE = "https://www.tikwm.com/api/feed/search"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.tiktok.com/",
}

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=90, connect=10)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

MAX_RESULTS_SHOWN = 5

HASHTAG_RE = re.compile(r"#([\w\u0400-\u04FF]+)")


# ===================== ПОИСК ВИДЕО =====================

async def search_tiktok_videos(query: str, count: int = 12) -> list:
    """Ищет видео TikTok по запросу (название/описание/хештеги) через TikWM API."""
    results = []
    params = {"keywords": query, "count": str(count), "hd": "1"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TIKWM_SEARCH_BASE, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status != 200:
                    return []
                res = await resp.json(content_type=None)
                if res.get("code") != 0:
                    return []
                videos = (res.get("data") or {}).get("videos") or []
    except Exception:
        return []

    for v in videos:
        if not isinstance(v, dict):
            continue

        v_id = str(v.get("id") or v.get("video_id") or "").strip()
        if not v_id:
            continue

        author = v.get("author") or {}
        uname = author.get("unique_id") or author.get("uniqueId") or "" if isinstance(author, dict) else str(author)
        nick = author.get("nickname") or uname if isinstance(author, dict) else uname

        play = v.get("hdplay") or v.get("play") or ""
        alt = v.get("play") if play != v.get("play") else v.get("hdplay") or ""
        music = v.get("music_info") or {}
        music_title = music.get("title", "") if isinstance(music, dict) else str(music or "")

        results.append({
            "video_id": v_id,
            "title": str(v.get("title") or v.get("desc") or "").strip(),
            "author": uname,
            "author_name": nick or uname,
            "duration": v.get("duration", 0),
            "music": music_title,
            "play_url": play,
            "alt_play_url": alt,
            "original_url": f"https://www.tiktok.com/@{uname}/video/{v_id}" if uname else f"https://www.tiktok.com/video/{v_id}",
        })

    return results


async def download_video_bytes(play_url: str) -> bytes | None:
    """Скачивает видео с CDN TikWM по прямой ссылке."""
    if not play_url:
        return None
    if play_url.startswith("/"):
        play_url = "https://www.tikwm.com" + play_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(play_url, headers=HEADERS, timeout=DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                total_size = 0
                chunks = []
                async for chunk in resp.content.iter_chunked(65536):
                    chunks.append(chunk)
                    total_size += len(chunk)
                    if total_size > MAX_FILE_SIZE:
                        return None
                data = b"".join(chunks)
                return data if len(data) > 5000 else None
    except Exception:
        return None


def _format_search_caption(meta: dict, elapsed: float, position: int, total: int) -> str:
    """Формирует подпись к найденному видео."""
    parts = [f"🔎 **TikTok Поиск** — результат {position}/{total}"]

    author = meta.get("author", "")
    if author:
        display = str(meta.get("author_name") or author)[:40]
        parts.append(f"👤 [{display}](https://www.tiktok.com/@{author})")

    title = str(meta.get("title", "")).strip()
    if title:
        if len(title) > 350:
            title = title[:345] + "..."
        parts.append(f"\n📝 {title}")

    info_bits = []
    if meta.get("duration"):
        mins = int(meta["duration"]) // 60
        secs = int(meta["duration"]) % 60
        info_bits.append(f"⏱ {mins}:{secs:02d}" if mins else f"⏱ {secs}с")
    if meta.get("music"):
        info_bits.append(f"🎵 {str(meta['music'])[:35]}")
    info_bits.append(f"⚡ {elapsed:.1f}s")
    parts.append("\n" + " • ".join(info_bits))

    if meta.get("original_url"):
        parts.append(f"\n🔗 [Смотреть в TikTok]({meta['original_url']})")

    if total > 1:
        parts.append(f"\n💡 Другие результаты: `.ttsh <запрос> 2` (до {MAX_RESULTS_SHOWN})")

    res = "\n".join(parts)
    if len(res) > 950:
        res = res[:940] + "..."
    return res


# ===================== КОМАНДА ЮЗЕРБОТА =====================

@core.command("ttsh", description="Поиск видео TikTok по названию/описанию/#хештегу", usage=".ttsh <запрос|#хештег> [N]")
async def ttsh_cmd(event: events.NewMessage.Event):
    """
    Ищет видео в TikTok по названию, описанию или хештегу.
    - .ttsh котики смешные     — поиск по названию/описанию
    - .ttsh #котики            — поиск видео с хештегом
    - .ttsh <запрос> 2         — отправить 2-й результат из найденных
    """
    raw = event.raw_text or ""
    parts = raw.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await event.edit(
            "🔎 **Поиск видео в TikTok**\n\n"
            "• `.ttsh <запрос>` — найти видео по названию/описанию\n"
            "• `.ttsh #хештег` — найти видео по хештегу в описании\n"
            "• `.ttsh <запрос> 2` — отправить 2-й результат (до 5)"
        )
        return

    query = parts[1].strip()

    # Опциональный номер результата в конце запроса
    index = 1
    m = re.search(r"\s+(\d{1,2})$", query)
    if m:
        index = int(m.group(1))
        query = query[:m.start()].strip()

    if not query:
        await event.edit("❌ **Укажи поисковый запрос** после `.ttsh`.")
        return

    t0 = time.time()

    # Извлекаем хештеги для приоритетной фильтрации результатов
    tags = [t.lower() for t in HASHTAG_RE.findall(query)]

    try:
        await event.edit("🔎 **Ищу видео в TikTok...**")
    except Exception:
        pass

    results = await search_tiktok_videos(query)

    # Если запрос с хештегом — приоритет видео, у которых # есть в описании
    if tags and results:
        strict = [
            v for v in results
            if all(tag in str(v.get("title", "")).lower() for tag in tags)
        ]
        if strict:
            results = strict

    if not results:
        await event.edit(
            "😕 **Ничего не найдено.**\n"
            "Попробуй другой запрос или проверь написание хештега."
        )
        return

    if index < 1 or index > MAX_RESULTS_SHOWN:
        index = 1
    if index > len(results):
        index = len(results)

    chosen = results[index - 1]

    try:
        await event.edit(f"📥 **Скачиваю найденное видео ({index}/{len(results)})...**")
    except Exception:
        pass

    video_bytes = await download_video_bytes(chosen.get("play_url") or chosen.get("alt_play_url"))

    if not video_bytes:
        await event.edit("❌ **Не удалось скачать видео.** Попробуй другой результат: `.ttsh <запрос> 2`.")
        return

    elapsed = time.time() - t0
    caption = _format_search_caption(chosen, elapsed, index, len(results))

    video_file = io.BytesIO(video_bytes)
    video_file.name = f"ttsearch_{chosen.get('video_id', 'video')}.mp4"

    try:
        await event.client.send_file(
            event.chat_id,
            video_file,
            caption=caption,
            reply_to=event.reply_to_msg_id,
            supports_streaming=True
        )
        await event.delete()
    except Exception as e:
        if "caption is too long" in str(e).lower():
            try:
                video_file.seek(0)
                await event.client.send_file(
                    event.chat_id,
                    video_file,
                    caption=f"🔎 **TikTok Поиск** • ⚡ {elapsed:.1f}s",
                    reply_to=event.reply_to_msg_id,
                    supports_streaming=True
                )
                await event.delete()
            except Exception as e2:
                await event.edit(f"❌ **Ошибка при отправке:** `{e2}`")
        else:
            await event.edit(f"❌ **Ошибка при отправке:** `{e}`")
