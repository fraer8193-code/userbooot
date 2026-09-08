import os
import sys
import logging
import importlib
import inspect
from pathlib import Path
from typing import Callable, Dict, List, Any, Optional
from telethon import events, TelegramClient
from config import CMD_PREFIX, MODULES_DIR

logger = logging.getLogger("Userbot.Loader")

class CommandInfo:
    def __init__(self, name: str, func: Callable, description: str = "", usage: str = ""):
        self.name = name
        self.func = func
        self.description = description or (inspect.getdoc(func) or "No description").strip()
        self.usage = usage or f"{CMD_PREFIX}{name}"

class ModuleInfo:
    def __init__(self, name: str, module_obj: Any):
        self.name = name
        self.module_obj = module_obj
        self.commands: Dict[str, CommandInfo] = {}
        self.handlers: List[tuple] = []  # List of (handler_func, telethon_event_builder)

class ModuleManager:
    def __init__(self, client: TelegramClient):
        self.client = client
        self.modules: Dict[str, ModuleInfo] = {}

    def command(self, name: str, description: str = "", usage: str = ""):
        """Декоратор для регистрации команды."""
        def decorator(func: Callable):
            func._is_userbot_command = True
            func._cmd_name = name.lower()
            func._cmd_desc = description
            func._cmd_usage = usage
            return func
        return decorator

    def register_module_handlers(self, mod_info: ModuleInfo):
        """Сканирует модуль на команды и регистрирует их в Telethon."""
        for attr_name in dir(mod_info.module_obj):
            attr = getattr(mod_info.module_obj, attr_name)
            if callable(attr) and getattr(attr, "_is_userbot_command", False):
                cmd_name = attr._cmd_name
                desc = attr._cmd_desc
                usage = attr._cmd_usage
                
                cmd_info = CommandInfo(name=cmd_name, func=attr, description=desc, usage=usage)
                mod_info.commands[cmd_name] = cmd_info

                # Поддерживаем и основной префикс (.), и слеш (/) для удобства
                prefix_pattern = rf"[\.{CMD_PREFIX}\/]" if CMD_PREFIX != "/" else r"[\/]"
                pattern = rf"(?i)^{prefix_pattern}{cmd_name}(?:\s+([\s\S]+))?$"

                handler_wrapper = self._create_wrapper(attr, cmd_name)
                event_filter = events.NewMessage(outgoing=True, pattern=pattern)
                
                self.client.add_event_handler(handler_wrapper, event_filter)
                mod_info.handlers.append((handler_wrapper, event_filter))
                logger.info(f"Registered command: {CMD_PREFIX}{cmd_name} (module: {mod_info.name})")

    def _create_wrapper(self, target_func: Callable, cmd_name: str):
        async def wrapper(event):
            try:
                await target_func(event)
            except Exception as e:
                logger.exception(f"Error executing {cmd_name}: {e}")
                try:
                    await event.reply(f"❌ **Error in `{cmd_name}`:**\n`{e}`")
                except Exception:
                    pass
        return wrapper

    def load_module(self, name: str) -> tuple[bool, str]:
        """Загружает модуль по имени файла (без .py)."""
        name = name.replace(".py", "").strip()
        if name in self.modules:
            self.unload_module(name)

        module_path = f"modules.{name}"
        try:
            if module_path in sys.modules:
                mod_obj = importlib.reload(sys.modules[module_path])
            else:
                mod_obj = importlib.import_module(module_path)

            mod_info = ModuleInfo(name, mod_obj)
            self.register_module_handlers(mod_info)
            self.modules[name] = mod_info
            
            if hasattr(mod_obj, "on_load") and callable(mod_obj.on_load):
                try:
                    mod_obj.on_load(self)
                except Exception as e:
                    logger.warning(f"Error in on_load of {name}: {e}")

            return True, f"Module `{name}` loaded."
        except Exception as e:
            logger.exception(f"Failed to load module {name}: {e}")
            return False, f"Failed to load `{name}`: {e}"

    def unload_module(self, name: str) -> tuple[bool, str]:
        """Выгружает модуль и удаляет его обработчики."""
        name = name.replace(".py", "").strip()
        if name not in self.modules:
            return False, f"Module `{name}` not found."

        mod_info = self.modules[name]

        if hasattr(mod_info.module_obj, "on_unload") and callable(mod_info.module_obj.on_unload):
            try:
                mod_info.module_obj.on_unload(self)
            except Exception as e:
                logger.warning(f"Error in on_unload of {name}: {e}")

        for handler_func, event_filter in mod_info.handlers:
            self.client.remove_event_handler(handler_func, event_filter)

        del self.modules[name]
        logger.info(f"Module {name} unloaded.")
        return True, f"Module `{name}` unloaded."

    def reload_module(self, name: str) -> tuple[bool, str]:
        """Перезагружает конкретный модуль."""
        self.unload_module(name)
        return self.load_module(name)

    def load_all_modules(self) -> Dict[str, bool]:
        """Загружает все модули из папки modules/."""
        os.makedirs(MODULES_DIR, exist_ok=True)
        results = {}

        if str(MODULES_DIR.parent) not in sys.path:
            sys.path.insert(0, str(MODULES_DIR.parent))

        for file in os.listdir(MODULES_DIR):
            if file.endswith(".py") and not file.startswith("__"):
                mod_name = file[:-3]
                success, _ = self.load_module(mod_name)
                results[mod_name] = success

        return results

    def get_all_commands(self) -> List[CommandInfo]:
        """Возвращает список всех зарегистрированных команд."""
        commands = []
        for mod in self.modules.values():
            commands.extend(mod.commands.values())
        return sorted(commands, key=lambda c: c.name)
