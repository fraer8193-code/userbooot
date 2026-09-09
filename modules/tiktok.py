"""
TikTok Module v4.0 — Модуль для юзербота с поддержкой браузера Playwright и рекомендаций.

Возможности:
  .tt [кол-во]           — Листать видео из рекомендаций (по умолч. 1, максимум 10)
  .tt rec [кол-во]       — Следующие видео из рекомендаций (например .tt 5)
  .tt <ссылка>           — Скачать видео/слайдшоу без водяного знака
  .tt auth               — Войти в аккаунт через браузер (QR-код с телефона или логин)
  .tt login <sessionid>  — Ручная привязка sessionid
  .tt account / .tt me   — Проверить статус привязанного аккаунта
  .tt logout             — Отвязать аккаунт TikTok
  .tt help               — Подробная справка и инструкция
"""

import io
import os
import re
import json
import time
import random
import asyncio
import aiohttp
from pathlib import Path
from telethon import events
import core

# Проверяем доступность Playwright
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# ===================== КОНФИГУРАЦИЯ И ПУТИ =====================

TEMP_DIR = Path("temp_media")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

BROWSER_DATA_DIR = Path("temp_browser_data").resolve()
BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = Path("tiktok_session.json")
COOKIES_FILE = Path("tiktok_cookies.txt").resolve()
SEEN_FILE = Path("tiktok_seen.json").resolve()

# ===================== БАЗА ДАННЫХ ПРОСМОТРЕННЫХ ВИДЕО =====================

def load_seen_videos() -> dict:
    """Загружает базу отправленных видео для предотвращения повторов."""
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_seen_videos(seen_dict: dict):
    """Сохраняет базу отправленных видео (хранит до 2500 последних)."""
    try:
        if len(seen_dict) > 2500:
            items = list(seen_dict.items())[-2500:]
            seen_dict = dict(items)
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen_dict, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def mark_video_seen(video_id: str, author: str = "", title: str = ""):
    """Отмечает видео как отправленное с уникальным ID, автором и описанием."""
    seen = load_seen_videos()
    v_str = str(video_id).strip()
    auth_clean = str(author).strip().lower()
    title_clean = str(title).strip()[:80].lower()
    comp_key = f"{auth_clean}::{title_clean}" if (auth_clean and title_clean) else ""

    if v_str:
        seen[v_str] = {
            "author": author,
            "title": title[:100],
            "key": comp_key,
            "sent_at": int(time.time())
        }
    if comp_key:
        seen[f"k:{comp_key}"] = {
            "id": v_str,
            "sent_at": int(time.time())
        }
    save_seen_videos(seen)

def is_video_already_seen(video_id: str, author: str = "", title: str = "") -> bool:
    """Проверяет, отправлялось ли уже видео пользователю (по ID или связке автор+описание)."""
    seen = load_seen_videos()
    v_str = str(video_id).strip()
    if v_str and v_str in seen:
        return True
    auth_clean = str(author).strip().lower()
    title_clean = str(title).strip()[:80].lower()
    if auth_clean and title_clean:
        comp_key = f"k:{auth_clean}::{title_clean}"
        if comp_key in seen:
            return True
    return False

async def export_netscape_cookies(ctx):
    """Экспортирует куки браузера в формат Netscape для yt-dlp и сессий."""
    try:
        cookies = await ctx.cookies("https://www.tiktok.com")
        lines = ["# Netscape HTTP Cookie File"]
        for c in cookies:
            domain = c.get("domain", ".tiktok.com")
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure") else "FALSE"
            expires = str(int(c.get("expires", 0))) if c.get("expires", 0) > 0 else "0"
            name = c.get("name", "")
            value = c.get("value", "")
            if name and value:
                lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
        COOKIES_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass

TIKWM_API_BASE = "https://www.tikwm.com/api/"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=90, connect=10)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.tiktok.com/",
}

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'be-BY', 'be', 'en-US', 'en'] });
Object.defineProperty(navigator, 'language', { get: () => 'ru-RU' });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--password-store=basic"
]
BROWSER_IGNORE_DEFAULT_ARGS = ["--enable-automation"]

# ===================== РЕГИОНАЛЬНЫЕ НАСТРОЙКИ И ФИЛЬТРЫ =====================

BELARUS_COORDINATES = {"latitude": 53.9006, "longitude": 27.5590}
BELARUS_TIMEZONE = "Europe/Minsk"
BELARUS_LOCALE = "ru-RU"

# Запрещенные восточные / индийские / арабские алфавиты
FOREIGN_SCRIPTS_RE = re.compile(
    r'[\u0900-\u0DFF'  # Индийские (Деванагари, Бенгали, Гуджарати, Тамильский, Телугу, Каннада, Малаялам, Сингальский)
    r'\u0E00-\u0EFF'  # Тайский, Лаосский
    r'\u1000-\u109F'  # Мьянма/Бирманский
    r'\u1780-\u17FF'  # Кхмерский
    r'\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF'  # Арабский, Урду, Персидский
    r']'
)

# Кириллица (русский, белорусский с і, ў, украинский)
CYRILLIC_RE = re.compile(r'[а-яА-ЯёЁіІўЎґҐ]')

# Стоп-слова зарубежного / индийского / азиатского мусора
NON_CIS_BAD_KEYWORDS = {
    'hindi', 'bhojpuri', 'desi', 'shayari', 'tiktokindia', 'bollywood',
    'pakistan', 'bangla', 'tamil', 'telugu', 'punjabi', 'urdu', 'kerala',
    'marathi', 'gujarati', 'indonesia', 'vietnam', 'philippines', 'tagalog',
    'arabic', 'dubai', 'saudi', 'egypt', 'morocco', 'iraq', 'syria'
}

# Запрещенные регионы
BLOCKED_REGIONS = {
    'IN', 'PK', 'BD', 'NP', 'LK', 'VN', 'TH', 'ID', 'PH', 'MY',
    'SA', 'AE', 'EG', 'IQ', 'SY', 'MA', 'DZ', 'TN', 'NG', 'KE', 'GH'
}

def is_quality_cis_video(data: dict) -> bool:
    """
    Проверяет видео на соответствие региону Беларусь/СНГ и отфильтровывает
    зарубежный спам (Индия, Азия, арабские страны и т.д.).
    """
    if not isinstance(data, dict):
        return False

    region = (
        data.get("region") or 
        data.get("countryCode") or 
        data.get("locationCreated") or 
        ""
    ).upper()
    if region in BLOCKED_REGIONS:
        return False

    title = str(data.get("desc") or data.get("title") or "")
    author = data.get("author") or {}
    if isinstance(author, dict):
        uname = author.get("uniqueId") or author.get("unique_id") or ""
        nick = author.get("nickname") or uname
    else:
        nick = str(author)
        uname = str(author)

    music = data.get("music") or data.get("music_info") or {}
    if isinstance(music, dict):
        music_title = music.get("title") or ""
    else:
        music_title = str(music or "")

    full_text = f"{title} {nick} {music_title}".strip()

    # 1. Жесткий бан восточных алфавитов
    if FOREIGN_SCRIPTS_RE.search(full_text):
        return False

    low = full_text.lower()

    # 2. Стоп-слова зарубежного мусора
    for bad in NON_CIS_BAD_KEYWORDS:
        if bad in low:
            return False

    # 3. Приоритет кириллицы (русский / белорусский контент)
    if CYRILLIC_RE.search(full_text):
        return True

    # 4. Если кириллицы нет (например на английском), проверяем ключевые слова Беларуси и СНГ
    for kw in ["belarus", "minsk", "gomel", "brest", "grodno", "vitebsk", "mogilev", "cis"]:
        if kw in low:
            return True

    return False

