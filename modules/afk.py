"""
AFK & AI Assistant Module for Femboy Userbot.

Режимы работы:
1. .afk [причина]   — Скрытый клон (100% маскировка под твой стиль на основе result.json, без упоминаний ИИ).
2. .aiafk [причина] — Открытый ИИ-ассистент (общается с собеседником и постоянно напоминает, что ты отошел и ответишь позже).
3. .ainoo <user>    — Черный список для ИИ: сообщает человеку, что владелец специально просил ему не отвечать, и ИИ прекращает диалог.
4. .unainoo <user>  — Удалить из списка .ainoo.
5. .ainoolist       — Показать список .ainoo.
6. .unafk / .back   — Выключить AFK режим.
"""

import os
import re
import json
import time
import random
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from telethon import events
from telethon.tl import types
import requests

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

import core
from config import CMD_PREFIX

logger = logging.getLogger("Userbot.AFK")

DATASET_FILE = Path("result.json")
PROCESSED_DATASET = Path("afk_ai_dataset.json")
WEIGHTS_FILE = Path("afk_model_weights.json")
STATE_FILE = Path("afk_state.json")

# Ключи и настройки AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GOROUTER_BASE_URL = os.getenv("GOROUTER_BASE_URL", "https://gorouter.app/v1")
gorouter_keys_env = os.getenv("GOROUTER_KEYS", "")
GOROUTER_KEYS = [k.strip() for k in gorouter_keys_env.split(",") if k.strip()] if gorouter_keys_env else []

# Состояние AFK
afk_state = {
    "is_afk": False,
    "reason": "Отошел",
    "since": 0,
    "mode": "secret",       # "secret" (клон), "aiafk" (ИИ-ассистент с напоминанием), "notify"
    "group_replies": True,  # отвечать на реплаи/теги в группах
    "auto_unafk": True,     # выключать при первой отправке своего сообщения
    "total_replies": 0,
    "replied_users": {},    # user_id -> count
    "ainoo_users": {}       # user_id -> {"username": ..., "name": ..., "notified": bool}
}

chat_histories = {}
last_chat_reply_time = {}
ainoo_notified_users = set()
_me_id = None
_dataset_cache = None

# =====================================================================
# 1. ОБРАБОТКА И ОБУЧЕНИЕ НА ДАТАСЕТЕ result.json
# =====================================================================

