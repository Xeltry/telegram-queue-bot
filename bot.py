import os
import json
import random
import logging
import asyncio
from datetime import time

import pytz
from fastapi import FastAPI, Request, HTTPException
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ====== Логирование ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Проверка окружения ======
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
if not TOKEN or not BASE_URL:
    raise RuntimeError("Не заданы TELEGRAM_BOT_TOKEN или BASE_URL")

# ====== Конфигурация ======
DATA_FILE     = "queues.json"
PHRASES_FILE  = "phrases.json"
MINSK_TZ      = pytz.timezone("Europe/Minsk")
file_lock     = asyncio.Lock()

# ====== Постоянная клавиатура ======
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["Купил кофе", "Почистил кофемашину"]],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# ====== Загрузка фраз ======
with open(PHRASES_FILE, encoding="utf-8") as f:
    phrases = json.load(f)
milk_phrases   = phrases.get("milk_phrases", [])
coffee_phrases = phrases.get("coffee_phrases", [])

# ====== Файловый ввод-вывод через to_thread ======
def _sync_load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Ошибка чтения JSON, создаём новый файл")
    return {}

def _sync_save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def load_data() -> dict:
    return await asyncio.to_thread(_sync_load_data)

async def save_data(data: dict) -> None:
    await asyncio.to_thread(_sync_save_data, data)

async def get_chat_data(chat_id: int) -> dict:
    async with file_lock:
        all_data = await load_data()
        cid = str(chat_id)
        if cid not in all_data:
            all_data[cid] = {
                "milk_queue": [], "coffee_queue": [],
                "milk_index": 0,  "coffee_index": 0,
                "milk_msg_id": None, "coffee_msg_id": None,
            }
            await save_data(all_data)
        return all_data[cid]

async def update_chat_data(chat_id: int, chat_data: dict) -> None:
    async with file_lock:
        all_data = await load_data()
        all_data[str(chat_id)] = chat_data
        await save_data(all_data)

# ====== Утилиты ======
def milk_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Купил(а) 🥛", callback_data="milk_done")]])

def coffee_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Почистил(а) ☕", callback_data="coffee_done")]])

async def safe_edit(bot, chat_id: int, msg_id: int, new_text: str, keyboard: InlineKeyboardMarkup):
    try:
        await bot.edit_message_text(
            text=new_text,
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        logger.error("safe_edit error: %s", e)

def format_queue(queue: list, index: int, title: str) -> str:
    if not queue:
        return f"{title}\n— очередь пуста."
    lines = [title]
    for offset in range(len(queue)):
        i      = (index + offset) % len(queue)
        marker = "→ сейчас" if offset == 0 else ""
        lines.append(f"{offset+1}. {queue[i]['mention']} {marker}".rstrip())
    return "\n".join(lines)

# ====== Общие хендлеры для очередей ======
async def add_to_queue(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       queue_name: str, msg_key: str, index_key: str,
                       title: str, keyboard_func):
    chat_id = update.effective_chat.id
    data    = await get_chat_data(chat_id)
    user    = update.effective_user

    if user.id not in [p["id"] for p in data[queue_name]]:
        mention = f"@{user.username}" if user.username else user.first_name
        data[queue_name].append({"id": user.id, "mention": mention})
        await update_chat_data(chat_id, data)

        await update.message.reply_text(
            f"✅ Вы добавлены в {title.lower()}",
            reply_markup=MAIN_KEYBOARD
        )
        if data[msg_key]:
            await safe_edit(context.bot, chat_id, data[msg_key],
                            format_queue(data[queue_name], data[index_key], title),
                            keyboard_func())
    else:
        await update.message.reply_text(
            f"Вы уже в {title.lower()}",
            reply_markup=MAIN_KEYBOARD
        )

async def remove_from_queue(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            queue_name: str, msg_key: str, index_key: str,
                            title: str, keyboard_func):
    chat_id = update.effective_chat.id
    data    = await get_chat_data(chat_id)
    user    = update.effective_user
    before  = len(data[queue_name])

    data[queue_name] = [p for p in data[queue_name] if p["id"] != user.id]
    if len(data[queue_name]) < before:
        await update_chat_data(chat_id, data)
        await update.message.reply_text(
            f"❌ Вы удалены из {title.lower()}",
            reply_markup=MAIN_KEYBOARD
        )
        if data[msg_key]:
            await safe_edit(context.bot, chat_id, data[msg_key],
                            format_queue(data[queue_name], data[index_key], title),
                            keyboard_func())
    else:
        await update.message.reply_text(
            f"Вас нет в {title.lower()}",
            reply_markup=MAIN_KEYBOARD
        )

async def handle_done(query, context: ContextTypes.DEFAULT_TYPE,
                      queue_name: str, msg_key: str, index_key: str,
                      title: str, keyboard_func, phrases: list):
    chat_id = query.message.chat.id
    data    = await get_chat_data(chat_id)

    if not data[queue_name]:
        await query.answer("Очередь пуста.")
        return

    current = data[queue_name][data[index_key]]
    if query.from_user.id != current["id"]:
        await query.answer("Сейчас не ваша очередь!", show_alert=True)
        return

    data[index_key] = (data[index_key] + 1) % len(data[queue_name])
    await update_chat_data(chat_id, data)

    if data[msg_key]:
        await safe_edit(context.bot, chat_id, data[msg_key],
                        format_queue(data[queue_name], data[index_key], title),
                        keyboard_func())

    next_user = data[queue_name][data[index_key]]
    doer      = f"@{query.from_user.username}" if query.from_user.username else query.from_user.first_name
    phrase    = random.choice(phrases).format(doer=doer, next=next_user["mention"])
    await context.bot.send_message(
        chat_id, phrase,
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KEYBOARD
    )
    await query.answer()

# ====== Хендлеры команд ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Выберите действие ниже:",
        reply_markup=MAIN_KEYBOARD
    )

