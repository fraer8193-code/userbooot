"""
MineDrop Module v2.0 — Автоматический перехват и активация промокодов с MineDrop.art
Функционал:
1. Авторизация на https://minedrop.art через интерактивное окно браузера или куки.
2. Мгновенная активация промокода через API (/api/promocode/redeem) + резервный ввод через Playwright в профиле.
3. Мониторинг указанного Telegram-канала, распознавание промокодов (включая скрытый текст/спойлеры).
4. Полная отладка в консоль и в Избранное (Saved Messages).
"""

import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from telethon import events, types
import core
from config import BASE_DIR, CMD_PREFIX

logger = logging.getLogger("Userbot.MineDrop")

# Проверяем доступность Playwright
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ===================== КОНФИГУРАЦИЯ И ПУТИ =====================

DATA_DIR = BASE_DIR
CONFIG_FILE = DATA_DIR / "minedrop_config.json"
COOKIES_FILE = DATA_DIR / "minedrop_cookies.json"
HISTORY_FILE = DATA_DIR / "minedrop_history.json"
BROWSER_USER_DATA_DIR = DATA_DIR / "temp_browser_data" / "minedrop"
BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Блокировка браузерных операций
_browser_lock = asyncio.Lock()

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================

def normalize_channel_id(cid: Any) -> str:
    """Приводит Telegram ID чата к единому числовому виду без префиксов -100 и -."""
    if cid is None:
        return ""
    s = str(cid).strip()
    if s.startswith("-100"):
        return s[4:]
    if s.startswith("-"):
        return s[1:]
    return s

def log_debug(message: str, color: str = "36"):
    """Печатает яркое отладочное сообщение в консоль бота."""
    prefix = f"\033[{color}m[MineDrop]\033[0m"
    print(f"{prefix} {message}")
    logger.info(message)

# ===================== УПРАВЛЕНИЕ СОСТОЯНИЕМ =====================

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Ошибка загрузки minedrop_config.json: {e}")
    return {
        "enabled": True,
        "channel_id": None,
        "channel_title": "",
        "auto_activate": True,
        "notify_me": True,
        "debug": True,
    }

def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения minedrop_config.json: {e}")

def load_cookies() -> list:
    if COOKIES_FILE.exists():
        try:
            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "cookies" in data:
                    return data["cookies"]
        except Exception as e:
            logger.warning(f"Ошибка чтения minedrop_cookies.json: {e}")
    return []

def save_cookies(cookie_list: list):
    try:
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookie_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения minedrop_cookies.json: {e}")

def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"used_promos": []}