def extract_dataset() -> dict:
    """Парсит result.json и извлекает профиль речи, словарь и пары диалогов."""
    global _dataset_cache
    if not DATASET_FILE.exists():
        return {
            "name": "Rew",
            "user_id": "7648062326",
            "username": "@nonosyisss",
            "messages": [],
            "dialogue_pairs": []
        }

    try:
        with open(DATASET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        p_info = data.get("personal_information", {})
        my_user_id = str(p_info.get("user_id", "7648062326"))
        my_name = p_info.get("first_name", "Rew | XRay")
        my_username = p_info.get("username", "@nonosyisss")

        user_messages = []
        dialogue_pairs = []

        chats = data.get("chats", {}).get("list", [])
        for chat in chats:
            c_name = chat.get("name", "Chat")
            msgs = chat.get("messages", [])

            prev_msg = None
            for msg in msgs:
                text = msg.get("text")
                if isinstance(text, list):
                    full_t = ""
                    for part in text:
                        if isinstance(part, str):
                            full_t += part
                        elif isinstance(part, dict) and "text" in part:
                            full_t += part.get("text", "")
                    text = full_t

                if not text or not isinstance(text, str) or not text.strip():
                    prev_msg = msg
                    continue

                text = text.strip()
                actor_id = str(msg.get("from_id") or msg.get("actor_id") or "")
                is_blessed = ("7469883317" in actor_id) or ("b1ess3d" in actor_name.lower()) or ("blessed" in actor_name.lower())
                is_me = (not is_blessed) and ((my_user_id in actor_id) or ("rew" in actor_name.lower()) or ("xray" in actor_name.lower()))

                if is_me:
                    user_messages.append(text)
                    if prev_msg:
                        p_text = prev_msg.get("text")
                        if isinstance(p_text, list):
                            p_text = "".join([x if isinstance(x, str) else x.get("text", "") for x in p_text])
                        p_actor_id = str(prev_msg.get("from_id") or prev_msg.get("actor_id") or "")
                        p_actor_name = prev_msg.get("from") or prev_msg.get("actor") or ""
                        
                        p_is_me = (my_user_id in p_actor_id) or (p_actor_name == my_name)
                        if p_text and isinstance(p_text, str) and p_text.strip() and not p_is_me:
                            dialogue_pairs.append({
                                "incoming": p_text.strip(),
                                "reply": text,
                                "chat": c_name
                            })
                prev_msg = msg

        summary = {
            "name": my_name,
            "user_id": my_user_id,
            "username": my_username,
            "total_user_messages": len(user_messages),
            "total_pairs": len(dialogue_pairs),
            "sample_phrases": user_messages[-120:],
            "dialogue_pairs": dialogue_pairs[-250:]
        }

        with open(PROCESSED_DATASET, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        _dataset_cache = summary
        logger.info(f"Dataset extracted successfully: {len(user_messages)} msgs, {len(dialogue_pairs)} pairs")
        return summary
    except Exception as e:
        logger.exception(f"Error parsing dataset from {DATASET_FILE}: {e}")
        return {}

def get_dataset() -> dict:
    """Возвращает кэшированный, обученный или сохраненный датасет."""
    global _dataset_cache
    if _dataset_cache:
        return _dataset_cache

    if WEIGHTS_FILE.exists():
        try:
            with open(WEIGHTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _dataset_cache = {
                    "name": data.get("persona", {}).get("name", "Rew | XRay"),
                    "user_id": "7648062326",
                    "username": data.get("persona", {}).get("username", "@nonosyisss"),
                    "dialogue_pairs": data.get("curated_dialogue_pairs", []),
                    "sample_phrases": data.get("sample_phrases", []),
                    "sticker_triggers": data.get("sticker_triggers", []),
                    "gif_triggers": data.get("gif_triggers", []),
                    "persona": data.get("persona", {}),
                    "feedback_memory": data.get("feedback_memory", []),
                    "learned_knowledge": data.get("learned_knowledge", {}),
                    "learned_rules": data.get("learned_rules", [])
                }
                return _dataset_cache
        except Exception as e:
            logger.warning(f"Failed to load weights from {WEIGHTS_FILE}: {e}")

    if PROCESSED_DATASET.exists():
        try:
            with open(PROCESSED_DATASET, "r", encoding="utf-8") as f:
                _dataset_cache = json.load(f)
                return _dataset_cache
        except Exception:
            pass

    return extract_dataset()

def find_relevant_examples(incoming_text: str, limit: int = 5) -> list:
    """Подбирает наиболее похожие примеры ответов из реальных переписок."""
    ds = get_dataset()
    pairs = ds.get("dialogue_pairs", [])
    if not pairs:
        return []

    words = set(re.findall(r'[a-zA-Zа-яА-ЯёЁ0-9]+', incoming_text.lower()))
    if not words:
        return random.sample(pairs, min(limit, len(pairs)))

    scored = []
    for p in pairs:
        p_words = set(re.findall(r'[a-zA-Zа-яА-ЯёЁ0-9]+', p.get("incoming", "").lower()))
        overlap = len(words.intersection(p_words))
        if overlap > 0:
            scored.append((overlap, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return [item[1] for item in scored[:limit]]
    
    return random.sample(pairs, min(limit, len(pairs)))

# =====================================================================
# 2. СОСТОЯНИЕ И НАСТРОЙКИ
# =====================================================================

def load_state():
    global afk_state
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                afk_state.update(saved)
                if "ainoo_users" not in afk_state:
                    afk_state["ainoo_users"] = {}
        except Exception:
            pass

def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(afk_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

load_state()

# =====================================================================
# 3. ГЕНЕРАЦИЯ СИСТЕМНОГО ПРОМПТА И ОТВЕТОВ
# =====================================================================

def build_secret_prompt(reason: str, incoming_text: str) -> str:
    """Скрытый режим: 100% маскировка под владельца аккаунта с использованием обученных весов и уроков."""
    ds = get_dataset()
    examples = find_relevant_examples(incoming_text, limit=6)
    examples_str = ""
    for ex in examples:
        examples_str += f"- Собеседник: \"{ex['incoming']}\" -> Твой ответ: \"{ex['reply']}\"\n"

    lessons_str = ""
    feedback_mem = ds.get("feedback_memory", [])
    if feedback_mem:
        lessons_str = "\n⚠️ УРОКИ И ЗАМЕЧАНИЯ ОТ ИИ-КОНТРОЛЕРА (СТРОГО СОБЛЮДАЙ ИХ):\n"
        for l in feedback_mem[-6:]:
            lessons_str += f"- На «{l.get('incoming')}» не отвечать «{l.get('bad_response')}»! Совет: {l.get('feedback')} -> Лучше: «{l.get('suggestion')}»\n"

    return f"""ТЫ — РЕАЛЬНЫЙ ЧЕЛОВЕК (парень 17 лет, ник Rew / XRay / @nonosyisss, живешь в РФ, делаешь софт/ботов на Python Telethon, играешь в CS2, общаешься в Telegram).
Ты лично переписываешься в Telegram в скрытом режиме (AFK).
ТВОЙ СТИЛЬ — ПРЕДЕЛЬНО КРАТКИЙ, КОРОТКИЙ, ПОНЯТНЫЙ, БЕЗ ЛИШНИХ ПОДРОБНОСТЕЙ И БЕЗ ЗАНУДСТВА (1-4 слова)!

⛔ ЖЕСТКИЕ ПРАВИЛА И ЗАПРЕТЫ:
1. КРАТКО И БЕЗ ЛИШНИХ ПОДРОБНОСТЕЙ (НЕ ВЫВАЛИВАЙ БИОГРАФИЮ):
   - «сколько тебе лет?» -> «17» или «17 мне» (НИКАКИХ упоминаний страны или переездов!).
   - «где живешь?» -> «в рф» или «в рф ща» (ТОЛЬКО РФ, никаких Польш и городов!).
   - «какой любимый цвет?» -> «черный» или «черный в основном».
   - «че делаешь?» -> «ниче в тг сижу», «код делаю», «лежу».
2. НИКАКИХ ЗАНУДНЫХ И НАУЧНЫХ СЛОВ (ТЫ НЕ ВИКИПЕДИЯ):
   - На «почему трава зеленая?», «почему небо синее?», «почему земля круглая?» отвечай по-человечески: «хз откуда мне знать», «загугли», «хз вообще». Запрещено умничать и сыпать терминами!
3. СТРОГИЙ ЗАПРЕТ ОТВЕТОВ НЕВПОПАД:
   - Запрещено отвечать «норм» на вопрос «какой любимый цвет?», «где живешь?», «сколько лет?».
   - Запрещено отвечать «ща погоди» на чужие эмоции и утверждения («завидую» -> «чему ахах» или «да нечему»).
4. НИКАКИХ СЛОВ-ПАРАЗИТОВ ("бро", "брат", "чувак", "приятель") и шаблонов автоответчика ("я отошел", "позже отвечу").
5. Пиши маленькими строчными буквами, без точек на конце.

{lessons_str}
📋 ПРИМЕРЫ ТВОИХ НАСТОЯЩИХ ОТВЕТОВ:
{examples_str}

Отвечай СТРОГО одной короткой живой фразой от своего лица (1-4 слова). Без кавычек."""

def build_aiafk_prompt(reason: str) -> str:
    """Режим .aiafk: открытый ИИ-ассистент, помогающий и постоянно напоминающий об AFK."""
    return f"""Ты — умный, вежливый и полезный персональный ИИ-ассистент владельца этого Telegram аккаунта (владельца зовут Rew / @nonosyisss).

ГЛАВНЫЙ КОНТЕКСТ И СТАТУС ВЛАДЕЛЬЦА:
- Владелец аккаунта СЕЙЧАС ОТОШЕЛ ИЛИ ЗАНЯТ (Текущая причина: {reason}).
- Владелец вернется позже и ответит лично, как только освободится.

ТВОЯ ЗАДАЧА:
1. Ответить собеседнику по существу его вопроса / реплики, помочь ему, поддержать диалог или подсказать информацию.
2. В КАЖДОМ ОТВЕТЕ обязательно и ненавязчиво напомнить собеседнику, что Rew сейчас не у телефона (причина: {reason}), вернётся позже и тогда сможет ответить лично.
3. Стиль: умный, тактичный, современный ассистент (1-3 аккуратных предложения с эмодзи). Не строй огромные простыни текста.

Пример структуры ответа:
"Привет! Я ИИ-ассистент Rew. По твоему вопросу: [краткий ответ/помощь]. Напоминаю, что Rew сейчас отошел ({reason}) и ответит тебе лично, как только будет на связи! ✨"
"""

_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None and genai and GEMINI_API_KEY:
        try:
            _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            logger.warning(f"Failed to init genai Client: {e}")
            _gemini_client = None
    return _gemini_client

async def _call_gemini_genai(model_name: str, system_prompt: str, prompt: str, history: list) -> str:
    """Вызов через официальный SDK google-genai с моделью Flash Lite."""
    client = get_gemini_client()
    if not client:
        return None

    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.75,
        max_output_tokens=300,
        safety_settings=[
            genai_types.SafetySetting(
                category=genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
            ),
            genai_types.SafetySetting(
                category=genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
            ),
            genai_types.SafetySetting(
                category=genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
            ),
            genai_types.SafetySetting(
                category=genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=genai_types.HarmBlockThreshold.BLOCK_NONE,
            ),
        ],
        automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True)
    )

    contents = []
    for h in history[-3:]:
        role_name = "User" if h["role"] == "user" else "Model"
        contents.append(f"{role_name}: {h['content']}")
    contents.append(f"User: {prompt}")
    full_prompt = "\n\n".join(contents)

    def _call():
        resp = client.models.generate_content(
            model=model_name,
            contents=full_prompt,
            config=config
        )
        if resp and resp.text:
            return resp.text.strip()
        return None

    return await asyncio.to_thread(_call)

async def generate_reply(chat_id: int, incoming_text: str, reason: str, mode: str) -> str:
    """Генерирует ответ в зависимости от выбранного режима AFK (secret или aiafk)."""
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    history = chat_histories[chat_id]

    if mode == "secret":
        try:
            from afk_trainer import trainer
            resp = await trainer.generate_response(incoming_text)
            if resp and resp.get("text"):
                reply = clean_ai_reply(resp["text"], mode="secret")
                history.append({"role": "user", "content": incoming_text})
                history.append({"role": "assistant", "content": reply})
                return reply
        except Exception as e:
            logger.warning(f"Error using trainer for secret AFK: {e}")

    # Для режима aiafk (открытый ассистент) используем ассистент-промпт
    system_prompt = build_aiafk_prompt(reason)

    # 1. Попытка через Google GenAI (модель Lite по умолчанию)
    for g_model in ["gemini-3.5-flash-lite", "gemini-3.6-flash"]:
        try:
            answer = await _call_gemini_genai(g_model, system_prompt, incoming_text, history)
            if answer and answer.strip():
                reply = clean_ai_reply(answer.strip(), mode=mode)
                history.append({"role": "user", "content": incoming_text})
                history.append({"role": "assistant", "content": reply})
                return reply
        except Exception as e:
            logger.warning(f"GenAI Client ({g_model}) failed: {e}")

    # 2. Попытка через GoRouter
    for api_key in GOROUTER_KEYS:
        try:
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-4:])
            messages.append({"role": "user", "content": incoming_text})

            answer = None
            if OpenAI:
                client = OpenAI(api_key=api_key, base_url=GOROUTER_BASE_URL, timeout=8.0)
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model="claude-opus-5",
                    messages=messages,
                    temperature=0.75,
                    max_tokens=200
                )
                answer = response.choices[0].message.content

            if answer and answer.strip():
                reply = clean_ai_reply(answer.strip(), mode=mode)
                history.append({"role": "user", "content": incoming_text})
                history.append({"role": "assistant", "content": reply})
                return reply
        except Exception:
            continue

    if mode == "aiafk":
        return f"🤖 Привет! Владелец аккаунта сейчас отсутствует ({reason}) и ответит тебе лично позже! ✨"
    
    try:
        from afk_trainer import generate_ideal_style_reply
        ideal = generate_ideal_style_reply(incoming_text)
        if ideal:
            return ideal
    except Exception:
        pass
    
    fallback_replies = ["хз", "ку", "че", "да норм", "не пон", "я в тг сижу", "позже"]
    return random.choice(fallback_replies)

def clean_ai_reply(text: str, mode: str = "secret") -> str:
    """Очищает ответ от артефактов."""
    text = re.sub(r'^(Rew|User|Assistant|Ответ|Ты|Я|ИИ):\s*', '', text, flags=re.IGNORECASE).strip()
    text = text.strip('"\'`«»')
    
    if mode == "secret":
        text = re.sub(r'\b(бро|брат|братик|чувак|дружище|приятель|челик)\b[,\s!]*', '', text, flags=re.IGNORECASE).strip()
        if text.endswith("."):
            text = text[:-1].strip()
    return text

# =====================================================================
# 4. ОБРАБОТЧИК ВХОДЯЩИХ СООБЩЕНИЙ ПРИ AFK
# =====================================================================

async def handle_incoming_afk(event: events.NewMessage.Event):
    """Отвечает на входящие сообщения во время AFK с учетом режима и списка ainoo."""
    global _me_id
    if not afk_state.get("is_afk", False):
        return

    # Игнорируем свои собственные сообщения
    if getattr(event, "out", False):
        return

    # Игнорируем каналы
    if getattr(event, "is_channel", False) and not getattr(event, "is_group", False):
        return

    sender_id = getattr(event, "sender_id", None)
    if not sender_id or sender_id in (777000, 1087968824, 136817688):
        return

    if getattr(event, "via_bot_id", None) is not None:
        return

    sender = None
    try:
        sender = await event.get_sender()
    except Exception:
        sender = None

    if sender and (getattr(sender, "bot", False) or getattr(sender, "is_bot", False)):
        return

    raw_text = (getattr(event, "raw_text", "") or getattr(event, "text", "") or "").strip()
    if not raw_text:
        return

    # -------------------------------------------------------------
    # ПРОВЕРКА СПИСКА AINOO (ЧЕРНЫЙ СПИСОК ДЛЯ ИИ)
    # -------------------------------------------------------------
    sender_uname = (getattr(sender, "username", "") or "").lower().lstrip("@")
    sender_id_str = str(sender_id)
    ainoo_dict = afk_state.get("ainoo_users", {})

    is_in_ainoo = (sender_id_str in ainoo_dict) or (sender_uname and sender_uname in [u.lower().lstrip("@") for u in ainoo_dict.values() if isinstance(u, str)])
    if not is_in_ainoo:
        # Проверяем по ключам/значениям словаря ainoo
        for k, v in ainoo_dict.items():
            if str(k) == sender_id_str:
                is_in_ainoo = True
                break
            if isinstance(v, dict) and v.get("username", "").lower().lstrip("@") == sender_uname:
                is_in_ainoo = True
                break

    if is_in_ainoo:
        # Пользователь находится в списке ainoo
        if sender_id not in ainoo_notified_users:
            ainoo_notified_users.add(sender_id)
            refuse_msg = "⛔ **Владелец аккаунта специально просил вам не отвечать.** Он сейчас занят, и ИИ не будет продолжать с вами общение."
            try:
                if getattr(event, "is_group", False):
                    await event.reply(refuse_msg)
                else:
                    await event.respond(refuse_msg)
            except Exception:
                pass
            logger.info(f"Sent AINOO refusal message to user {sender_id} (@{sender_uname})")
        return

    # -------------------------------------------------------------
    # ОБЫЧНАЯ ОБРАБОТКА AFK / AIAFK
    # -------------------------------------------------------------
    is_group = bool(getattr(event, "is_group", False) or (getattr(event, "chat_id", 0) < 0 and getattr(event, "is_channel", False)))
    is_private = bool(getattr(event, "is_private", False) or (getattr(event, "chat_id", 0) > 0 and not is_group))

    if _me_id is None:
        try:
            me = await event.client.get_me()
            if me:
                _me_id = me.id
        except Exception:
            pass

    should_reply = False
    if is_private:
        should_reply = True
    elif is_group and afk_state.get("group_replies", True):
        reply_to = getattr(event, "reply_to_msg_id", None)
        if reply_to:
            try:
                reply_msg = await event.get_reply_message()
                if reply_msg and (getattr(reply_msg, "sender_id", None) == _me_id or getattr(reply_msg, "out", False)):
                    should_reply = True
            except Exception:
                pass
        
        if not should_reply and _me_id:
            if f"tg://user?id={_me_id}" in raw_text or "@nonosyisss" in raw_text.lower():
                should_reply = True

    if not should_reply:
        return

    chat_id = event.chat_id
    now = time.time()
    if chat_id in last_chat_reply_time:
        if now - last_chat_reply_time[chat_id] < 3.0:
            return

    last_chat_reply_time[chat_id] = now
    reason = afk_state.get("reason", "Отошел")
    mode = afk_state.get("mode", "secret")

    try:
        reply_text = await generate_reply(chat_id, raw_text, reason, mode)
        if not reply_text:
            return

        if mode == "notify":
            reply_text = f"💤 **[AFK — {reason}]**\n{reply_text}"

        type_delay = min(max(len(reply_text) * 0.04 + random.uniform(0.8, 1.8), 1.0), 4.0)
        try:
            async with event.client.action(chat_id, 'typing'):
                await asyncio.sleep(type_delay)
        except Exception:
            await asyncio.sleep(type_delay)

        if is_group:
            await event.reply(reply_text)
        else:
            await event.respond(reply_text)

        afk_state["total_replies"] = afk_state.get("total_replies", 0) + 1
        user_key = str(sender_id)
        afk_state["replied_users"][user_key] = afk_state.get("replied_users", {}).get(user_key, 0) + 1
        save_state()

        sender_title = getattr(sender, "first_name", "") or str(sender_id)
        logger.info(f"AFK ({mode}) replied to {sender_title} in {chat_id}: '{reply_text}'")

    except Exception as e:
        logger.warning(f"Failed to send AFK reply: {e}")

async def handle_outgoing_auto_unafk(event: events.NewMessage.Event):
    """Автоматически выключает AFK, если владелец сам начал писать в чаты (при auto_unafk: True)."""
    if not afk_state.get("is_afk", False) or not afk_state.get("auto_unafk", True):
        return

    if not getattr(event, "out", False):
        return

    text = (event.raw_text or "").strip()
    if text.startswith(CMD_PREFIX) or text.startswith("."):
        return

    afk_state["is_afk"] = False
    afk_state["since"] = 0
    save_state()
    chat_histories.clear()
    ainoo_notified_users.clear()

    logger.info("Auto-unafk triggered by outgoing message.")

def format_duration(seconds: float) -> str:
    """Форматирует секунды в читаемое время."""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} мин")
    if secs > 0 or not parts:
        parts.append(f"{secs} сек")
    return " ".join(parts)

