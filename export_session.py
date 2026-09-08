import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import API_ID, API_HASH, SESSION_NAME

async def main():
    print("=" * 50)
    print("    ЭКСПОРТ / СОЗДАНИЕ СТРОКИ СЕССИИ (SESSION_STRING)")
    print("=" * 50)

    # 1. Попытка конвертировать существующий локальный файл сессии
    try:
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
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
            return
        await client.disconnect()
    except Exception as e:
        print(f"[-] Локальный файл сессии недоступен или не авторизован: {e}")

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
