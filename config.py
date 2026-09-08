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

# Имя файла сессии Telethon
SESSION_NAME = os.getenv("SESSION_NAME", "userbot_session")

# Префикс для команд бота (например, .ping, .help)
CMD_PREFIX = os.getenv("CMD_PREFIX", ".")

# Версия юзербота
BOT_VERSION = "1.0.0"