async def safe_edit(event: events.NewMessage.Event, text: str):
    """Безопасное редактирование сообщения с fallback на отправку нового."""
    try:
        return await event.edit(text)
    except Exception:
        try:
            return await event.respond(text)
        except Exception:
            return None

# =====================================================================
# 5. КОМАНДЫ МОДУЛЯ
# =====================================================================

@core.command("afk", description="Скрытый AFK клон (100% маскировка под тебя)", usage=f"{CMD_PREFIX}afk [причина]")
async def afk_cmd(event: events.NewMessage.Event):
    """Включает скрытый ИИ AFK режим (клон)."""
    args = event.raw_text.split(maxsplit=1)
    reason = args[1].strip() if len(args) > 1 else "Отошел"

    ds = get_dataset()
    pairs_count = len(ds.get("dialogue_pairs", []))

    afk_state["is_afk"] = True
    afk_state["mode"] = "secret"
    afk_state["reason"] = reason
    afk_state["since"] = time.time()
    afk_state["total_replies"] = 0
    afk_state["replied_users"] = {}
    save_state()
    chat_histories.clear()
    ainoo_notified_users.clear()

    msg_text = (
        "💤 **Скрытый AFK режим активирован!**\n\n"
        f"📝 **Причина:** `{reason}`\n"
        f"🎭 **Режим:** `🤫 Скрытый клон (100% маскировка под тебя)`\n"
        f"🧠 **Обучение:** `{pairs_count}` диалогов из `result.json`\n"
        f"⚡ *ИИ будет отвечать в точности твоими словами и фразами.*"
    )

    msg = await safe_edit(event, msg_text)
    await asyncio.sleep(4)
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass

