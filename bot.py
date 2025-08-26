import os
import json
from datetime import time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
PORT = int(os.getenv("PORT", 10000))
DATA_FILE = "queues.json"

# ===== Настройки =====
MINSK_TZ = pytz.timezone("Europe/Minsk")
monday_wishes = [
    "🌞 Доброе утро! Пусть эта неделя будет лёгкой и продуктивной.",
    "💪 С понедельником! Новые цели — новые победы!",
    "🚀 Удачного старта недели и бодрого настроения!",
    "☕ Доброе утро! Пусть кофе бодрит, а идеи вдохновляют.",
    "📅 Отличного начала недели! Пусть она принесёт только хорошие новости.",
    "🌿 Спокойного и уверенного понедельника, пусть всё идёт по плану.",
    "✨ Новая неделя — новые возможности. Улыбнись и вперёд!"
]

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
    all_data = load_data()
    cid = str(chat_id)
    if cid not in all_data:
        all_data[cid] = {
            "milk_queue": [],
            "coffee_queue": [],
            "milk_index": 0,
            "coffee_index": 0,
            "milk_msg_id": None,
            "coffee_msg_id": None,
            "wish_index": 0
        }
        save_data(all_data)
    elif "wish_index" not in all_data[cid]:
        all_data[cid]["wish_index"] = 0
        save_data(all_data)
    return all_data[cid]

def update_chat_data(chat_id, chat_data):
    all_data = load_data()
    all_data[str(chat_id)] = chat_data
    save_data(all_data)

# ===== Вспомогательные =====
def milk_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Купил(а) 🥛", callback_data="milk_done")]])

def coffee_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Почистил(а) ☕", callback_data="coffee_done")]])

async def safe_edit(bot, chat_id, msg_id, new_text, keyboard):
    try:
        await bot.edit_message_text(
            new_text, chat_id=chat_id, message_id=msg_id,
            reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        else:
            raise

def format_queue(queue, index, title):
    if not queue:
        return f"{title}\n— очередь пуста."
    lines = [title]
    for offset in range(len(queue)):
        i = (index + offset) % len(queue)
        marker = "→ сейчас" if offset == 0 else ""
        lines.append(f"{offset+1}. {queue[i]['mention']} {marker}".rstrip())
    return "\n".join(lines)

# ===== Пожелания =====
async def monday_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    chat_data = get_chat_data(chat_id)
    idx = chat_data["wish_index"] % len(monday_wishes)
    message = monday_wishes[idx]
    chat_data["wish_index"] = (idx + 1) % len(monday_wishes)
    update_chat_data(chat_id, chat_data)
    await context.bot.send_message(chat_id=chat_id, text=message)

def schedule_weekly_wish(job_queue, chat_id):
    job_queue.run_daily(
        monday_job,
        time=time(hour=8, minute=0, tzinfo=MINSK_TZ),
        days=(0,),  # Monday
        chat_id=chat_id,
        name=f"monday_{chat_id}"
    )

# ===== Очереди =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)

    milk_text = format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко")
    coffee_text = format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину")

    if data["milk_msg_id"]:
        await safe_edit(context.bot, chat_id, data["milk_msg_id"], milk_text, milk_keyboard())
    else:
        msg = await update.message.reply_text(milk_text, reply_markup=milk_keyboard())
        data["milk_msg_id"] = msg.message_id

    if data["coffee_msg_id"]:
        await safe_edit(context.bot, chat_id, data["coffee_msg_id"], coffee_text, coffee_keyboard())
    else:
        msg = await update.message.reply_text(coffee_text, reply_markup=coffee_keyboard())
        data["coffee_msg_id"] = msg.message_id

    update_chat_data(chat_id, data)

    # Автоподписка на еженедельное пожелание
    schedule_weekly_wish(context.job_queue, chat_id)

    await update.message.reply_text("☀️ Пожелания на понедельник теперь будут приходить каждую неделю в 08:00.")

async def add_milk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    user = update.effective_user
    if user.id not in [p["id"] for p in data["milk_queue"]]:
        mention = f"@{user.username}" if user.username else user.first_name
        data["milk_queue"].append({"id": user.id, "mention": mention})
        update_chat_data(chat_id, data)
        await update.message.reply_text("✅ Вы добавлены в очередь на молоко.")
    else:
        await update.message.reply_text("Вы уже в очереди на молоко.")

async def add_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = get_chat_data(chat_id)
    user = update.effective_user
    if user.id not in [p["id"] for p in data["coffee_queue"]]:
        mention = f"@{user.username}" if user.username else user.first_name
        data["coffee_queue"].append({"id": user.id, "mention": mention})
        update_chat_data(chat_id, data)
        await update.message.reply_text("✅ Вы добавлены в очередь на кофемашину.")
    else:
        await update.message.reply_text("Вы уже в очереди на кофемашину.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat.id
    data = get_chat_data(chat_id)

    if query.data == "milk_done":
        if not data["milk_queue"]:
            await query.answer("Очередь пуста."); return
        if query.from_user.id != data["milk_queue"][data["milk_index"]]["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True); return

        data["milk_index"] = (data["milk_index"] + 1) % len(data["milk_queue"])
        update_chat_data(chat_id, data)
        await safe_edit(context.bot, chat_id, data["milk_msg_id"],
                        format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко"),
                        milk_keyboard())
        next_user = data["milk_queue"][data["milk_index"]]
        await context.bot.send_message(chat_id=chat_id,
                                       text=f"➡️ {next_user['mention']}, теперь ваша очередь на 🥛",
                                       parse_mode=ParseMode.HTML)

    elif query.data == "coffee_done":
        if not data["coffee_queue"]:
            await query.answer("Очередь пуста."); return
        if query.from_user.id != data["coffee_queue"][data["coffee_index"]]["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True); return

        data["coffee_index"] = (data["coffee_index"] + 1) % len(data["coffee_queue"])
        update_chat_data(chat_id, data)
        await safe_edit(context.bot,
