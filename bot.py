import os
import json
import logging
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
PORT = int(os.getenv("PORT", 10000))
DATA_FILE = "queues.json"

if not TOKEN or not BASE_URL:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN и BASE_URL должны быть заданы в переменных окружения!")

# === РАБОТА С ДАННЫМИ ===
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("⚠️ Файл данных повреждён, создаю новый.")
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
    for offset in range(len(queue)):
        i = (index + offset) % len(queue)
        marker = "→ сейчас" if offset == 0 else ""
        lines.append(f"{offset+1}. {queue[i]['mention']} {marker}".rstrip())
    return "\n".join(lines)

def milk_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Купил(а) 🥛", callback_data="milk_done")]])

def coffee_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Почистил(а) ☕", callback_data="coffee_done")]])

# === ОБРАБОТЧИКИ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start от {update.effective_user.id}")
    await update.message.reply_text("Привет! Это бот очередей. Вот текущая ситуация:")

    data = load_data()
    milk_text = format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко")
    coffee_text = format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину")

    await update.message.reply_text(milk_text, reply_markup=milk_keyboard())
    await update.message.reply_text(coffee_text, reply_markup=coffee_keyboard())

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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()

    if query.data == "milk_done":
        if not data["milk_queue"]:
            await query.answer("Очередь пуста.")
            return
        current = data["milk_queue"][data["milk_index"]]
        if query.from_user.id != current["id"]:
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
        if query.from_user.id != current["id"]:
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

# === УСТАНОВКА WEBHOOK ===
async def set_webhook():
    webhook_url = f"{BASE_URL}/{TOKEN}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": webhook_url}
        )
    if resp.status_code == 200 and resp.json().get("ok"):
        logger.info(f"✅ Webhook установлен: {webhook_url}")
    else:
        logger.error(f"❌ Ошибка установки webhook: {resp.text}")

# === ЗАПУСК ===
async def main():
    await set_webhook()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addmilk", add_milk))
    app.add_handler(CommandHandler("addcoffee", add_coffee))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Запуск в режиме webhook")
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{BASE_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    asyncio.run(main())
