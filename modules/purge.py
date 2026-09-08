import asyncio
from telethon import events
import core

@core.command("purge", description="Purge messages from reply to current", usage=".purge (в ответ на сообщение)")
async def purge_cmd(event: events.NewMessage.Event):
    """Deletes all messages between replied message and current."""
    if not event.is_reply:
        await event.edit("Ответьте на сообщение, с которого нужно начать очистку.")
        return

    reply = await event.get_reply_message()
    from_id = reply.id
    to_id = event.id

    client = event.client
    chat = await event.get_input_chat()

    msg_ids = list(range(from_id, to_id + 1))
    await event.edit(f"Очистка `{len(msg_ids)}` сообщений...")

    # Удаляем пачками до 100 сообщений
    deleted_count = 0
    for i in range(0, len(msg_ids), 100):
        chunk = msg_ids[i:i + 100]
        try:
            await client.delete_messages(chat, chunk)
            deleted_count += len(chunk)
        except Exception:
            pass

    status_msg = await client.send_message(event.chat_id, f"Удалено сообщений: `{deleted_count}`")
    await asyncio.sleep(2)
    try:
        await status_msg.delete()
    except Exception:
        pass

@core.command("del", description="Delete replied message", usage=".del (в ответ на сообщение)")
async def del_cmd(event: events.NewMessage.Event):
    """Deletes replied message and command itself."""
    if not event.is_reply:
        await event.delete()
        return

    reply = await event.get_reply_message()
    try:
        await reply.delete()
        await event.delete()
    except Exception as e:
        await event.edit(f"Не удалось удалить: `{e}`")
