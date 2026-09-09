import time
import asyncio
from telethon import events
from telethon.tl.types import (
    Channel,
    Chat,
    User,
    InputMessagesFilterPhotos,
    InputMessagesFilterVideo,
    InputMessagesFilterDocument,
    InputMessagesFilterMusic,
    InputMessagesFilterVoice,
    InputMessagesFilterRoundVideo,
    InputMessagesFilterUrl
)
from telethon.utils import get_display_name
import core
from config import CMD_PREFIX


def format_num(n: int | float | None) -> str:
    """Форматирует число с разделителями тысяч (например, 1 254 890)."""
    if n is None:
        return "0"
    return f"{int(n):,}".replace(",", " ")


def extract_count(result) -> int:
    """Извлекает поле total из ответа Telethon TotalList."""
    if isinstance(result, Exception) or result is None:
        return 0
    return getattr(result, "total", 0) or 0


@core.command(
    "soo",
    description="Моментальный подсчет сообщений (даже при 1 000 000+ соо)",
    usage=f"{CMD_PREFIX}soo [reply | @user | id | all | help]"
)
async def soo_cmd(event: events.NewMessage.Event):
    """
    Моментальный подсчет сообщений в текущем чате (любого размера, хоть 1 000 000+).
    Работает мгновенно через серверные индексы Telegram (limit=0).
    """
    client = event.client
    raw_args = event.raw_text.split(maxsplit=1)
    query = raw_args[1].strip() if len(raw_args) > 1 else ""

    # Справка по команде
    if query.lower() in ("help", "помощь", "?"):
        help_text = (
            f"📊 **Модуль моментального подсчета сообщений (`{CMD_PREFIX}soo`)**\n\n"
            f"⚡ **Как использовать:**\n"
            f"• `{CMD_PREFIX}soo` — подсчет ваших сообщений и общего числа в чате\n"
            f"• `{CMD_PREFIX}soo` (в ответ на соо) — подсчет сообщений отвеченного пользователя\n"
            f"• `{CMD_PREFIX}soo @username` или `ID` — подсчет сообщений указанного пользователя\n"
            f"• `{CMD_PREFIX}soo all` (или `chat`) — моментальная статистика чата по медиа\n"
            f"• `{CMD_PREFIX}soo help` — эта справка\n\n"
            f"🚀 **Особенность:** Подсчет идет напрямую через серверные базы Telegram (`limit=0`), "
            f"поэтому результат выводится **моментально** (~50–150 мс) даже в чатах на **миллионы сообщений**!"
        )
        await event.edit(help_text)
        return

    chat = await event.get_chat()
    chat_title = getattr(chat, "title", None) or getattr(chat, "first_name", "Чат")

    # Режим расширенной статистики по типам медиа (.soo all / .soo chat)
    if query.lower() in ("all", "chat", "все", "чат", "stats", "стата"):
        await event.edit("⚡ **Моментальный сбор статистики чата...**")
        t_start = time.perf_counter()

        tasks = [
            client.get_messages(event.chat_id, 0),
            client.get_messages(event.chat_id, 0, filter=InputMessagesFilterPhotos),
            client.get_messages(event.chat_id, 0, filter=InputMessagesFilterVideo),
            client.get_messages(event.chat_id, 0, filter=InputMessagesFilterVoice),
            client.get_messages(event.chat_id, 0, filter=InputMessagesFilterRoundVideo),
            client.get_messages(event.chat_id, 0, filter=InputMessagesFilterDocument),
            client.get_messages(event.chat_id, 0, filter=InputMessagesFilterMusic),
            client.get_messages(event.chat_id, 0, filter=InputMessagesFilterUrl),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        total_cnt = extract_count(results[0])
        photos_cnt = extract_count(results[1])
        video_cnt = extract_count(results[2])
        voice_cnt = extract_count(results[3])
        round_cnt = extract_count(results[4])
        doc_cnt = extract_count(results[5])
        music_cnt = extract_count(results[6])
        url_cnt = extract_count(results[7])

        stats_text = (
            f"📊 **Статистика чата:** «**{chat_title}**»\n\n"
            f"💬 **Всего сообщений:** `{format_num(total_cnt)}`\n"
            f"📷 **Фотографий:** `{format_num(photos_cnt)}`\n"
            f"🎥 **Видео:** `{format_num(video_cnt)}`\n"
            f"🎤 **Голосовых (ГС):** `{format_num(voice_cnt)}`\n"
            f"📹 **Видеосообщений (кружков):** `{format_num(round_cnt)}`\n"
            f"📁 **Файлов / Документов:** `{format_num(doc_cnt)}`\n"
            f"🎵 **Аудиозаписей:** `{format_num(music_cnt)}`\n"
            f"🔗 **Ссылок:** `{format_num(url_cnt)}`\n\n"
            f"⚡ **Скорость:** `{elapsed_ms:.2f} ms`"
        )
        await event.edit(stats_text)
        return

    # Обычный режим (.soo): определяем цель (пользователя)
    me = await client.get_me()
    target_user = None
    is_me = False

    if event.is_reply:
        try:
            reply_msg = await event.get_reply_message()
            target_user = await reply_msg.get_sender()
        except Exception:
            target_user = None
    elif query:
        # Поиск по юзернейму или числовому ID
        target_id_or_user = int(query) if query.lstrip("-").isdigit() else query
        try:
            target_user = await client.get_entity(target_id_or_user)
        except Exception as e:
            await event.edit(f"❌ **Пользователь `{query}` не найден:**\n`{e}`")
            return
    else:
        target_user = me
        is_me = True

    if target_user and target_user.id == me.id:
        is_me = True

    # Личные сообщения (PM)
    if event.is_private:
        t_start = time.perf_counter()
        chat_res = await client.get_messages(event.chat_id, 0)
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        total_cnt = extract_count(chat_res)

        pm_name = get_display_name(chat) or "Собеседник"
        pm_text = (
            f"💬 **Личный диалог:** [{pm_name}](tg://user?id={event.chat_id})\n\n"
            f"✉️ **Всего сообщений в диалоге:** `{format_num(total_cnt)}`\n"
            f"ℹ️ _В личных переписках Telegram API не предоставляет серверный фильтр по конкретному автору._\n\n"
            f"⚡ **Скорость:** `{elapsed_ms:.2f} ms`"
        )
        await event.edit(pm_text)
        return

    # Каналы (вещательные, где нет сообщений конкретных пользователей)
    if isinstance(chat, Channel) and getattr(chat, "broadcast", False):
        t_start = time.perf_counter()
        chat_res = await client.get_messages(event.chat_id, 0)
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        total_cnt = extract_count(chat_res)

        chan_text = (
            f"📢 **Канал:** «**{chat_title}**»\n\n"
            f"💬 **Всего постов в канале:** `{format_num(total_cnt)}`\n\n"
            f"⚡ **Скорость:** `{elapsed_ms:.2f} ms`"
        )
        await event.edit(chan_text)
        return

    # Группы и супергруппы
    t_start = time.perf_counter()

    # Параллельный серверный запрос общего числа сообщений и сообщений пользователя
    tasks = [client.get_messages(event.chat_id, 0)]
    if target_user:
        tasks.append(client.get_messages(event.chat_id, 0, from_user=target_user))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed_ms = (time.perf_counter() - t_start) * 1000

    chat_res = results[0]
    chat_total = extract_count(chat_res)

    user_total = 0
    user_fetch_ok = False
    if len(results) > 1 and not isinstance(results[1], Exception):
        user_total = extract_count(results[1])
        user_fetch_ok = True

    # Расчет процента
    percent = (user_total / chat_total * 100) if chat_total > 0 else 0.0

    # Оформление информации о пользователе
    if target_user:
        user_name = get_display_name(target_user) or "Пользователь"
        user_mention = f"[{user_name}](tg://user?id={target_user.id})"
        if getattr(target_user, "username", None):
            user_mention += f" (@{target_user.username})"
        label = "Вы" if is_me else "Пользователь"
        user_id_str = f"`{target_user.id}`"
    else:
        user_mention = "Неизвестно"
        label = "Пользователь"
        user_id_str = "—"

    if user_fetch_ok:
        result_text = (
            f"📊 **Подсчет сообщений**\n\n"
            f"💬 **Чат:** «**{chat_title}**»\n"
            f"👤 **{label}:** {user_mention}\n"
            f"🆔 **ID:** {user_id_str}\n\n"
            f"✉️ **Сообщений:** `{format_num(user_total)}`\n"
            f"📈 **Доля в чате:** `{percent:.2f}%`\n"
            f"🌐 **Всего в чате:** `{format_num(chat_total)}`\n\n"
            f"⚡ **Скорость:** `{elapsed_ms:.2f} ms`"
        )
    else:
        result_text = (
            f"📊 **Подсчет сообщений**\n\n"
            f"💬 **Чат:** «**{chat_title}**»\n"
            f"🌐 **Всего сообщений в чате:** `{format_num(chat_total)}`\n\n"
            f"⚡ **Скорость:** `{elapsed_ms:.2f} ms`"
        )

    await event.edit(result_text)
