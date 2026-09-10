"""
Rofl Module — «рофл-язык» для исходящих сообщений.

Возможности:
  .rofl    — Включить режим: в каждом твоём сообщении после каждой 3-й буквы
             будет вставляться случайный эмодзи из всех доступных.
  .rofl    — Повторный ввод деактивирует режим.

Состояние сохраняется между перезапусками бота (rofl_state.json).
"""

import os
import json
import random
import asyncio
import logging
from telethon import events
import core

logger = logging.getLogger("Femboy.Rofl")

STATE_FILE = "rofl_state.json"
is_enabled = False

# ===================== ПУЛ ЭМОДЗИ («все доступные») =====================

EMOJIS = [
    "😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂", "🙂", "🙃",
    "😉", "😊", "😇", "🥰", "😍", "🤩", "😘", "😗", "😚", "😙",
    "🥲", "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🤫",
    "🤔", "🤐", "🤨", "😐", "😑", "😶", "😏", "😒", "🙄", "😬",
    "😮‍💨", "🤥", "😌", "😔", "😪", "🤤", "😴", "😷", "🤒", "🤕",
    "🤢", "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯", "🤠", "🥳",
    "🥸", "😎", "🤓", "🧐", "😕", "😟", "🙁", "😯", "😲", "😳",
    "🥺", "😦", "😧", "😨", "😰", "😥", "😢", "😭", "😱", "😖",
    "😣", "😞", "😓", "😩", "😫", "🥱", "😤", "😡", "😠", "🤬",
    "😈", "👿", "💀", "💩", "🤡", "👹", "👺", "👻", "👽", "🤖",
    "😺", "😹", "😻", "😼", "😽", "🙀", "😿", "😾", "🙈", "🙉",
    "🙊", "💋", "💌", "💘", "💝", "💖", "💗", "💓", "💞", "💕",
    "💟", "❣️", "💔", "❤️", "🧡", "💛", "💚", "💙", "💜", "🤎",
    "🖤", "🤍", "💯", "💢", "💥", "💫", "💦", "💨", "🕳️", "💣",
    "💬", "👁️", "🧠", "🫡", "🫠", "🥹", "😈", "🔥", "⭐", "🌟",
    "✨", "⚡", "🎉", "🎊", "🎈", "🎁", "🏆", "🥇", "🎯", "🎮",
    "🍕", "🍔", "🍟", "🌮", "🍩", "🍪", "🎂", "🍰", "🍦", "🍉",
    "🍺", "🍻", "🥂", "☕", "🍵", "🚀", "🛸", "🌈", "☀️", "🌙",
    "🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯",
    "🦁", "🐮", "🐷", "🐸", "🐵", "🐔", "🐧", "🐦", "🦄", "🐝",
]

# ===================== СОСТОЯНИЕ =====================

def load_state():
    global is_enabled
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                is_enabled = bool(data.get("enabled", False))
        except Exception:
            is_enabled = False

def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"enabled": is_enabled}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

load_state()

# ===================== ПРЕОБРАЗОВАНИЕ ТЕКСТА =====================

def _roflify(text: str) -> str:
    """Вставляет случайный эмодзи после каждой 3-й буквы текста."""
    out = []
    letter_count = 0
    for ch in text:
        out.append(ch)
        if ch.isalpha():
            letter_count += 1
            if letter_count % 3 == 0:
                out.append(random.choice(EMOJIS))
    return "".join(out)

# ===================== ХЕНДЛЕР ИСХОДЯЩИХ СООБЩЕНИЙ =====================

async def _rofl_handler(event: events.NewMessage.Event):
    if not is_enabled:
        return

    text = (event.raw_text or "").strip()
    if not text:
        return

    # Команды бота (начинаются с префикса или слеша) не искажаем
    if text.startswith(".") or text.startswith("/"):
        return

    await asyncio.sleep(0.2)

    try:
        await event.edit(_roflify(text))
    except Exception:
        pass

_handlers_registered = False

def on_load(manager):
    global _handlers_registered
    if not _handlers_registered:
        manager.client.add_event_handler(_rofl_handler, events.NewMessage(outgoing=True))
        _handlers_registered = True
        logger.info(f"Rofl-хендлер подключен (режим: {'ВКЛ' if is_enabled else 'ВЫКЛ'}).")

def on_unload(manager):
    global _handlers_registered
    if _handlers_registered:
        manager.client.remove_event_handler(_rofl_handler, events.NewMessage(outgoing=True))
        _handlers_registered = False
        logger.info("Rofl-хендлер отключен.")

# ===================== КОМАНДА ПЕРЕКЛЮЧЕНИЯ =====================

@core.command("rofl", description="Rofl-режим: эмодзи после каждой 3-й буквы (повторный ввод выключает)", usage=".rofl")
async def rofl_cmd(event: events.NewMessage.Event):
    """Включает/выключает rofl-режим для всех твоих исходящих сообщений."""
    global is_enabled

    is_enabled = not is_enabled
    save_state()

    status = (
        "🤪 **Rofl-режим:** `ВКЛЮЧЕН`\n"
        "✨ Теперь после каждой 3-й буквы в твоих сообщениях будет случайный эмодзи.\n"
        "💡 Напиши `.rofl` ещё раз, чтобы выключить."
    ) if is_enabled else (
        "🤪 **Rofl-режим:** `ВЫКЛЮЧЕН`\n"
        "💬 Сообщения отправляются как обычно."
    )

    try:
        await event.edit(status)
    except Exception:
        try:
            await event.client.send_message(event.chat_id, status)
        except Exception:
            pass
