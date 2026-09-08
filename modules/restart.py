import os
import sys
import asyncio
from telethon import events
from core import command

@command("restart", description="Restart Femboy", usage=".restart")
async def restart_cmd(event: events.NewMessage.Event):
    """Restart the Femboy process cleanly."""
    target_id = event.id
    try:
        msg = await event.edit("🔄 **Restarting Femboy...**")
        target_id = msg.id
    except Exception:
        pass

    try:
        with open(".restart_state", "w", encoding="utf-8") as f:
            f.write(f"{event.chat_id}:{target_id}")
    except Exception:
        pass
    
    await asyncio.sleep(0.5)
    os.execv(sys.executable, [sys.executable] + sys.argv)