def save_history(hist: dict):
    try:
        if len(hist.get("used_promos", [])) > 1000:
            hist["used_promos"] = hist["used_promos"][-1000:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def is_promo_processed(code: str) -> bool:
    hist = load_history()
    code_clean = code.strip().upper()
    for item in hist.get("used_promos", []):
        if isinstance(item, dict) and item.get("code", "").upper() == code_clean:
            return True
        if isinstance(item, str) and item.upper() == code_clean:
            return True
    return False

def mark_promo_processed(code: str, result: str = "", source: str = ""):
    hist = load_history()
    hist.setdefault("used_promos", []).append({
        "code": code.strip().upper(),
        "result": result,
        "source": source,
        "timestamp": int(time.time()),
        "date": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    save_history(hist)

# ===================== ПАРСИНГ КУКИ =====================

def parse_cookies_input(raw_input: str) -> list:
    raw_input = raw_input.strip()
    result = []

    # 1. JSON
    if (raw_input.startswith("[") and raw_input.endswith("]")) or (raw_input.startswith("{") and raw_input.endswith("}")):
        try:
            data = json.loads(raw_input)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("name") and item.get("value") is not None:
                        result.append({
                            "name": str(item["name"]),
                            "value": str(item["value"]),
                            "domain": item.get("domain", "minedrop.art"),
                            "path": item.get("path", "/"),
                        })
                if result:
                    return result
            elif isinstance(data, dict):
                for k, v in data.items():
                    result.append({
                        "name": str(k),
                        "value": str(v),
                        "domain": "minedrop.art",
                        "path": "/",
                    })
                if result:
                    return result
        except Exception:
            pass

    # 2. Netscape format
    lines = raw_input.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            result.append({
                "domain": parts[0],
                "path": parts[2],
                "name": parts[5],
                "value": parts[6],
            })

    if result:
        return result

    # 3. HTTP Header
    pairs = raw_input.split(";")
    for p in pairs:
        if "=" in p:
            k, v = p.split("=", 1)
            k, v = k.strip(), v.strip()
            if k:
                result.append({
                    "name": k,
                    "value": v,
                    "domain": "minedrop.art",
                    "path": "/",
                })

    return result

# ===================== БРАУЗЕРНАЯ АВТОРИЗАЦИЯ =====================

async def run_browser_auth(event: events.NewMessage.Event) -> bool:
    if not PLAYWRIGHT_AVAILABLE:
        await event.edit(
            "❌ **Движок Playwright не установлен.**\n"
            "Выполните в терминале:\n`pip install playwright && playwright install chromium`"
        )
        return False

    msg = await event.edit(
        "🌐 **Запуск браузера для авторизации на MineDrop.art...**\n\n"
        "🖥 На твоём экране открывается окно браузера.\n"
        "🔑 **Войди в свой аккаунт** на сайте под своим логином и паролем.\n\n"
        "⏳ *Ожидаю завершения входа (таймаут 180 секунд)...*"
    )

    async with _browser_lock:
        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    str(BROWSER_USER_DATA_DIR),
                    headless=False,
                    user_agent=DEFAULT_USER_AGENT,
                    viewport={"width": 1280, "height": 850},
                    locale="ru-RU",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-default-browser-check",
                        "--no-first-run",
                    ]
                )

                page = context.pages[0] if context.pages else await context.new_page()

                try:
                    await page.goto("https://minedrop.art/login", wait_until="domcontentloaded", timeout=25000)
                except Exception as e:
                    logger.warning(f"Ошибка загрузки login: {e}")

                start_time = time.time()
                logged_in = False
                detected_username = ""

                while time.time() - start_time < 180:
                    await asyncio.sleep(2)
                    current_url = page.url
                    
                    is_on_profile_or_main = ("/profile" in current_url) or (
                        current_url.rstrip("/") == "https://minedrop.art" and not current_url.endswith("/login")
                    )
                    
                    has_auth_indicator = False
                    try:
                        profile_elem = await page.query_selector('a[href="/profile"], .user-profile-mini, a[href="/logout"]')
                        if profile_elem:
                            has_auth_indicator = True
                    except Exception:
                        pass

                    if (is_on_profile_or_main and has_auth_indicator) or ("/profile" in current_url):
                        logged_in = True
                        try:
                            nick_elem = await page.query_selector('.user-profile-mini, .header-username, .pv2-name')
                            if nick_elem:
                                detected_username = (await nick_elem.inner_text()).strip()
                        except Exception:
                            pass
                        
                        all_cookies = await context.cookies()
                        minedrop_cookies = [
                            c for c in all_cookies
                            if "minedrop.art" in c.get("domain", "") or c.get("domain", "") == ""
                        ]
                        save_cookies(minedrop_cookies or all_cookies)
                        break

                await context.close()

                if logged_in:
                    user_str = f" (**{detected_username}**)" if detected_username else ""
                    await msg.edit(
                        f"✅ **Авторизация MineDrop успешно завершена!**{user_str}\n\n"
                        f"🍪 Куки успешно перехвачены и сохранены в `{COOKIES_FILE.name}`.\n"
                        f"⚡ Теперь юзербот готов автоматически вводить промокоды!"
                    )
                    log_debug(f"Авторизация успешна! Куки сохранены: {len(minedrop_cookies)} шт.", "32")
                    return True
                else:
                    await msg.edit(
                        "⚠️ **Время ожидания авторизации истекло (180 сек).**\n"
                        "Если окно закрылось раньше времени, попробуй снова через `.md auth`."
                    )
                    return False

        except Exception as e:
            logger.exception(f"Ошибка browser_auth: {e}")
            await msg.edit(f"❌ **Ошибка при запуске браузера:**\n`{e}`")
            return False

# ===================== БЫСТРАЯ АКТИВАЦИЯ ЧЕРЕЗ API =====================

def activate_via_api_sync(code: str) -> Tuple[bool, str]:
    """
    Быстрая активация промокода напрямую через HTTP API:
    POST https://minedrop.art/api/promocode/redeem
    Работает за 150-300 миллисекунд!
    """
    cookies_list = load_cookies()
    if not cookies_list:
        return False, "Куки не найдены"

    s = requests.Session()
    s.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    })
    for c in cookies_list:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", "minedrop.art"), path=c.get("path", "/"))

    # 1. Получаем CSRF токен из профиля
    try:
        r_prof = s.get("https://minedrop.art/profile", timeout=8, allow_redirects=False)
        if r_prof.status_code == 302 or "/login" in r_prof.headers.get("Location", ""):
            return False, "Сессия истекла (редирект на /login). Требуется повторный `.md auth`"
        
        csrf_match = re.search(r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', r_prof.text)
        csrf_token = csrf_match.group(1) if csrf_match else ""
    except Exception as e:
        return False, f"Ошибка соединения с профилем: {e}"

    # 2. Отправляем запрос на активацию промокода
    try:
        headers = {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf_token,
            "Referer": "https://minedrop.art/profile",
            "Origin": "https://minedrop.art",
        }
        resp = s.post(
            "https://minedrop.art/api/promocode/redeem",
            headers=headers,
            json={"code": code.strip().upper()},
            timeout=10
        )
        
        try:
            data = resp.json()
        except Exception:
            return False, f"Некорректный ответ сервера: HTTP {resp.status_code}"

        if resp.status_code == 200:
            if data.get("error"):
                return False, f"Ответ сайта: {data['error']}"
            
            if data.get("kind") == "deposit":
                return True, f"Активирован промокод на пополнение: {data.get('code', code)}"
            
            msg = data.get("message") or ("Промокод успешно активирован!" if data.get("success") else "Ответ получен")
            if data.get("bonusBalance"):
                msg += f" (Баланс бонусов: {data['bonusBalance']} BONUS)"
            if data.get("rewardType"):
                msg += f" (Награда: {data['rewardType']})"
            return True, msg
        else:
            err = data.get("error") or f"HTTP {resp.status_code}"
            return False, f"Ошибка: {err}"

    except Exception as e:
        return False, f"Ошибка API запроса: {e}"

# ===================== РЕЗЕРВНАЯ АКТИВАЦИЯ ЧЕРЕЗ PLAYWRIGHT =====================

async def activate_via_playwright(code: str) -> Tuple[bool, str]:
    """Резервная браузерная активация промокода во вкладке «Бонусы»."""
    cookies = load_cookies()
    if not cookies or not PLAYWRIGHT_AVAILABLE:
        return False, "Playwright или куки недоступны"

    async with _browser_lock:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                context = await browser.new_context(
                    user_agent=DEFAULT_USER_AGENT,
                    viewport={"width": 1280, "height": 900},
                    locale="ru-RU",
                )

                formatted = []
                for c in cookies:
                    formatted.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", "minedrop.art"),
                        "path": c.get("path", "/"),
                    })
                await context.add_cookies(formatted)
                page = await context.new_page()

                await page.goto("https://minedrop.art/profile", wait_until="domcontentloaded", timeout=25000)
                if "/login" in page.url:
                    await browser.close()
                    return False, "Сессия истекла (редирект на /login)"

                await asyncio.sleep(1)

                # Ищем точный input формы промокода
                input_field = await page.query_selector('input.bonus-promo-input, input[name="code"], input[placeholder*="промокод" i]')
                if not input_field:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(0.5)
                    input_field = await page.query_selector('input.bonus-promo-input, input[name="code"]')

                if not input_field:
                    await browser.close()
                    return False, "Поле ввода промокода не найдено в профиле"

                await input_field.scroll_into_view_if_needed()
                await input_field.fill(code)

                submit_btn = await page.query_selector('button.bonus-promo-submit, button[type="submit"]:has-text("Активировать")')
                if submit_btn:
                    await submit_btn.click()
                else:
                    await input_field.press("Enter")

                await asyncio.sleep(2)

                # Считываем результат
                result_text = ""
                msg_el = await page.query_selector('[data-promo-message], .bonus-promo-message, .toast, .alert')
                if msg_el and await msg_el.is_visible():
                    result_text = (await msg_el.inner_text()).strip()

                await browser.close()
                return True, result_text or "Код отправлен через форму профиля!"

        except Exception as e:
            return False, f"Ошибка браузера: {e}"