async def show_milk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data    = await get_chat_data(chat_id)
    text    = format_queue(data["milk_queue"], data["milk_index"], "🥛 очередь на молоко")
    msg     = await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)
    data["milk_msg_id"] = msg.message_id
    await update_chat_data(chat_id, data)

async def show_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data    = await get_chat_data(chat_id)
    text    = format_queue(data["coffee_queue"], data["coffee_index"], "☕ очередь на кофемашину")
    msg     = await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)
    data["coffee_msg_id"] = msg.message_id
    await update_chat_data(chat_id, data)

async def add_milk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_to_queue(update, context,
                       "milk_queue", "milk_msg_id", "milk_index",
                       "🥛 очередь на молоко", milk_keyboard)

async def add_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_to_queue(update, context,
                       "coffee_queue", "coffee_msg_id", "coffee_index",
                       "☕ очередь на кофемашину", coffee_keyboard)

async def remove_milk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await remove_from_queue(update, context,
                            "milk_queue", "milk_msg_id", "milk_index",
                            "🥛 очередь на молоко", milk_keyboard)

async def remove_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await remove_from_queue(update, context,
                            "coffee_queue", "coffee_msg_id", "coffee_index",
                            "☕ очередь на кофемашину", coffee_keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "/addmilk — встать в очередь на молоко\n"
        "/addcoffee — встать в очередь на кофе\n"
        "/removemilk — выйти из очереди на молоко\n"
        "/removecoffee — выйти из очереди на кофе\n"
        "/milk — показать очередь на молоко\n"
        "/coffee — показать очередь на кофе\n"
    )
    await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "milk_done":
        await handle_done(query, context,
                          "milk_queue", "milk_msg_id", "milk_index",
                          "🥛 очередь на молоко", milk_keyboard, milk_phrases)
    elif query.data == "coffee_done":
        await handle_done(query, context,
                          "coffee_queue", "coffee_msg_id", "coffee_index",
                          "☕ очередь на кофемашину", coffee_keyboard, coffee_phrases)

# ====== FastAPI + Webhook ======
app = FastAPI()
application = Application.builder().token(TOKEN).build()

for cmd, handler in [
    ("start", start),
    ("help",  help_command),
    ("addmilk", add_milk),
    ("addcoffee", add_coffee),
    ("removemilk", remove_milk),
    ("removecoffee", remove_coffee),
    ("milk", show_milk),
    ("coffee", show_coffee),
]:
    application.add_handler(CommandHandler(cmd, handler))

application.add_handler(CallbackQueryHandler(button_handler))

@app.on_event("startup")
async def on_startup():
    await application.initialize()
    await application.startup()
    await application.bot.set_webhook(f"{BASE_URL}/webhook")
    logger.info("Webhook установлен: %s/webhook", BASE_URL)

@app.on_event("shutdown")
async def on_shutdown():
    await application.shutdown()

@app.post("/webhook")
async def webhook(req: Request):
    try:
        payload = await req.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    update = Update.de_json(payload, application.bot)
    await application.process_update(update)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))


