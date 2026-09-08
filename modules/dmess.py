import os
import json
import logging
import collections
from datetime import datetime
from telethon import events
import core

logger = logging.getLogger("Femboy.Dmess")

# Максимальное количество сообщений в кэше
MAX_CACHE_SIZE = 10000

# Структура кэша: msg_id -> dict
message_cache = collections.OrderedDict()

# Файл состояния
STATE_FILE = "dmess_state.json"
is_enabled = True
target_chat_id = None  # None = со всех чатов/каналов/ЛС
target_chat_title = None

def load_state():
    global is_enabled, target_chat_id, target_chat_title
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                is_enabled = data.get("enabled", True)
                target_chat_id = data.get("target_chat_id", None)
                target_chat_title = data.get("target_chat_title", None)
        except Exception:
            is_enabled = True
            target_chat_id = None
            target_chat_title = None

def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "enabled": is_enabled,
                "target_chat_id": target_chat_id,
                "target_chat_title": target_chat_title
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

load_state()

# --- Обработчик сохранения входящих сообщений ---

async def on_new_message(event: events.NewMessage.Event):
    if not is_enabled:
        return

    # Не кэшируем свои исходящие сообщения
    if event.out:
        return

    try:
        msg = event.message
        if not msg:
            return

        chat_id = event.chat_id
        
        # Если задан конкретный канал/чат и сообщение не из него — пропускаем
        if target_chat_id is not None and chat_id != target_chat_id:
            return

        msg_id = event.id
        sender_id = event.sender_id

        # Быстрое получение имени отправителя
        sender_name = "Пользователь"
        try:
            sender = event.sender
            if sender:
                fname = getattr(sender, "first_name", "") or ""
                lname = getattr(sender, "last_name", "") or ""
                full = f"{fname} {lname}".strip()
                uname = getattr(sender, "username", "")
                if uname:
                    sender_name = f"{full} (@{uname})" if full else f"@{uname}"
                elif full:
                    sender_name = full
                else:
                    sender_name = str(sender_id)
            elif sender_id:
                sender_name = str(sender_id)
        except Exception:
            sender_name = str(sender_id)

        # Название чата или канала
        chat_title = "Личные сообщения (ЛС)"
        try:
            chat = event.chat
            if chat and hasattr(chat, "title") and chat.title:
                chat_title = chat.title
            elif not event.is_private:
                chat_title = f"Чат ID: {chat_id}"
        except Exception:
            pass

        text_content = msg.message or ""

        # Сохраняем в кэш
        message_cache[msg_id] = {
            "text": text_content,
            "sender_name": sender_name,
            "sender_id": sender_id,
            "chat_title": chat_title,
            "chat_id": chat_id,
            "date": datetime.now().strftime("%H:%M:%S"),
            "has_media": bool(msg.media),
            "media": msg.media
        }

        # Ограничение размера кэша
        if len(message_cache) > MAX_CACHE_SIZE:
            message_cache.popitem(last=False)

    except Exception as e:
        logger.error(f"Ошибка кэширования сообщения: {e}")

# --- Обработчик удаления сообщений ---

async def on_message_deleted(event: events.MessageDeleted.Event):
    if not is_enabled:
        return

    client = event.client
    event_chat_id = event.chat_id

    # Если удаление произошло в конкретном чате и задан фильтр, который не совпадает
    if target_chat_id is not None and event_chat_id is not None and event_chat_id != target_chat_id:
        return

    try:
        for msg_id in event.deleted_ids:
            if msg_id in message_cache:
                data = message_cache[msg_id]
                
                # Проверка фильтра по чату из кэша
                if target_chat_id is not None and data["chat_id"] != target_chat_id:
                    continue

                text_content = data["text"] if data["text"] else "*(Медиа / стикер / без текста)*"
                
                log_text = (
                    "🗑️ **Удаленное сообщение**\n"
                    f"👤 **От:** {data['sender_name']} (`{data['sender_id']}`)\n"
                    f"💬 **Чат/Канал:** {data['chat_title']}\n"
                    f"🕒 **Время:** `{data['date']}`\n\n"
                    f"📝 **Текст:**\n{text_content}"
                )
                
                logger.info(f"Обнаружено удаление сообщения {msg_id} в {data['chat_title']}")

                try:
                    if data["has_media"] and data["media"]:
                        try:
                            await client.send_message("me", log_text, file=data["media"])
                        except Exception:
                            await client.send_message("me", log_text)
                    else:
                        await client.send_message("me", log_text)
                except Exception as e:
                    logger.error(f"Не удалось отправить удаленное сообщение в 'me': {e}")
    except Exception as e:
        logger.error(f"Ошибка в on_message_deleted: {e}")