# ===================== ЕДИНАЯ ФУНКЦИЯ АКТИВАЦИИ =====================

async def activate_promocode(code: str) -> Tuple[bool, str]:
    """
    Мгновенно активирует промокод: сначала через супербыстрый HTTP API,
    а при необходимости — через Playwright.
    """
    code = code.strip()
    if not code:
        return False, "Пустой промокод"

    log_debug(f"🚀 Запуск активации промокода '{code}'...", "35")

    # Шаг 1: Пробуем моментальный API запрос
    if REQUESTS_AVAILABLE:
        loop = asyncio.get_running_loop()
        success, api_result = await loop.run_in_executor(None, activate_via_api_sync, code)
        log_debug(f"Результат API активации '{code}': {api_result}", "32" if success else "33")
        
        # Если ответ от сервера получен (успех или известная ошибка сайта) — возвращаем сразу
        if success or ("Ответ сайта:" in api_result) or ("Сессия истекла" in api_result):
            return success, api_result

    # Шаг 2: Резервная браузерная активация
    if PLAYWRIGHT_AVAILABLE:
        log_debug(f"Резервная попытка через Playwright для '{code}'...", "34")
        return await activate_via_playwright(code)

    return False, "Не удалось выполнить запрос к сайту"

# ===================== ПАРСИНГ ПРОМОКОДОВ И СПОЙЛЕРОВ =====================

