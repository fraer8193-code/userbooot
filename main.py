import os
import sys
import subprocess
import logging

# Обеспечиваем корректную работу UTF-8 в консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --- Функция авто-проверки и установки зависимостей для Bothost.ru и локального ПК ---
def ensure_dependencies():
    packages = {
        "telethon": "telethon>=1.36.0",
        "colorama": "colorama>=0.4.6",
        "dotenv": "python-dotenv>=1.0.0",
        "aiohttp": "aiohttp>=3.9.0",
        "psutil": "psutil>=5.9.0",
        "PIL": "pillow>=10.0.0",
        "google.genai": "google-genai>=0.1.0",
        "openai": "openai>=1.0.0",
        "requests": "requests>=2.31.0"
    }
    missing_pip = []
    
    for import_name, pip_spec in packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_pip.append(pip_spec)
            
    if missing_pip:
        print(f"[*] [Bothost.ru] Missing dependencies detected: {', '.join(missing_pip)}")
        print("[*] [Bothost.ru] Installing dependencies automatically via pip...")
        try:
            req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
            if os.path.exists(req_file):
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
            else:
                subprocess.check_call([sys.executable, "-m", "pip", "install", *missing_pip])
            print("[+] [Bothost.ru] All dependencies installed successfully!\n")
        except Exception as e:
            print(f"[!] [Bothost.ru] Warning during pip install: {e}")

ensure_dependencies()

import asyncio
from colorama import init, Fore, Style
from telethon import TelegramClient
import core
from config import API_ID, API_HASH, SESSION_NAME, CMD_PREFIX, BOT_VERSION, MODULES_DIR, BOT_TOKEN, BOT_USERNAME

# Инициализация colorama
init(autoreset=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s : %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Femboy")

BANNER = f"""{Fore.MAGENTA}
==================================================
        TELEGRAM MODULAR FEMBOY v{BOT_VERSION}
==================================================
{Fore.GREEN}  Python: {sys.version.split()[0]}
{Fore.YELLOW}  Prefix: {CMD_PREFIX} | Modules dir: {MODULES_DIR.name}/
{Style.RESET_ALL}"""

async def handle_startup_message(client: TelegramClient):
    """Отправляет/обновляет стартовое сообщение и затем удаляет его."""
    try:
        restart_file = ".restart_state"
        if os.path.exists(restart_file):
            try:
                with open(restart_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if os.path.exists(restart_file):
                    os.remove(restart_file)
                if ":" in content:
                    chat_id_str, msg_id_str = content.split(":", 1)
                    chat_id = int(chat_id_str)
                    msg_id = int(msg_id_str)
                    
                    entity = None
                    try:
                        entity = await client.get_input_entity(chat_id)
                    except Exception:
                        try:
                            entity = await client.get_entity(chat_id)
                        except Exception:
                            entity = None

                    if entity:
                        msg = await client.edit_message(entity, msg_id, "✨ **Femboy Running**")
                        await asyncio.sleep(3)
                        await msg.delete()
                        return
            except Exception as e:
                logger.debug(f"Restart message edit skipped: {e}")

        msg = await client.send_message("me", "✨ **Femboy Running**")
        await asyncio.sleep(3)
        await msg.delete()
    except Exception as e:
        logger.warning(f"Could not send startup message: {e}")

async def main():
    print(BANNER)
    
    if not API_ID or not API_HASH:
        logger.error("API_ID or API_HASH is missing in config.py!")
        return

    logger.info("Initializing Telegram client...")
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    # Инициализация и регистрация менеджера модулей
    mgr = core.ModuleManager(client)
    core.module_manager = mgr

    # Инициализация бота-помощника для инлайн-кнопок
    bot_client = None
    if BOT_TOKEN:
        try:
            logger.info("Initializing Inline Helper Bot...")
            bot_client = TelegramClient("bot_session", API_ID, API_HASH)

            async def _init_bot():
                await bot_client.connect()
                if not await bot_client.is_user_authorized():
                    await bot_client.sign_in(bot_token=BOT_TOKEN)
                return await bot_client.get_me()

            try:
                bot_me = await asyncio.wait_for(_init_bot(), timeout=15.0)
                core.bot_client = bot_client
                mgr.bot_client = bot_client
                print(f"{Fore.GREEN}[+] Inline Bot connected:{Style.RESET_ALL} @{bot_me.username}")
            except asyncio.TimeoutError:
                logger.warning("Inline Bot initialization timed out (15s). Continuing without it.")
                try:
                    await bot_client.disconnect()
                except Exception:
                    pass
                bot_client = None
        except Exception as e:
            logger.warning(f"Could not start inline helper bot: {e}")
            bot_client = None

    logger.info("Connecting to Telegram user account...")
    await client.start()
    
    me = await client.get_me()
    first_name = me.first_name or "User"
    user_id = me.id
    username = f"@{me.username}" if me.username else "no username"
    
    print(f"\n{Fore.GREEN}[+] Logged in as:{Style.RESET_ALL} {first_name} ({username}) [ID: {user_id}]")

    # Загрузка всех модулей
    logger.info("Loading modules from modules/ ...")
    load_results = mgr.load_all_modules()
    
    success_count = sum(1 for v in load_results.values() if v)
    total_count = len(load_results)
    all_commands = mgr.get_all_commands()
    
    print(f"{Fore.CYAN}[+] Modules loaded: {success_count}/{total_count}")
    print(f"[+] Active commands: {len(all_commands)}{Style.RESET_ALL}")
    for cmd in all_commands:
        print(f"   {Fore.YELLOW}* {CMD_PREFIX}{cmd.name:<10}{Style.RESET_ALL} - {cmd.description}")

    # Отправка и авто-удаление сообщения в фоне
    asyncio.create_task(handle_startup_message(client))

    print(f"\n{Fore.MAGENTA}[*] Femboy is ready! Press Ctrl+C to stop.{Style.RESET_ALL}\n")
    
    if bot_client:
        await asyncio.gather(
            client.run_until_disconnected(),
            bot_client.run_until_disconnected()
        )
    else:
        await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print(f"\n{Fore.RED}[!] Femboy stopped.{Style.RESET_ALL}")
