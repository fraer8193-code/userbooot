import random
import string
from telethon import events
import core

def generate_password(length=12, use_digits=True, use_special=True):
    letters = string.ascii_letters
    digits = string.digits if use_digits else ''
    special = "!@#$%^&*()-_=+[]{}<>?" if use_special else ''
    
    all_chars = letters + digits + special
    if not all_chars:
        return "Ошибка: не выбраны символы для генерации."
        
    return ''.join(random.choice(all_chars) for _ in range(length))

@core.command("pass", description="Сгенерировать надежный пароль", usage=".pass [длина]")
async def pass_cmd(event: events.NewMessage.Event):
    """Генерирует случайный пароль заданной длины (по умолчанию 12)."""
    args = event.raw_text.split(maxsplit=1)
    length = 12
    if len(args) > 1 and args[1].strip().isdigit():
        length = max(4, min(128, int(args[1].strip())))

    pwd = generate_password(length=length)
    await event.edit(
        f"🔐 **Сгенерированный пароль:**\n"
        f"`{pwd}`\n\n"
        f"📏 **Длина:** `{length}` симв."
    )