KEYWORD_PATTERNS = [
    r'(?i)\bпромо\b',
    r'(?i)\bпромокод[а-я]*\b',
    r'(?i)\bпромик[а-я]*\b',
    r'(?i)\bpromo\b',
    r'(?i)\bpromocode\b',
    r'(?i)\bкод[ы]?\b',
    r'(?i)\bбонус[ы]?\b',
]

STOPWORDS = {
    "HTTP", "HTTPS", "MINE", "DROP", "MINEDROP", "NEW", "POST", "OPEN", "CASE", "TG",
    "TELEGRAM", "BOT", "CHANNEL", "PROMO", "ПРОМОКОД", "БОНУС", "КОД", "ART", "NET", "COM", "RU",
    "ДАЕТ", "ДАЁТ", "НА", "ДЛЯ", "ОТ", "ПО", "ИЛИ"
}

def get_telegram_entity_text(raw_text: str, entity: types.TypeMessageEntity) -> str:
    """
    Извлекает текст сущности Telegram с точным учетом UTF-16 code units.
    Это критически важно, если перед спойлером в тексте есть эмодзи (суррогатные пары).
    """
    try:
        raw_bytes = raw_text.encode("utf-16-le")
        start = entity.offset * 2
        end = (entity.offset + entity.length) * 2
        return raw_bytes[start:end].decode("utf-16-le", errors="ignore").strip()
    except Exception:
        return raw_text[entity.offset : entity.offset + entity.length].strip()