@core.command("aiafk", description="Открытый ИИ-ассистент с напоминанием об AFK", usage=f"{CMD_PREFIX}aiafk [причина]")
async def aiafk_cmd(event: events.NewMessage.Event):
    """Включает режим умного ИИ-ассистента, который общается и напоминает, что ты отошел."""
    args = event.raw_text.split(maxsplit=1)
    reason = args[1].strip() if len(args) > 1 else "Отошел"

    afk_state["is_afk"] = True
    afk_state["mode"] = "aiafk"
    afk_state["reason"] = reason
    afk_state["since"] = time.time()
    afk_state["total_replies"] = 0
    afk_state["replied_users"] = {}
    save_state()
    chat_histories.clear()
    ainoo_notified_users.clear()

    msg_text = (
        "🤖 **AI-AFK Ассистент активирован!**\n\n"
        f"📝 **Причина:** `{reason}`\n"
        f"🎭 **Режим:** `🤖 Открытый умный ИИ-помощник`\n"
        f"📢 *ИИ будет отвечать собеседникам и постоянно напоминать, что ты отошел ({reason}) и ответишь позже.*"
    )

    msg = await safe_edit(event, msg_text)
    await asyncio.sleep(4)
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass

@core.command("ainoo", description="ИИ скажет пользователю, что ты просил не отвечать", usage=f"{CMD_PREFIX}ainoo <@username|id|reply>")
async def ainoo_cmd(event: events.NewMessage.Event):
    """Добавляет пользователя в список ainoo (ИИ отказывает в общении по твоей просьбе)."""
    args = event.raw_text.split(maxsplit=1)
    target_user = None

    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.sender_id:
            try:
                target_user = await event.client.get_entity(reply_msg.sender_id)
            except Exception:
                target_user = reply_msg.sender
    elif len(args) > 1:
        target_str = args[1].strip().lstrip("@")
        try:
            target_user = await event.client.get_entity(int(target_str) if target_str.isdigit() else target_str)
        except Exception:
            target_user = None

    if not target_user:
        await safe_edit(event, f"❌ **Использование:** `{CMD_PREFIX}ainoo @username` или в ответ на сообщение.")
        return

    uid = str(getattr(target_user, "id", 0))
    uname = getattr(target_user, "username", "") or ""
    fname = getattr(target_user, "first_name", "") or getattr(target_user, "title", "") or uid

    afk_state["ainoo_users"][uid] = {
        "username": uname,
        "name": fname
    }
    save_state()

    tag_str = f"@{uname}" if uname else f"ID `{uid}`"
    text = (
        "🚫 **Пользователь добавлен в `.ainoo`!**\n\n"
        f"👤 **Пользователь:** {fname} ({tag_str})\n"
        f"💬 **Реакция ИИ при AFK:** *Сообщит, что владелец специально просил вам не отвечать и прекратит диалог.*"
    )
    await safe_edit(event, text)

