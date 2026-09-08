import json
import random
import asyncio
from pathlib import Path
from telethon import events, Button
import core
from config import CMD_PREFIX, BOT_USERNAME, BOT_TOKEN

DATA_FILE = Path(__file__).parent.parent / "games_data.json"

# --- Хранилище баланса и рекордов ---
default_data = {
    "balance": 1000,
    "snake_highscore": 0,
    "maze_level": 1,
    "score_2048": 0,
    "dungeon_wins": 0,
    "wins": 0,
    "losses": 0
}

data = default_data.copy()

def load_data():
    global data
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                data.update(saved)
        except Exception:
            pass

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

load_data()

# Активные сессии игр
active_games = {}

# ==========================================
# 0. ИНЛАЙН-КЛИЕНТ И ОТПРАВКА КНОПОК
# ==========================================

async def get_bot_client():
    """Возвращает активного бота-помощника."""
    bot = getattr(core, "bot_client", None)
    if bot is not None:
        try:
            if bot.is_connected():
                return bot
        except Exception:
            pass

    if BOT_TOKEN:
        try:
            from config import API_ID, API_HASH
            from telethon import TelegramClient
            bot = TelegramClient("bot_session", API_ID, API_HASH)
            await bot.connect()
            if not await bot.is_user_authorized():
                await bot.sign_in(bot_token=BOT_TOKEN)
            core.bot_client = bot
            bot.add_event_handler(global_callback_dispatcher, events.CallbackQuery)
            bot.add_event_handler(bot_cmd_handler, events.NewMessage(incoming=True))
            bot.add_event_handler(bot_inline_handler, events.InlineQuery)
            return bot
        except Exception as e:
            print(f"[!] Error auto-connecting inline bot: {e}")
    return None

async def send_game_message(event, text, buttons=None, query_key=None):
    """Отправляет игровое сообщение с инлайн-кнопками."""
    bot = await get_bot_client()

    # 1. Основной способ: отправка через inline_query (работает во ВСЕХ чатах, в ЛС и Избранном)
    if BOT_USERNAME:
        try:
            q = query_key or ("snake" if "ЗМЕЙКА" in text else ("maze" if "ЛАБИРИНТ" in text else ("2048" if "2048" in text else ("bj" if "БЛЭКДЖЕК" in text else ("mines" if "МИННОЕ" in text else "games")))))
            results = await event.client.inline_query(BOT_USERNAME, q)
            if results and len(results) > 0:
                await results[0].click(event.chat_id)
                try:
                    await event.delete()
                except Exception:
                    pass
                return
        except Exception as e:
            pass

    # 2. Второй способ: прямая отправка от бота (в группах)
    if bot:
        try:
            try:
                input_entity = await event.client.get_input_entity(event.chat_id)
            except Exception:
                input_entity = event.chat_id

            msg = await bot.send_message(input_entity, text, buttons=buttons)
            try:
                await event.delete()
            except Exception:
                pass
            return msg
        except Exception:
            pass

    # 3. Резервный режим
    await event.edit(text)

# ==========================================
# 0.1 🎮 МЕНЮ ИГР (GAMES HUB)
# ==========================================

def render_games_menu_text():
    return (
        "🎮 **ИГРОВОЙ ЦЕНТР — ВЫБЕРИТЕ ИГРУ**\n\n"
        f"💰 **Баланс:** `{data.get('balance', 1000)}` 🪙\n"
        f"🐍 **Рекорд Змейки:** `{data.get('snake_highscore', 0)}`\n"
        f"🏰 **Этаж Лабиринта:** `{data.get('maze_level', 1)}`\n"
        f"🔢 **Рекорд 2048:** `{data.get('score_2048', 0)}`\n"
        f"📊 **Побед:** `{data.get('wins', 0)}` | 💥 **Поражений:** `{data.get('losses', 0)}`\n\n"
        "🎮 **Доступные игры с кнопками:**\n"
        "• `.snake` — 🐍 Змейка\n"
        "• `.maze` — 🏰 Лабиринт\n"
        "• `.2048` — 🔢 2048\n"
        "• `.bj` — 🃏 Блэкджек (21)\n"
        "• `.mines` — 💣 Минное поле"
    )

def get_games_menu_buttons():
    return [
        [Button.inline("🐍 Змейка", b"start:snake"), Button.inline("🏰 Лабиринт", b"start:maze")],
        [Button.inline("🔢 2048", b"start:2048"), Button.inline("🃏 Блэкджек", b"start:bj")],
        [Button.inline("💣 Минное поле", b"start:mines")]
    ]

@core.command("games", description="Interactive games hub with stats", usage=".games")
async def games_cmd(event: events.NewMessage.Event):
    """Игровое меню с кнопками для выбора игр."""
    text = render_games_menu_text()
    buttons = get_games_menu_buttons()
    await send_game_message(event, text, buttons, "games")

@core.command("game", description="Interactive games hub with stats", usage=".game")
async def game_alias_cmd(event: events.NewMessage.Event):
    """Алиас для игрового меню."""
    await games_cmd(event)

# ==========================================
# 1. 🐍 ЗМЕЙКА (SNAKE) С ИНЛАЙН-КНОПКАМИ
# ==========================================

SNAKE_WIDTH = 7
SNAKE_HEIGHT = 7