def extract_promocodes_from_message(message: types.Message) -> List[str]:
    """
    Извлекает ВСЕ промокоды из сообщения Telegram.
    
    1. Если в посте есть скрытый текст (спойлеры), промокоды извлекаются ИСКЛЮЧИТЕЛЬНО из них
       с корректным UTF-16 декодированием. Это гарантирует отсутствие ложных срабатываний
       (названия кейсов, призов и обрезанных слов).
    2. Если спойлеров нет, используются моноширинный шрифт, кавычки и точные регулярки после слова «промокод».
    """
    if not message:
        return []

    raw_text = message.text or message.raw_text or ""
    if not raw_text:
        return []

    # 1. Приоритет 1: Спойлеры Telegram
    spoiler_codes = []
    if getattr(message, "entities", None):
        for ent in message.entities:
            if isinstance(ent, types.MessageEntitySpoiler):
                chunk = get_telegram_entity_text(raw_text, ent)
                # Извлекаем токены из спойлера (поддерживаем латиницу, кириллицу, цифры, дефис и подчеркивание)
                for word in re.findall(r'[A-Za-z0-9_\-А-Яа-яЁё]{2,35}', chunk):
                    clean = word.strip("-_ \t\n\r\"'`«»")
                    if len(clean) >= 3 and clean.upper() not in STOPWORDS:
                        log_debug(f"🎯 Найден промокод под спойлером: '{clean}'", "32")
                        spoiler_codes.append(clean)

    # Если в посте были спойлеры с промокодами — возвращаем именно их!
    if spoiler_codes:
        unique_spoilers = []
        seen = set()
        for c in spoiler_codes:
            c_up = c.upper()
            if c_up not in seen:
                seen.add(c_up)
                unique_spoilers.append(c)
        return unique_spoilers

    # 2. Если спойлеров нет, проверяем моноширинный шрифт (`code`)
    code_entities = []
    if getattr(message, "entities", None):
        for ent in message.entities:
            if isinstance(ent, (types.MessageEntityCode, types.MessageEntityPre)):
                chunk = get_telegram_entity_text(raw_text, ent)
                for word in re.findall(r'[A-Za-z0-9_\-А-Яа-яЁё]{2,35}', chunk):
                    clean = word.strip("-_ \t\n\r\"'`«»")
                    if len(clean) >= 3 and clean.upper() not in STOPWORDS:
                        log_debug(f"🎯 Найден промокод в моноширинном тексте: '{clean}'", "32")
                        code_entities.append(clean)

    if code_entities:
        unique_mono = []
        seen = set()
        for c in code_entities:
            c_up = c.upper()
            if c_up not in seen:
                seen.add(c_up)
                unique_mono.append(c)
        return unique_mono

    # 3. Поиск по ключевым словам и кавычкам
    found_codes = []
    has_keyword = any(re.search(p, raw_text) for p in KEYWORD_PATTERNS)

    # В кавычках или обратных кавычках
    in_quotes_or_code = re.findall(r'[`"\'«]([A-Za-z0-9_\-А-Яа-яЁё]{3,35})[`"\'»]', raw_text)
    for candidate in in_quotes_or_code:
        clean = candidate.strip("-_ ")
        if len(clean) >= 3 and clean.upper() not in STOPWORDS:
            found_codes.append(clean)

    # Регулярка после слова "промокод/промо"
    regex_after_word = re.findall(
        r'(?i)(?:промокод[а-я]*|промо|промик[а-я]*|promo|promocode|код[ы]?)[\s:=—–-]+([A-Za-z0-9_\-А-Яа-яЁё]{3,35})',
        raw_text
    )
    for candidate in regex_after_word:
        clean = candidate.strip("-_ ")
        if len(clean) >= 3 and clean.upper() not in STOPWORDS:
            found_codes.append(clean)

    # Удаляем дубликаты
    unique_codes = []
    seen = set()
    for c in found_codes:

        c_upper = c.strip().upper()
        if c_upper not in seen and len(c_upper) >= 3:
            seen.add(c_upper)
            unique_codes.append(c.strip())

    return unique_codes

def extract_promocode_from_message(message: types.Message) -> Optional[str]:
    """Для обратной совместимости: возвращает первый найденный промокод."""
    codes = extract_promocodes_from_message(message)
    return codes[0] if codes else None

# ===================== ОБРАБОТЧИК СООБЩЕНИЙ ИЗ КАНАЛА =====================

