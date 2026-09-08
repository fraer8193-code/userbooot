"""
Fake Geolocation Module for Femboy Userbot.

Автоматическая подмена и ручная отправка геолокаций в Telegram:
- Перехват исходящей реальной статической геопозиции и авто-подмена
- Перехват и симуляция Live Location (прямого эфира) с реалистичным перемещением (drift)
- Ручные команды для отправки фейк-локации, старта/остановки прямого эфира, смены стран и координат
"""

import os
import json
import math
import random
import asyncio
import logging
from pathlib import Path
from telethon import events, errors
from telethon.tl import types, functions
import core
from config import CMD_PREFIX

logger = logging.getLogger("Userbot.Geo")

# Файл настроек модуля геопозиции
SETTINGS_FILE = Path("geo_settings.json")

DEFAULT_LOCATIONS = {
    "pl": {"name": "Польша, Вроцлав (ul. Grabiszyńska 102)", "lat": 51.101235, "long": 17.009412},
    "pl_krakow": {"name": "Польша, Краков (ul. Kazimierza Wielkiego 45)", "lat": 50.071832, "long": 19.924715},
    "pl_poznan": {"name": "Польша, Познань (ul. Głogowska 82)", "lat": 52.391204, "long": 16.897451},
    "de": {"name": "Германия, Берлин (Brandenburg Gate)", "lat": 52.516275, "long": 13.377704},
    "de_munich": {"name": "Германия, Мюнхен (Marienplatz)", "lat": 48.137154, "long": 11.576124},
    "de_frankfurt": {"name": "Германия, Франкфурт (Römerberg)", "lat": 50.110924, "long": 8.682127},
    "fr": {"name": "Франция, Париж (Eiffel Tower)", "lat": 48.858370, "long": 2.294481},
    "uk": {"name": "Великобритания, Лондон (Big Ben)", "lat": 51.500729, "long": -0.124625},
    "us": {"name": "США, Нью-Йорк (Times Square)", "lat": 40.758896, "long": -73.985130},
    "ae": {"name": "ОАЭ, Дубай (Burj Khalifa)", "lat": 25.197197, "long": 55.274376},
    "th": {"name": "Таиланд, Бангкок (Grand Palace)", "lat": 13.750000, "long": 100.491667}
}

DEFAULT_SETTINGS = {
    "enabled": True,
    "current_country": "pl",
    "custom_lat": 51.101235,
    "custom_long": 17.009412,
    "use_custom": False,
    "live_drift_enabled": True,
    "drift_speed_meters": 15
}

# Хранилище запущенных фоновых симуляций Live Location: { (chat_id, msg_id): Task }
active_live_tasks = {}

# Список ID сообщений, отправленных/отредактированных ботом, чтобы исключить зацикливание
bot_handled_msg_ids = set()

# Ссылка на активный TelegramClient
_client = None
_handlers_registered = False


def load_settings():
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in DEFAULT_SETTINGS.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Failed to save geo settings: {e}")


def get_current_location():
    settings = load_settings()
    if settings.get("use_custom"):
        return {
            "name": f"Пользовательские ({settings['custom_lat']:.5f}, {settings['custom_long']:.5f})",
            "lat": float(settings["custom_lat"]),
            "long": float(settings["custom_long"])
        }
    code = settings.get("current_country", "pl")
    return DEFAULT_LOCATIONS.get(code, DEFAULT_LOCATIONS.get("pl", {"name": "Польша", "lat": 51.101235, "long": 17.009412}))


def calculate_offset(lat, lon, distance_meters, bearing_degrees):
    """Вычисляет новые координаты со смещением на заданное расстояние и угол."""
    R = 6378137.0  # Радиус Земли в метрах
    bearing_rad = math.radians(bearing_degrees)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)

    new_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(distance_meters / R) +
        math.cos(lat_rad) * math.sin(distance_meters / R) * math.cos(bearing_rad)
    )
    new_lon_rad = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(distance_meters / R) * math.cos(lat_rad),
        math.cos(distance_meters / R) - math.sin(lat_rad) * math.sin(new_lat_rad)
    )
    return math.degrees(new_lat_rad), math.degrees(new_lon_rad)


def is_near_target(lat1, lon1, lat2, lon2, max_meters=3000):
    """Проверяет, находятся ли координаты близко к целевым."""
    R = 6378137.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    dist = R * c
    return dist <= max_meters


