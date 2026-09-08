import time
import asyncio
from telethon import events
from core import command

@command("ping", description="Check connection latency", usage=".ping")
async def ping_cmd(event: events.NewMessage.Event):
    """Measures Telegram server response latency."""
    start_time = time.time()
    msg = await event.edit("⏳ **Testing connection...**")
    end_time = time.time()
    
    latency_ms = (end_time - start_time) * 1000
    await msg.edit(f"⚡ **Ping:** `{latency_ms:.2f} ms`")
    await asyncio.sleep(4)
    await msg.delete()
