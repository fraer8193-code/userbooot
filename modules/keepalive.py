import os
import asyncio
import logging
import aiohttp
from aiohttp import web
from telethon import events
from telethon.tl.functions.help import GetNearestDcRequest
import core
from core.utils import get_uptime
from config import CMD_PREFIX

logger = logging.getLogger("Userbot.KeepAlive")

# Интервал дерганья бота (5 минут = 300 секунд)
PING_INTERVAL_SECONDS = 300

# Порт веб-сервера (по умолчанию 8080 или из окружения хостинга PORT)
PORT = int(os.getenv("PORT", "8080"))
SELF_PING_URL = os.getenv("KEEP_ALIVE_URL", f"http://127.0.0.1:{PORT}")

_task: asyncio.Task = None
_server_task: asyncio.Task = None
_web_runner = None
_heartbeat_count: int = 0

async def handle_root(request):
    """Ответ на HTTP-запрос для проверки хостингом (health check)."""
    return web.Response(
        text=f"✨ Femboy Userbot is running 24/7!\nUptime: {get_uptime()}\nHeartbeats: {_heartbeat_count}\nStatus: OK",
        content_type="text/plain"
    )

async def handle_health(request):
    """JSON ответ для мониторинга (UptimeRobot, Cron-Job и т.д.)."""
    return web.json_response({
        "status": "ok",
        "service": "userbot",
        "uptime": get_uptime(),
        "heartbeats": _heartbeat_count
    })

async def start_web_server():
    """Запускает легковесный веб-сервер, чтобы хостинг не закрывал контейнер."""
    global _web_runner
    try:
        app = web.Application()
        app.router.add_get("/", handle_root)
        app.router.add_get("/ping", handle_health)
        app.router.add_get("/health", handle_health)
        
        _web_runner = web.AppRunner(app)
        await _web_runner.setup()
        site = web.TCPSite(_web_runner, "0.0.0.0", PORT)
        await site.start()
        logger.info(f"KeepAlive web server listening on port {PORT}")
    except Exception as e:
        logger.warning(f"Could not start KeepAlive web server on port {PORT}: {e}")

async def keepalive_worker(client):
    """Каждые 5 минут дергает соединение с Telegram и пингует веб-сервер."""
    global _heartbeat_count
    logger.info(f"KeepAlive worker started (interval: {PING_INTERVAL_SECONDS}s / 5m).")

    # Ждем 10 секунд после старта перед первым циклом
    await asyncio.sleep(10)

    while True:
        try:
            _heartbeat_count += 1
            
            # 1. Дергаем Telegram API, чтобы сокет оставался активным
            if client and client.is_connected():
                try:
                    await client(GetNearestDcRequest())
                except Exception:
                    try:
                        await client.get_me()
                    except Exception:
                        pass

            # 2. Дергаем инлайн-бота (если подключен)
            if core.bot_client and core.bot_client.is_connected():
                try:
                    await core.bot_client.get_me()
                except Exception:
                    pass

            # 3. Самопинг веб-сервера через HTTP (чтобы хостинг видел веб-трафик)
            try:
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    url_to_ping = os.getenv("KEEP_ALIVE_URL") or f"http://127.0.0.1:{PORT}/ping"
                    async with session.get(url_to_ping) as resp:
                        await resp.text()
            except Exception:
                pass

            logger.info(f"💓 [KeepAlive] Heartbeat #{_heartbeat_count} sent. Bot alive! Uptime: {get_uptime()}")

            # Спим ровно 5 минут
            await asyncio.sleep(PING_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Error in keepalive worker: {e}")
            await asyncio.sleep(30)

def on_load(mgr):
    global _task, _server_task
    if _task and not _task.done():
        _task.cancel()
    if _server_task and not _server_task.done():
        _server_task.cancel()

    _server_task = asyncio.create_task(start_web_server())
    _task = asyncio.create_task(keepalive_worker(mgr.client))

def on_unload(mgr):
    global _task, _server_task, _web_runner
    if _task and not _task.done():
        _task.cancel()
        _task = None
    if _server_task and not _server_task.done():
        _server_task.cancel()
        _server_task = None
    if _web_runner:
        asyncio.create_task(_web_runner.cleanup())
        _web_runner = None

@core.command("keepalive", description="KeepAlive 24/7 status & heartbeat", usage=f"{CMD_PREFIX}keepalive [ping]")
async def keepalive_cmd(event: events.NewMessage.Event):
    """Показывает статус системы предотвращения отключения бота."""
    args = event.raw_text.split(maxsplit=1)
    sub = args[1].lower() if len(args) > 1 else ""

    if sub in ("ping", "now"):
        await event.edit("💓 **Отправка внеочередного пинга...**")
        client = event.client
        try:
            await client(GetNearestDcRequest())
            status_text = "🟢 Успешно"
        except Exception as e:
            status_text = f"🟡 Ошибка: {e}"

        await event.edit(
            f"💓 **KeepAlive Heartbeat отправлен!**\n"
            f"• Статус соединения: {status_text}\n"
            f"• Аптайм: `{get_uptime()}`\n"
            f"• Всего импульсов: `{_heartbeat_count}`"
        )
        return

    text = (
        f"💓 **KeepAlive 24/7 (Анти-засыпание хостинга)**\n\n"
        f"• **Интервал дёрганья:** `каждые 5 минут`\n"
        f"• **Отправлено импульсов:** `{_heartbeat_count}`\n"
        f"• **Аптайм бота:** `{get_uptime()}`\n"
        f"• **Веб-порт:** `{PORT}` (для Render, Railway, Bothost)\n"
        f"• **HTTP эндпоинты:** `/` и `/ping`\n\n"
        f"💡 Команда `{CMD_PREFIX}keepalive ping` — отправить пинг прямо сейчас."
    )
    await event.edit(text)