async def simulate_live_movement(client, chat_id, message_id, base_lat, base_long, total_seconds):
    """
    Фоновая симуляция ходьбы/движения по городу во время активного прямого эфира (Live Location).
    """
    task_key = (chat_id, message_id)
    cur_lat, cur_lon = base_lat, base_long
    heading = random.randint(0, 360)
    step_seconds = 10
    elapsed = 0

    logger.info(f"Запущена симуляция Live Location для чата {chat_id}, msg {message_id} на {total_seconds} сек.")

    try:
        while elapsed < total_seconds:
            await asyncio.sleep(step_seconds)
            elapsed += step_seconds

            settings = load_settings()
            if not settings.get("enabled", True) or not settings.get("live_drift_enabled", True):
                continue

            # Случайное изменение направления на +/- 25 градусов (правдоподобный маршрут)
            heading = (heading + random.randint(-25, 25)) % 360
            # Скорость пешехода: ~8-16 метров за 10 сек
            step_distance = random.uniform(8.0, 16.0)
            cur_lat, cur_lon = calculate_offset(cur_lat, cur_lon, step_distance, heading)

            remaining_period = max(60, total_seconds - elapsed)

            bot_handled_msg_ids.add(message_id)
            try:
                await client(functions.messages.EditMessageRequest(
                    peer=chat_id,
                    id=message_id,
                    media=types.InputMediaGeoLive(
                        geo_point=types.InputGeoPoint(lat=cur_lat, long=cur_lon),
                        period=remaining_period,
                        heading=heading,
                        proximity_notification_radius=None
                    )
                ))
                logger.debug(f"Live Location обновлен: {cur_lat:.5f}, {cur_lon:.5f} (курс {heading}°)")
            except Exception as e:
                logger.warning(f"Не удалось обновить Live Location для {message_id}: {e}")
                break
    except asyncio.CancelledError:
        logger.info(f"Симуляция Live Location отменена для msg {message_id}")
    finally:
        active_live_tasks.pop(task_key, None)


# --- ПЕРЕХВАТ ИСХОДЯЩИХ ГЕОЛОКАЦИЙ ---

async def handle_outgoing_geo(event: events.NewMessage.Event):
    """Перехват реальной геопозиции при отправке из Telegram клиента."""
    if not event.media:
        return

    msg_id = event.id
    if msg_id in bot_handled_msg_ids:
        return

    settings = load_settings()
    if not settings.get("enabled", True):
        return

    target_loc = get_current_location()
    target_lat = target_loc["lat"]
    target_long = target_loc["long"]
    client = event.client

    # 1. ОБЫЧНАЯ СТАТИЧЕСКАЯ ГЕОПОЗИЦИЯ
    if isinstance(event.media, types.MessageMediaGeo) and not isinstance(event.media, types.MessageMediaGeoLive):
        real_geo = event.media.geo
        if isinstance(real_geo, types.GeoPoint):
            # Если геопозиция уже фейковая (в пределах 1 км), не трогаем
            if is_near_target(real_geo.lat, real_geo.long, target_lat, target_long, max_meters=1000):
                return

            logger.info(f"Перехвачена реальная статическая геопозиция ({real_geo.lat:.4f}, {real_geo.long:.4f}). Подменяем на {target_loc['name']}...")
            
            chat = await event.get_input_chat()
            reply_to = event.reply_to_msg_id

            # Удаляем оригинальное сообщение с настоящими координатами
            await event.delete()

            # Отправляем поддельные координаты
            new_msg = await client.send_file(
                chat,
                types.InputMediaGeoPoint(
                    geo_point=types.InputGeoPoint(lat=target_lat, long=target_long)
                ),
                reply_to=reply_to
            )
            bot_handled_msg_ids.add(new_msg.id)
            logger.info("Успешно подменено на выбранную локацию.")

    # 2. ПРЯМАЯ ТРАНСЛЯЦИЯ (LIVE LOCATION)
    elif isinstance(event.media, types.MessageMediaGeoLive):
        real_geo = event.media.geo
        period = getattr(event.media, 'period', 3600)
        heading = getattr(event.media, 'heading', random.randint(0, 360))

        if isinstance(real_geo, types.GeoPoint):
            if is_near_target(real_geo.lat, real_geo.long, target_lat, target_long, max_meters=2000):
                return

            logger.info(f"Перехвачена Live-трансляция реальной геопозиции! Подменяем на {target_loc['name']}...")

            # Редактируем сообщение на фейковые координаты
            bot_handled_msg_ids.add(msg_id)
            try:
                await client(functions.messages.EditMessageRequest(
                    peer=await event.get_input_chat(),
                    id=msg_id,
                    media=types.InputMediaGeoLive(
                        geo_point=types.InputGeoPoint(lat=target_lat, long=target_long),
                        period=period,
                        heading=heading
                    )
                ))
                logger.info("Координаты начала прямого эфира успешно подменены!")
            except Exception as e:
                logger.error(f"Ошибка при подмене Live Location: {e}")

            # Запускаем симуляцию живого движения в фоновом режиме
            task_key = (event.chat_id, msg_id)
            if task_key in active_live_tasks:
                active_live_tasks[task_key].cancel()

            task = asyncio.create_task(
                simulate_live_movement(client, event.chat_id, msg_id, target_lat, target_long, period)
            )
            active_live_tasks[task_key] = task