@core.command("unainoo", description="Удалить пользователя из списка .ainoo", usage=f"{CMD_PREFIX}unainoo <@username|id|reply>")
async def unainoo_cmd(event: events.NewMessage.Event):
    """Удаляет пользователя из списка ainoo."""
    args = event.raw_text.split(maxsplit=1)
    target_id = None

    if event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg:
            target_id = str(reply_msg.sender_id)
    elif len(args) > 1:
        target_str = args[1].strip().lstrip("@")
        if target_str.isdigit():
            target_id = target_str
        else:
            for uid, info in afk_state.get("ainoo_users", {}).items():
                if isinstance(info, dict) and info.get("username", "").lower() == target_str.lower():
                    target_id = uid
                    break
            if not target_id:
                try:
                    ent = await event.client.get_entity(target_str)
                    if ent:
                        target_id = str(ent.id)
                except Exception:
                    pass

    if not target_id or target_id not in afk_state.get("ainoo_users", {}):
        await safe_edit(event, f"❌ Пользователь не найден в списке `.ainoo`.")
        return

    del afk_state["ainoo_users"][target_id]
    save_state()
    await safe_edit(event, f"✅ Пользователь `ID: {target_id}` удален из списка `.ainoo`.")

@core.command("ainoolist", description="Список пользователей в .ainoo", usage=f"{CMD_PREFIX}ainoolist")
async def ainoolist_cmd(event: events.NewMessage.Event):
    """Выводит список пользователей, которым запрещен диалог с ИИ."""
    ainoo_dict = afk_state.get("ainoo_users", {})
    if not ainoo_dict:
        await safe_edit(event, "📋 **Список `.ainoo` пуст.** Все пользователи могут получать ответы ИИ.")
        return

    lines = []
    for uid, info in ainoo_dict.items():
        if isinstance(info, dict):
            name = info.get("name", "User")
            uname = f"@{info['username']}" if info.get("username") else f"ID `{uid}`"
            lines.append(f"• **{name}** ({uname})")
        else:
            lines.append(f"• ID `{uid}`")

    text = (
        f"🚫 **СПИСОК `.ainoo` ({len(lines)}):**\n\n"
        + "\n".join(lines)
        + f"\n\n💡 *ИИ скажет этим людям, что ты специально просил им не отвечать.*"
    )
    await safe_edit(event, text)