async def on_new_channel_message(event: events.NewMessage.Event):
    """
    Слушатель сообщений. Обрабатывает ВСЕ сообщения (включая исходящие при тестировании)
    из заданного канала. Поддерживает несколько промокодов в одном посте!
    """
    cfg = load_config()
    if not cfg.get("enabled", True):
        return

    target_id = cfg.get("channel_id")
    if not target_id:
        return

    # Нормализуем ID канала для гарантированного совпадения
    norm_target = normalize_channel_id(target_id)
    norm_chat = normalize_channel_id(event.chat_id)
    norm_peer = normalize_channel_id(getattr(getattr(event, "peer_id", None), "channel_id", None))

    matches = (norm_chat == norm_target) or (norm_peer and norm_peer == norm_target)
    if not matches:
        return

    msg = event.message
    if not msg:
        return

    raw_text = msg.text or msg.raw_text or ""
    channel_name = cfg.get("channel_title") or f"ID {target_id}"

    # Яркий вывод в консоль для мгновенной отладки
    log_debug(f"📩 Новое сообщение в отслеживаемом канале '{channel_name}' (ID {event.chat_id}):\n{raw_text}", "36")

    # Извлекаем ВСЕ промокоды из сообщения
    promo_codes = extract_promocodes_from_message(msg)

    # Если включен режим отладки — дублируем информацию в Избранное
    if cfg.get("debug", True):
        try:
            preview = raw_text[:120] + "..." if len(raw_text) > 120 else raw_text
            codes_found_str = f"Найдено промокодов: {len(promo_codes)} шт. ({', '.join(promo_codes)})" if promo_codes else "Промокоды не обнаружены"
            await event.client.send_message(
                "me",
                f"🔎 **MineDrop Отладка:** получено сообщение из `{channel_name}`:\n\n"
                f"_{preview}_\n\n"
                f"📊 *{codes_found_str}*"
            )
        except Exception:
            pass

    if not promo_codes:
        log_debug(f"⚠️ Промокоды в сообщении канала '{channel_name}' не обнаружены.", "33")
        return

    # Фильтруем те, которые уже были активированы ранее
    unprocessed_codes = [c for c in promo_codes if not is_promo_processed(c)]
    if not unprocessed_codes:
        log_debug(f"ℹ️ Все промокоды ({promo_codes}) уже были активированы ранее. Пропуск.", "33")
        return

    count = len(unprocessed_codes)
    codes_str = ", ".join(f"`{c}`" for c in unprocessed_codes)
    log_debug(f"🔥 ПЕРЕХВАЧЕНО ПРОМОКОДОВ: {count} шт. -> {codes_str}!", "32")

    # Уведомление о старте активации списка
    if cfg.get("notify_me", True):
        try:
            await event.client.send_message(
                "me",
                f"⚡ **MineDrop: Перехвачено промокодов ({count} шт.)!**\n\n"
                f"🎁 **Коды:** {codes_str}\n"
                f"📢 **Канал:** `{channel_name}`\n\n"
                f"🚀 *Начинаю активацию...*"
            )
        except Exception:
            pass

    # Активируем каждый промокод по очереди
    results = []
    for i, code in enumerate(unprocessed_codes, 1):
        mark_promo_processed(code, result="В процессе...", source=channel_name)
        
        start_time = time.time()
        success, result_message = await activate_promocode(code)
        elapsed = time.time() - start_time
        
        mark_promo_processed(code, result=result_message, source=channel_name)
        results.append((code, success, result_message, elapsed))
        
        log_debug(f"[{i}/{count}] Результат '{code}' за {elapsed:.2f}с: {result_message}", "32" if success else "31")

        # Небольшая пауза между кодами, чтобы сервер не заблокировал за флуд
        if i < count:
            await asyncio.sleep(0.4)

    # Итоговый отчет в Избранное
    report_lines = []
    for code, success, res_msg, el in results:
        status_icon = "✅" if success else "❌"
        report_lines.append(f"{status_icon} `{code}`: {res_msg} ({el:.2f}с)")

    report_text = (
        f"🎁 **Отчет по активации MineDrop ({count} шт.):**\n\n"
        + "\n".join(report_lines)
        + f"\n\n📢 **Канал:** `{channel_name}`\n"
        f"🕒 **Время:** `{time.strftime('%H:%M:%S')}`"
    )

    if cfg.get("notify_me", True):
        try:
            await event.client.send_message("me", report_text)
        except Exception as e:
            logger.error(f"Не удалось отправить отчет в 'me': {e}")


# ===================== РЕГИСТРАЦИЯ ХУКОВ =====================

_channel_handler_registered = False

def on_load(manager):
    global _channel_handler_registered
    if not _channel_handler_registered and manager.client:
        # events.NewMessage() без incoming=True перехватывает ВСЕ сообщения (включая свои при тестировании)
        manager.client.add_event_handler(on_new_channel_message, events.NewMessage())
        _channel_handler_registered = True
        log_debug("Хэндлер канала успешно подключен к Telethon.", "32")

def on_unload(manager):
    global _channel_handler_registered
    if _channel_handler_registered and manager.client:
        manager.client.remove_event_handler(on_new_channel_message, events.NewMessage())
        _channel_handler_registered = False
        log_debug("Хэндлер канала отключен.", "33")

# ===================== КОМАНДЫ ЮЗЕРБОТА =====================

@core.command("minedrop", description="MineDrop Auto-Promo catcher", usage=f"{CMD_PREFIX}md [auth|channel|promo|cookies|test|on|off|status|help]")
async def minedrop_cmd(event: events.NewMessage.Event):
    await md_cmd(event)

