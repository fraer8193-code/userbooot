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

def get_gemini_keys() -> list[str]:
    keys = []
    for var_name in ("GEMINI_API_KEY", "GEMINI_API_KEYS"):
        val = os.getenv(var_name, "").strip()
        if val:
            for part in val.split(","):
                k = part.strip().strip('"').strip("'").strip()
                if k and k not in keys:
                    keys.append(k)
    try:
        from config import GEMINI_API_KEYS as CFG_KEYS
        for k in CFG_KEYS:
            if k and k not in keys:
                keys.append(k)
    except Exception:
        pass
    return keys

_nb_clients = {}

def get_gemini_client(api_key: str | None = None):
    global _nb_clients
    if not api_key:
        keys = get_gemini_keys()
        if not keys:
            return None
        api_key = keys[0]
    if api_key in _nb_clients:
        return _nb_clients[api_key]
    try:
        client = genai.Client(api_key=api_key)
        _nb_clients[api_key] = client
        return client
    except Exception:
        return None

def translate_and_enrich_prompt(ru_prompt: str) -> str:
    """Переводит и детально обогащает промпт с русского на английский через Gemini Flash с пулом ключей."""
    keys = get_gemini_keys()
    if not keys:
        return ru_prompt

    system_instruction = """You are Nano Banana 2 Image Prompt Master.
Convert the user Russian prompt into a highly detailed, stunning, high-quality visual art prompt in English for Image Generation (FLUX/Photorealistic/Art style).
Enhance details, lighting, aesthetics, atmosphere, and resolution.
Output ONLY the final English prompt without any explanations, prefixes, or quotes."""

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
        max_output_tokens=120,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )

    for k in keys:
        client = get_gemini_client(api_key=k)
        if not client:
            continue
        for m in ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-flash-latest"]:
            try:
                resp = client.models.generate_content(model=m, contents=ru_prompt, config=config)
                if resp and resp.text and resp.text.strip():
                    text = resp.text.strip().replace('"', '').replace("'", "")
                    return text if text else ru_prompt
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "quota" in str(e).lower():
                    break
                continue
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
