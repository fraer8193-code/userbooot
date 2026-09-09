from datetime import datetime
from zoneinfo import ZoneInfo
from telethon import events
import core

@core.command("time", description="Показывает текущее время в Москве", usage=".time")
async def show_moscow_time(event: events.NewMessage.Event):
    """Выводит текущее время в Москве с красивым оформлением."""
    try:
        moscow_tz = ZoneInfo("Europe/Moscow")
        moscow_time = datetime.now(moscow_tz)
    except Exception:
        # Запасной вариант на случай проблем с базой зон
        from datetime import timezone, timedelta
        moscow_time = datetime.now(timezone(timedelta(hours=3)))
    
    formatted_time = moscow_time.strftime("%H:%M:%S")
    formatted_date = moscow_time.strftime("%d.%m.%Y")
    
    text = (
        "🕒 **Текущее время в Москве**\n\n"
        f"📅 Дата: `{formatted_date}`\n"
        f"⏰ Время: `{formatted_time}` MSK"
    )
    
    await event.edit(text)