import time
from datetime import timedelta

# Время старта бота для вычисления аптайма
START_TIME = time.time()

def get_uptime() -> str:
    """Возвращает строку со временем работы бота."""
    delta = int(time.time() - START_TIME)
    return str(timedelta(seconds=delta))

def format_ping(ms: float) -> str:
    """Форматирует миллисекунды задержки с цветовым индикатором."""
    if ms < 100:
        indicator = "🟢"
    elif ms < 300:
        indicator = "🟡"
    else:
        indicator = "🔴"
    return f"{indicator} `{ms:.2f} ms`"
