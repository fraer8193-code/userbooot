import asyncio
import os
import shutil
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import API_ID, API_HASH, SESSION_NAME

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

async def main():
    print("=" * 50)
    print("    ЭКСПОРТ / СОЗДАНИЕ СТРОКИ СЕССИИ (SESSION_STRING)")
    print("=" * 50)

    # 1. Попытка конвертировать существующий локальный файл сессии
    session_file = f"{SESSION_NAME}.session"
    if os.path.exists(session_file):
        for target_session, is_temp in [(SESSION_NAME, False), ("_temp_export_session", True)]:
            if is_temp:
                try:
                    shutil.copyfile(session_file, f"{target_session}.session")
                except Exception as e:
                    print(f"[-] Не удалось скопировать сессию: {e}")
                    continue
            try:
                client = TelegramClient(target_session, API_ID, API_HASH)
                await client.connect()
                if await client.is_user_authorized():
                    string = StringSession.save(client.session)
                    print(f"\n[+] Успешно получена сессия из файла {SESSION_NAME}.session!")
                    print("\n" + "=" * 60)
                    print(string)
                    print("=" * 60)
                    print("\nСкопируйте эту строку и добавьте в переменные окружения сервера (Environment Variables):")
                    print(f'SESSION_STRING="{string}"\n')
                    await client.disconnect()
                    if is_temp:
                        for ext in ("", "-journal"):
                            f_path = f"{target_session}.session{ext}"
                            if os.path.exists(f_path):
                                try:
                                    os.remove(f_path)
                                except Exception:
                                    pass
                    return
                await client.disconnect()
            except Exception as e:
                if not is_temp:
                    # Возможно файл заблокирован запущенным юзерботом, пробуем копию
                    continue
                print(f"[-] Локальный файл сессии недоступен или не авторизован: {e}")
            finally:
                if is_temp:
                    for ext in ("", "-journal"):
                        f_path = f"{target_session}.session{ext}"
                        if os.path.exists(f_path):
                            try:
                                os.remove(f_path)
                            except Exception:
                                pass

    # 2. Интерактивная авторизация и создание строки с нуля
    print("\nАвторизация для получения новой StringSession...")
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        string = client.session.save()
        print("\n[+] Новая сессия успешно создана!")
        print("\n" + "=" * 60)
        print(string)
        print("=" * 60)
        print("\nСкопируйте эту строку и добавьте в переменные окружения сервера (Environment Variables):")
        print(f'SESSION_STRING="{string}"\n')

if __name__ == "__main__":
    asyncio.run(main())

