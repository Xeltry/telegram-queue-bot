import os, json, random, logging, asyncio
import pytz
from fastapi import FastAPI, Request, HTTPException
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# ====== Логирование ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Окружение ======
TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
if not TOKEN or not BASE_URL:
    raise RuntimeError("Не заданы TELEGRAM_BOT_TOKEN или BASE_URL")

# ====== Константы ======
DATA_FILE, PHRASES_FILE = "queues.json", "phrases.json"
MINSK_TZ  = pytz.timezone("Europe/Minsk")
file_lock = asyncio.Lock()

# ====== Главное меню (ReplyKeyboardMarkup) ======
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["Купил(а) 🥛", "Почистил(а) ☕"]],
    resize_keyboard=True,
    one_time_keyboard=False,
    input_field_placeholder="Выберите действие…"
)

def milk_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Купил(а) 🥛", callback_data="milk_done")]])

def coffee_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Почистил(а) ☕", callback_data="coffee_done")]])

# ====== Фразы ======
with open(PHRASES_FILE, encoding="utf-8") as f:
    phrases = json.load(f)

# ====== Конфиг очередей ======
QUEUE_CONFIG = {
    "milk": {
        "queue": "milk_queue", "msg_id": "milk_msg_id", "index": "milk_index",
        "title": "🥛 очередь", "keyboard": milk_keyboard,
        "phrases": phrases.get("milk_phrases", [])
    },
    "coffee": {
        "queue": "coffee_queue", "msg_id": "coffee_msg_id", "index": "coffee_index",
        "title": "☕ очередь", "keyboard": coffee_keyboard,
        "phrases": phrases.get("coffee_phrases", [])
    }
}

# ====== Администраторы ======
ADMINS = [847100761]  # замени на свой Telegram user_id

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# ====== Работа с файлами ======
def _sync_load():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("JSON повреждён")
    return {}

def _sync_save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def load():
    return await asyncio.to_thread(_sync_load)

async def save(d):
    await asyncio.to_thread(_sync_save, d)

async def get_chat(chat_id):
    async with file_lock:
        all_data = await load()
        cid = str(chat_id)
        if cid not in all_data:
            all_data[cid] = {c["queue"]: [] for c in QUEUE_CONFIG.values()}
            for k in ["milk_index", "coffee_index", "milk_msg_id", "coffee_msg_id"]:
                all_data[cid][k] = 0 if "index" in k else None
            await save(all_data)
        return all_data[cid]

async def update_chat(chat_id, data):
    async with file_lock:
        all_data = await load()
        all_data[str(chat_id)] = data
        await save(all_data)

# ====== Утилиты ======
async def safe_edit(bot, chat_id, msg_id, text, kb):
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "not modified" not in str(e):
            logger.error("safe_edit: %s", e)

def format_queue(queue, index, title):
    if not queue:
        return f"<b>{title}</b>\n— очередь пуста."
    lines = [f"<b>{title}</b> ({len(queue)} чел.)\n"]
    for off in range(len(queue)):
        i = (index + off) % len(queue)
        user = queue[i]["mention"]
        if off == 0:
            lines.append(f"👉 <b>{user}</b> — сейчас")
        else:
            lines.append(f"{off+1}. {user}")
    return "\n".join(lines)

# ====== Пользовательские действия ======
async def start(update, context):
    await update.message.reply_text(
        "Привет! Это бот для очередей 🥛☕\n\nВыберите действие кнопкой ниже:",
        reply_markup=MAIN_KEYBOARD
    )

async def help_cmd(update, context):
    help_text = (
        "<b>Доступные команды:</b>\n\n"
        "— /start – запустить бота и показать меню\n"
        "— /help – показать это сообщение\n\n"
        "— /addmilk – добавить себя в 🥛 очередь\n"
        "— /addcoffee – добавить себя в ☕ очередь\n"
        "— /removemilk – выйти из 🥛 очереди\n"
        "— /removecoffee – выйти из ☕ очереди\n"
        "— /milk – показать 🥛 очередь\n"
        "— /coffee – показать ☕ очередь\n\n"
        "<b>Кнопки внизу:</b>\n"
        "• «Купил(а) 🥛» – двигает очередь молока вперёд (только если ваша очередь)\n"
        "• «Почистил(а) ☕» – двигает очередь кофемашины вперёд (только если ваша очередь)\n\n"
        "<b>Админ‑команды:</b>\n"
        "— /adminaddmilk @username или user_id – добавить человека в 🥛 очередь\n"
        "— /adminaddcoffee @username или user_id – добавить человека в ☕ очередь\n"
        "— /adminremovemilk @username или user_id – удалить человека из 🥛 очереди\n"
        "— /adminremovecoffee @username или user_id – удалить человека из ☕ очереди\n"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=MAIN_KEYBOARD)