# Очередь предзагруженных рекомендаций из ленты
_rec_feed_queue = []
_seen_video_ids = set()

# Блокировка для избежания конфликтов одновременного запуска Chromium
_browser_lock = asyncio.Lock()

# ===================== УПРАВЛЕНИЕ СЕССИЕЙ АККАУНТА =====================

def load_account_session() -> dict:
    """Загружает сохраненную сессию аккаунта TikTok с авто-восстановлением и полной поддержкой cookies."""
    data = {}
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    # Если в сохраненной сессии есть sessionid
    if data and data.get("sessionid"):
        # Если нет полных cookies_str или cookie_list, обогащаем из COOKIES_FILE если он существует
        if COOKIES_FILE.exists() and (not data.get("cookie_list") or len(data.get("cookies", {})) <= 1):
            try:
                c_map = {}
                c_list = []
                for line in COOKIES_FILE.read_text("utf-8").splitlines():
                    if line.startswith("#") or not line.strip():
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        name, val = parts[5].strip(), parts[6].strip()
                        c_map[name] = val
                        c_list.append({
                            "name": name,
                            "value": val,
                            "domain": parts[0].strip(),
                            "path": parts[2].strip() or "/"
                        })
                if c_map:
                    data["cookies"] = c_map
                    data["cookie_list"] = c_list
                    if not data.get("cookies_str") or data["cookies_str"] == f"sessionid={data['sessionid']}":
                        data["cookies_str"] = "; ".join(f"{k}={v}" for k, v in c_map.items())
            except Exception:
                pass
        return data

    # Авто-восстановление из cookies.txt если сессия есть в браузере
    if COOKIES_FILE.exists():
        try:
            sid = ""
            c_map = {}
            c_list = []
            for line in COOKIES_FILE.read_text("utf-8").splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    name, val = parts[5].strip(), parts[6].strip()
                    c_map[name] = val
                    c_list.append({
                        "name": name,
                        "value": val,
                        "domain": parts[0].strip(),
                        "path": parts[2].strip() or "/"
                    })
                    if name in ("sessionid", "sessionid_ss") and not sid:
                        sid = val
            if sid:
                cookie_str = "; ".join(f"{k}={v}" for k, v in c_map.items())
                acc = {
                    "sessionid": sid,
                    "cookies_str": cookie_str,
                    "cookies": c_map,
                    "cookie_list": c_list,
                    "username": "iamkinngs",
                    "nickname": "iamkinngs",
                    "avatar_url": "",
                    "last_login": int(time.time()),
                    "browser_auth": True
                }
                save_account_session(acc)
                return acc
        except Exception:
            pass

    return {
        "sessionid": "",
        "cookies_str": "",
        "cookies": {},
        "cookie_list": [],
        "username": "",
        "nickname": "",
        "avatar_url": "",
        "last_login": 0,
        "browser_auth": False
    }

def save_account_session(data: dict):
    """Сохраняет данные сессии аккаунта и синхронизирует куки."""
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Если переданы куки, также синхронизируем tiktok_cookies.txt (Netscape)
    try:
        c_list = data.get("cookie_list")
        if not c_list and data.get("cookies"):
            c_list = [
                {"name": k, "value": v, "domain": ".tiktok.com", "path": "/"}
                for k, v in data["cookies"].items()
            ]
        elif not c_list and data.get("sessionid"):
            c_list = [
                {"name": "sessionid", "value": data["sessionid"], "domain": ".tiktok.com", "path": "/"},
                {"name": "sessionid_ss", "value": data["sessionid"], "domain": ".tiktok.com", "path": "/"},
                {"name": "sid_tt", "value": data["sessionid"], "domain": ".tiktok.com", "path": "/"},
            ]
        if c_list and not COOKIES_FILE.exists():
            lines = ["# Netscape HTTP Cookie File"]
            for c in c_list:
                dom = c.get("domain", ".tiktok.com")
                flag = "TRUE" if dom.startswith(".") else "FALSE"
                path = c.get("path", "/")
                lines.append(f"{dom}\t{flag}\t{path}\tTRUE\t0\t{c['name']}\t{c['value']}")
            COOKIES_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass

def parse_cookies_input(raw_input: str) -> tuple[str, dict, list]:
    """
    Извлекает sessionid, словарь cookies и список cookie-объектов из любого формата:
    - JSON (Cookie-Editor, EditThisCookie)
    - Netscape Cookie format
    - HTTP Cookie header (k1=v1; k2=v2)
    - Одиночный sessionid
    """
    raw_input = raw_input.strip()
    cookies_dict = {}
    cookies_list = []
    sessionid = ""

    # 1. Попытка распарсить как JSON (список кук или словарь)
    if (raw_input.startswith("[") and raw_input.endswith("]")) or (raw_input.startswith("{") and raw_input.endswith("}")):
        try:
            parsed = json.loads(raw_input)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("name") and item.get("value"):
                        n, v = str(item["name"]).strip(), str(item["value"]).strip()
                        cookies_dict[n] = v
                        cookies_list.append({
                            "name": n,
                            "value": v,
                            "domain": str(item.get("domain") or ".tiktok.com").strip(),
                            "path": str(item.get("path") or "/").strip()
                        })
            elif isinstance(parsed, dict):
                for k, v in parsed.items():
                    n, val = str(k).strip(), str(v).strip()
                    cookies_dict[n] = val
                    cookies_list.append({
                        "name": n,
                        "value": val,
                        "domain": ".tiktok.com",
                        "path": "/"
                    })
            sessionid = cookies_dict.get("sessionid") or cookies_dict.get("sessionid_ss") or ""
            if sessionid:
                return sessionid, cookies_dict, cookies_list
        except Exception:
            pass

    # 2. Попытка распарсить как Netscape Cookie формат (табы)
    if "\t" in raw_input:
        for line in raw_input.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                n, v = parts[5].strip(), parts[6].strip()
                cookies_dict[n] = v
                cookies_list.append({
                    "name": n,
                    "value": v,
                    "domain": parts[0].strip(),
                    "path": parts[2].strip() or "/"
                })
        sessionid = cookies_dict.get("sessionid") or cookies_dict.get("sessionid_ss") or ""
        if sessionid:
            return sessionid, cookies_dict, cookies_list

    # 3. HTTP Cookie строка (k1=v1; k2=v2)
    if "=" in raw_input or ";" in raw_input:
        parts = raw_input.split(";")
        for part in parts:
            if "=" in part:
                k, v = part.strip().split("=", 1)
                n, val = k.strip(), v.strip()
                if n and val:
                    cookies_dict[n] = val
                    cookies_list.append({
                        "name": n,
                        "value": val,
                        "domain": ".tiktok.com",
                        "path": "/"
                    })
        sessionid = cookies_dict.get("sessionid") or cookies_dict.get("sessionid_ss") or ""
    else:
        # 4. Одиночный sessionid
        sessionid = raw_input
        cookies_dict["sessionid"] = sessionid
        cookies_list.append({
            "name": "sessionid",
            "value": sessionid,
            "domain": ".tiktok.com",
            "path": "/"
        })

    return sessionid, cookies_dict, cookies_list

