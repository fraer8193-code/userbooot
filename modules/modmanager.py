import os
import re
import asyncio
import logging
from pathlib import Path
from telethon import events
import core
from config import CMD_PREFIX, MODULES_DIR

logger = logging.getLogger("Userbot.ModManager")

# Системные модули, которые нельзя случайно удалить через .dell
PROTECTED_MODULES = {"modmanager", "core", "config", "main", "help"}

def extract_code_content(raw_text: str) -> str:
    """Удаляет Markdown-обертку кода (```python ... ``` или ``` ... ```)."""
    text = raw_text.strip()
    match = re.search(r"```(?:python|py)?\n?([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text

@core.command("load", description="Load a module", usage=f"{CMD_PREFIX}load <name>")
async def load_mod_cmd(event: events.NewMessage.Event):
    """Load module from modules/ directory."""
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        try:
            await event.edit(f"💡 **Использование:** `{CMD_PREFIX}load <module_name>`")
            await asyncio.sleep(3)
            await event.delete()
        except Exception:
            pass
        return

    mod_name = args[1].strip().replace(".py", "")
    mgr = core.module_manager
    success, message = mgr.load_module(mod_name)
    
    text = f"🧩 Модуль `{mod_name}` загружен." if success else f"❌ Ошибка загрузки `{mod_name}`:\n`{message}`"
    try:
        await event.edit(text)
        await asyncio.sleep(2.5)
        await event.delete()
    except Exception:
        try:
            msg = await event.respond(text)
            await asyncio.sleep(2.5)
            await msg.delete()
        except Exception:
            pass

@core.command("unload", description="Unload a module", usage=f"{CMD_PREFIX}unload <name>")
async def unload_mod_cmd(event: events.NewMessage.Event):
    """Unload active module."""
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        try:
            await event.edit(f"💡 **Использование:** `{CMD_PREFIX}unload <module_name>`")
            await asyncio.sleep(3)
            await event.delete()
        except Exception:
            pass
        return

    mod_name = args[1].strip().replace(".py", "")
    mgr = core.module_manager
    success, message = mgr.unload_module(mod_name)
    
    text = f"🧩 Модуль `{mod_name}` выгружен." if success else f"❌ Модуль `{mod_name}` не найден."
    try:
        await event.edit(text)
        await asyncio.sleep(2.5)
        await event.delete()
    except Exception:
        try:
            msg = await event.respond(text)
            await asyncio.sleep(2.5)
            await msg.delete()
        except Exception:
            pass

@core.command("reload", description="Reload all modules", usage=f"{CMD_PREFIX}reload")
async def reload_all_cmd(event: events.NewMessage.Event):
    """Reload all modules in memory."""
    try:
        await event.edit("🔄 **Перезагрузка модулей...**")
    except Exception:
        pass

    mgr = core.module_manager
    loaded = list(mgr.modules.keys())
    for mod in loaded:
        mgr.unload_module(mod)
        
    results = mgr.load_all_modules()
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    
    text = f"🔄 **Перезагружено модулей:** `{success_count}/{total_count}`"
    try:
        await event.edit(text)
        await asyncio.sleep(2.5)
        await event.delete()
    except Exception:
        try:
            msg = await event.respond(text)
            await asyncio.sleep(2.5)
            await msg.delete()
        except Exception:
            pass

@core.command("modules", description="Show active loaded modules", usage=f"{CMD_PREFIX}modules")
async def list_modules_cmd(event: events.NewMessage.Event):
    """Display active loaded modules and total count."""
    mgr = core.module_manager
    active_mods = sorted(mgr.modules.keys())
    
    text = (
        f"🧩 **Active Modules ({len(active_mods)})**\n\n"
    )
    for m in active_mods:
        mod_obj = mgr.modules[m]
        cmd_list = ", ".join(f"`{CMD_PREFIX}{c}`" for c in sorted(mod_obj.commands.keys()))
        text += f"• **{m}**: {cmd_list if cmd_list else '*(нет команд)*'}\n"
        
    try:
        await event.edit(text)
    except Exception:
        try:
            await event.respond(text)
        except Exception:
            pass

@core.command("create", description="Create and load a new python module", usage=f"{CMD_PREFIX}create <name> <code>")
async def create_mod_cmd(event: events.NewMessage.Event):
    """Создает новый модуль из Python-кода и мгновенно регистрирует его."""
    mgr = core.module_manager
    if not mgr:
        await event.edit("❌ **Менеджер модулей не инициализирован.**")
        return

    reply = await event.get_reply_message()
    raw = event.raw_text

    # Удаляем префикс и команду .create
    pattern = rf"(?i)^[\.{CMD_PREFIX}\/]create(?:\s+([\s\S]+))?$"
    match = re.match(pattern, raw)
    body = match.group(1).strip() if (match and match.group(1)) else ""

    mod_name = ""
    code = ""

    # Сценарий 1: Документ или файл в самом сообщении с командой
    if event.file:
        fname = getattr(event.file, "name", None) or ""
        if fname.lower().endswith(".py") or not fname:
            mod_name = body.strip().replace(".py", "") if body else (Path(fname).stem if fname else "")
            file_bytes = await event.download_media(bytes)
            if file_bytes:
                code = file_bytes.decode("utf-8", errors="replace")

    # Сценарий 2: Ответ (reply) на сообщение
    if not code and reply:
        # Проверяем файл в ответе (документ .py или текстовый файл)
        if reply.file:
            fname = getattr(reply.file, "name", None) or ""
            # Если имя файла есть
            if fname:
                mod_name = body.strip().replace(".py", "") if body else Path(fname).stem
            else:
                mod_name = body.strip().replace(".py", "") if body else ""
            file_bytes = await reply.download_media(bytes)
            if file_bytes:
                code = file_bytes.decode("utf-8", errors="replace")
        elif reply.raw_text:
            # Текст из сообщения в реплае
            if body:
                mod_name = body.split(maxsplit=1)[0].replace(".py", "")
            code = extract_code_content(reply.raw_text)
    
    # Сценарий 3: Всё в одном текстовом сообщении
    if not code and body:
        parts = body.split(maxsplit=1)
        if len(parts) >= 2:
            mod_name = parts[0].replace(".py", "")
            code = extract_code_content(parts[1])
        elif len(parts) == 1 and "\n" in body:
            lines = body.split("\n", 1)
            mod_name = lines[0].strip().replace(".py", "")
            code = extract_code_content(lines[1])
        elif len(parts) == 1 and reply and reply.raw_text:
            mod_name = parts[0].replace(".py", "")
            code = extract_code_content(reply.raw_text)

    # Если имя модуля так и не определено, но код есть (например, из файла без имени)
    if not mod_name and code and body:
        mod_name = body.strip().replace(".py", "")

    if not mod_name or not code:
        usage_text = (
            f"💡 **Использование команды `{CMD_PREFIX}create`:**\n\n"
            f"1️⃣ **Прикрепить `.py` файл к сообщению:**\n"
            f"`{CMD_PREFIX}create [имя_модуля]` (в подписи к файлу)\n\n"
            f"2️⃣ **Ответом (reply) на `.py` файл или код:**\n"
            f"`{CMD_PREFIX}create <имя_модуля>`\n\n"
            f"3️⃣ **В одном сообщении с кодом:**\n"
            f"`{CMD_PREFIX}create <имя_модуля>`\n"
            f"```python\n"
            f"import core\n\n"
            f"@core.command(\"hello\")\n"
            f"async def hello(event):\n"
            f"    await event.edit(\"Hello World!\")\n"
            f"```"
        )
        await event.edit(usage_text)
        return

    # Очистка имени модуля
    mod_name = mod_name.strip().lower()
    if not re.match(r"^[a-zA-Z0-9_]+$", mod_name):
        await event.edit("❌ **Некорректное имя модуля!** Используйте только латинские буквы, цифры и символ `_`.")
        return

    if mod_name in ("__init__", "core", "config", "main"):
        await event.edit(f"❌ **Запрещено использовать системное имя:** `{mod_name}`")
        return

    # Проверка синтаксиса перед записью
    try:
        compile(code, f"{mod_name}.py", "exec")
    except SyntaxError as se:
        err_line = f"Строка {se.lineno}: {se.msg}"
        await event.edit(f"❌ **Ошибка синтаксиса в коде модуля `{mod_name}`:**\n`{err_line}`")
        return
    except Exception as e:
        await event.edit(f"❌ **Ошибка проверки кода:**\n`{e}`")
        return

    # Запись файла на диск
    target_file = MODULES_DIR / f"{mod_name}.py"
    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        await event.edit(f"❌ **Не удалось сохранить файл модуля:**\n`{e}`")
        return

    # Загрузка модуля в память
    success, msg = mgr.load_module(mod_name)
    if success:
        mod_info = mgr.modules.get(mod_name)
        cmds = list(mod_info.commands.keys()) if mod_info else []
        if cmds:
            cmd_str = ", ".join(f"`{CMD_PREFIX}{c}`" for c in cmds)
            await event.edit(
                f"✨ **Модуль `{mod_name}` успешно создан и активирован!**\n\n"
                f"📁 **Файл:** `modules/{mod_name}.py`\n"
                f"⚡ **Команды:** {cmd_str}\n"
                f"💡 Удалить модуль: `{CMD_PREFIX}dell {mod_name}`"
            )
        else:
            await event.edit(
                f"⚠️ **Модуль `{mod_name}` сохранен, но команды не найдены!**\n\n"
                f"📁 **Файл:** `modules/{mod_name}.py`\n\n"
                f"❓ **Причина:**\n"
                f"В коде нет зарегистрированных команд. Для юзербота функция команды должна быть помечена декоратором `@core.command(\"имя\")` или называться `cmd_<имя>(event)`.\n\n"
                f"💡 **Пример правильного модуля:**\n"
                f"```python\n"
                f"from telethon import events\n"
                f"import core\n\n"
                f"@core.command(\"{mod_name}\")\n"
                f"async def {mod_name}_cmd(event: events.NewMessage.Event):\n"
                f"    await event.edit(\"Команда работает!\")\n"
                f"```\n\n"
                f"💡 Удалить этот файл: `{CMD_PREFIX}dell {mod_name}`"
            )
    else:
        # Если загрузка не удалась, сообщаем подробности
        await event.edit(
            f"⚠️ **Файл сохранен, но ошибка при загрузке модуля `{mod_name}`:**\n"
            f"`{msg}`\n\n"
            f"💡 Чтобы удалить сломанный файл, используйте `{CMD_PREFIX}dell {mod_name}`"
        )

@core.command("dell", description="Delete and unload a module", usage=f"{CMD_PREFIX}dell <name>")
async def dell_mod_cmd(event: events.NewMessage.Event):
    """Удаляет файл модуля и выгружает его из системы."""
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await event.edit(f"💡 **Использование:** `{CMD_PREFIX}dell <module_name>`")
        return

    mod_name = args[1].strip().replace(".py", "").lower()

    if mod_name in PROTECTED_MODULES:
        await event.edit(f"🚫 **Запрещено удалять системный модуль `{mod_name}`!**")
        return

    mgr = core.module_manager
    if mgr and mod_name in mgr.modules:
        mgr.unload_module(mod_name)

    # Удаляем .py файл
    target_file = MODULES_DIR / f"{mod_name}.py"
    deleted_file = False
    if target_file.exists():
        try:
            target_file.unlink()
            deleted_file = True
        except Exception as e:
            logger.warning(f"Failed to delete {target_file}: {e}")

    # Удаляем скомпилированный кэш .pyc
    pycache_dir = MODULES_DIR / "__pycache__"
    if pycache_dir.exists():
        for pyc in pycache_dir.glob(f"{mod_name}.*.pyc"):
            try:
                pyc.unlink()
            except Exception:
                pass

    if deleted_file or (mgr and mod_name not in mgr.modules):
        await event.edit(
            f"🗑 **Модуль `{mod_name}` успешно удалён!**\n"
            f"• Модуль выгружен из памяти\n"
            f"• Файл `modules/{mod_name}.py` удалён"
        )
    else:
        await event.edit(f"❌ **Модуль `{mod_name}` не найден в папке `modules/`!**")