async def add_to(update, context, kind):
    cfg, chat_id, user = QUEUE_CONFIG[kind], update.effective_chat.id, update.effective_user
    data = await get_chat(chat_id)

    if user.id not in [p["id"] for p in data[cfg["queue"]]]:
        mention = f"@{user.username}" if user.username else user.first_name
        data[cfg["queue"]].append({"id": int(user.id), "mention": mention})
        await update_chat(chat_id, data)

        if data[cfg["msg_id"]]:
            await safe_edit(
                context.bot, chat_id, data[cfg["msg_id"]],
                format_queue(data[cfg["queue"]], data[cfg["index"]], cfg["title"]),
                cfg["keyboard"]()
            )

async def remove_from(update, context, kind):
    cfg, chat_id, user = QUEUE_CONFIG[kind], update.effective_chat.id, update.effective_user
    data = await get_chat(chat_id)

    before = len(data[cfg["queue"]])
    data[cfg["queue"]] = [p for p in data[cfg["queue"]] if p["id"] != user.id]

    if len(data[cfg["queue"]]) < before:
        await update_chat(chat_id, data)

        if data[cfg["msg_id"]]:
            await safe_edit(
                context.bot, chat_id, data[cfg["msg_id"]],
                format_queue(data[cfg["queue"]], data[cfg["index"]], cfg["title"]),
                cfg["keyboard"]()
            )

async def show_queue(update, context, kind):
    cfg, chat_id = QUEUE_CONFIG[kind], update.effective_chat.id
    data = await get_chat(chat_id)
    msg = await update.message.reply_text(
        format_queue(data[cfg["queue"]], data[cfg["index"]], cfg["title"]),
        reply_markup=MAIN_KEYBOARD,
        parse_mode=ParseMode.HTML
    )
    data[cfg["msg_id"]] = msg.message_id
    await update_chat(chat_id, data)

async def advance_queue_from_text(update, context, kind):
    cfg = QUEUE_CONFIG[kind]
    chat_id = update.effective_chat.id
    user = update.effective_user

    data = await get_chat(chat_id)
    if not data[cfg["queue"]]:
        return
    current = data[cfg["queue"]][data[cfg["index"]]]
    if user.id != current["id"]:
        return

    # сдвигаем очередь
    data[cfg["index"]] = (data[cfg["index"]] + 1) % len(data[cfg["queue"]])
    await update_chat(chat_id, data)

    # обновляем сообщение с очередью
    if data[cfg["msg_id"]]:
        await safe_edit(
            context.bot, chat_id, data[cfg["msg_id"]],
            format_queue(data[cfg["queue"]], data[cfg["index"]], cfg["title"]),
            cfg["keyboard"]()
        )

    # отправляем только фразу из списка
    next_user = data[cfg["queue"]][data[cfg["index"]]]
    doer = f"@{user.username}" if user.username else user.first_name
    phrase = random.choice(cfg["phrases"]) if cfg["phrases"] else "{doer} сделал дело, теперь {next}!"
    phrase = phrase.format(doer=doer, next=f"<b>{next_user['mention']}</b>")
    await context.bot.send_message(chat_id, phrase, parse_mode=ParseMode.HTML, reply_markup=MAIN_KEYBOARD)

async def milk_done_from_button(update, context):
    await advance_queue_from_text(update, context, "milk")

async def coffee_done_from_button(update, context):
    await advance_queue_from_text(update, context, "coffee")