# ===================== АВТОРИЗАЦИЯ ЧЕРЕЗ БРАУЗЕР (QR-КОД) =====================

async def browser_tiktok_auth(event: events.NewMessage.Event):
    """
    Открывает видимое окно Chromium на ПК для сканирования QR-кода
    со смартфона (iPhone / Android) или логина.
    """
    if not PLAYWRIGHT_AVAILABLE:
        await event.edit(
            "❌ **Движок Playwright не установлен.**\n"
            "Выполните в терминале:\n`pip install playwright && playwright install chromium`"
        )
        return

    await event.edit(
        "🌐 **Запуск браузера для авторизации в TikTok...**\n\n"
        "🖥 На твоём компьютере сейчас откроется окно браузера с QR-кодом.\n\n"
        "📱 **Как войти с телефона (iPhone / Android):**\n"
        "1. Открой **TikTok** на телефоне\n"
        "2. Перейди в **Профиль ➔ Меню (3 полоски) ➔ Мой QR-код ➔ значок Сканера (справа сверху)**\n"
        "3. Наведи камеру на QR-код в окне браузера на ПК и нажми **Подтвердить**\n\n"
        "⏳ *Ожидаю авторизацию (таймаут 120 секунд)...*"
    )

    logged_in = False
    username = ""
    sid = ""

    async with _browser_lock:
        try:
            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    str(BROWSER_DATA_DIR),
                    headless=False,
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 850},
                    locale="ru-RU",
                    ignore_default_args=BROWSER_IGNORE_DEFAULT_ARGS,
                    args=BROWSER_ARGS
                )
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.add_init_script(STEALTH_JS)

                try:
                    await page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    pass

                start_time = time.time()
                while time.time() - start_time < 120:
                    await asyncio.sleep(2.5)
                    cookies = await ctx.cookies("https://www.tiktok.com")
                    c_map = {c["name"]: c["value"] for c in cookies}
                    sid = c_map.get("sessionid") or c_map.get("sessionid_ss")

                    # Если появилась кука сессии или ушли со страницы логина
                    if sid:
                        logged_in = True
                        await asyncio.sleep(3)
                        try:
                            user_elem = await page.query_selector('a[href*="/@"]')
                            if user_elem:
                                href = await user_elem.get_attribute("href")
                                if href and "/@" in href:
                                    username = href.split("/@")[-1].split("/")[0].split("?")[0]
                        except Exception:
                            pass

                        if not username:
                            username = c_map.get("uid_tt", "TikTok User")
                        break

                await export_netscape_cookies(ctx)
                await ctx.close()
        except Exception as e:
            await event.edit(f"❌ **Ошибка при работе браузера:** `{e}`")
            return

    if logged_in:
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        acc_data = {
            "sessionid": sid,
            "cookies_str": cookie_str,
            "cookies": {c["name"]: c["value"] for c in cookies},
            "cookie_list": [
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".tiktok.com"),
                    "path": c.get("path", "/")
                }
                for c in cookies
            ],
            "username": username,
            "nickname": username,
            "avatar_url": "",
            "last_login": int(time.time()),
            "browser_auth": True
        }
        save_account_session(acc_data)
        _rec_feed_queue.clear()
        _seen_video_ids.clear()
        await event.edit(
            "🎉 **TikTok аккаунт успешно авторизован через браузер!**\n\n"
            f"👤 **Профиль:** `@{username}`\n"
            "🔒 Данные сохранены в браузере юзербота.\n\n"
            "🚀 *Теперь пиши `.tt` чтобы листать свои рекомендации прямо в чат!*"
        )
    else:
        await event.edit(
            "⏳ **Время ожидания истекло (120 сек).**\n"
            "Вход не был подтвержден. Чтобы попробовать снова, напиши: `.tt auth`."
        )

# ===================== ЗАГРУЗКА И СИНХРОНИЗАЦИЯ КУКИ В PLAYWRIGHT =====================

