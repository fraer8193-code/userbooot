from telethon import events
import core
from config import CMD_PREFIX, BOT_VERSION

@core.command("help", description="Show commands list", usage=f"{CMD_PREFIX}help [command]")
async def help_cmd(event: events.NewMessage.Event):
    """Стильное меню помощи с эмодзи и аккуратным форматированием."""
    args = event.raw_text.split(maxsplit=1)
    mgr = core.module_manager
    
    if not mgr:
        await event.edit("❌ **Module manager is not ready.**")
        return

    if len(args) > 1:
        target = args[1].lower().lstrip(CMD_PREFIX).lstrip("/")
        found_cmd = None
        for mod in mgr.modules.values():
            if target in mod.commands:
                found_cmd = mod.commands[target]
                break
        
        if found_cmd:
            text = (
                f"📖 **Command:** `{CMD_PREFIX}{found_cmd.name}`\n\n"
                f"📝 **Описание:** {found_cmd.description}\n"
                f"💡 **Синтаксис:** `{found_cmd.usage}`"
            )
            await event.edit(text)
        else:
            await event.edit(f"❌ **Command** `{CMD_PREFIX}{target}` **not found.**")
        return

    modules_count = len(mgr.modules)
    all_cmds = mgr.get_all_commands()
    
    text = (
        f"⚡ **Femboy Commands**\n"
        f"📦 Модулей: `{modules_count}` • ⚡ Команд: `{len(all_cmds)}`\n\n"
    )

    categories = {
        "info": "🐧 **General**",
        "ping": "🐧 **General**",
        "restart": "🐧 **General**",
        "eval": "💻 **Developer**",
        "purge": "🧹 **Purge & Clean**",
        "type": "✨ **Animation**",
        "love": "✨ **Animation**",
        "id": "🔍 **Inspect**",
        "moderation": "🛡 **Moderation**",
        "dmess": "🗑 **Logger**",
        "modmanager": "🧩 **Modules**",
        "games": "🎮 **Mini Games**",
        "ai": "🤖 **Artificial Intelligence**",
        "nanobanano": "🍌 **Nano Banana 2**",
        "veo": "🎬 **Google Veo 3**",
        "tiktok": "📱 **TikTok**",
        "geo": "📍 **Fake Geolocation**",
        "ramka": "🖼 **Frame / Рамка**",
        "afk": "💤 **AFK & Secret AI Clone**",
        "autotime": "🕐 **Auto Time / Время**",
        "keepalive": "💓 **KeepAlive / 24/7**",
        "help": "🌸 **General**"
    }

    # Группируем команды
    category_groups = {}
    for mod_name, mod_info in sorted(mgr.modules.items()):
        if not mod_info.commands:
            continue
        cat_title = categories.get(mod_name, f"📦 **{mod_name.capitalize()}**")
        if cat_title not in category_groups:
            category_groups[cat_title] = []
        for cmd_name, cmd_info in sorted(mod_info.commands.items()):
            category_groups[cat_title].append(f"  • `{CMD_PREFIX}{cmd_name}` — {cmd_info.description}")

    for cat_title, cmds in category_groups.items():
        text += f"{cat_title}\n"
        text += "\n".join(cmds) + "\n\n"

    text += f"💡 Напишите `{CMD_PREFIX}help <команда>` для подробностей"
    
    await event.edit(text)