async def handle_edited_geo(event: events.MessageEdited.Event):
    """
    Перехватывает попытки Telegram клиента обновить координаты во время трансляции прямого эфира.
    """
    if not event.media or not isinstance(event.media, types.MessageMediaGeoLive):
        return

    msg_id = event.id
    if msg_id in bot_handled_msg_ids:
        return

    settings = load_settings()
    if not settings.get("enabled", True):
        return

    target_loc = get_current_location()
    target_lat = target_loc["lat"]
    target_long = target_loc["long"]
    real_geo = event.media.geo

    if isinstance(real_geo, types.GeoPoint):
        if is_near_target(real_geo.lat, real_geo.long, target_lat, target_long, max_meters=2000):
            return

        logger.info(f"Перехвачено обновление Live Location от клиента! Перезаписываем на {target_loc['name']}...")
        period = getattr(event.media, 'period', 3600)
        heading = getattr(event.media, 'heading', random.randint(0, 360))

        bot_handled_msg_ids.add(msg_id)
        try:
            await event.client(functions.messages.EditMessageRequest(
                peer=await event.get_input_chat(),
                id=msg_id,
                media=types.InputMediaGeoLive(
                    geo_point=types.InputGeoPoint(lat=target_lat, long=target_long),
                    period=period,
                    heading=heading
                )
            ))
        except Exception as e:
            logger.warning(f"Ошибка перезаписи Live Location: {e}")


# --- ЖИЗНЕННЫЙ ЦИКЛ МОДУЛЯ ---

def on_load(manager):
    global _client, _handlers_registered
    _client = manager.client
    if not _handlers_registered:
        manager.client.add_event_handler(handle_outgoing_geo, events.NewMessage(outgoing=True))
        manager.client.add_event_handler(handle_edited_geo, events.MessageEdited(outgoing=True))
        _handlers_registered = True
        logger.info("Модуль Fake Geo успешно инициализирован и зарегистрировал перехватчики.")


def on_unload(manager):
    global _client, _handlers_registered
    # Останавливаем все фоновые симуляции
    for task_key, task in list(active_live_tasks.items()):
        task.cancel()
    active_live_tasks.clear()

    if _handlers_registered and _client:
        try:
            _client.remove_event_handler(handle_outgoing_geo, events.NewMessage(outgoing=True))
            _client.remove_event_handler(handle_edited_geo, events.MessageEdited(outgoing=True))
        except Exception as e:
            logger.warning(f"Ошибка при снятии хэндлеров Fake Geo: {e}")
        _handlers_registered = False
        logger.info("Модуль Fake Geo выгружен.")


# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ---

@core.command("geo", description="Send static fake geolocation", usage=f"{CMD_PREFIX}geo")
async def cmd_send_geo(event: events.NewMessage.Event):
    """Отправляет статическую точку с поддельной геолокацией."""
    target_loc = get_current_location()
    chat = await event.get_input_chat()
    reply_to = event.reply_to_msg_id

    await event.delete()
    msg = await event.client.send_file(
        chat,
        types.InputMediaGeoPoint(
            geo_point=types.InputGeoPoint(lat=target_loc["lat"], long=target_loc["long"])
        ),
        reply_to=reply_to
    )
    bot_handled_msg_ids.add(msg.id)


