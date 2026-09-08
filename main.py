import os
import sys
import subprocess
import logging
from pathlib import Path

# Обеспечиваем немедленный вывод логов в консоль Docker/Bothost без буферизации
os.environ["PYTHONUNBUFFERED"] = "1"
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
else:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

# --- Функция авто-проверки и установки зависимостей для Bothost.ru и локального ПК ---
def ensure_dependencies():
    packages = {
        "telethon": "telethon",
        "colorama": "colorama",
        "dotenv": "python-dotenv",
        "aiohttp": "aiohttp",
        "PIL": "pillow",
        "google.genai": "google-genai",
        "openai": "openai",
        "requests": "requests"
    }
    missing_pip = []
    
    for import_name, pip_spec in packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_pip.append(pip_spec)
            
    if missing_pip:
        print(f"[*] [Bothost.ru] Missing dependencies detected: {', '.join(missing_pip)}")
        
        # 1. Проверяем наличие pip, если нет — устанавливаем автоматически
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            print("[*] [Bothost.ru] pip is missing in container. Bootstrapping pip...")
            try:
                import ensurepip
                ensurepip.bootstrap()
            except Exception:
                try:
                    import urllib.request
                    import tempfile
                    get_pip_file = os.path.join(tempfile.gettempdir(), "get-pip.py")
                    urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip_file)
                    subprocess.check_call([sys.executable, get_pip_file, "--no-warn-script-location"])
                except Exception as e:
                    print(f"[!] [Bothost.ru] Could not bootstrap pip: {e}")

        # 2. Устанавливаем зависимости
        print("[*] [Bothost.ru] Installing dependencies automatically via pip...")
        try:
            req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
            install_cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir"]
            if os.path.exists(req_file):
                subprocess.check_call(install_cmd + ["-r", req_file])
            else:
                subprocess.check_call(install_cmd + missing_pip)
            print("[+] [Bothost.ru] All dependencies installed successfully!\n")
            
            import site
            import importlib
            importlib.invalidate_caches()
        except Exception as e:
            print(f"[!] [Bothost.ru] Warning during pip install: {e}")

ensure_dependencies()

import asyncio

# Безопасная инициализация colorama (не падать, если отсутствует)
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class _DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = _DummyColor()
    Style = _DummyColor()

from telethon import TelegramClient
from telethon.sessions import StringSession
import core
from config import API_ID, API_HASH, SESSION_NAME, SESSION_STRING, CMD_PREFIX, BOT_VERSION, MODULES_DIR, BOT_TOKEN, BOT_USERNAME

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
    
    # Поиск файла сессии в рабочей директории и /app/data
    session_target = None
    potential_dirs = [Path("."), Path("data"), Path("/app"), Path("/app/data")]
    found_session_path = None

    for pdir in potential_dirs:
        if pdir.exists() and pdir.is_dir():
            # Сначала проверяем точное имя
            exact = pdir / f"{SESSION_NAME}.session"
            if exact.exists() and exact.stat().st_size > 0:
                found_session_path = exact
                break
            # Затем любой .session файл
            for sfile in pdir.glob("*.session"):
                if sfile.name != "bot_session.session" and sfile.stat().st_size > 0:
                    found_session_path = sfile
                    break
        if found_session_path:
            break

    if found_session_path:
        # Убираем расширение .session для Telethon
        session_stem = str(found_session_path).replace("\\", "/")
        if session_stem.endswith(".session"):
            session_stem = session_stem[:-8]
        logger.info(f"[+] Found session file: {found_session_path.name} at {found_session_path} ({found_session_path.stat().st_size} bytes), using it!")
        session_target = session_stem
    elif SESSION_STRING:
        logger.info(f"[+] Using StringSession (length: {len(SESSION_STRING)} chars)")
        session_target = StringSession(SESSION_STRING)
    else:
        logger.warning(f"[-] No session file found in {[str(d) for d in potential_dirs]} and SESSION_STRING is empty!")
        session_target = SESSION_NAME

    client = TelegramClient(session_target, API_ID, API_HASH)

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
    try:
        await client.start()
    except EOFError:
        logger.error(
            "Не удалось войти в аккаунт: сессия не авторизована, а ввод с клавиатуры недоступен (контейнер/сервер).\n"
            "Решение:\n"
            "1. Запустите скрипт export_session.py на компьютере, чтобы получить SESSION_STRING.\n"
            "2. Укажите переменную окружения SESSION_STRING на сервере (в .env или настройках хостинга).\n"
            "Либо скопируйте файл userbot_session.session на сервер."
        )
        return
    
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