def render_snake_board(snake, apple):
    board = []
    head = snake[0]
    for y in range(SNAKE_HEIGHT):
        row = []
        for x in range(SNAKE_WIDTH):
            pos = (x, y)
            if pos == head:
                row.append("🐸")
            elif pos in snake:
                row.append("🟩")
            elif pos == apple:
                row.append("🍎")
            else:
                row.append("⬛")
        board.append("".join(row))
    return "\n".join(board)

def spawn_apple(snake):
    free = [(x, y) for x in range(SNAKE_WIDTH) for y in range(SNAKE_HEIGHT) if (x, y) not in snake]
    return random.choice(free) if free else None

def get_snake_buttons(game_id):
    return [
        [Button.inline("⬆️", f"snk:{game_id}:w".encode())],
        [Button.inline("⬅️", f"snk:{game_id}:a".encode()), Button.inline("🛑", f"snk:{game_id}:stop".encode()), Button.inline("➡️", f"snk:{game_id}:d".encode())],
        [Button.inline("⬇️", f"snk:{game_id}:s".encode())]
    ]

@core.command("snake", description="Play Snake with inline buttons", usage=".snake")
async def snake_cmd(event: events.NewMessage.Event):
    """Запускает Змейку с инлайн-кнопками."""
    snake = [(3, 3), (3, 4), (3, 5)]
    apple = spawn_apple(snake)
    game_id = str(random.randint(10000, 99999))

    active_games[game_id] = {
        "type": "snake",
        "snake": snake,
        "apple": apple,
        "score": 0
    }

    text = (
        "🐍 **ИГРА: ЗМЕЙКА**\n\n"
        f"{render_snake_board(snake, apple)}\n\n"
        f"🍎 **Счет:** `0` | 🏆 **Рекорд:** `{data.get('snake_highscore', 0)}`"
    )

    buttons = get_snake_buttons(game_id)
    await send_game_message(event, text, buttons, "snake")

async def handle_snake_callback(event, game_id: str, action: str):
    if game_id not in active_games or active_games[game_id].get("type") != "snake":
        await event.answer("⚠️ Игра завершена.", alert=True)
        return

    if action == "stop":
        del active_games[game_id]
        await event.edit("🐍 **Игра Змейка остановлена.**", buttons=None)
        await event.answer("Игра остановлена")
        return

    game = active_games[game_id]
    snake = game["snake"]
    apple = game["apple"]
    score = game["score"]

    dirs = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}
    if action not in dirs:
        return

    dx, dy = dirs[action]
    head = snake[0]
    new_head = (head[0] + dx, head[1] + dy)

    if not (0 <= new_head[0] < SNAKE_WIDTH and 0 <= new_head[1] < SNAKE_HEIGHT):
        del active_games[game_id]
        if score > data.get("snake_highscore", 0):
            data["snake_highscore"] = score
            save_data()
            h_str = " 🔥 **НОВЫЙ РЕКОРД!**"
        else:
            h_str = ""

        text = (
            f"💥 **ВРЕЗАЛИСЬ В СТЕНУ! GAME OVER!**{h_str}\n\n"
            f"{render_snake_board(snake, apple)}\n\n"
            f"🍎 Итоговый счет: `{score}` | 🏆 Рекорд: `{data.get('snake_highscore', 0)}`"
        )
        restart_btn = [[Button.inline("🔄 Играть снова", b"start:snake")]]
        await event.edit(text, buttons=restart_btn)
        await event.answer("💥 Столкновение со стеной!")
        return

    if new_head in snake[:-1]:
        del active_games[game_id]
        text = (
            "💀 **УКУСИЛИ СЕБЯ ЗА ХВОСТ! GAME OVER!**\n\n"
            f"{render_snake_board(snake, apple)}\n\n"
            f"🍎 Итоговый счет: `{score}` | 🏆 Рекорд: `{data.get('snake_highscore', 0)}`"
        )
        restart_btn = [[Button.inline("🔄 Играть снова", b"start:snake")]]
        await event.edit(text, buttons=restart_btn)
        await event.answer("💀 Столкновение с хвостом!")
        return

    snake.insert(0, new_head)

    if new_head == apple:
        score += 1
        game["score"] = score
        apple = spawn_apple(snake)
        game["apple"] = apple
        await event.answer(f"🍎 +1 Яблоко! (Счет: {score})")
        if apple is None:
            del active_games[game_id]
            await event.edit(f"👑 **ВЫ ПРОШЛИ ВСЮ ЗМЕЙКУ! ПОБЕДА!**\nСчет: `{score}`", buttons=None)
            return
    else:
        snake.pop()
        await event.answer()

    text = (
        "🐍 **ИГРА: ЗМЕЙКА**\n\n"
        f"{render_snake_board(snake, apple)}\n\n"
        f"🍎 **Счет:** `{score}` | 🏆 **Рекорд:** `{data.get('snake_highscore', 0)}`"
    )

    buttons = get_snake_buttons(game_id)
    await event.edit(text, buttons=buttons)

# ==========================================
# 2. 🏰 ЛАБИРИНТ (MAZE) С ИНЛАЙН-КНОПКАМИ
# ==========================================

MAZE_W = 9
MAZE_H = 9