async def apply_saved_cookies_to_context(ctx):
    """
    Загружает полный набор cookies авторизованного пользователя в контекст Playwright
    перед любыми переходами по страницам (sessionid, passport, token, auth cookies).
    Поддерживает:
    - Детальный список cookie_list
    - Netscape-дамп tiktok_cookies.txt
    - Словарь cookies
    - Строку cookies_str
    - Авто-синтез обязательных cookies TikTok, если в tiktok_session.json есть только sessionid.
    """
    account = load_account_session()
    sid = account.get("sessionid", "").strip()

    cookies_to_add = []

    # 1. Загружаем из cookie_list (если сохранен детальный список)
    if isinstance(account.get("cookie_list"), list):
        for c in account["cookie_list"]:
            if isinstance(c, dict) and c.get("name") and c.get("value"):
                cookies_to_add.append({
                    "name": str(c["name"]).strip(),
                    "value": str(c["value"]).strip(),
                    "domain": str(c.get("domain") or ".tiktok.com").strip(),
                    "path": str(c.get("path") or "/").strip(),
                })

    # 2. Загружаем из Netscape-дампа tiktok_cookies.txt (полные куки браузера)
    if COOKIES_FILE.exists():
        try:
            for line in COOKIES_FILE.read_text("utf-8").splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    c_name = parts[5].strip()
                    c_val = parts[6].strip()
                    c_dom = parts[0].strip() or ".tiktok.com"
                    c_path = parts[2].strip() or "/"
                    if c_name and c_val:
                        cookies_to_add.append({
                            "name": c_name,
                            "value": c_val,
                            "domain": c_dom,
                            "path": c_path
                        })
        except Exception:
            pass

    # 3. Загружаем из словаря cookies в account
    if isinstance(account.get("cookies"), dict):
        for k, v in account["cookies"].items():
            if k and v:
                cookies_to_add.append({
                    "name": str(k).strip(),
                    "value": str(v).strip(),
                    "domain": ".tiktok.com",
                    "path": "/"
                })

    # 4. Загружаем из сохраненной строки cookies_str
    cookies_str = account.get("cookies_str", "").strip()
    if cookies_str:
        for part in cookies_str.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                k = k.strip()
                v = v.strip()
                if k and v:
                    cookies_to_add.append({
                        "name": k,
                        "value": v,
                        "domain": ".tiktok.com",
                        "path": "/"
                    })

    # 5. Если в сессии есть sessionid (даже если передан ТОЛЬКО sessionid без остальных кук)
    # Автоматически добавляем необходимые для нормальной работы аккаунта cookies
    if sid:
        cookies_to_add.append({"name": "sessionid", "value": sid, "domain": ".tiktok.com", "path": "/"})
        cookies_to_add.append({"name": "sessionid_ss", "value": sid, "domain": ".tiktok.com", "path": "/"})
        cookies_to_add.append({"name": "sid_tt", "value": sid, "domain": ".tiktok.com", "path": "/"})
        cookies_to_add.append({"name": "sid_guard", "value": sid, "domain": ".tiktok.com", "path": "/"})
        cookies_to_add.append({"name": "passport_fe_beating_status", "value": "true", "domain": ".www.tiktok.com", "path": "/"})
        cookies_to_add.append({
            "name": "cookie-consent",
            "value": "%7B%22optional%22%3Atrue%2C%22ga%22%3Atrue%2C%22af%22%3Atrue%2C%22fbp%22%3Atrue%2C%22lip%22%3Atrue%2C%22bing%22%3Atrue%2C%22ttads%22%3Atrue%2C%22reddit%22%3Atrue%2C%22hubspot%22%3Atrue%2C%22version%22%3A%22v10%22%7D",
            "domain": ".tiktok.com",
            "path": "/"
        })

    if cookies_to_add:
        # Убираем дубликаты по имени и домену с нормализацией
        unique = {}
        for c in cookies_to_add:
            dom = c.get("domain", ".tiktok.com")
            if not dom.startswith(".") and not dom.startswith("www"):
                dom = "." + dom
            key = (c["name"], dom)
            unique[key] = {
                "name": c["name"],
                "value": c["value"],
                "domain": dom,
                "path": c.get("path", "/")
            }
        cookie_list = list(unique.values())
        try:
            await ctx.add_cookies(cookie_list)
        except Exception:
            for c in cookie_list:
                try:
                    await ctx.add_cookies([c])
                except Exception:
                    pass

# ===================== ИЗВЛЕЧЕНИЕ РЕКОМЕНДАЦИЙ (BROWSER) =====================

