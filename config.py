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

# Gemini API Keys (поддержка одного или нескольких ключей через запятую)
_raw_gemini_parts = []
for _var in ("GEMINI_API_KEY", "GEMINI_API_KEYS"):
    _val = os.getenv(_var, "").strip()
    if _val.startswith(f"{_var}="):
        _val = _val.split("=", 1)[1].strip()
    if _val:
        _raw_gemini_parts.append(_val)
_combined_keys = ",".join(_raw_gemini_parts)
GEMINI_API_KEYS = []
for _k in _combined_keys.split(","):
    _k_clean = _k.strip().strip('"').strip("'").strip()
    if _k_clean and _k_clean not in GEMINI_API_KEYS:
        GEMINI_API_KEYS.append(_k_clean)
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""

# Версия юзербота
BOT_VERSION = "1.0.0"