def generate_maze(width=9, height=9):
    grid = [["🧱" for _ in range(width)] for _ in range(height)]
    
    def carve(x, y):
        grid[y][x] = "▫️"
        dirs = [(0, -2), (0, 2), (-2, 0), (2, 0)]
        random.shuffle(dirs)
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if 1 <= nx < width - 1 and 1 <= ny < height - 1 and grid[ny][nx] == "🧱":
                grid[y + dy // 2][x + dx // 2] = "▫️"
                carve(nx, ny)

    carve(1, 1)
    free_cells = [(x, y) for y in range(height) for x in range(width) if grid[y][x] == "▫️" and (x, y) != (1, 1)]
    key_pos = random.choice(free_cells)
    free_cells.remove(key_pos)
    exit_pos = random.choice(free_cells)
    return grid, (1, 1), key_pos, exit_pos

def render_maze(grid, player, key_pos, exit_pos, has_key):
    out = []
    for y in range(len(grid)):
        row = []
        for x in range(len(grid[0])):
            pos = (x, y)
            if pos == player:
                row.append("🧙‍♂️")
            elif not has_key and pos == key_pos:
                row.append("🗝️")
            elif pos == exit_pos:
                row.append("🌀")
            else:
                row.append(grid[y][x])
        out.append("".join(row))
    return "\n".join(out)

def get_maze_buttons(game_id):
    return [
        [Button.inline("⬆️", f"mz:{game_id}:w".encode())],
        [Button.inline("⬅️", f"mz:{game_id}:a".encode()), Button.inline("🌀", f"mz:{game_id}:stop".encode()), Button.inline("➡️", f"mz:{game_id}:d".encode())],
        [Button.inline("⬇️", f"mz:{game_id}:s".encode())]
    ]

@core.command("maze", description="Play Maze with inline buttons", usage=".maze")
async def maze_cmd(event: events.NewMessage.Event):
    """Запускает Лабиринт с кнопками."""
    grid, player, key_pos, exit_pos = generate_maze(MAZE_W, MAZE_H)
    lvl = data.get("maze_level", 1)
    game_id = str(random.randint(10000, 99999))

    active_games[game_id] = {
        "type": "maze",
        "grid": grid,
        "player": player,
        "key_pos": key_pos,
        "exit_pos": exit_pos,
        "has_key": False,
        "steps": 0
    }

    text = (
        f"🏰 **ПОДЗЕМЕЛЬНЫЙ ЛАБИРИНТ — ЭТАЖ {lvl}**\n\n"
        f"{render_maze(grid, player, key_pos, exit_pos, False)}\n\n"
        "🎯 **Цель:** Найди ключ 🗝️ и активируй портал 🌀!"
    )

    buttons = get_maze_buttons(game_id)
    await send_game_message(event, text, buttons, "maze")

async def handle_maze_callback(event, game_id: str, action: str):
    if game_id not in active_games or active_games[game_id].get("type") != "maze":
        await event.answer("⚠️ Лабиринт закрыт.", alert=True)
        return

    if action == "stop":
        del active_games[game_id]
        await event.edit("🏰 **Лабиринт покинут.**", buttons=None)
        await event.answer("Вы вышли из лабиринта")
        return

    game = active_games[game_id]
    grid = game["grid"]
    px, py = game["player"]
    key_pos = game["key_pos"]
    exit_pos = game["exit_pos"]
    has_key = game["has_key"]

    dirs = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}
    if action not in dirs:
        return

    dx, dy = dirs[action]
    nx, ny = px + dx, py + dy

    if 0 <= nx < len(grid[0]) and 0 <= ny < len(grid) and grid[ny][nx] != "🧱":
        px, py = nx, ny
        game["player"] = (px, py)
        game["steps"] += 1
        if (px, py) == key_pos and not has_key:
            has_key = True
            game["has_key"] = True
            await event.answer("🗝️ Ключ найден! Беги к порталу 🌀!", alert=True)
        else:
            await event.answer()
    else:
        await event.answer("🧱 Стена!")
        return

    if (px, py) == exit_pos:
        if has_key:
            del active_games[game_id]
            data["maze_level"] = data.get("maze_level", 1) + 1
            data["balance"] += 200
            save_data()
            text = (
                f"🎉 **ЭТАЖ ПРОЙДЕН! ПОРТАЛ АКТИВИРОВАН!**\n\n"
                f"🏆 Вы перешли на **Этаж {data['maze_level']}**! (+200 🪙)\n"
            )
            next_btn = [[Button.inline("🚀 Следующий этаж", b"start:maze")]]
            await event.edit(text, buttons=next_btn)
            return
        else:
            status_hint = "⚠️ **Портал заперт!** Сначала найдите ключ 🗝️."
    else:
        status_hint = "🗝️ **Ключ найден!** Беги к порталу 🌀." if has_key else "🔍 Найди ключ 🗝️"

    text = (
        f"🏰 **ПОДЗЕМЕЛЬНЫЙ ЛАБИРИНТ — ЭТАЖ {data.get('maze_level', 1)}**\n\n"
        f"{render_maze(grid, (px, py), key_pos, exit_pos, has_key)}\n\n"
        f"{status_hint} (Шагов: `{game['steps']}`)"
    )

    buttons = get_maze_buttons(game_id)
    await event.edit(text, buttons=buttons)

# ==========================================
# 3. 🔢 2048 С ИНЛАЙН-КНОПКАМИ
# ==========================================