@core.command("unafk", description="Выключить AFK режим и показать статистику", usage=f"{CMD_PREFIX}unafk")
async def unafk_cmd(event: events.NewMessage.Event):
    """Выключает AFK режим и показывает сводку."""
    if not afk_state.get("is_afk", False):
        msg = await safe_edit(event, "ℹ️ **Ты не находишься в режиме AFK.**")
        await asyncio.sleep(3)
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        return

    since = afk_state.get("since", 0)
    duration_str = format_duration(time.time() - since) if since else "0 сек"
    total_replies = afk_state.get("total_replies", 0)
    users_count = len(afk_state.get("replied_users", {}))

    afk_state["is_afk"] = False
    afk_state["since"] = 0
    save_state()
    chat_histories.clear()
    ainoo_notified_users.clear()

    report = (
        "👋 **С возвращением! AFK выключен.**\n\n"
        f"⏱ **Время отсутствия:** `{duration_str}`\n"
        f"🤖 **Ответов сгенерировано:** `{total_replies}`\n"
        f"👥 **Собеседников обслужено:** `{users_count}`"
    )

    msg = await safe_edit(event, report)
    await asyncio.sleep(5)
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass

@core.command("back", description="Синоним .unafk", usage=f"{CMD_PREFIX}back")
async def back_cmd(event: events.NewMessage.Event):
    """Синоним для .unafk."""
    await unafk_cmd(event)

