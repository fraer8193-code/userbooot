import io
import os
import textwrap
import asyncio
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from telethon import events
import core

BASE_DIR = Path(__file__).parent.parent.resolve()
FRAME_PATH = BASE_DIR / "i.webp"

def get_system_font(size: int = 24, bold: bool = False):
    """Загружает стандартный системный шрифт Segoe UI или Arial."""
    font_candidates = []
    if bold:
        font_candidates = [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/tahomabd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ]
    else:
        font_candidates = [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/tahoma.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ]

    for p in font_candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass

    try:
        return ImageFont.load_default()
    except Exception:
        return None

def render_telegram_bubble(
    message_text: str,
    time_str: str,
    media_bytes: bytes = None
) -> bytes:
    """
    Создает чистый Telegram-бабл сообщения и помещает его в центр золотой рамки i.webp.
    """
    if not FRAME_PATH.exists():
        raise FileNotFoundError(f"Файл рамки не найден: {FRAME_PATH}")

    # Загрузка и 3x масштабирование рамки для высокой четкости (1269x960)
    frame_orig = Image.open(FRAME_PATH).convert("RGBA")
    scale = 3
    frame = frame_orig.resize((frame_orig.width * scale, frame_orig.height * scale), Image.Resampling.LANCZOS)
    
    # Координаты внутреннего окна рамки (831 x 504)
    ix1 = int(73 * scale)
    iy1 = int(69 * scale)
    ix2 = int(350 * scale)
    iy2 = int(237 * scale)
    iw = ix2 - ix1
    ih = iy2 - iy1

    # Цветовая гамма Telegram Desktop Dark Theme
    bg_color = (14, 22, 33, 255)       # Фон чата (#0e1621)
    bubble_color = (24, 37, 51, 255)   # Бабл сообщения (#182533)
    text_color = (255, 255, 255, 255)  # Текст (#ffffff)
    time_color = (110, 130, 150, 255)  # Время (#6e8296)

    card = Image.new("RGBA", (iw, ih), bg_color)
    draw = ImageDraw.Draw(card)

    text = (message_text or "").strip()

    # 1. Если прикреплено фото или стикер
    if media_bytes:
        try:
            media_img = Image.open(io.BytesIO(media_bytes)).convert("RGBA")
            max_pw = iw - 100
            max_ph = ih - 80

            media_img.thumbnail((max_pw, max_ph), Image.Resampling.LANCZOS)
            mw, mh = media_img.size

            bx1 = (iw - mw) // 2
            by1 = (ih - mh) // 2

            # Закругленные углы для фото
            pmask = Image.new("L", (mw, mh), 0)
            ImageDraw.Draw(pmask).rounded_rectangle([0, 0, mw, mh], radius=20, fill=255)
            card.paste(media_img, (bx1, by1), pmask)

            # Плашка со временем в правом нижнем углу фото
            font_time = get_system_font(size=18)
            time_tag = time_str
            t_bb = draw.textbbox((0, 0), time_tag, font=font_time)
            tw = t_bb[2] - t_bb[0]
            th = t_bb[3] - t_bb[1]

            pill_pad_x = 12
            pill_pad_y = 6
            pill_w = tw + pill_pad_x * 2
            pill_h = th + pill_pad_y * 2
            pill_x2 = bx1 + mw - 12
            pill_y2 = by1 + mh - 12
            pill_x1 = pill_x2 - pill_w
            pill_y1 = pill_y2 - pill_h

            draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=10, fill=(0, 0, 0, 140))
            draw.text((pill_x1 + pill_pad_x, pill_y1 + pill_pad_y - t_bb[1]), time_tag, font=font_time, fill=(255, 255, 255, 240))

        except Exception:
            media_bytes = None

    # 2. Текстовое сообщение в Telegram-бабле
    if not media_bytes:
        if not text:
            text = "*(Пустое сообщение)*"

        # Короткий текст (одна строка) -> крупный текст + время рядом на одной строке
        if "\n" not in text and len(text) < 35:
            # Крупный шрифт
            f_size = 52 if len(text) < 15 else 44
            font_text = get_system_font(size=f_size)
            font_time = get_system_font(size=int(f_size * 0.52))

            t_bbox = draw.textbbox((0, 0), text, font=font_text)
            tw = t_bbox[2] - t_bbox[0]
            th = t_bbox[3] - t_bbox[1]

            time_display = time_str
            time_bbox = draw.textbbox((0, 0), time_display, font=font_time)
            timew = time_bbox[2] - time_bbox[0]
            timeh = time_bbox[3] - time_bbox[1]

            pad_x = 36
            pad_y = 26
            gap = 26

            bw = tw + gap + timew + pad_x * 2
            bh = max(th, timeh) + pad_y * 2

            if bw > iw - 60:
                bw = iw - 60

            bx1 = (iw - bw) // 2
            by1 = (ih - bh) // 2
            bx2 = bx1 + bw
            by2 = by1 + bh

            draw.rounded_rectangle([bx1, by1, bx2, by2], radius=24, fill=bubble_color)

            # Текст сообщения
            tx = bx1 + pad_x
            ty = by1 + (bh - th) // 2 - t_bbox[1]
            draw.text((tx, ty), text, font=font_text, fill=text_color)

            # Время рядом с текстом
            timex = tx + tw + gap
            timey = by1 + bh - pad_y - timeh - time_bbox[1] + 2
            draw.text((timex, timey), time_display, font=font_time, fill=time_color)

        else:
            # Многострочное сообщение
            if len(text) < 90:
                f_size = 38
                wrap_chars = 26
                lh = 50
            elif len(text) < 200:
                f_size = 30
                wrap_chars = 36
                lh = 40
            else:
                f_size = 24
                wrap_chars = 46
                lh = 32

            font_text = get_system_font(size=f_size)
            font_time = get_system_font(size=int(f_size * 0.58))

            lines = []
            for p in text.split("\n"):
                w = textwrap.wrap(p, width=wrap_chars)
                if not w:
                    lines.append("")
                else:
                    lines.extend(w)

            max_lines = max((ih - 100) // lh, 2)
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines[-1] = lines[-1][:wrap_chars - 3] + "..."

            pad_x = 32
            pad_y = 26

            max_lw = 0
            for l in lines:
                bb = draw.textbbox((0, 0), l, font=font_text)
                lw = bb[2] - bb[0]
                if lw > max_lw:
                    max_lw = lw

            time_display = time_str
            time_bbox = draw.textbbox((0, 0), time_display, font=font_time)
            timew = time_bbox[2] - time_bbox[0]
            timeh = time_bbox[3] - time_bbox[1]

            bw = max(max_lw + pad_x * 2, timew + pad_x * 2 + 50)
            bw = min(max(bw, 280), iw - 60)
            bh = len(lines) * lh + timeh + pad_y * 2 + 10
            bh = min(bh, ih - 50)

            bx1 = (iw - bw) // 2
            by1 = (ih - bh) // 2
            bx2 = bx1 + bw
            by2 = by1 + bh

            draw.rounded_rectangle([bx1, by1, bx2, by2], radius=24, fill=bubble_color)

            ty = by1 + pad_y
            for l in lines:
                draw.text((bx1 + pad_x, ty), l, font=font_text, fill=text_color)
                ty += lh

            # Время в правом нижнем углу бабла
            draw.text((bx2 - pad_x, by2 - pad_y + 4), time_display, font=font_time, fill=time_color, anchor="rb")

    # Вставка сообщения в золотую рамку
    frame.paste(card, (ix1, iy1))

    out_buf = io.BytesIO()
    frame.convert("RGB").save(out_buf, format="JPEG", quality=95)
    return out_buf.getvalue()

@core.command("ramka", description="Поместить бабл сообщения в золотую рамку", usage=".ramka [в ответ на сообщение или текст]")
async def ramka_cmd(event: events.NewMessage.Event):
    """
    Создает чистый скриншот бабла сообщения Telegram и помещает его в рамку i.webp.
    """
    raw_text = event.raw_text or getattr(event, "text", "") or ""
    args = raw_text.split(maxsplit=1)
    extra_text = args[1].strip() if len(args) > 1 else ""

    reply = None
    try:
        reply = await event.get_reply_message()
    except Exception:
        reply = None

    if not reply and not extra_text:
        await event.edit("💡 **Использование:** Ответьте `.ramka` на сообщение или напишите `.ramka <текст>`")
        await asyncio.sleep(3)
        await event.delete()
        return

    await event.edit("🖼 **Создаю рамку...**")

    message_text = ""
    time_str = datetime.now().strftime("%H:%M")
    media_bytes = None

    if reply:
        message_text = (getattr(reply, "raw_text", "") or getattr(reply, "text", "") or "").strip()
        if extra_text:
            message_text = f"{message_text}\n\n{extra_text}" if message_text else extra_text

        if getattr(reply, "date", None):
            try:
                time_str = reply.date.strftime("%H:%M")
            except Exception:
                pass

        if getattr(reply, "photo", None) or getattr(reply, "sticker", None) or getattr(reply, "media", None):
            try:
                media_bytes = await event.client.download_media(reply, file=bytes)
            except Exception:
                media_bytes = None
    else:
        message_text = extra_text

    try:
        img_bytes = await asyncio.to_thread(
            render_telegram_bubble,
            message_text=message_text,
            time_str=time_str,
            media_bytes=media_bytes
        )

        reply_to_id = reply.id if reply else getattr(event, "reply_to_msg_id", None)

        file_obj = io.BytesIO(img_bytes)
        file_obj.name = "ramka.jpg"

        await event.client.send_file(
            event.chat_id,
            file=file_obj,
            reply_to=reply_to_id
        )
        try:
            await event.delete()
        except Exception:
            pass

    except Exception as e:
        await event.edit(f"❌ **Ошибка при создании рамки:** `{e}`")

@core.command("frame", description="Поместить бабл сообщения в золотую рамку", usage=".frame [в ответ на сообщение]")
async def frame_alias_cmd(event: events.NewMessage.Event):
    """Алиас для .ramka"""
    await ramka_cmd(event)