# ====== Админ-команды ======
async def admin_add(update, context, kind):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return

    target = context.args[0]
    chat_id = update.effective_chat.id
    data = await get_chat(chat_id)

    try:
        if target.startswith("@"):
            mention = target
            user_id = target.lower()
        else:
            user_id = int(target)
            mention = f"id:{user_id}"
    except Exception:
        return

    if int(user_id) not in [p["id"] for p in data[QUEUE_CONFIG[kind]["queue"]]]:
        data[QUEUE_CONFIG[kind]["queue"]].append({"id": int(user_id), "mention": mention})
        await update_chat(chat_id, data)
        if data[QUEUE_CONFIG[kind]["msg_id"]]:
            await safe_edit(
                context.bot, chat_id, data[QUEUE_CONFIG[kind]["msg_id"]],
                format_queue(data[QUEUE_CONFIG[kind]["queue"]], data[QUEUE_CONFIG[kind]["index"]], QUEUE_CONFIG[kind]["title"]),
                QUEUE_CONFIG[kind]["keyboard"]()
            )

async def admin_remove(update, context, kind):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return

    target = context.args[0]
    chat_id = update.effective_chat.id
    data = await get_chat(chat_id)

    before = len(data[QUEUE_CONFIG[kind]["queue"]])
    data[QUEUE_CONFIG[kind]["queue"]] = [
        p for p in data[QUEUE_CONFIG[kind]["queue"]]
        if p["mention"] != target and str(p["id"]) != target
    ]

    if len(data[QUEUE_CONFIG[kind]["queue"]]) < before:
        await update_chat(chat_id, data)
        if data[QUEUE_CONFIG[kind]["msg_id"]]:
            await safe_edit(
                context.bot, chat_id, data[QUEUE_CONFIG[kind]["msg_id"]],
                format_queue(data[QUEUE_CONFIG[kind]["queue"]], data[QUEUE_CONFIG[kind]["index"]], QUEUE_CONFIG[kind]["title"]),
                QUEUE_CONFIG[kind]["keyboard"]()
            )

# ====== FastAPI + Telegram Application ======
app = FastAPI()
application = Application.builder().token(TOKEN).updater(None).build()

# Пользовательские команды
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("addmilk", lambda u, c: add_to(u, c, "milk")))
application.add_handler(CommandHandler("addcoffee", lambda u, c: add_to(u, c, "coffee")))
application.add_handler(CommandHandler("removemilk", lambda u, c: remove_from(u, c, "milk")))
application.add_handler(CommandHandler("removecoffee", lambda u, c: remove_from(u, c, "coffee")))
application.add_handler(CommandHandler("milk", lambda u, c: show_queue(u, c, "milk")))
application.add_handler(CommandHandler("coffee", lambda u, c: show_queue(u, c, "coffee")))

# Админ-команды
application.add_handler(CommandHandler("adminaddmilk", lambda u, c: admin_add(u, c, "milk")))
application.add_handler(CommandHandler("adminaddcoffee", lambda u, c: admin_add(u, c, "coffee")))
application.add_handler(CommandHandler("adminremovemilk", lambda u, c: admin_remove(u, c, "milk")))
application.add_handler(CommandHandler("adminremovecoffee", lambda u, c: admin_remove(u, c, "coffee")))

# Callback и текстовые кнопки
CALLBACK_MAP = {"milk_done": "milk", "coffee_done": "coffee"}
TEXT_MAP = {"Купил(а) 🥛": milk_done_from_button, "Почистил(а) ☕": coffee_done_from_button}

async def button_handler(update, context):
    kind = CALLBACK_MAP.get(update.callback_query.data)
    if kind:
        await advance_queue_from_text(update, context, kind)
        await update.callback_query.answer()

async def text_button_handler(update, context):
    handler = TEXT_MAP.get(update.message.text)
    if handler:
        await handler(update, context)

application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_button_handler))

# ====== Webhook ======
@app.on_event("startup")
async def on_startup():
    await application.initialize()
    await application.start()
    webhook_url = f"{BASE_URL}/webhook"
    await application.bot.set_webhook(webhook_url)
    logger.info("Webhook установлен: %s", webhook_url)

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()

@app.post("/webhook")
async def webhook(req: Request):
    try:
        payload = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    update = Update.de_json(payload, application.bot)
    await application.process_update(update)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok"}

# ====== Запуск локально ======
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