@core.command("afkstatus", description="Статус и настройки AFK ИИ", usage=f"{CMD_PREFIX}afkstatus")
async def afkstatus_cmd(event: events.NewMessage.Event):
    """Показывает текущий статус и подробности AFK."""
    is_afk = afk_state.get("is_afk", False)
    status_str = "🟢 **ВКЛЮЧЕН**" if is_afk else "🔴 **ВЫКЛЮЧЕН**"
    reason = afk_state.get("reason", "Нет")
    mode = afk_state.get("mode", "secret")
    since = afk_state.get("since", 0)
    duration_str = format_duration(time.time() - since) if is_afk and since else "—"
    replies = afk_state.get("total_replies", 0)
    ainoo_count = len(afk_state.get("ainoo_users", {}))

    mode_names = {
        "secret": "🤫 Скрытый клон (100% маскировка)",
        "aiafk": "🤖 AI-Ассистент (напоминает об AFK)",
        "notify": "📢 С плашкой [AFK]"
    }

    text = (
        "⚙️ **СТАТУС AFK & AI ASSISTANT**\n\n"
        f"📊 **Статус:** {status_str}\n"
        f"📝 **Причина:** `{reason}`\n"
        f"⏱ **Длительность:** `{duration_str}`\n"
        f"🎭 **Режим:** `{mode_names.get(mode, mode)}`\n"
        f"💬 **Ответов за сессию:** `{replies}`\n"
        f"🚫 **В списке `.ainoo`:** `{ainoo_count}` польз.\n\n"
        f"💡 *Команды:*\n"
        f"• `{CMD_PREFIX}afk [причина]` — Скрытый клон\n"
        f"• `{CMD_PREFIX}aiafk [причина]` — Открытый ИИ-ассистент\n"
        f"• `{CMD_PREFIX}ainoo <@user>` — Добавить в игнор-список\n"
        f"• `{CMD_PREFIX}ainoolist` — Список игнора\n"
        f"• `{CMD_PREFIX}afktrain` — Веб-студия обучения клона\n"
        f"• `{CMD_PREFIX}unafk` — Выключить AFK"
    )

    await safe_edit(event, text)