def render_2048(board):
    rows = []
    for r in board:
        row_str = " ".join(f"`[{val:^4}]`" if val else "`[    ]`" for val in r)
        rows.append(row_str)
    return "\n".join(rows)

def spawn_2048_tile(board):
    empty = [(r, c) for r in range(4) for c in range(4) if board[r][c] == 0]
    if empty:
        r, c = random.choice(empty)
        board[r][c] = 4 if random.random() > 0.85 else 2

def get_2048_buttons(game_id):
    return [
        [Button.inline("⬆️", f"2048:{game_id}:w".encode())],
        [Button.inline("⬅️", f"2048:{game_id}:a".encode()), Button.inline("🔄", f"2048:{game_id}:restart".encode()), Button.inline("➡️", f"2048:{game_id}:d".encode())],
        [Button.inline("⬇️", f"2048:{game_id}:s".encode())]
    ]

@core.command("2048", description="Play 2048 with inline buttons", usage=".2048")
async def game_2048_cmd(event: events.NewMessage.Event):
    """Запускает 2048 с кнопками."""
    board = [[0]*4 for _ in range(4)]
    spawn_2048_tile(board)
    spawn_2048_tile(board)
    game_id = str(random.randint(10000, 99999))

    active_games[game_id] = {
        "type": "2048",
        "board": board,
        "score": 0
    }

    text = (
        "🔢 **ИГРА 2048**\n\n"
        f"{render_2048(board)}\n\n"
        f"📊 **Счет:** `0` | 🏆 **Рекорд:** `{data.get('score_2048', 0)}`"
    )

    buttons = get_2048_buttons(game_id)
    await send_game_message(event, text, buttons, "2048")

def slide_and_merge_row(row):
    non_zero = [x for x in row if x != 0]
    merged = []
    score_add = 0
    skip = False
    for i in range(len(non_zero)):
        if skip:
            skip = False
            continue
        if i + 1 < len(non_zero) and non_zero[i] == non_zero[i+1]:
            val = non_zero[i] * 2
            merged.append(val)
            score_add += val
            skip = True
        else:
            merged.append(non_zero[i])
    merged += [0] * (4 - len(merged))
    return merged, score_add

async def handle_2048_callback(event, game_id: str, action: str):
    if game_id not in active_games or active_games[game_id].get("type") != "2048":
        await event.answer("⚠️ Партия завершена.", alert=True)
        return

    if action == "restart":
        board = [[0]*4 for _ in range(4)]
        spawn_2048_tile(board)
        spawn_2048_tile(board)
        active_games[game_id]["board"] = board
        active_games[game_id]["score"] = 0
        text = (
            "🔢 **ИГРА 2048 (ПЕРЕЗАПУСК)**\n\n"
            f"{render_2048(board)}\n\n"
            f"📊 **Счет:** `0` | 🏆 **Рекорд:** `{data.get('score_2048', 0)}`"
        )
        await event.edit(text, buttons=get_2048_buttons(game_id))
        await event.answer("Новая партия началась!")
        return

    game = active_games[game_id]
    b = game["board"]
    score = game["score"]
    changed = False

    if action == "a":
        for r in range(4):
            new_r, s_add = slide_and_merge_row(b[r])
            if new_r != b[r]: changed = True
            b[r] = new_r
            score += s_add
    elif action == "d":
        for r in range(4):
            rev = b[r][::-1]
            new_r, s_add = slide_and_merge_row(rev)
            new_r = new_r[::-1]
            if new_r != b[r]: changed = True
            b[r] = new_r
            score += s_add
    elif action == "w":
        for c in range(4):
            col = [b[r][c] for r in range(4)]
            new_c, s_add = slide_and_merge_row(col)
            if new_c != col: changed = True
            for r in range(4): b[r][c] = new_c[r]
            score += s_add
    elif action == "s":
        for c in range(4):
            col = [b[r][c] for r in range(4)][::-1]
            new_c, s_add = slide_and_merge_row(col)
            new_c = new_c[::-1]
            if new_c != [b[r][c] for r in range(4)]: changed = True
            for r in range(4): b[r][c] = new_c[r]
            score += s_add

    if changed:
        spawn_2048_tile(b)
        game["score"] = score
        if score > data.get("score_2048", 0):
            data["score_2048"] = score
            save_data()
        await event.answer()
    else:
        await event.answer("Нет доступных ходов")
        return

    text = (
        "🔢 **ИГРА 2048**\n\n"
        f"{render_2048(b)}\n\n"
        f"📊 **Счет:** `{score}` | 🏆 **Рекорд:** `{data.get('score_2048', 0)}`"
    )

    await event.edit(text, buttons=get_2048_buttons(game_id))

# ==========================================
# 4. 🃏 БЛЭКДЖЕК (21)
# ==========================================

SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANKS = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 10, "Q": 10, "K": 10, "A": 11
}

def create_deck():
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck

def calc_hand(hand):
    val = sum(RANKS[r] for r, s in hand)
    aces = sum(1 for r, s in hand if r == "A")
    while val > 21 and aces > 0:
        val -= 10
        aces -= 1
    return val

def format_hand(hand, hide_second=False):
    if hide_second and len(hand) >= 2:
        return f"`[{hand[0][0]}{hand[0][1]}]` `[🂠 ?]`"
    return " ".join(f"`[{r}{s}]`" for r, s in hand)