async def fetch_tiktok_recommendations_browser(count: int = 15, preload_first: bool = True) -> list:
    """
    Запускает headless Chromium с профилем пользователя,
    загружает все сохраненные cookies авторизации,
    открывает личную ленту tiktok.com/foryou
    и перехватывает свежую ленту рекомендаций аккаунта.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return []

    videos = []
    seen_ids = set()

    async with _browser_lock:
        try:
            async with async_playwright() as p:
                ctx = await p.chromium.launch_persistent_context(
                    str(BROWSER_DATA_DIR),
                    headless=True,
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 850},
                    locale="ru-RU",
                    ignore_default_args=BROWSER_IGNORE_DEFAULT_ARGS,
                    args=BROWSER_ARGS
                )

                # Загружаем все cookies авторизации перед запросами
                await apply_saved_cookies_to_context(ctx)

                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.add_init_script(STEALTH_JS)

                # Блокируем картинки, шрифты и тяжелое медиа страницы, чтобы TikTok не тормозил и загружался мгновенно
                async def _route_blocker(route):
                    if route.request.resource_type in ("image", "media", "font"):
                        await route.abort()
                    else:
                        await route.continue_()

                try:
                    await page.route("**/*", _route_blocker)
                except Exception:
                    pass

                feed_ready_event = asyncio.Event()

                async def handle_response(resp):
                    url = resp.url
                    if any(k in url for k in ["/api/recommend/item_list", "/api/item/list", "item_list"]):
                        try:
                            res = await resp.json()
                            items = res.get("itemList") or res.get("data") or []
                            if isinstance(items, list):
                                for it in items:
                                    if not isinstance(it, dict):
                                        continue

                                    v_id = str(it.get("id") or it.get("video_id") or "")
                                    if not v_id or v_id in seen_ids or v_id in _seen_video_ids:
                                        continue

                                    author = it.get("author", {})
                                    uname = ""
                                    nick = ""
                                    if isinstance(author, dict):
                                        uname = author.get("uniqueId") or author.get("unique_id") or ""
                                        nick = author.get("nickname", uname)
                                    elif isinstance(author, str):
                                        uname = author
                                        nick = author

                                    desc = it.get("desc") or it.get("title") or ""

                                    # Защита от повторов: если видео уже отправлялось раньше — пропускаем!
                                    if is_video_already_seen(v_id, uname, desc):
                                        continue

                                    # Фильтр от мусора и индийских спам-скриптов
                                    if not is_quality_cis_video(it):
                                        continue

                                    video_info = it.get("video", {}) if isinstance(it.get("video"), dict) else {}
                                    play_url = video_info.get("playAddr") or video_info.get("downloadAddr") or it.get("hdplay") or it.get("play")
                                    alt_url = video_info.get("downloadAddr") if play_url != video_info.get("downloadAddr") else video_info.get("playAddr")
                                    if not play_url:
                                        continue

                                    seen_ids.add(v_id)

                                    music_title = ""
                                    music_obj = it.get("music") or it.get("music_info")
                                    if isinstance(music_obj, dict):
                                        music_title = music_obj.get("title", "")

                                    orig_url = f"https://www.tiktok.com/@{uname}/video/{v_id}" if uname else f"https://www.tiktok.com/video/{v_id}"

                                    videos.append({
                                        "video_id": v_id,
                                        "title": desc,
                                        "author": uname,
                                        "author_name": nick or uname,
                                        "duration": video_info.get("duration", 0),
                                        "music": music_title,
                                        "play_url": play_url,
                                        "alt_play_url": alt_url,
                                        "original_url": orig_url,
                                        "source": "account_fyp"
                                    })
                                if len(videos) > 0:
                                    feed_ready_event.set()
                        except Exception:
                            pass

                page.on("response", handle_response)

                try:
                    await page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=12000)
                except Exception:
                    pass

                # Быстрый скролл для перехвата свежих видео из For You (до 6 секунд максимум)
                for _ in range(12):
                    if feed_ready_event.is_set():
                        break
                    await asyncio.sleep(0.5)
                    try:
                        await page.mouse.wheel(0, 900)
                    except Exception:
                        pass

                # 2. Предзагрузка ровно 1 (первого) видео из полученных рекомендаций
                if preload_first and videos:
                    target_v = videos[0]
                    for p_url in [target_v.get("play_url"), target_v.get("alt_play_url")]:
                        if not p_url or target_v.get("video_bytes"):
                            continue
                        try:
                            v_resp = await ctx.request.get(
                                p_url,
                                headers={"Referer": "https://www.tiktok.com/"},
                                timeout=8000
                            )
                            if v_resp.status in (200, 206):
                                v_data = await v_resp.body()
                                if len(v_data) > 5000:
                                    target_v["video_bytes"] = v_data
                                    break
                        except Exception:
                            pass

                # Сохраняем куки
                cookies = await ctx.cookies("https://www.tiktok.com")
                cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                for v in videos:
                    v["cookies_str"] = cookie_str

                await export_netscape_cookies(ctx)
                await ctx.close()
        except Exception:
            pass

    return videos

async def download_video_browser(play_url: str, cookies_str: str = "") -> bytes | None:
    """
    Высокоскоростное скачивание видео напрямую с CDN TikTok.
    1) Мгновенный aiohttp с видеоплеерными заголовками (300-500 мс).
    2) Резервный Playwright Request API при блокировке Akamai CDN.
    """
    if not play_url:
        return None

    # 1. Быстрый способ: aiohttp (0.3 - 0.7 сек)
    cookies = {}
    if cookies_str:
        for part in cookies_str.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v

    try:
        req_headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.tiktok.com/",
            "Range": "bytes=0-",
            "Accept": "*/*",
            "Sec-Fetch-Dest": "video",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(play_url, headers=req_headers, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status in (200, 206):
                    data = await resp.read()
                    if len(data) > 5000:
                        return data
    except Exception:
        pass

    # 2. Резерв: Playwright Request API — 100% обход Akamai CDN блокировок
    if PLAYWRIGHT_AVAILABLE:
        async with _browser_lock:
            try:
                async with async_playwright() as p:
                    ctx = await p.chromium.launch_persistent_context(
                        str(BROWSER_DATA_DIR),
                        headless=True,
                        user_agent=USER_AGENT,
                        locale="ru-RU",
                        ignore_default_args=BROWSER_IGNORE_DEFAULT_ARGS,
                        args=BROWSER_ARGS
                    )
                    await apply_saved_cookies_to_context(ctx)
                    resp = await ctx.request.get(
                        play_url,
                        headers={"Referer": "https://www.tiktok.com/"},
                        timeout=9000
                    )
                    if resp.status in (200, 206):
                        data = await resp.body()
                        await ctx.close()
                        if len(data) > 5000:
                            return data
                    await ctx.close()
            except Exception:
                pass

    return None

# ===================== УТИЛИТЫ ССЫЛОК =====================

def _extract_tiktok_url(text: str) -> str | None:
    """Извлекает ссылку TikTok из текста."""
    patterns = [
        r'(https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+[^\s]*)',
        r'(https?://(?:www\.)?tiktok\.com/@[\w.-]+/photo/\d+[^\s]*)',
        r'(https?://vm\.tiktok\.com/[\w]+[^\s]*)',
        r'(https?://vt\.tiktok\.com/[\w]+[^\s]*)',
        r'(https?://(?:www\.)?tiktok\.com/t/[\w]+[^\s]*)',
        r'(https?://(?:www\.)?tiktok\.com/@[\w.-]+[^\s]*)'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None

async def _resolve_short_url(session: aiohttp.ClientSession, short_url: str) -> str:
    """Разворачивает короткую ссылку vm.tiktok.com в полный URL."""
    try:
        async with session.get(short_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10), headers=HEADERS) as resp:
            final = str(resp.url)
            if "/video/" in final or "/photo/" in final or "@" in final:
                return final
    except Exception:
        pass
    return short_url

# ===================== ИЗВЛЕЧЕНИЕ РЕКОМЕНДАЦИЙ (HTTP FALLBACK) =====================

async def fetch_tiktok_recommendations_http(sessionid: str = "") -> list:
    """
    Запасной метод: получение рекомендаций через прямой HTTP запрос или TikWM.
    """
    account = load_account_session()
    sid = sessionid or account.get("sessionid", "")

    cookies = {}
    if sid:
        cookies["sessionid"] = sid
        if account.get("cookies_str"):
            try:
                _, c_dict, _ = parse_cookies_input(account["cookies_str"])
                cookies.update(c_dict)
            except Exception:
                pass
        if isinstance(account.get("cookies"), dict):
            cookies.update(account["cookies"])

    req_headers = {
        **HEADERS,
        "Referer": "https://www.tiktok.com/foryou",
    }

    url = (
        "https://www.tiktok.com/api/recommend/item_list/?"
        "aid=1988&app_language=ru-RU&app_name=tiktok_web&browser_language=ru-RU&"
        "browser_name=Mozilla&browser_online=true&browser_platform=Win32&"
        "channel=tiktok_web&cookie_enabled=true&count=16&device_id=7382910384910293847&"
        "focus_state=true&from_page=fyp&history_len=0&is_fullscreen=false&"
        "is_page_visible=true&os=windows&priority_region=BY&region=BY&tz_name=Europe%2FMinsk"
    )

    videos = []

    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.get(url, headers=req_headers, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = data.get("itemList", [])
                    if isinstance(items, list) and items:
                        for it in items:
                            if not is_quality_cis_video(it):
                                continue
                            v_id = str(it.get("id", ""))
                            author = it.get("author", {})
                            uname = author.get("uniqueId", "") if isinstance(author, dict) else ""
                            desc = it.get("desc", "")
                            if is_video_already_seen(v_id, uname, desc):
                                continue
                            video_info = it.get("video", {})
                            play_url = video_info.get("downloadAddr") or video_info.get("playAddr")
                            if v_id and author and play_url:
                                videos.append({
                                    "video_id": v_id,
                                    "title": desc,
                                    "author": uname,
                                    "author_name": author.get("nickname", uname) if isinstance(author, dict) else uname,
                                    "duration": video_info.get("duration", 0),
                                    "music": it.get("music", {}).get("title", "") if isinstance(it.get("music"), dict) else "",
                                    "play_url": play_url,
                                    "original_url": f"https://www.tiktok.com/@{uname}/video/{v_id}" if uname else "",
                                    "source": "account_fyp"
                                })
    except Exception:
        pass

    return videos

# ===================== СКАЧИВАНИЕ ВИДЕО ПО ССЫЛКЕ =====================

async def _download_bytes(session: aiohttp.ClientSession, url: str, cookies: dict = None) -> bytes | None:
    """Скачивает видео в виде байтов."""
    if not url:
        return None
    if url.startswith("/"):
        url = "https://www.tikwm.com" + url

    try:
        async with session.get(url, headers=HEADERS, cookies=cookies or {}, timeout=DOWNLOAD_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            total_size = 0
            chunks = []
            async for chunk in resp.content.iter_chunked(65536):
                chunks.append(chunk)
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    return None
            return b"".join(chunks)
    except Exception:
        return None

async def download_tiktok_by_url(tiktok_url: str) -> tuple[bytes | None, dict]:
    """
    Скачивает видео из TikTok по прямой или короткой ссылке.
    Каскад: TikWM -> yt-dlp -> aiohttp.
    """
    metadata = {
        "title": "",
        "author": "",
        "author_name": "",
        "duration": 0,
        "music": "",
        "original_url": tiktok_url,
        "video_id": "",
        "source": "unknown"
    }

    account = load_account_session()
    sid = account.get("sessionid", "")
    cookies = {"sessionid": sid} if sid else {}

    async with aiohttp.ClientSession(cookies=cookies) as session:
        # Разворачиваем короткие ссылки
        if any(x in tiktok_url for x in ["vm.tiktok.com", "vt.tiktok.com", "tiktok.com/t/"]):
            tiktok_url = await _resolve_short_url(session, tiktok_url)
            metadata["original_url"] = tiktok_url

        # Метод 1: TikWM API (быстрый таймаут 2.5 сек)
        try:
            form = aiohttp.FormData()
            form.add_field("url", tiktok_url)
            form.add_field("hd", "1")
            async with session.post(TIKWM_API_BASE, data=form, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=2.5)) as resp:
                if resp.status == 200:
                    res = await resp.json(content_type=None)
                    if res.get("code") == 0 and res.get("data"):
                        data = res["data"]
                        play = data.get("hdplay") or data.get("play")
                        video_bytes = await _download_bytes(session, play)
                        if video_bytes and len(video_bytes) > 5000:
                            author = data.get("author", {})
                            metadata.update({
                                "title": data.get("title", "")[:200],
                                "author": author.get("unique_id", "") if isinstance(author, dict) else "",
                                "author_name": author.get("nickname", "") if isinstance(author, dict) else "",
                                "duration": data.get("duration", 0),
                                "music": data.get("music_info", {}).get("title", "") if isinstance(data.get("music_info"), dict) else "",
                                "video_id": str(data.get("id", "")),
                                "source": "tikwm"
                            })
                            return video_bytes, metadata
        except Exception:
            pass

    # Метод 2: yt-dlp
    try:
        import yt_dlp
        temp_file = TEMP_DIR / f"tt_{int(time.time())}_{random.randint(1000, 9999)}"
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'best[ext=mp4][filesize<50M]/best',
            'outtmpl': str(temp_file) + '.%(ext)s',
            'overwrites': True,
            'http_headers': {'User-Agent': USER_AGENT},
            'socket_timeout': 8,
            'retries': 1,
            'fragment_retries': 1,
        }
        if COOKIES_FILE.exists():
            ydl_opts['cookiefile'] = str(COOKIES_FILE)

        info = None
        def _ytdl_run():
            nonlocal info
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(tiktok_url, download=True)

        await asyncio.to_thread(_ytdl_run)

        for f in TEMP_DIR.glob(f"{temp_file.name}*"):
            try:
                if f.stat().st_size > 5000:
                    v_bytes = f.read_bytes()
                    f.unlink()
                    if info:
                        metadata.update({
                            "title": str(info.get("title", ""))[:200],
                            "author": info.get("uploader_id", info.get("uploader", "")),
                            "author_name": info.get("uploader", ""),
                            "duration": info.get("duration", 0),
                            "video_id": str(info.get("id", "")),
                            "source": "yt-dlp"
                        })
                    return v_bytes, metadata
                f.unlink()
            except Exception:
                pass
    except Exception:
        pass

    return None, metadata

# ===================== ПОЛУЧЕНИЕ СЛЕДУЮЩЕГО ВИДЕО РЕКОМЕНДАЦИЙ =====================

_refill_lock = asyncio.Lock()

async def _background_refill_and_preload():
    """
    Фоновый воркер:
    Если в очереди осталось меньше 3 роликов — в фоновом режиме пополняет очередь свежими ссылками из FYP.
    Не скачивает видеофайлы заранее, чтобы не забивать интернет-канал и трафик.
    """
    if _refill_lock.locked():
        return

    async with _refill_lock:
        try:
            if len(_rec_feed_queue) < 3:
                fresh = await fetch_tiktok_recommendations_browser(count=8, preload_first=False)
                if fresh:
                    for it in fresh:
                        v_id = it.get("video_id")
                        if v_id and v_id not in _seen_video_ids and is_quality_cis_video(it):
                            _rec_feed_queue.append(it)
        except Exception:
            pass

async def get_next_recommendation_video() -> tuple[bytes | None, dict]:
    """
    Возвращает следующее видео из ленты рекомендаций пользователя (Беларусь/СНГ).
    Использует кэшированную очередь, пополняя её через браузер Playwright.
    Если скачивание одного видео не удается, пробует следующее из очереди.
    """
    global _rec_feed_queue, _seen_video_ids

    # Очищаем очередь от любых не-СНГ/иностранных элементов
    _rec_feed_queue = [v for v in _rec_feed_queue if is_quality_cis_video(v)]

    # Пополняем очередь, если пусто
    if not _rec_feed_queue:
        new_batch = await fetch_tiktok_recommendations_browser()
        if not new_batch:
            new_batch = await fetch_tiktok_recommendations_http()

        # Строгая фильтрация (контент без повторов)
        filtered = [
            v for v in new_batch 
            if is_quality_cis_video(v) and not is_video_already_seen(v.get("video_id", ""), v.get("author", ""), v.get("title", ""))
        ]
        fresh = [v for v in filtered if v.get("video_id") not in _seen_video_ids]
        if not fresh and filtered:
            _seen_video_ids.clear()
            fresh = filtered
        if fresh:
            _rec_feed_queue.extend(fresh)

    if not _rec_feed_queue:
        return None, {}

    # Перебираем очередь, пока не найдем успешно скачанное видео
    while _rec_feed_queue:
        chosen = _rec_feed_queue.pop(0)
        v_id = str(chosen.get("video_id", ""))
        author = str(chosen.get("author", ""))
        title = str(chosen.get("title", ""))

        # Исключаем повторы по уникальному ID и связке автор+описание
        if is_video_already_seen(v_id, author, title):
            continue

        if not is_quality_cis_video(chosen):
            continue

        if v_id:
            _seen_video_ids.add(v_id)
        if len(_seen_video_ids) > 500:
            _seen_video_ids.clear()

        # 1. Если видео уже предварительно скачано прямо в сессии браузера или фоне
        if chosen.get("video_bytes") and len(chosen["video_bytes"]) > 5000:
            mark_video_seen(v_id, author, title)
            # В фоне готовим следующие видео, пока пользователь смотрит текущее
            asyncio.create_task(_background_refill_and_preload())
            return chosen["video_bytes"], chosen

        # 2. Скачивание play_url через direct request с куками
        play_url = chosen.get("play_url") or chosen.get("alt_play_url")
        video_bytes = None
        if play_url:
            video_bytes = await download_video_browser(play_url, cookies_str=chosen.get("cookies_str", ""))

        # 3. Если прямой URL не скачался, скачиваем по оригинальной ссылке (yt-dlp)
        if (not video_bytes or len(video_bytes) <= 5000) and chosen.get("original_url"):
            video_bytes, meta = await download_tiktok_by_url(chosen["original_url"])
            if video_bytes and len(video_bytes) > 5000:
                chosen.update({k: v for k, v in meta.items() if v})

        if video_bytes and len(video_bytes) > 5000:
            mark_video_seen(v_id, author, title)
            # В фоне готовим следующие видео
            asyncio.create_task(_background_refill_and_preload())
            return video_bytes, chosen

    return None, {}

def _format_caption(meta: dict, elapsed: float, is_fyp: bool = False) -> str:
    """Форматирует красивый текст для сообщения (с защитой от лимита Telegram 1024 символа)."""
    parts = []

    if meta.get("author"):
        profile_url = f"https://www.tiktok.com/@{meta['author']}"
        author_display = str(meta.get("author_name") or meta["author"])[:40]
        parts.append(f"👤 [{author_display}]({profile_url})")
    elif not is_fyp:
        parts.append("🎬 **TikTok**")

    title = str(meta.get("title", "")).strip()
    if title:
        # Лимит Telegram на подпись к медиа строго 1024 символа
        if len(title) > 350:
            title = title[:345] + "..."
        parts.append(f"\n📝 {title}")

    info_bits = []
    if meta.get("duration"):
        mins = int(meta["duration"]) // 60
        secs = int(meta["duration"]) % 60
        info_bits.append(f"⏱ {mins}:{secs:02d}" if mins else f"⏱ {secs}с")

    if meta.get("music"):
        music = str(meta["music"])[:35]
        info_bits.append(f"🎵 {music}")

    info_bits.append(f"⚡ {elapsed:.1f}s")
    if info_bits:
        parts.append("\n" + " • ".join(info_bits))

    if meta.get("original_url"):
        parts.append(f"\n🔗 [Смотреть в TikTok]({meta['original_url']})")

    res = "\n".join(parts)
    if len(res) > 950:
        res = res[:940] + "..."
    return res

# ===================== КОМАНДЫ ЮЗЕРБОТА =====================

@core.command("tt", description="Листать рекомендации или скачать видео TikTok", usage=".tt [ссылка/auth/rec/me/help]")
async def tiktok_cmd(event: events.NewMessage.Event):
    """
    Главная команда модуля TikTok.
    - .tt            — Листать твои рекомендации (For You)
    - .tt auth       — Войти в аккаунт через браузер (QR-код с телефона)
    - .tt <ссылка>   — Скачать видео без водяного знака
    - .tt login <id> — Ручная привязка sessionid
    - .tt me         — Статус аккаунта
    - .tt logout     — Выйти из аккаунта
    - .tt help       — Справка
    """
    raw = event.raw_text or ""
    parts = raw.split(maxsplit=1)
    subcmd = parts[1].strip() if len(parts) > 1 else ""

    t0 = time.time()

    # --- Подкоманда: ПОМОЩЬ ---
    if subcmd.lower() in ("help", "помощь", "инфо"):
        account = load_account_session()
        has_acc = "✅ Привязан" if account.get("sessionid") else "❌ Не привязан"
        uname = f" (@{account.get('username')})" if account.get("username") else ""
        help_text = (
            "🎬 **TIKTOK МОДУЛЬ С РЕКОМЕНДАЦИЯМИ**\n\n"
            f"👤 **Статус аккаунта:** `{has_acc}`{uname}\n\n"
            "✨ **Команды:**\n"
            "• `.tt [кол-во]` — Листать видео из рекомендаций (по умолч. 1, макс. 10)\n"
            "• `.tt <число>` — Скачать сразу несколько видео (например: `.tt 5`)\n"
            "• `.tt auth` — 📸 **Войти по QR-коду со смартфона** (через окно браузера)\n"
            "• `.tt <ссылка>` — Скачать видео без водяного знака\n"
            "• `.tt login <sessionid>` — Ручная привязка sessionid\n"
            "• `.tt me` — Проверить статус аккаунта\n"
            "• `.tt logout` — Отвязать аккаунт\n\n"
            "💡 **Как подключить рекомендации за 1 минуту:**\n"
            "1. Напиши `.tt auth` в чат.\n"
            "2. На ПК откроется браузер с QR-кодом.\n"
            "3. В TikTok на телефоне отсканируй QR-код (Профиль ➔ Меню ➔ Мой QR-код ➔ Сканер)."
        )
        await event.edit(help_text)
        return

    # --- Подкоманда: АВТОРИЗАЦИЯ ЧЕРЕЗ БРАУЗЕР (.tt auth или .tt login без аргументов) ---
    if subcmd.lower() in ("auth", "авторизация", "войти", "qr") or subcmd.lower() == "login":
        await browser_tiktok_auth(event)
        return

    # --- Подкоманда: ВХОД ПО SESSIONID / COOKIES (.tt login / .tt cookie / .tt setcookie) ---
    if subcmd.lower().startswith(("login ", "setcookie ", "cookie ", "cookies ")):
        cookie_data = subcmd.split(maxsplit=1)[1].strip()
        sessionid, cookies_dict, cookie_list = parse_cookies_input(cookie_data)

        if not sessionid:
            await event.edit("❌ **Ошибка:** Не найден `sessionid`. Укажи: `.tt login <sessionid>` или `.tt auth`.")
            return

        await event.edit("🔄 **Сохраняю сессию и cookies аккаунта TikTok...**")

        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies_dict.items())
        account_data = {
            "sessionid": sessionid,
            "cookies_str": cookie_str,
            "cookies": cookies_dict,
            "cookie_list": cookie_list,
            "username": "",
            "nickname": "",
            "avatar_url": "",
            "last_login": int(time.time()),
            "browser_auth": False
        }
        save_account_session(account_data)

        # Синхронизируем Netscape cookies для Playwright и yt-dlp
        if cookie_list:
            lines = ["# Netscape HTTP Cookie File"]
            for c in cookie_list:
                dom = c.get("domain", ".tiktok.com")
                flag = "TRUE" if dom.startswith(".") else "FALSE"
                path = c.get("path", "/")
                lines.append(f"{dom}\t{flag}\t{path}\tTRUE\t0\t{c['name']}\t{c['value']}")
            COOKIES_FILE.write_text("\n".join(lines), encoding="utf-8")

        # Очищаем старую очередь
        _rec_feed_queue.clear()
        _seen_video_ids.clear()

        c_count = len(cookies_dict)
        success_text = (
            "🎉 **Аккаунт TikTok сохранен!**\n\n"
            f"🔑 **Session ID:** `{sessionid[:8]}...{sessionid[-4:]}`\n"
            f"🍪 **Загружено cookies:** `{c_count}` шт.\n\n"
            "💡 *Все куки будут автоматически добавлены в Playwright до перехода в For You.*\n"
            "🚀 Пиши `.tt` чтобы листать рекомендации!"
        )
        await event.edit(success_text)
        return

    # --- Подкоманда: ВЫХОД ИЗ АККАУНТА (LOGOUT) ---
    if subcmd.lower() in ("logout", "unlogin", "выйти"):
        save_account_session({})
        _rec_feed_queue.clear()
        _seen_video_ids.clear()
        await event.edit("🚪 **Аккаунт TikTok отвязан.** Рекомендации сброшены.")
        return

    # --- Подкоманда: СТАТУС АККАУНТА (ME / ACCOUNT) ---
    if subcmd.lower() in ("me", "account", "аккаунт", "профиль"):
        account = load_account_session()
        sid = account.get("sessionid")
        if sid:
            masked = f"{sid[:8]}...{sid[-4:]}"
            queue_len = len(_rec_feed_queue)
            user_str = f"@{account.get('username')}" if account.get("username") else "Авторизован"
            b_auth = "🌐 Браузерный профиль (Playwright)" if account.get("browser_auth") else "🔑 Session ID"
            text = (
                "👤 **ПРИВЯЗАННЫЙ АККАУНТ TIKTOK**\n\n"
                "🟢 **Статус:** Активен\n"
                f"👤 **Пользователь:** `{user_str}`\n"
                f"⚙️ **Тип авторизации:** `{b_auth}`\n"
                f"🔑 **Сессия:** `{masked}`\n"
                f"📥 **В очереди рекомендаций:** `{queue_len}` видео\n\n"
                "💡 *Пиши `.tt` для листания ленты или `.tt logout` для отвязки.*"
            )
        else:
            text = (
                "👤 **АККАУНТ TIKTOK НЕ ПРИВЯЗАН**\n\n"
                "🔴 **Статус:** Не подключен\n\n"
                "💡 **Чтобы бот листал твои персональные рекомендации:**\n"
                "Напиши: `.tt auth` (вход по QR-коду со смартфона)."
            )
        await event.edit(text)
        return

    # --- РЕЖИМ 1: СКАЧИВАНИЕ ПО ССЫЛКЕ ---
    tiktok_url = _extract_tiktok_url(subcmd)
    if not tiktok_url:
        try:
            reply = await event.get_reply_message()
            if reply and reply.raw_text:
                tiktok_url = _extract_tiktok_url(reply.raw_text)
        except Exception:
            pass

    if tiktok_url:
        await event.edit("📥 **Скачиваю видео из TikTok...**")
        video_bytes, meta = await download_tiktok_by_url(tiktok_url)
        elapsed = time.time() - t0

        if not video_bytes:
            await event.edit("❌ **Не удалось скачать видео.** Возможно, видео удалено или приватное.")
            return

        caption = _format_caption(meta, elapsed, is_fyp=False)
        video_file = io.BytesIO(video_bytes)
        video_file.name = f"tiktok_{meta.get('video_id', 'video')}.mp4"

        try:
            await event.client.send_file(
                event.chat_id,
                video_file,
                caption=caption,
                reply_to=event.reply_to_msg_id,
                supports_streaming=True
            )
            await event.delete()
        except Exception as e:
            if "caption is too long" in str(e).lower():
                try:
                    video_file.seek(0)
                    short_cap = f"🎬 **TikTok** • ⚡ {elapsed:.1f}s"
                    if meta.get("original_url"):
                        short_cap += f"\n🔗 [Смотреть в TikTok]({meta['original_url']})"
                    await event.client.send_file(
                        event.chat_id,
                        video_file,
                        caption=short_cap,
                        reply_to=event.reply_to_msg_id,
                        supports_streaming=True
                    )
                    await event.delete()
                except Exception as e2:
                    await event.edit(f"❌ **Ошибка при отправке:** `{e2}`")
            else:
                await event.edit(f"❌ **Ошибка при отправке:** `{e}`")
        return

    # --- РЕЖИМ 2: ЛИСТАНИЕ РЕКОМЕНДАЦИЙ (FYP) ---
    # Парсим количество видео (по умолчанию 1, максимум 10)
    count = 1
    if subcmd.isdigit():
        count = int(subcmd)
    elif subcmd.lower().startswith("rec") or subcmd.lower().startswith("fyp"):
        rec_parts = subcmd.split()
        if len(rec_parts) > 1 and rec_parts[1].isdigit():
            count = int(rec_parts[1])

    count = max(1, min(count, 10))

    account = load_account_session()
    has_sid = bool(account.get("sessionid"))

    sent_count = 0
    for i in range(count):
        # Если в памяти уже лежит готовое видео, не тратим время на лишний edit в Telegram
        if not (_rec_feed_queue and _rec_feed_queue[0].get("video_bytes")):
            if count > 1:
                status_msg = f"🎬 **Загружаю видео ({i + 1}/{count}) из TikTok...**"
            else:
                status_msg = "🎬 **Ищу видео из TikTok...**"
            try:
                await event.edit(status_msg)
            except Exception:
                pass

        video_bytes, meta = await get_next_recommendation_video()
        elapsed = time.time() - t0

        if not video_bytes:
            if sent_count == 0:
                if not has_sid:
                    msg = (
                        "⚠️ **Не удалось загрузить рекомендации.**\n\n"
                        "💡 **Подключи свой аккаунт TikTok, чтобы листать рекомендации:**\n"
                        "Напиши в чат: `.tt auth` и отсканируй QR-код со своего телефона."
                    )
                else:
                    msg = (
                        "⚠️ **Лента рекомендаций пуста или сессия устарела.**\n\n"
                        "💡 Обнови авторизацию через QR-код:\n"
                        "Напиши: `.tt auth`"
                    )
                await event.edit(msg)
            break

        caption = _format_caption(meta, elapsed, is_fyp=has_sid)
        video_file = io.BytesIO(video_bytes)
        video_file.name = f"tiktok_fyp_{meta.get('video_id', f'rec_{i}')}.mp4"

        try:
            await event.client.send_file(
                event.chat_id,
                video_file,
                caption=caption,
                reply_to=event.reply_to_msg_id,
                supports_streaming=True
            )
            sent_count += 1
        except Exception as e:
            if "caption is too long" in str(e).lower():
                try:
                    author_part = f"👤 @{meta['author']} • " if meta.get("author") else ""
                    short_cap = f"{author_part}⚡ {elapsed:.1f}s"
                    if meta.get("original_url"):
                        short_cap += f"\n🔗 [Смотреть в TikTok]({meta['original_url']})"
                    await event.client.send_file(
                        event.chat_id,
                        video_file,
                        caption=short_cap,
                        reply_to=event.reply_to_msg_id,
                        supports_streaming=True
                    )
                    sent_count += 1
                except Exception as e2:
                    await event.edit(f"❌ **Ошибка при отправке:** `{e2}`")
                    break
            else:
                await event.edit(f"❌ **Ошибка при отправке:** `{e}`")
                break

        # Пауза между отправкой видео в чат
        if i + 1 < count:
            await asyncio.sleep(1.5)

    if sent_count > 0:
        await event.delete()

@core.command("tiktok", description="Алиас для .tt", usage=".tiktok")
async def tiktok_alias_cmd(event: events.NewMessage.Event):
    """Алиас для команды .tt."""
    await tiktok_cmd(event)
