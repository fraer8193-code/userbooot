from telethon import TelegramClient
from core.loader import ModuleManager
from core.utils import get_uptime, format_ping, START_TIME

# Глобальная ссылка на менеджер модулей и бота-помощника
module_manager: ModuleManager = None
bot_client: TelegramClient = None

def command(name: str, description: str = "", usage: str = ""):
    """Декоратор команды для использования в файлах модулей."""
    def decorator(func):
        func._is_userbot_command = True
        func._cmd_name = name.lower()
        func._cmd_desc = description
        func._cmd_usage = usage
        return func
    return decorator

__all__ = ["ModuleManager", "module_manager", "bot_client", "command", "get_uptime", "format_ping", "START_TIME"]