def get_bj_buttons(game_id):
    return [
        [Button.inline("🃏 Взять карту (+1)", f"bj:{game_id}:hit".encode()), Button.inline("🛑 Вскрыть карты", f"bj:{game_id}:stand".encode())]
    ]

@core.command("bj", description="Play Blackjack with buttons", usage=".bj [ставка]")
async def blackjack_cmd(event: events.NewMessage.Event):
    """Блэкджек с кнопками."""
    args = event.raw_text.split(maxsplit=1)
    bet = 50
    if len(args) > 1:
        try:
            bet = int(args[1])
            if bet <= 0: bet = 50
        except ValueError:
            bet = 50

    if data["balance"] < bet:
        await event.edit(f"❌ **Недостаточно фишек.** Баланс: `{data['balance']}` 🪙")
        await asyncio.sleep(2.5)
        await event.delete()
        return

    data["balance"] -= bet
    save_data()

    deck = create_deck()
    p_hand = [deck.pop(), deck.pop()]
    d_hand = [deck.pop(), deck.pop()]
    game_id = str(random.randint(10000, 99999))

    active_games[game_id] = {
        "type": "bj",
        "deck": deck,
        "p_hand": p_hand,
        "d_hand": d_hand,
        "bet": bet
    }

    p_score = calc_hand(p_hand)
    if p_score == 21:
        del active_games[game_id]
        win = int(bet * 2.5)
        data["balance"] += win
        data["wins"] += 1
        save_data()
        text = (
            "🔥 **NATURAL BLACKJACK (21)! ПОБЕДА!**\n\n"
            f"👤 **Ваша рука:** {format_hand(p_hand)} (`21`)\n"
            f"🎩 **Дилер:** {format_hand(d_hand)} (`{calc_hand(d_hand)}`)\n\n"
            f"💰 **Выигрыш:** `+{win}` 🪙 (Баланс: `{data['balance']}`)"
        )
        restart_btn = [[Button.inline("🔄 Сыграть еще", b"start:bj")]]
        await send_game_message(event, text, restart_btn, "bj")
        return

    text = (
        "🃏 **БЛЭКДЖЕК (21 ОЧКО)**\n\n"
        f"👤 **Ваша рука:** {format_hand(p_hand)} (Очки: `{p_score}`)\n"
        f"🎩 **Дилер:** {format_hand(d_hand, hide_second=True)}\n\n"
        f"💵 **Ставка:** `{bet}` 🪙"
    )

    buttons = get_bj_buttons(game_id)
    await send_game_message(event, text, buttons, "bj")

async def handle_bj_callback(event, game_id: str, action: str):
    if game_id not in active_games or active_games[game_id].get("type") != "bj":
        await event.answer("⚠️ Партия завершена.", alert=True)
        return

    game = active_games[game_id]
    bet = game["bet"]

    if action == "hit":
        game["p_hand"].append(game["deck"].pop())
        p_score = calc_hand(game["p_hand"])

        if p_score > 21:
            del active_games[game_id]
            data["losses"] += 1
            save_data()
            text = (
                "💥 **ПЕРЕБОР (BUST)! ВЫ ПРОИГРАЛИ.**\n\n"
                f"👤 **Ваша рука:** {format_hand(game['p_hand'])} (Очки: `{p_score}`)\n"
                f"🎩 **Дилер:** {format_hand(game['d_hand'])}\n\n"
                f"💀 Потеряно: `-{bet}` 🪙 (Баланс: `{data['balance']}`)"
            )
            restart_btn = [[Button.inline("🔄 Сыграть еще", b"start:bj")]]
            await event.edit(text, buttons=restart_btn)
            await event.answer("💥 Перебор!")
            return

        text = (
            "🃏 **БЛЭКДЖЕК (21 ОЧКО)**\n\n"
            f"👤 **Ваша рука:** {format_hand(game['p_hand'])} (Очки: `{p_score}`)\n"
            f"🎩 **Дилер:** {format_hand(game['d_hand'], hide_second=True)}\n\n"
            f"💵 **Ставка:** `{bet}` 🪙"
        )
        buttons = [
            [Button.inline("🃏 Взять карту (+1)", f"bj:{game_id}:hit".encode()), Button.inline("🛑 Вскрыть карты", f"bj:{game_id}:stand".encode())]
        ]
        await event.edit(text, buttons=buttons)
        await event.answer()

    elif action == "stand":
        del active_games[game_id]
        p_score = calc_hand(game["p_hand"])
        d_hand = game["d_hand"]
        deck = game["deck"]

        while calc_hand(d_hand) < 17:
            d_hand.append(deck.pop())

        d_score = calc_hand(d_hand)

        if d_score > 21:
            win = bet * 2
            data["balance"] += win
            data["wins"] += 1
            res = f"🎉 **ДИЛЕР ПЕРЕБРАЛ! ВЫ ПОБЕДИЛИ!** (+{win} 🪙)"
        elif p_score > d_score:
            win = bet * 2
            data["balance"] += win
            data["wins"] += 1
            res = f"🎉 **ВЫ НАБРАЛИ БОЛЬШЕ И ПОБЕДИЛИ!** (+{win} 🪙)"
        elif p_score < d_score:
            data["losses"] += 1
            res = f"💀 **ДИЛЕР ПОБЕДИЛ.** (-{bet} 🪙)"
        else:
            data["balance"] += bet
            res = "🤝 **НИЧЬЯ (PUSH)!** Ставка возвращена."

        save_data()
        text = (
            f"{res}\n\n"
            f"👤 **Ваша рука:** {format_hand(game['p_hand'])} (`{p_score}`)\n"
            f"🎩 **Дилер:** {format_hand(d_hand)} (`{d_score}`)\n\n"
            f"💰 **Баланс:** `{data['balance']}` 🪙"
        )
        restart_btn = [[Button.inline("🔄 Сыграть еще", b"start:bj")]]
        await event.edit(text, buttons=restart_btn)
        await event.answer()

