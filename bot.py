import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === Настройки через переменные окружения ===
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]  # имя переменной окружения
BASE_URL = os.environ["BASE_URL"]         # имя переменной окружения
PORT = int(os.environ.get("PORT", 10000))        # Render сам подставляет PORT

DATA_FILE = "queues.json"

# === Работа с данными ===
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"milk_queue": [], "coffee_queue": [], "milk_index": 0, "coffee_index": 0}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def mention(user):
    return f"@{user.username}" if user.username else user.first_name

def format_queue(queue, index, title):
    if not queue:
        return f"{title}\n— очередь пуста."
    lines = [title]
    n = len(queue)
    for offset in range(n):
        i = (index + offset) % n
        marker = "→ сейчас" if offset == 0 else ""
        lines.append(f"{offset+1}. {queue[i]['mention']} {marker}".rstrip())
    return "\n".join(lines)

def milk_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Купил(а) 🥛", callback_data="milk_done")]])

def coffee_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Почистил(а) ☕", callback_data="coffee_done")]])

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    milk_text = format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко")
    milk_msg = await update.message.reply_text(milk_text, reply_markup=milk_keyboard())

    coffee_text = format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину")
    coffee_msg = await update.message.reply_text(coffee_text, reply_markup=coffee_keyboard())

    # Запомним сообщения (пригодится, если захочешь обновлять их из команд)
    context.application.bot_data["chat_id"] = update.effective_chat.id
    context.application.bot_data["milk_msg_id"] = milk_msg.message_id
    context.application.bot_data["coffee_msg_id"] = coffee_msg.message_id

async def add_milk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    if user.id not in [p["id"] for p in data["milk_queue"]]:
        data["milk_queue"].append({
            "id": user.id,
            "mention": mention(user),
            "username": f"@{user.username}" if user.username else ""
        })
        save_data(data)
        await update.message.reply_text("✅ Вы добавлены в очередь на молоко.")
    else:
        await update.message.reply_text("Вы уже в очереди на молоко.")

async def add_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    if user.id not in [p["id"] for p in data["coffee_queue"]]:
        data["coffee_queue"].append({
            "id": user.id,
            "mention": mention(user),
            "username": f"@{user.username}" if user.username else ""
        })
        save_data(data)
        await update.message.reply_text("✅ Вы добавлены в очередь на кофемашину.")
    else:
        await update.message.reply_text("Вы уже в очереди на кофемашину.")

# === Обработка кнопок ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_data()

    # Подстрахуемся: если у нажавшего нет username — попросим его установить
    if not query.from_user.username:
        await query.answer("У вас не установлен @username в Telegram. Задайте его в настройках профиля.", show_alert=True)
        return

    if query.data == "milk_done":
        if not data["milk_queue"]:
            await query.answer("Очередь пуста.")
            return

        current = data["milk_queue"][data["milk_index"]]
        # Разрешаем клик только текущему по username
        if query.from_user.username != current["username"].lstrip("@"):
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return

        done_mention = current["mention"]
        data["milk_index"] = (data["milk_index"] + 1) % len(data["milk_queue"])
        next_mention = data["milk_queue"][data["milk_index"]]["mention"]
        save_data(data)

        new_text = (
            f"✅ {done_mention} купил(а) молоко.\n"
            f"Следующий: {next_mention}\n\n"
            + format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко")
        )
        await query.edit_message_text(new_text, reply_markup=milk_keyboard())

    elif query.data == "coffee_done":
        if not data["coffee_queue"]:
            await query.answer("Очередь пуста.")
            return

        current = data["coffee_queue"][data["coffee_index"]]
        if query.from_user.username != current["username"].lstrip("@"):
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return

        done_mention = current["mention"]
        data["coffee_index"] = (data["coffee_index"] + 1) % len(data["coffee_queue"])
        next_mention = data["coffee_queue"][data["coffee_index"]]["mention"]
        save_data(data)

        new_text = (
            f"✅ {done_mention} почистил(а) кофемашину.\n"
            f"Следующий: {next_mention}\n\n"
            + format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину")
        )
        await query.edit_message_text(new_text, reply_markup=coffee_keyboard())

    await query.answer()

# === Запуск через вебхуки ===
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addmilk", add_milk))
    app.add_handler(CommandHandler("addcoffee", add_coffee))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Поднимаем встроенный веб-сервер и регистрируем вебхук
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,                          # секретный путь = ваш токен
        webhook_url=f"{BASE_URL}/{TOKEN}",       # Telegram будет слать апдейты сюда
    )

if __name__ == "__main__":
    main()
