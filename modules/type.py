import asyncio
from telethon import events
import core

@core.command("type", description="Typewriter animation effect", usage=".type <text>")
async def type_cmd(event: events.NewMessage.Event):
    """Prints text symbol by symbol like a typewriter."""
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.edit("Использование: `.type <текст>`")
        return

    text = args[1]
    current = ""
    typing_symbol = "▒"

    for char in text:
        current += char
        try:
            await event.edit(current + typing_symbol)
            await asyncio.sleep(0.08)
        except Exception:
            pass

    try:
        await event.edit(current)
    except Exception:
        pass
