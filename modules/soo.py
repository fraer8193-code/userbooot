import asyncio
from telethon import events
from telethon.tl.types import (
    Channel,
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
    description="Моментальный подсчет сообщений",
    usage=f"{CMD_PREFIX}soo [reply | @user | id | all]"
)
async def soo_cmd(event: events.NewMessage.Event):
    """
    Моментальный подсчет сообщений в текущем чате (любого размера, хоть 1 000 000+).
    Работает мгновенно через серверные индексы Telegram (limit=0).
    """
    client = event.client
    raw_args = event.raw_text.split(maxsplit=1)
    query = raw_args[1].strip() if len(raw_args) > 1 else ""

    chat = await event.get_chat()
    chat_title = getattr(chat, "title", None) or getattr(chat, "first_name", "Чат")

    # Режим расширенной статистики по типам (.soo all / .soo chat)
    if query.lower() in ("all", "chat", "все", "чат", "stats", "стата"):
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

        total_cnt = extract_count(results[0])
        photos_cnt = extract_count(results[1])
        video_cnt = extract_count(results[2])
        voice_cnt = extract_count(results[3])
        round_cnt = extract_count(results[4])
        doc_cnt = extract_count(results[5])
        music_cnt = extract_count(results[6])
        url_cnt = extract_count(results[7])

        stats_text = (
            f"📊 **Сообщения в** «**{chat_title}**»\n\n"
            f"💬 **Всего:** `{format_num(total_cnt)}`\n"
            f"📷 **Фото:** `{format_num(photos_cnt)}`\n"
            f"🎥 **Видео:** `{format_num(video_cnt)}`\n"
            f"🎤 **Голосовые:** `{format_num(voice_cnt)}`\n"
            f"📹 **Кружочки:** `{format_num(round_cnt)}`\n"
            f"📁 **Файлы:** `{format_num(doc_cnt)}`\n"
            f"🎵 **Музыка:** `{format_num(music_cnt)}`\n"
            f"🔗 **Ссылки:** `{format_num(url_cnt)}`"
        )
        await event.edit(stats_text)
        return

    # Личные сообщения (PM)
    if event.is_private:
        chat_res = await client.get_messages(event.chat_id, 0)
        total_cnt = extract_count(chat_res)
        pm_name = get_display_name(chat) or "Собеседник"

        pm_text = (
            f"💬 **Диалог с** [{pm_name}](tg://user?id={event.chat_id})\n"
            f"✉️ **Всего сообщений:** `{format_num(total_cnt)}`"
        )
        await event.edit(pm_text)
        return

    # Каналы (вещательные)
    if isinstance(chat, Channel) and getattr(chat, "broadcast", False):
        chat_res = await client.get_messages(event.chat_id, 0)
        total_cnt = extract_count(chat_res)

        chan_text = (
            f"📢 **Канал:** «**{chat_title}**»\n"
            f"✉️ **Всего сообщений:** `{format_num(total_cnt)}`"
        )
        await event.edit(chan_text)
        return

    # Группы и супергруппы
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
        target_id_or_user = int(query) if query.lstrip("-").isdigit() else query
        try:
            target_user = await client.get_entity(target_id_or_user)
        except Exception:
            target_user = None
    else:
        target_user = me
        is_me = True

    if target_user and target_user.id == me.id:
        is_me = True

    # Моментальные параллельные запросы общего числа сообщений и сообщений пользователя
    tasks = [client.get_messages(event.chat_id, 0)]
    if target_user:
        tasks.append(client.get_messages(event.chat_id, 0, from_user=target_user))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    chat_total = extract_count(results[0])
    user_total = 0
    user_fetch_ok = False

    if len(results) > 1 and not isinstance(results[1], Exception):
        user_total = extract_count(results[1])
        user_fetch_ok = True

    percent = (user_total / chat_total * 100) if chat_total > 0 else 0.0

    if user_fetch_ok and target_user:
        if is_me:
            user_label = "Ваших сообщений"
        else:
            user_name = get_display_name(target_user) or "пользователя"
            user_label = f"Сообщений [{user_name}](tg://user?id={target_user.id})"

        result_text = (
            f"💬 **Чат:** «**{chat_title}**»\n"
            f"✉️ **Всего сообщений:** `{format_num(chat_total)}`\n"
            f"👤 **{user_label}:** `{format_num(user_total)}` (`{percent:.2f}%`)"
        )
    else:
        result_text = (
            f"💬 **Чат:** «**{chat_title}**»\n"
            f"✉️ **Всего сообщений:** `{format_num(chat_total)}`"
        )

    await event.edit(result_text)
