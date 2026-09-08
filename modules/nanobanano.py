import io
import os
import time
import random
import asyncio
import urllib.parse
import requests
from telethon import events
from google import genai
from google.genai import types
import core

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if not _gemini_client and GEMINI_API_KEY:
        try:
            _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception:
            _gemini_client = None
    return _gemini_client

def translate_and_enrich_prompt(ru_prompt: str) -> str:
    """Переводит и детально обогащает промпт с русского на английский через Gemini Flash."""
    client = get_gemini_client()
    if not client:
        return ru_prompt

    system_instruction = """You are Nano Banana 2 Image Prompt Master.
Convert the user Russian prompt into a highly detailed, stunning, high-quality visual art prompt in English for Image Generation (FLUX/Photorealistic/Art style).
Enhance details, lighting, aesthetics, atmosphere, and resolution.
Output ONLY the final English prompt without any explanations, prefixes, or quotes."""

    try:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            max_output_tokens=120,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=ru_prompt,
            config=config
        )
        text = resp.text.strip().replace('"', '').replace("'", "")
        return text if text else ru_prompt
    except Exception:
        return ru_prompt

def generate_image_bytes(en_prompt: str, timeout: float = 25.0) -> bytes:
    """Генерирует изображение высокого качества через Nano Banana 2 / FLUX."""
    encoded_prompt = urllib.parse.quote(en_prompt)
    seed = random.randint(100000, 99999999)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&model=flux&nologo=true"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    if r.status_code == 200 and len(r.content) > 3000:
        return r.content
    raise RuntimeError(f"HTTP {r.status_code} при генерации")

@core.command("nb", description="Nano Banana 2: генерация изображений через AI", usage=".nb <описание>")
async def nanobanano_cmd(event: events.NewMessage.Event):
    """Генерирует уникальное изображение по текстовому описанию."""
    raw = event.raw_text or getattr(event, "text", "") or ""
    args = raw.split(maxsplit=1)
    if len(args) < 2:
        await event.edit("💡 **Использование:** `.nb <описание картинки>`\n*(например: `.nb киберпанк кот в неоновом городе`)*")
        await asyncio.sleep(3)
        await event.delete()
        return

    query = args[1].strip()
    await event.edit("🍌 **Nano Banana 2 генерирует...**")
    
    t0 = time.time()
    reply_to = getattr(event, "reply_to_msg_id", None)

    try:
        # 1. Перевод и обогащение промпта на английский
        en_prompt = await asyncio.to_thread(translate_and_enrich_prompt, query)
        
        # 2. Генерация изображения
        img_bytes = await asyncio.to_thread(generate_image_bytes, en_prompt)
        
        elapsed = time.time() - t0
        caption = "🍌 **Nano Banana 2**"

        file_obj = io.BytesIO(img_bytes)
        file_obj.name = "nanobanano.jpg"

        await event.client.send_file(
            event.chat_id,
            file=file_obj,
            caption=caption,
            reply_to=reply_to
        )
        try:
            await event.delete()
        except Exception:
            pass

    except Exception as e:
        await event.edit(f"❌ **Ошибка Nano Banana 2:** `{e}`")

@core.command("nanobanano", description="Nano Banana 2: генерация изображений через AI", usage=".nanobanano <описание>")
async def nanobanano_alias_cmd(event: events.NewMessage.Event):
    """Алиас для .nb"""
    await nanobanano_cmd(event)