# ==========================================
# 5. 💣 МИННОЕ ПОЛЕ
# ==========================================

MINE_MULTIPLIERS = [1.2, 1.5, 2.0, 2.8, 4.0, 6.0, 9.0, 15.0, 25.0, 50.0]

def render_mines_board_text(grid, revealed):
    res = []
    for row in range(5):
        line = []
        for col in range(5):
            idx = row * 5 + col
            if idx in revealed:
                line.append("💣" if grid[idx] == "M" else "💎")
            else:
                line.append("⬛")
        res.append(" ".join(line))
    return "\n".join(res)

def get_mines_buttons(game_id, revealed):
    buttons = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in revealed:
                row.append(Button.inline("💎", b"mines:noop"))
            else:
                row.append(Button.inline(f"{idx+1}", f"mns:{game_id}:{idx}".encode()))
        buttons.append(row)
    buttons.append([Button.inline("💰 Забрать выигрыш (Cashout)", f"mns:{game_id}:cashout".encode())])
    return buttons

@core.command("mines", description="Play Minesweeper with buttons", usage=".mines [ставка]")
async def mines_cmd(event: events.NewMessage.Event):
    """Минное поле с кнопками."""
    args = event.raw_text.split(maxsplit=1)
    bet = 50
    if len(args) > 1:
        try:
            bet = int(args[1])
            if bet <= 0: bet = 50
        except ValueError:
            bet = 50

    if data["balance"] < bet:
        await event.edit(f"❌ **Недостаточно фишек.** Баланс: `{data['balance']}` 🪙")
        await asyncio.sleep(2.5)
        await event.delete()
        return

    data["balance"] -= bet
    save_data()

    grid = ["D"] * 21 + ["M"] * 4
    random.shuffle(grid)
    game_id = str(random.randint(10000, 99999))

    active_games[game_id] = {
        "type": "mines",
        "grid": grid,
        "revealed": set(),
        "diamonds_found": 0,
        "bet": bet
    }

    text = (
        "💣 **МИННОЕ ПОЛЕ (4 МИНЫ / 21 АЛМАЗ)**\n\n"
        f"{render_mines_board_text(grid, set())}\n\n"
        f"💵 **Ставка:** `{bet}` 🪙 | 💎 **Найдено:** `0` | 📈 **Множитель:** `x1.00`"
    )

    buttons = get_mines_buttons(game_id, set())
    await send_game_message(event, text, buttons, "mines")

async def handle_mines_callback(event, game_id: str, action: str):
    if game_id not in active_games or active_games[game_id].get("type") != "mines":
        await event.answer("⚠️ Игра завершена.", alert=True)
        return

    game = active_games[game_id]
    grid = game["grid"]
    revealed = game["revealed"]
    bet = game["bet"]

    if action == "cashout":
        del active_games[game_id]
        d_count = game["diamonds_found"]
        if d_count == 0:
            data["balance"] += bet
            save_data()
            await event.edit("🪙 **Ставка возвращена.**", buttons=None)
            await event.answer("Возврат ставки")
            return

        mult = MINE_MULTIPLIERS[min(d_count - 1, len(MINE_MULTIPLIERS) - 1)]
        win = int(bet * mult)
        data["balance"] += win
        data["wins"] += 1
        save_data()

        text = (
            "💰 **УСПЕШНЫЙ КЭШАУТ!**\n\n"
            f"{render_mines_board_text(grid, revealed)}\n\n"
            f"🎉 **Забрано:** `+{win}` 🪙 (`x{mult}`)\n"
            f"💵 **Баланс:** `{data['balance']}` 🪙"
        )
        restart_btn = [[Button.inline("🔄 Сыграть еще", b"start:mines")]]
        await event.edit(text, buttons=restart_btn)
        await event.answer(f"Забрано +{win} 🪙!")
        return

    try:
        cell = int(action)
    except ValueError:
        return

    if cell in revealed:
        await event.answer()
        return

    revealed.add(cell)

    if grid[cell] == "M":
        all_cells = set(range(25))
        del active_games[game_id]
        data["losses"] += 1
        save_data()
        text = (
            "💥 **БУМ! ВЫ ПОДОРВАЛИСЬ НА МИНЕ!**\n\n"
            f"{render_mines_board_text(grid, all_cells)}\n\n"
            f"💀 Потеряно: `-{bet}` 🪙 (Баланс: `{data['balance']}`)"
        )
        restart_btn = [[Button.inline("🔄 Сыграть еще", b"start:mines")]]
        await event.edit(text, buttons=restart_btn)
        await event.answer("💥 БУМ! Мина!", alert=True)
        return

    game["diamonds_found"] += 1
    d_count = game["diamonds_found"]
    mult = MINE_MULTIPLIERS[min(d_count - 1, len(MINE_MULTIPLIERS) - 1)]
    cur_win = int(bet * mult)

    text = (
        "💎 **КРИСТАЛЛ НАЙДЕН!**\n\n"
        f"{render_mines_board_text(grid, revealed)}\n\n"
        f"💵 **Ставка:** `{bet}` 🪙 | 💎 **Найдено:** `{d_count}`\n"
        f"📈 **Множитель:** `x{mult}` (Куш: `+{cur_win}` 🪙)"
    )

    buttons = get_mines_buttons(game_id, revealed)
    await event.edit(text, buttons=buttons)
    await event.answer(f"💎 +1 Кристалл! (x{mult})")

