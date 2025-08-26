import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
PORT = int(os.getenv("PORT", 10000))
DATA_FILE = "queues.json"


# ===== Работа с данными =====
def load_all():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}

def save_all(all_data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

def get_chat_data(chat_id):
    all_data = load_all()
    cid = str(chat_id)
    if cid not in all_data:
        all_data[cid] = {
            "milk_queue": [],
            "coffee_queue": [],
            "milk_index": 0,
            "coffee_index": 0,
            "milk_msg_id": None,
            "coffee_msg_id": None
        }
        save_all(all_data)
    return all_data[cid]

def update_chat_data(chat_id, chat_data):
    all_data = load_all()
    all_data[str(chat_id)] = chat_data
    save_all(all_data)


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


# ===== Основные команды =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = get_chat_data(chat_id)

    milk_text = format_queue(chat_data["milk_queue"], chat_data["milk_index"], "🥛 Очередь на молоко")
    coffee_text = format_queue(chat_data["coffee_queue"], chat_data["coffee_index"], "☕ Очередь на кофемашину")

    if chat_data["milk_msg_id"]:
        await context.bot.edit_message_text(milk_text, chat_id=chat_id,
                                            message_id=chat_data["milk_msg_id"], reply_markup=milk_keyboard())
    else:
        msg = await update.message.reply_text(milk_text, reply_markup=milk_keyboard())
        chat_data["milk_msg_id"] = msg.message_id

    if chat_data["coffee_msg_id"]:
        await context.bot.edit_message_text(coffee_text, chat_id=chat_id,
                                            message_id=chat_data["coffee_msg_id"], reply_markup=coffee_keyboard())
    else:
        msg = await update.message.reply_text(coffee_text, reply_markup=coffee_keyboard())
        chat_data["coffee_msg_id"] = msg.message_id

    update_chat_data(chat_id, chat_data)


async def add_milk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = get_chat_data(chat_id)
    user = update.effective_user

    if user.id not in [p["id"] for p in chat_data["milk_queue"]]:
        chat_data["milk_queue"].append({"id": user.id, "mention": mention(user)})
        update_chat_data(chat_id, chat_data)
        await update.message.reply_text("✅ Вы добавлены в очередь на молоко.")
        await refresh_messages(context, chat_id, chat_data)
    else:
        await update.message.reply_text("Вы уже в очереди на молоко.")


async def add_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_data = get_chat_data(chat_id)
    user = update.effective_user

    if user.id not in [p["id"] for p in chat_data["coffee_queue"]]:
        chat_data["coffee_queue"].append({"id": user.id, "mention": mention(user)})
        update_chat_data(chat_id, chat_data)
        await update.message.reply_text("✅ Вы добавлены в очередь на кофемашину.")
        await refresh_messages(context, chat_id, chat_data)
    else:
        await update.message.reply_text("Вы уже в очереди на кофемашину.")


# ===== Обновление двух сообщений =====
async def refresh_messages(context, chat_id, chat_data):
    milk_text = format_queue(chat_data["milk_queue"], chat_data["milk_index"], "🥛 Очередь на молоко")
    coffee_text = format_queue(chat_data["coffee_queue"], chat_data["coffee_index"], "☕ Очередь на кофемашину")

    if chat_data["milk_msg_id"]:
        await context.bot.edit_message_text(milk_text, chat_id=chat_id,
                                            message_id=chat_data["milk_msg_id"], reply_markup=milk_keyboard())
    if chat_data["coffee_msg_id"]:
        await context.bot.edit_message_text(coffee_text, chat_id=chat_id,
                                            message_id=chat_data["coffee_msg_id"], reply_markup=coffee_keyboard())


# ===== Обработка кнопок =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat.id
    chat_data = get_chat_data(chat_id)

    if query.data == "milk_done":
        if not chat_data["milk_queue"]:
            await query.answer("Очередь пуста.")
            return
        current = chat_data["milk_queue"][chat_data["milk_index"]]
        if query.from_user.id != current["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return

        chat_data["milk_index"] = (chat_data["milk_index"] + 1) % len(chat_data["milk_queue"])
        update_chat_data(chat_id, chat_data)

        next_user = chat_data["milk_queue"][chat_data["milk_index"]]["mention"]
        milk_text = format_queue(chat_data["milk_queue"], chat_data["milk_index"], "🥛 Очередь на молоко") \
                    + f"\n\n➡️ Сейчас: {next_user}"
        await context.bot.edit_message_text(milk_text, chat_id=chat_id,
                                            message_id=chat_data["milk_msg_id"], reply_markup=milk_keyboard())

    elif query.data == "coffee_done":
        if not chat_data["coffee_queue"]:
            await query.answer("Очередь пуста.")
            return
        current = chat_data["coffee_queue"][chat_data["coffee_index"]]
        if query.from_user.id != current["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return

        chat_data["coffee_index"] = (chat_data["coffee_index"] + 1) % len(chat_data["coffee_queue"])
        update_chat_data(chat_id, chat_data)

        next_user = chat_data["coffee_queue"][chat_data["coffee_index"]]["mention"]
        coffee_text = format_queue(chat_data["coffee_queue"], chat_data["coffee_index"], "☕ Очередь на кофемашину") \
                      + f"\n\n➡️ Сейчас: {next_user}"
        await context.bot.edit_message_text(coffee_text, chat_id=chat_id,
