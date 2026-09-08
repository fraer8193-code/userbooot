import os
import re
import time
import json
from pathlib import Path
from typing import Optional, Tuple
from telethon import events
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
import core

DATA_FILE = Path(__file__).parent.parent / "muted_users.json"
muted_users = {}

def load_muted():
    global muted_users
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                muted_users = {int(k): v for k, v in data.items()}
        except Exception:
            muted_users = {}

def save_muted():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(muted_users, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

load_muted()

def parse_time(time_str: str) -> Optional[Tuple[int, str]]:
    """Парсит строку времени: 10s, 5m, 1h, 2d, 1w."""
    match = re.match(r"^(\d+)\s*([smhdwсмчднSMHDWСМЧДН]?)$", time_str.strip())
    if not match:
        return None
    
    val = int(match.group(1))
    unit = match.group(2).lower()
    
    if unit in ("s", "с", ""):
        return val, f"{val}s"
    elif unit in ("m", "м"):
        return val * 60, f"{val}m"
    elif unit in ("h", "ч"):
        return val * 3600, f"{val}h"
    elif unit in ("d", "д"):
        return val * 86400, f"{val}d"
    elif unit in ("w", "н"):
        return val * 604800, f"{val}w"
    return None

async def resolve_target_user(event: events.NewMessage.Event) -> Optional[Tuple[int, str]]:
    """Определяет ID и имя целевого пользователя из реплая, лички или аргументов."""
    if event.is_reply:
        reply = await event.get_reply_message()
        if reply and reply.sender_id:
            sender = await reply.get_sender()
            name = getattr(sender, "first_name", str(reply.sender_id)) or str(reply.sender_id)
            return reply.sender_id, name

    if event.is_private:
        chat = await event.get_chat()
        name = getattr(chat, "first_name", str(event.chat_id)) or str(event.chat_id)
        return event.chat_id, name

    args = event.raw_text.split()
    if len(args) > 1:
        target = args[1]
        try:
            entity = await event.client.get_entity(target)
            name = getattr(entity, "first_name", str(entity.id)) or str(entity.id)
            return entity.id, name
        except Exception:
            pass

    return None

# --- Обработчик удаления входящих сообщений ---
_incoming_handler = None

async def handle_incoming_muted(event: events.NewMessage.Event):
    sender_id = event.sender_id
    if sender_id and sender_id in muted_users:
        expire_at = muted_users[sender_id]
        if expire_at and time.time() > expire_at:
            del muted_users[sender_id]
            save_muted()
            return
        
        try:
            await event.delete()
        except Exception:
            pass

def on_load(manager):
    global _incoming_handler
    _incoming_handler = handle_incoming_muted
    manager.client.add_event_handler(_incoming_handler, events.NewMessage(incoming=True))

def on_unload(manager):
    global _incoming_handler
    if _incoming_handler:
        manager.client.remove_event_handler(_incoming_handler, events.NewMessage(incoming=True))
        _incoming_handler = None

# --- Команды модерации со стильным оформлением ---

@core.command("ban", description="Block a user", usage=".ban [reply/pm/@user]")
async def ban_cmd(event: events.NewMessage.Event):
    """Blocks the user in PM or by reply."""
    target = await resolve_target_user(event)
    if not target:
        await event.edit("⚠️ **User not found.** Use in PM or reply to message.")
        return

    user_id, name = target
    try:
        await event.client(BlockRequest(id=user_id))
        await event.edit(
            f"🚫 **User Blocked**\n"
            f"👤 **Name:** [{name}](tg://user?id={user_id})\n"
            f"🆔 **ID:** `{user_id}`"
        )
    except Exception as e:
        await event.edit(f"❌ **Failed to block user:** `{e}`")

@core.command("unban", description="Unblock a user", usage=".unban [reply/pm/@user]")
async def unban_cmd(event: events.NewMessage.Event):
    """Unblocks the user in PM or by reply."""
    target = await resolve_target_user(event)
    if not target:
        await event.edit("⚠️ **User not found.** Use in PM or reply to message.")
        return

    user_id, name = target
    try:
        await event.client(UnblockRequest(id=user_id))
        await event.edit(
            f"✅ **User Unblocked**\n"
            f"👤 **Name:** [{name}](tg://user?id={user_id})\n"
            f"🆔 **ID:** `{user_id}`"
        )
    except Exception as e:
        await event.edit(f"❌ **Failed to unblock user:** `{e}`")

@core.command("mute", description="Mute user (auto-delete incoming)", usage=".mute [time: 1h/30m/1d]")
async def mute_cmd(event: events.NewMessage.Event):
    """Mutes a user for specified duration or permanently."""
    target = await resolve_target_user(event)
    if not target:
        await event.edit("⚠️ **User not found.** Use in PM or reply to message.")
        return

    user_id, name = target
    args = event.raw_text.split()
    
    expire_time = None
    duration_text = "Forever"

    for arg in args[1:]:
        if arg.startswith("@"):
            continue
        parsed = parse_time(arg)
        if parsed:
            seconds, duration_text = parsed
            expire_time = time.time() + seconds
            break

    muted_users[user_id] = expire_time
    save_muted()

    await event.edit(
        f"🔇 **User Muted**\n"
        f"👤 **Target:** [{name}](tg://user?id={user_id})\n"
        f"⏳ **Duration:** `{duration_text}`\n"
        f"⚡ **Action:** `Auto-deleting messages`"
    )

@core.command("unmute", description="Unmute a user", usage=".unmute [reply/pm/@user]")
async def unmute_cmd(event: events.NewMessage.Event):
    """Unmutes a user and stops deleting their messages."""
    target = await resolve_target_user(event)
    if not target:
        await event.edit("⚠️ **User not found.** Use in PM or reply to message.")
        return

    user_id, name = target
    if user_id in muted_users:
        del muted_users[user_id]
        save_muted()
        await event.edit(
            f"🔊 **User Unmuted**\n"
            f"👤 **Target:** [{name}](tg://user?id={user_id})\n"
            f"✨ **Status:** `Active`"
        )
    else:
        await event.edit(f"ℹ️ **User** [{name}](tg://user?id={user_id}) **is not muted.**")
