from telethon import events
import core

@core.command("id", description="Show chat, user, and message IDs", usage=".id [reply/pm]")
async def id_cmd(event: events.NewMessage.Event):
    """Shows IDs and peer info of the current chat, sender, and replied message."""
    client = event.client
    chat = await event.get_chat()
    chat_id = event.chat_id
    chat_title = getattr(chat, "title", None) or getattr(chat, "first_name", "Private Chat")

    text = f"**Chat ID:** `{chat_id}`\n**Chat Title:** `{chat_title}`\n"

    if event.is_reply:
        reply = await event.get_reply_message()
        sender = await reply.get_sender()
        sender_name = getattr(sender, "first_name", "Unknown") or "Unknown"
        if getattr(sender, "username", None):
            sender_name += f" (@{sender.username})"

        text += (
            f"\n**Replied User:** [{sender_name}](tg://user?id={reply.sender_id})\n"
            f"**User ID:** `{reply.sender_id}`\n"
            f"**Message ID:** `{reply.id}`\n"
        )
    else:
        me = await client.get_me()
        text += (
            f"\n**Your User ID:** `{me.id}`\n"
            f"**Message ID:** `{event.id}`\n"
        )

    await event.edit(text)