# ==========================================
# 6. ОБРАБОТЧИКИ БОТА И ИНЛАЙН
# ==========================================

_callback_handler = None
_cmd_handler = None
_inline_handler = None

async def global_callback_dispatcher(event: events.CallbackQuery.Event):
    """Центральный обработчик всех нажатий на кнопки."""
    raw_data = event.data.decode("utf-8", errors="ignore")

    # Быстрый старт игр из меню
    if raw_data.startswith("start:"):
        game_name = raw_data.split(":", 1)[1]
        if game_name == "snake":
            await snake_cmd(event)
        elif game_name == "maze":
            await maze_cmd(event)
        elif game_name == "2048":
            await game_2048_cmd(event)
        elif game_name == "bj":
            await blackjack_cmd(event)
        elif game_name == "mines":
            await mines_cmd(event)
        elif game_name in ("games", "game"):
            await games_cmd(event)
        return

    # Змейка
    if raw_data.startswith("snk:"):
        parts = raw_data.split(":")
        if len(parts) == 3:
            await handle_snake_callback(event, parts[1], parts[2])
        return

    # Лабиринт
    if raw_data.startswith("mz:"):
        parts = raw_data.split(":")
        if len(parts) == 3:
            await handle_maze_callback(event, parts[1], parts[2])
        return

    # 2048
    if raw_data.startswith("2048:"):
        parts = raw_data.split(":")
        if len(parts) == 3:
            await handle_2048_callback(event, parts[1], parts[2])
        return

    # Блэкджек
    if raw_data.startswith("bj:"):
        parts = raw_data.split(":")
        if len(parts) == 3:
            await handle_bj_callback(event, parts[1], parts[2])
        return

    # Минное поле
    if raw_data.startswith("mns:"):
        parts = raw_data.split(":")
        if len(parts) == 3:
            await handle_mines_callback(event, parts[1], parts[2])
        return

    if raw_data == "mines:noop":
        await event.answer()
        return

async def bot_cmd_handler(event: events.NewMessage.Event):
    """Позволяет запускать игры с кнопками прямо в диалоге с ботом."""
    raw = (event.raw_text or "").strip().lower()
    if raw.startswith("/start") or raw.startswith(".start") or raw.startswith("/games") or raw.startswith(".games") or raw.startswith("/game") or raw.startswith(".game"):
        await games_cmd(event)
    elif raw.startswith("/snake") or raw.startswith(".snake"):
        await snake_cmd(event)
    elif raw.startswith("/maze") or raw.startswith(".maze"):
        await maze_cmd(event)
    elif raw.startswith("/2048") or raw.startswith(".2048"):
        await game_2048_cmd(event)
    elif raw.startswith("/bj") or raw.startswith(".bj") or raw.startswith("/blackjack") or raw.startswith(".blackjack"):
        await blackjack_cmd(event)
    elif raw.startswith("/mines") or raw.startswith(".mines"):
        await mines_cmd(event)