@core.command("md", description="MineDrop Auto-Promo catcher", usage=f"{CMD_PREFIX}md [auth|channel|promo|cookies|test|on|off|status|help]")
async def md_cmd(event: events.NewMessage.Event):
    args = event.raw_text.split(maxsplit=2)
    subcmd = args[1].lower() if len(args) > 1 else "status"

    cfg = load_config()

    # 1. Авторизация через браузер
    if subcmd == "auth":
        await run_browser_auth(event)
        return

    # 2. Установка или просмотр канала
    elif subcmd in ["channel", "ch"]:
        if len(args) < 3:
            curr = cfg.get("channel_title") or cfg.get("channel_id") or "Не задан"
            curr_id = cfg.get("channel_id") or "нет"
            await event.edit(
                f"📢 **Текущий канал MineDrop:** `{curr}` (`{curr_id}`)\n\n"
                f"Чтобы изменить, укажите юзернейм или ID:\n"
                f"`{CMD_PREFIX}md channel @minecraftdrop`"
            )
            return

        raw_channel = args[2].strip()
        try:
            entity = await event.client.get_entity(raw_channel)
            channel_id = entity.id
            channel_title = getattr(entity, "title", None) or getattr(entity, "first_name", str(entity.id))

            cfg["channel_id"] = channel_id
            cfg["channel_title"] = channel_title
            cfg["enabled"] = True
            save_config(cfg)

            log_debug(f"Канал мониторинга установлен: '{channel_title}' (ID {channel_id})", "32")

            await event.edit(
                f"✅ **Канал для перехвата промокодов успешно установлен!**\n\n"
                f"📢 **Канал:** `{channel_title}`\n"
                f"🆔 **ID:** `{channel_id}` (норм: `{normalize_channel_id(channel_id)}`)\n"
                f"🟢 **Авто-перехватчик:** `ВКЛЮЧЕН`"
            )
        except Exception as e:
            await event.edit(f"❌ **Ошибка при поиске канала `{raw_channel}`:**\n`{e}`")
        return

    # 3. Ручной ввод промокода
    elif subcmd in ["promo", "code"]:
        if len(args) < 3:
            await event.edit(f"Использование: `{CMD_PREFIX}md promo <ПРОМОКОД>`")
            return
        
        test_code = args[2].strip()
        msg = await event.edit(f"⏳ **Активирую промокод `{test_code}` на MineDrop.art...**")
        start = time.time()
        success, result_text = await activate_promocode(test_code)
        elapsed = time.time() - start
        
        icon = "✅" if success else "❌"
        await msg.edit(
            f"{icon} **Результат активации `{test_code}` ({elapsed:.2f}с):**\n\n"
            f"{result_text}"
        )
        return

    # 4. Проверка подключения и профиля (Test)
    elif subcmd in ["test", "check"]:
        msg = await event.edit("⏳ **Проверяю подключение к профилю MineDrop...**")
        cookies = load_cookies()
        if not cookies:
            await msg.edit("❌ **Куки не найдены.** Сначала выполните `.md auth`.")
            return

        # Проверяем через requests
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": DEFAULT_USER_AGENT})
            for c in cookies:
                s.cookies.set(c["name"], c["value"], domain=c.get("domain", "minedrop.art"), path=c.get("path", "/"))
            r = s.get("https://minedrop.art/profile", allow_redirects=False, timeout=10)
            if r.status_code == 200:
                nick_match = re.search(r'class=["\']pv2-name["\'][^>]*>([^<]+)<', r.text)
                nick = nick_match.group(1).strip() if nick_match else "Авторизован"
                await msg.edit(f"✅ **Куки действительны!**\n👤 Профиль: **{nick}**\n🌐 Статус: `200 OK`")
            elif r.status_code == 302:
                await msg.edit("⚠️ **Куки устарели (302 Redirect).** Выполните `.md auth` заново.")
            else:
                await msg.edit(f"⚠️ Ответ сервера: `HTTP {r.status_code}`")
        except Exception as e:
            await msg.edit(f"❌ Ошибка проверки: `{e}`")
        return

    # 5. Ручная передача куки
    elif subcmd in ["cookies", "cookie"]:
        if len(args) < 3:
            cookies = load_cookies()
            c_count = len(cookies)
            await event.edit(
                f"🍪 **Сохранено кук:** `{c_count}` шт.\n\n"
                f"Чтобы передать новые куки вручную, используйте:\n"
                f"`{CMD_PREFIX}md cookies [JSON список или строка k=v; k2=v2]`"
            )
            return

        raw_data = args[2].strip()
        parsed = parse_cookies_input(raw_data)
        if not parsed:
            await event.edit("❌ **Не удалось распознать формат куков.** Поддерживается JSON, Netscape или заголовок `k=v;`.")
            return

        save_cookies(parsed)
        await event.edit(f"✅ **Успешно сохранено кук:** `{len(parsed)}` шт. в `{COOKIES_FILE.name}`")
        return

    # 6. Переключение отладки
    elif subcmd == "debug":
        cfg["debug"] = not cfg.get("debug", True)
        save_config(cfg)
        status_str = "ВКЛЮЧЕНА (все события канала дублируются в Избранное)" if cfg["debug"] else "ВЫКЛЮЧЕНА"
        await event.edit(f"🔍 **Отладка MineDrop:** `{status_str}`")
        return

    # 7. Включение / Выключение
    elif subcmd == "on":
        cfg["enabled"] = True
        save_config(cfg)
        ch = cfg.get("channel_title") or cfg.get("channel_id") or "не задан"
        await event.edit(f"🟢 **Авто-перехват промокодов MineDrop:** `ВКЛЮЧЕН`\nКанал: `{ch}`")
        return

    elif subcmd == "off":
        cfg["enabled"] = False
        save_config(cfg)
        await event.edit("🔴 **Авто-перехват промокодов MineDrop:** `ВЫКЛЮЧЕН`")
        return

    # 8. Статус модуля
    elif subcmd == "status":
        cookies = load_cookies()
        c_status = f"✅ Активны ({len(cookies)} шт.)" if cookies else "❌ Отсутствуют"
        ch_status = f"`{cfg.get('channel_title')}` (`{cfg.get('channel_id')}`)" if cfg.get("channel_id") else "⚠️ Не установлен"
        state_status = "🟢 ВКЛЮЧЕН" if cfg.get("enabled", True) else "🔴 ВЫКЛЮЧЕН"
        dbg_status = "🟢 ВКЛ" if cfg.get("debug", True) else "⚪ ВЫКЛ"

        hist = load_history()
        used = hist.get("used_promos", [])
        last_promo = used[-1]["code"] if used else "нет"

        text = (
            "⛏️ **MineDrop Auto-Promocode — Статус:**\n\n"
            f"⚙️ **Состояние:** {state_status}\n"
            f"📢 **Канал:** {ch_status}\n"
            f"🍪 **Куки аккаунта:** {c_status}\n"
            f"🔍 **Режим отладки в Избранное:** {dbg_status}\n"
            f"🎁 **Последний промокод:** `{last_promo}`\n"
            f"📊 **Всего обработано:** `{len(used)}` шт.\n\n"
            f"💡 *Проверить профиль:* `{CMD_PREFIX}md test`\n"
            f"💡 *Справка по командам:* `{CMD_PREFIX}md help`"
        )
        await event.edit(text)
        return

    # 9. Справка
    elif subcmd in ["help", "info"]:
        help_text = (
            "⛏️ **MineDrop Auto-Promocode — Справка по командам:**\n\n"
            f"🔹 `{CMD_PREFIX}md auth` — Запустить браузер для входа на MineDrop (бот сохранит куки)\n"
            f"🔹 `{CMD_PREFIX}md channel @username` — Задать канал для мониторинга промокодов\n"
            f"🔹 `{CMD_PREFIX}md promo <код>` — Вручную активировать промокод на сайте\n"
            f"🔹 `{CMD_PREFIX}md test` — Проверить валидность куков и профиль\n"
            f"🔹 `{CMD_PREFIX}md debug` — Включить/выключить подробные отчеты в Избранное\n"
            f"🔹 `{CMD_PREFIX}md on` / `{CMD_PREFIX}md off` — Включить / выключить перехватчик\n"
            f"🔹 `{CMD_PREFIX}md status` — Проверить статус и авторизацию\n\n"
            "✨ *Модуль автоматически считывает даже скрытый текст (спойлеры ||текст||)!*"
        )
        await event.edit(help_text)
        return

    else:
        await event.edit(f"Неизвестная подкоманда. Используйте `{CMD_PREFIX}md help`")