# --- Регистрация хуков модуля ---

_handlers_registered = False

def on_load(manager):
    global _handlers_registered
    if not _handlers_registered:
        manager.client.add_event_handler(on_new_message, events.NewMessage(incoming=True))
        manager.client.add_event_handler(on_message_deleted, events.MessageDeleted())
        _handlers_registered = True
        logger.info("Хэндлеры dmess успешно подключены к клиенту.")

def on_unload(manager):
    global _handlers_registered
    if _handlers_registered:
        manager.client.remove_event_handler(on_new_message, events.NewMessage(incoming=True))
        manager.client.remove_event_handler(on_message_deleted, events.MessageDeleted())
        _handlers_registered = False
        logger.info("Хэндлеры dmess отключены.")

# --- Команда переключения ---

@core.command("dmess", description="Toggle or set channel for deleted messages logger", usage=".dmess [канал/@username/пусто]")
async def dmess_cmd(event: events.NewMessage.Event):
    """
    Бесшумно настраивает перехват удаленных сообщений.
    - .dmess — перехватывать отовсюду (все чаты, группы, каналы, ЛС) или выключить.
    - .dmess @канал (или ссылка) — перехватывать только из указанного канала/чата.
    """
    global is_enabled, target_chat_id, target_chat_title
    
    args = event.raw_text.split(maxsplit=1)
    
    # Моментально удаляем сообщение с командой из текущего чата
    try:
        await event.delete()
    except Exception:
        pass

    # Если указан конкретный канал / чат (.dmess @channel или .dmess -100xxxx)
    if len(args) > 1:
        target_raw = args[1].strip()
        try:
            entity = await event.client.get_entity(target_raw)
            target_chat_id = entity.id
            target_chat_title = getattr(entity, "title", None) or getattr(entity, "first_name", str(entity.id))
            is_enabled = True
            save_state()
            
            notify_text = (
                "🗑️ **Логер удаленных сообщений (.dmess):** `ВКЛЮЧЕН`\n"
                f"🎯 **Фильтр:** Только для `{target_chat_title}` (`{target_chat_id}`)"
            )
            await event.client.send_message("me", notify_text)
            return
        except Exception as e:
            await event.client.send_message("me", f"❌ **Ошибка поиска канала `{target_raw}`:**\n`{e}`")
            return

    # Если вызвано просто .dmess:
    # Если был включен конкретный канал, сбрасываем на "Отовсюду"
    if target_chat_id is not None:
        target_chat_id = None
        target_chat_title = None
        is_enabled = True
        save_state()
        notify_text = "🗑️ **Логер удаленных сообщений (.dmess):** `ВКЛЮЧЕН (Отовсюду: все чаты, каналы, группы и ЛС)`"
    else:
        # Обычный тоггл ВКЛ / ВЫКЛ для всех чатов
        is_enabled = not is_enabled
        save_state()
        status_str = "ВКЛЮЧЕН (Отовсюду: все чаты, каналы, группы и ЛС)" if is_enabled else "ВЫКЛЮЧЕН"
        notify_text = f"🗑️ **Логер удаленных сообщений (.dmess):** `{status_str}`"

    try:
        await event.client.send_message("me", notify_text)
    except Exception:
        pass