@core.command("afktrain", description="Веб-студия обучения нейросетевого клона AFK", usage=f"{CMD_PREFIX}afktrain")
async def afktrain_cmd(event: events.NewMessage.Event):
    """Открывает или запускает веб-студию обучения нейросетевого клона."""
    import subprocess
    import socket

    port = 5050
    # Проверка запущен ли сервер
    server_running = False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        res = sock.connect_ex(("127.0.0.1", port))
        if res == 0:
            server_running = True
    except Exception:
        pass
    finally:
        sock.close()

    if not server_running:
        py_path = sys.executable if hasattr(sys, "executable") else "python"
        server_script = Path(__file__).parent.parent / "afk_web_server.py"
        try:
            subprocess.Popen([py_path, str(server_script)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            await asyncio.sleep(1.5)
            server_running = True
        except Exception as e:
            logger.warning(f"Failed to launch afk_web_server: {e}")

    weights_exist = WEIGHTS_FILE.exists()
    status_icon = "🟢 Обучена" if weights_exist else "🟡 Требуется обучение"

    msg = (
        "⚡ **AFK Neural Clone Studio**\n\n"
        f"🧠 **Модель:** `Gemini 3.5 Flash Lite`\n"
        f"📊 **База данных:** `result.json` (5 606 авторских реплик)\n"
        f"🎯 **Статус весов:** {status_icon}\n\n"
        f"🌐 **Веб-дашборд обучения:**\n"
        f"👉 `http://localhost:{port}`\n\n"
        f"💡 *В веб-приложении доступен график Loss/Accuracy, настройка времени (до 2 часов), лог батчей и интерактивный тест-чат!*"
    )

    await safe_edit(event, msg)

# =====================================================================
# 6. РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ПРИ ЗАГРУЗКЕ
# =====================================================================

_incoming_afk_handler = None
_outgoing_afk_handler = None

def on_load(manager):
    """Регистрирует фоновые слушатели событий Telethon."""
    global _incoming_afk_handler, _outgoing_afk_handler
    
    get_dataset()
    client = manager.client
    
    _incoming_afk_handler = client.add_event_handler(
        handle_incoming_afk,
        events.NewMessage(incoming=True)
    )

    _outgoing_afk_handler = client.add_event_handler(
        handle_outgoing_auto_unafk,
        events.NewMessage(outgoing=True)
    )

    logger.info("AFK & AI Assistant module loaded.")

def on_unload(manager):
    """Удаляет фоновые слушатели событий."""
    global _incoming_afk_handler, _outgoing_afk_handler
    client = manager.client

    if _incoming_afk_handler is not None:
        try:
            client.remove_event_handler(handle_incoming_afk)
        except Exception:
            pass
        _incoming_afk_handler = None

    if _outgoing_afk_handler is not None:
        try:
            client.remove_event_handler(handle_outgoing_auto_unafk)
        except Exception:
            pass
        _outgoing_afk_handler = None

    logger.info("AFK module unloaded.")