@core.command("geolive", description="Start live fake geolocation with walking movement", usage=f"{CMD_PREFIX}geolive [минуты]")
async def cmd_send_live(event: events.NewMessage.Event):
    """Запускает прямой эфир геопозиции с симуляцией реалистичного перемещения."""
    args = event.raw_text.split()
    mins = 60
    if len(args) > 1 and args[1].isdigit():
        mins = int(args[1])

    if mins > 9999:
        total_seconds = 0x7FFFFFFF  # Бесконечный эфир
    else:
        total_seconds = mins * 60

    target_loc = get_current_location()
    chat = await event.get_input_chat()
    reply_to = event.reply_to_msg_id

    await event.delete()
    msg = await event.client.send_file(
        chat,
        types.InputMediaGeoLive(
            geo_point=types.InputGeoPoint(lat=target_loc["lat"], long=target_loc["long"]),
            period=total_seconds,
            heading=random.randint(0, 360)
        ),
        reply_to=reply_to
    )
    bot_handled_msg_ids.add(msg.id)

    task_key = (event.chat_id, msg.id)
    task = asyncio.create_task(
        simulate_live_movement(event.client, event.chat_id, msg.id, target_loc["lat"], target_loc["long"], total_seconds)
    )
    active_live_tasks[task_key] = task


@core.command("geolivestat", description="Start static live fake geolocation (stay at place)", usage=f"{CMD_PREFIX}geolivestat [минуты]")
async def cmd_send_live_static(event: events.NewMessage.Event):
    """Запускает прямой эфир статично (без перемещения, человек на месте)."""
    args = event.raw_text.split()
    mins = 60
    if len(args) > 1 and args[1].isdigit():
        mins = int(args[1])

    if mins > 9999:
        total_seconds = 0x7FFFFFFF
    else:
        total_seconds = mins * 60

    target_loc = get_current_location()
    chat = await event.get_input_chat()
    reply_to = event.reply_to_msg_id

    await event.delete()
    msg = await event.client.send_file(
        chat,
        types.InputMediaGeoLive(
            geo_point=types.InputGeoPoint(lat=target_loc["lat"], long=target_loc["long"]),
            period=total_seconds,
            heading=0
        ),
        reply_to=reply_to
    )
    bot_handled_msg_ids.add(msg.id)


@core.command("geostop", description="Stop active fake live geolocation streams", usage=f"{CMD_PREFIX}geostop")
async def cmd_stop_live(event: events.NewMessage.Event):
    """Останавливает трансляцию Live Location в текущем чате."""
    chat_id = event.chat_id
    stopped_count = 0
    reply_msg = await event.get_reply_message()

    target_msg_ids = []
    if reply_msg and isinstance(reply_msg.media, types.MessageMediaGeoLive):
        target_msg_ids.append(reply_msg.id)
    else:
        for (c_id, m_id) in list(active_live_tasks.keys()):
            if c_id == chat_id:
                target_msg_ids.append(m_id)

    for m_id in target_msg_ids:
        task_key = (chat_id, m_id)
        if task_key in active_live_tasks:
            active_live_tasks[task_key].cancel()
            active_live_tasks.pop(task_key, None)

        try:
            bot_handled_msg_ids.add(m_id)
            await event.client(functions.messages.EditMessageRequest(
                peer=await event.get_input_chat(),
                id=m_id,
                media=types.InputMediaGeoLive(
                    stopped=True,
                    geo_point=types.InputGeoPointEmpty()
                )
            ))
            stopped_count += 1
        except Exception as e:
            logger.warning(f"Ошибка при остановке Live Location для msg {m_id}: {e}")

    await event.delete()


@core.command("country", description="Switch fake country/city preset", usage=f"{CMD_PREFIX}country [код]")
async def cmd_set_country(event: events.NewMessage.Event):
    """Переключает страну/город из списка пресетов."""
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        list_str = "\n".join([f"• `{c}`: {d['name']}" for c, d in DEFAULT_LOCATIONS.items()])
        await event.edit(f"📍 **Использование:** `{CMD_PREFIX}country <код>`\n\n🌍 **Доступные пресеты:**\n{list_str}")
        return

    code = args[1].strip().lower()
    if code in DEFAULT_LOCATIONS:
        settings = load_settings()
        settings["current_country"] = code
        settings["use_custom"] = False
        save_settings(settings)
        loc = DEFAULT_LOCATIONS[code]
        await event.edit(f"✅ Локация переключена на: **{loc['name']}**\nКоординаты: `{loc['lat']}, {loc['long']}`")
    else:
        await event.edit(f"❌ Код `{code}` не найден. Введите `{CMD_PREFIX}country` для списка.")