async def bot_inline_handler(event: events.InlineQuery.Event):
    """Инлайн-режим для вызова игр в любом диалоге с точной маршрутизацией запроса."""
    query = (event.text or "").strip().lower()
    if query.startswith("ai") or query in ("settings", "config", "aisettings", "aimode", "aimodel", "aiconfig", "aisetting"):
        return

    builder = event.builder
    articles = {}

    # 1. Меню игр
    menu_text = render_games_menu_text()
    articles["games"] = builder.article(
        "🎮 Игровой Центр (Все игры)",
        text=menu_text,
        buttons=get_games_menu_buttons(),
        description="Выбор игры: Змейка, Лабиринт, 2048, Блэкджек, Мины"
    )

    # 2. Змейка
    s_id = str(random.randint(10000, 99999))
    snake = [(3, 3), (3, 4), (3, 5)]
    apple = spawn_apple(snake)
    active_games[s_id] = {"type": "snake", "snake": snake, "apple": apple, "score": 0}
    s_text = f"🐍 **ИГРА: ЗМЕЙКА**\n\n{render_snake_board(snake, apple)}\n\n🍎 **Счет:** `0` | 🏆 **Рекорд:** `{data.get('snake_highscore', 0)}`"
    articles["snake"] = builder.article(
        "🐍 Змейка (Snake)",
        text=s_text,
        buttons=get_snake_buttons(s_id),
        description="Классическая змейка с управлением кнопками"
    )

    # 3. Лабиринт
    m_id = str(random.randint(10000, 99999))
    grid, player, key_pos, exit_pos = generate_maze(MAZE_W, MAZE_H)
    active_games[m_id] = {"type": "maze", "grid": grid, "player": player, "key_pos": key_pos, "exit_pos": exit_pos, "has_key": False, "steps": 0}
    m_text = f"🏰 **ПОДЗЕМЕЛЬНЫЙ ЛАБИРИНТ — ЭТАЖ {data.get('maze_level', 1)}**\n\n{render_maze(grid, player, key_pos, exit_pos, False)}\n\n🎯 **Цель:** Найди ключ 🗝️ и активируй портал 🌀!"
    articles["maze"] = builder.article(
        "🏰 Лабиринт (Maze)",
        text=m_text,
        buttons=get_maze_buttons(m_id),
        description="Исследуй подземелье, найди ключ и активируй портал"
    )

    # 4. 2048
    b_id = str(random.randint(10000, 99999))
    board = [[0]*4 for _ in range(4)]
    spawn_2048_tile(board); spawn_2048_tile(board)
    active_games[b_id] = {"type": "2048", "board": board, "score": 0}
    b_text = f"🔢 **ИГРА 2048**\n\n{render_2048(board)}\n\n📊 **Счет:** `0` | 🏆 **Рекорд:** `{data.get('score_2048', 0)}`"
    articles["2048"] = builder.article(
        "🔢 2048",
        text=b_text,
        buttons=get_2048_buttons(b_id),
        description="Объединяй плитки и собери 2048"
    )

    # 5. Блэкджек
    bj_id = str(random.randint(10000, 99999))
    bet = 50
    deck = create_deck()
    p_hand = [deck.pop(), deck.pop()]
    d_hand = [deck.pop(), deck.pop()]
    active_games[bj_id] = {"type": "bj", "deck": deck, "p_hand": p_hand, "d_hand": d_hand, "bet": bet}
    p_score = calc_hand(p_hand)
    bj_text = (
        "🃏 **БЛЭКДЖЕК (21 ОЧКО)**\n\n"
        f"👤 **Ваша рука:** {format_hand(p_hand)} (Очки: `{p_score}`)\n"
        f"🎩 **Дилер:** {format_hand(d_hand, hide_second=True)}\n\n"
        f"💵 **Ставка:** `{bet}` 🪙"
    )
    articles["bj"] = builder.article(
        "🃏 Блэкджек (Blackjack)",
        text=bj_text,
        buttons=get_bj_buttons(bj_id),
        description="Набери 21 очко против дилера"
    )

    # 6. Минное поле
    mns_id = str(random.randint(10000, 99999))
    m_bet = 50
    m_grid = ["D"] * 21 + ["M"] * 4
    random.shuffle(m_grid)
    active_games[mns_id] = {"type": "mines", "grid": m_grid, "revealed": set(), "diamonds_found": 0, "bet": m_bet}
    mns_text = (
        "💣 **МИННОЕ ПОЛЕ (4 МИНЫ / 21 АЛМАЗ)**\n\n"
        f"{render_mines_board_text(m_grid, set())}\n\n"
        f"💵 **Ставка:** `{m_bet}` 🪙 | 💎 **Найдено:** `0` | 📈 **Множитель:** `x1.00`"
    )
    articles["mines"] = builder.article(
        "💣 Минное поле (Mines)",
        text=mns_text,
        buttons=get_mines_buttons(mns_id, set()),
        description="Ищи алмазы и избегай мин"
    )

    results = []
    # Маршрутизируем: если запрошена конкретная игра, она становится results[0]
    if query in articles:
        results.append(articles[query])
        for k in ["games", "snake", "maze", "2048", "bj", "mines"]:
            if k != query and k in articles:
                results.append(articles[k])
    elif query in ("blackjack", "21"):
        results.append(articles["bj"])
        for k in ["games", "snake", "maze", "2048", "mines"]:
            if k in articles:
                results.append(articles[k])
    elif query in ("game", "hub", "menu"):
        results.append(articles["games"])
        for k in ["snake", "maze", "2048", "bj", "mines"]:
            if k in articles:
                results.append(articles[k])
    else:
        # По умолчанию меню игр первым
        for k in ["games", "snake", "maze", "2048", "bj", "mines"]:
            if k in articles:
                results.append(articles[k])

    await event.answer(results, cache_time=1)

def on_load(manager):
    global _callback_handler, _cmd_handler, _inline_handler
    _callback_handler = global_callback_dispatcher
    _cmd_handler = bot_cmd_handler
    _inline_handler = bot_inline_handler
    bot = getattr(manager, "bot_client", None) or getattr(core, "bot_client", None)
    if bot:
        bot.add_event_handler(_callback_handler, events.CallbackQuery)
        bot.add_event_handler(_cmd_handler, events.NewMessage(incoming=True))
        bot.add_event_handler(_inline_handler, events.InlineQuery)

def on_unload(manager):
    global _callback_handler, _cmd_handler, _inline_handler
    bot = getattr(manager, "bot_client", None) or getattr(core, "bot_client", None)
    if bot:
        if _callback_handler:
            bot.remove_event_handler(_callback_handler, events.CallbackQuery)
            _callback_handler = None
        if _cmd_handler:
            bot.remove_event_handler(_cmd_handler, events.NewMessage(incoming=True))
            _cmd_handler = None
        if _inline_handler:
            bot.remove_event_handler(_inline_handler, events.InlineQuery)
            _inline_handler = None
