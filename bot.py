import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
PORT = int(os.getenv("PORT", 10000))
DATA_FILE = "queues.json"

# ===== Работа с данными =====
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_chat_data(chat_id):
    data = load_data()
    if str(chat_id) not in data:
        data[str(chat_id)] = {
            "milk_queue": [], "coffee_queue": [],
            "milk_index": 0, "coffee_index": 0,
            "milk_msg_id": None, "coffee_msg_id": None
        }
        save_data(data)
    return data

def update_chat_data(chat_id, chat_data):
    data = load_data()
    data[str(chat_id)] = chat_data
    save_data(data)

# ===== Вспомогательные =====
def mention(user):
    return f"@{user.username}" if user.username else user.first_name

def format_queue(queue, index, title):
    if not queue:
        return f"{title}\n— очередь пуста."
    lines = [title]
    for offset in range(len(queue)):
        i = (index + offset) % len(queue)
        marker = "→ сейчас" if offset == 0 else ""
        lines.append(f"{offset+1}. {queue[i]['mention']} {marker}".rstrip())
    return "\n".join(lines)

def milk_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Купил(а) 🥛", callback_data="milk_done")]])

def coffee_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Почистил(а) ☕", callback_data="coffee_done")]])

# ===== Команды =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)

    milk_text = format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко")
    coffee_text = format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину")

    if data["milk_msg_id"]:
        await context.bot.edit_message_text(milk_text, chat_id=chat_id, message_id=data["milk_msg_id"],
                                            reply_markup=milk_keyboard())
    else:
        msg = await update.message.reply_text(milk_text, reply_markup=milk_keyboard())
        data["milk_msg_id"] = msg.message_id

    if data["coffee_msg_id"]:
        await context.bot.edit_message_text(coffee_text, chat_id=chat_id, message_id=data["coffee_msg_id"],
                                            reply_markup=coffee_keyboard())
    else:
        msg = await update.message.reply_text(coffee_text, reply_markup=coffee_keyboard())
        data["coffee_msg_id"] = msg.message_id

    update_chat_data(chat_id, data)

async def add_milk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    user = update.effective_user
    if user.id not in [p["id"] for p in data["milk_queue"]]:
        data["milk_queue"].append({
            "id": user.id,
            "mention": mention(user),
            "username": f"@{user.username}" if user.username else ""
        })
        update_chat_data(chat_id, data)
        await update.message.reply_text("✅ Вы добавлены в очередь на молоко.")
    else:
        await update.message.reply_text("Вы уже в очереди на молоко.")

async def add_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    user = update.effective_user
    if user.id not in [p["id"] for p in data["coffee_queue"]]:
        data["coffee_queue"].append({
            "id": user.id,
            "mention": mention(user),
            "username": f"@{user.username}" if user.username else ""
        })
        update_chat_data(chat_id, data)
        await update.message.reply_text("✅ Вы добавлены в очередь на кофемашину.")
    else:
        await update.message.reply_text("Вы уже в очереди на кофемашину.")

# ===== Обработка кнопок =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat.id
    data = get_chat_data(chat_id)

    if query.data == "milk_done":
        if not data["milk_queue"]:
            await query.answer("Очередь пуста.")
            return
        current = data["milk_queue"][data["milk_index"]]
        if query.from_user.id != current["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return
        data["milk_index"] = (data["milk_index"] + 1) % len(data["milk_queue"])
        update_chat_data(chat_id, data)
        next_user = data["milk_queue"][data["milk_index"]]["mention"]
        milk_text = format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко") + f"\n\n➡️ Сейчас: {next_user}"
        await context.bot.edit_message_text(milk_text, chat_id=chat_id, message_id=data["milk_msg_id"],
                                            reply_markup=milk_keyboard())

    elif query.data == "coffee_done":
        if not data["coffee_queue"]:
            await query.answer("Очередь пуста.")
            return
        current = data["coffee_queue"][data["coffee_index"]]
        if query.from_user.id != current["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return
        data["coffee_index"] = (data["coffee_index"] + 1) % len(data["coffee_queue"])
        update_chat_data(chat_id, data)
        next_user = data["coffee_queue"][data["coffee_index"]]["mention"]
        coffee_text = format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину") + f"\n\n➡️ Сейчас: {next_user}"
        await context.bot.edit_message_text(coffee_text, chat_id=chat_id, message_id=data["coffee_msg_id"],
                                            reply_markup=coffee_keyboard())

    await query.answer()

# ===== Запуск =====
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addmilk", add_milk))
    app.add_handler(CommandHandler("addcoffee", add_coffee))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_webhook(listen="0.0.0.0", port=PORT,
                    url_path=TOKEN, webhook_url=f"{BASE_URL}/{TOKEN}")

if __name__ == "__main__":
    main()