@core.command("setgeo", description="Set custom coordinates", usage=f"{CMD_PREFIX}setgeo <lat> <lon>")
async def cmd_set_custom_geo(event: events.NewMessage.Event):
    """Устанавливает произвольные широту и долготу."""
    parts = event.raw_text.split()
    if len(parts) < 3:
        await event.edit(f"📍 **Использование:** `{CMD_PREFIX}setgeo <широта> <долгота>`\nПример: `{CMD_PREFIX}setgeo 52.5200 13.4050`")
        return

    try:
        lat = float(parts[1])
        lon = float(parts[2])
        settings = load_settings()
        settings["use_custom"] = True
        settings["custom_lat"] = lat
        settings["custom_long"] = lon
        save_settings(settings)
        await event.edit(f"✅ Установлены пользовательские координаты:\nШирота: `{lat}`\nДолгота: `{lon}`")
    except Exception as e:
        await event.edit(f"❌ Ошибка парсинга координат: {e}")


@core.command("geostatus", description="Show fake geolocation status and settings", usage=f"{CMD_PREFIX}geostatus")
async def cmd_status(event: events.NewMessage.Event):
    """Показывает текущие настройки и активные трансляции."""
    settings = load_settings()
    loc = get_current_location()
    status_str = "🟢 Включена" if settings.get("enabled", True) else "🔴 Выключена"
    drift_str = "🟢 Включена" if settings.get("live_drift_enabled", True) else "🔴 Выключена"

    text = (
        f"📊 **Статус Fake Geo Module:**\n\n"
        f"• Авто-подмена: {status_str}\n"
        f"• Симуляция движения (Live Drift): {drift_str}\n"
        f"• Текущая локация: **{loc['name']}**\n"
        f"• Координаты: `{loc['lat']:.6f}, {loc['long']:.6f}`\n"
        f"• Активных трансляций: `{len(active_live_tasks)}`"
    )
    await event.edit(text)


@core.command("geotoggle", description="Toggle auto geo-spoofing on/off", usage=f"{CMD_PREFIX}geotoggle")
async def cmd_toggle(event: events.NewMessage.Event):
    """Включает или выключает автоматическую подмену отправляемых геопозиций."""
    settings = load_settings()
    new_state = not settings.get("enabled", True)
    settings["enabled"] = new_state
    save_settings(settings)
    status_str = "🟢 **ВКЛЮЧЕНА**" if new_state else "🔴 **ВЫКЛЮЧЕНА**"
    await event.edit(f"Авто-подмена геопозиции: {status_str}")


@core.command("geodrift", description="Toggle live movement simulation", usage=f"{CMD_PREFIX}geodrift")
async def cmd_toggle_drift(event: events.NewMessage.Event):
    """Включает или выключает перемещение при прямых эфирах."""
    settings = load_settings()
    new_state = not settings.get("live_drift_enabled", True)
    settings["live_drift_enabled"] = new_state
    save_settings(settings)
    status_str = "🟢 **ВКЛЮЧЕНА**" if new_state else "🔴 **ВЫКЛЮЧЕНА**"
    await event.edit(f"Симуляция ходьбы при Live-трансляциях: {status_str}")


@core.command("geohelp", description="Show detailed Fake Geo help", usage=f"{CMD_PREFIX}geohelp")
async def cmd_geo_help(event: events.NewMessage.Event):
    """Подробная справка по работе с модулем Fake Geo."""
    text = (
        "📍 **Fake Geo Module Guide**\n\n"
        "**Команды:**\n"
        f"• `{CMD_PREFIX}geo` — Отправить статичную фейковую геопозицию\n"
        f"• `{CMD_PREFIX}geolive [минуты]` — Прямой эфир с симуляцией ходьбы (> 9999 = бесконечно)\n"
        f"• `{CMD_PREFIX}geolivestat [минуты]` — Прямой эфир статично (без движения)\n"
        f"• `{CMD_PREFIX}geostop` — Остановить активный прямой эфир\n"
        f"• `{CMD_PREFIX}country [код]` — Сменить страну/город\n"
        f"• `{CMD_PREFIX}setgeo <lat> <lon>` — Установить свои координаты вручную\n"
        f"• `{CMD_PREFIX}geostatus` — Текущий статус и выбранная локация\n"
        f"• `{CMD_PREFIX}geotoggle` — Вкл/Выкл авто-подмену реальной геолокации\n"
        f"• `{CMD_PREFIX}geodrift` — Вкл/Выкл симуляцию ходьбы для будущих эфиров\n\n"
        "🌍 **Доступные коды стран (`.country <код>`):**\n"
    )
    for code, data in DEFAULT_LOCATIONS.items():
        text += f"• `{code}`: {data['name']}\n"

    await event.edit(text)
