import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка переменных окружения из .env если существует
load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
MODULES_DIR = BASE_DIR / "modules"

# Telegram API credentials
API_ID = int(os.getenv("API_ID", "34289456"))
API_HASH = os.getenv("API_HASH", "6b132e982dcc6c1fbebc51d7d10793e9")

# Telegram Bot Token для интерактивных инлайн-кнопок
BOT_TOKEN = os.getenv("BOT_TOKEN", "8951677161:AAE4OwQNfrUIiS-MI9_gWUyJ32tM5bH2d2Y")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MuInlineFemboy_bot")

# Имя файла сессии Telethon или готовая строка сессии (для деплоя без файла .session)
SESSION_NAME = os.getenv("SESSION_NAME", "userbot_session")
_raw_session_str = os.getenv("SESSION_STRING", "").strip()
if _raw_session_str.startswith("SESSION_STRING="):
    _raw_session_str = _raw_session_str.split("=", 1)[1].strip()
SESSION_STRING = _raw_session_str.strip('"').strip("'").strip()

# Префикс для команд бота (например, .ping, .help)
CMD_PREFIX = os.getenv("CMD_PREFIX", ".")

# Gemini API Key (очистка кавычек и пробелов)
_raw_gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
if _raw_gemini_key.startswith("GEMINI_API_KEY="):
    _raw_gemini_key = _raw_gemini_key.split("=", 1)[1].strip()
GEMINI_API_KEY = _raw_gemini_key.strip('"').strip("'").strip()

# Версия юзербота
BOT_VERSION = "1.0.0"
