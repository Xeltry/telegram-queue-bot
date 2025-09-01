import os
import json
import random
from datetime import time
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

# ====== Конфигурация ======
TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL    = os.getenv("BASE_URL")
PORT        = int(os.getenv("PORT", 10000))
DATA_FILE   = "queues.json"
MINSK_TZ    = pytz.timezone("Europe/Minsk")

# ====== Фразы ======
monday_wishes = [
    "🌞 Доброе утро! Пусть эта неделя будет лёгкой и продуктивной.",
    "💪 С понедельником! Новые цели — новые победы!",
    "🚀 Удачного старта недели и бодрого настроения!",
    "☕ Доброе утро! Пусть кофе бодрит, а идеи вдохновляют.",
    "📅 Отличного начала недели! Пусть она принесёт только хорошие новости.",
    "🌿 Спокойного и уверенного понедельника, пусть всё идёт по плану.",
    "✨ Новая неделя — новые возможности. Улыбнись и вперёд!"
]

milk_phrases = [
    "🥛 Миссия молоко выполнена героем {doer}! Эстафета у {next}",
    "{doer} добыл молоко из туманных долин холодильника! ➡️ {next}, готовься",
    "Великий молочный квест закрыт благодаря {doer}. Следующий в бой — {next}",
    "🥛 {doer} спас утренний кофе! Теперь очередь у {next}",
    "Молочный фронт держит {doer}, а следующий — {next}",
    "Куплено молоко, {doer} — наш герой дня! На подходе {next}",
    "Холодильник пополнен, спасибо {doer}! Вперёд, {next}",
    "🥛 {doer} вернулся с добычей! {next}, готовься к своему походу",
    "{doer} пополнил стратегический запас молока. Теперь {next} на страже",
    "Молочная миссия завершена! Спасибо {doer}. {next}, твой выход",
    "🥛 {doer} сделал утро вкуснее. {next}, держи курс на магазин",
    "Молоко на месте — {doer} постарался. {next}, эстафета у тебя"
]

coffee_phrases = [
    "☕ {doer} приручил дикого зверя по имени «Кофемашина»! Теперь ход за {next}",
    "{doer} очистил кофейный портал — теперь он сияет. ➡️ {next}, твой выход",
    "Легенда гласит, что {doer} оставил кофемашину в идеальном состоянии. Следующий герой — {next}",
    "☕ Кофейный храм снова в порядке благодаря {doer}. {next}, принимай эстафету",
    "{doer} победил кофейного монстра! Теперь {next} на линии фронта",
    "Чаши блестят — {doer} сделал своё дело. Готовься, {next}",
    "Запах чистоты витает! Спасибо {doer}. {next}, теперь твой черёд",
    "☕ {doer} вернул кофемашине вторую жизнь. {next}, готовься к смене",
    "Кофейный дух умиротворён благодаря {doer}. {next}, твой ход",
    "☕ {doer} очистил путь к идеальному эспрессо. {next}, держи ритм",
    "Кофемашина сияет, а {doer} — герой дня. {next}, на старт",
    "☕ {doer} завершил ритуал чистки. {next}, готовься к своей миссии"
]

# ====== Работа с данными ======
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}

def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_chat_data(chat_id: int) -> dict:
    all_data = load_data()
    cid = str(chat_id)
    if cid not in all_data:
        all_data[cid] = {
            "milk_queue":   [],
            "coffee_queue": [],
            "milk_index":   0,
            "coffee_index": 0,
            "milk_msg_id":  None,
            "coffee_msg_id": None,
            "wish_index":   0
        }
        save_data(all_data)
    return all_data[cid]

def update_chat_data(chat_id: int, chat_data: dict) -> None:
    all_data = load_data()
    all_data[str(chat_id)] = chat_data
    save_data(all_data)

# ====== Утилиты ======
def milk_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Купил(а) 🥛", callback_data="milk_done")]])

def coffee_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Почистил(а) ☕", callback_data="coffee_done")]])

async def safe_edit(
    bot,
    chat_id: int,
    msg_id: int,
    new_text: str,
    keyboard: InlineKeyboardMarkup
) -> None:
    try:
        await bot.edit_message_text(
            new_text,
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise

def format_queue(queue: list, index: int, title: str) -> str:
    if not queue:
        return f"{title}\n— очередь пуста."
    lines = [title]
    for offset in range(len(queue)):
        i = (index + offset) % len(queue)
        marker = "→ сейчас" if offset == 0 else ""
        lines.append(f"{offset+1}. {queue[i]['mention']} {marker}".rstrip())
    return "\n".join(lines)

# ====== Еженедельные пожелания ======
async def monday_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id   = context.job.chat_id
    chat_data = get_chat_data(chat_id)

    idx = chat_data["wish_index"] % len(monday_wishes)
    message = monday_wishes[idx]
    chat_data["wish_index"] = (idx + 1) % len(monday_wishes)
    update_chat_data(chat_id, chat_data)

    await context.bot.send_message(chat_id=chat_id, text=message)

def schedule_weekly_wish(job_queue, chat_id: int) -> None:
    job_queue.run_daily(
        monday_job,
        time=time(hour=8, minute=0, tzinfo=MINSK_TZ),
        days=(0,),  # 0 = понедельник
        chat_id=chat_id,
        name=f"monday_{chat_id}"
    )

# ====== Хендлеры очередей ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    data    = get_chat_data(chat_id)

    milk_text   = format_queue(data["milk_queue"],   data["milk_index"],   "🥛 Очередь на молоко")
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

    schedule_weekly_wish(context.job_queue, chat_id)
    await update.message.reply_text("☀️ Пожелания на понедельник активированы (08:00, Минск).")

async def add_milk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    data    = get_chat_data(chat_id)
    user    = update.effective_user

    if user.id not in [p["id"] for p in data["milk_queue"]]:
        mention = f"@{user.username}" if user.username else user.first_name
        data["milk_queue"].append({"id": user.id, "mention": mention})
        update_chat_data(chat_id, data)
        await update.message.reply_text("✅ Вы добавлены в очередь на молоко.")
        await safe_edit(
            context.bot,
            chat_id,
            data["milk_msg_id"],
            format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко"),
            milk_keyboard()
        )
    else:
        await update.message.reply_text("Вы уже в очереди на молоко.")

async def add_coffee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    data    = get_chat_data(chat_id)
    user    = update.effective_user

    if user.id not in [p["id"] for p in data["coffee_queue"]]:
        mention = f"@{user.username}" if user.username else user.first_name
        data["coffee_queue"].append({"id": user.id, "mention": mention})
        update_chat_data(chat_id, data)
        await update.message.reply_text("✅ Вы добавлены в очередь на кофемашину.")
        await safe_edit(
            context.bot,
            chat_id,
            data["coffee_msg_id"],
            format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину"),
            coffee_keyboard()
        )
    else:
        await update.message.reply_text("Вы уже в очереди на кофемашину.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    chat_id = query.message.chat.id
    data    = get_chat_data(chat_id)

    if query.data == "milk_done":
        if not data["milk_queue"]:
            await query.answer("Очередь пуста."); return

        current = data["milk_queue"][data["milk_index"]]
        if query.from_user.id != current["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return

        data["milk_index"] = (data["milk_index"] + 1) % len(data["milk_queue"])
        update_chat_data(chat_id, data)

        await safe_edit(
            context.bot,
            chat_id,
            data["milk_msg_id"],
            format_queue(data["milk_queue"], data["milk_index"], "🥛 Очередь на молоко"),
            milk_keyboard()
        )

        next_user = data["milk_queue"][data["milk_index"]]
        doer      = f"@{query.from_user.username}" if query.from_user.username else query.from_user.first_name
        phrase    = random.choice(milk_phrases).format(doer=doer, next=next_user["mention"])
        await context.bot.send_message(chat_id=chat_id, text=phrase, parse_mode=ParseMode.HTML)

    elif query.data == "coffee_done":
        if not data["coffee_queue"]:
            await query.answer("Очередь пуста."); return

        current = data["coffee_queue"][data["coffee_index"]]
        if query.from_user.id != current["id"]:
            await query.answer("Сейчас не ваша очередь!", show_alert=True)
            return

        data["coffee_index"] = (data["coffee_index"] + 1) % len(data["coffee_queue"])
        update_chat_data(chat_id, data)

        await safe_edit(
            context.bot,
            chat_id,
            data["coffee_msg_id"],
            format_queue(data["coffee_queue"], data["coffee_index"], "☕ Очередь на кофемашину"),
            coffee_keyboard()
        )

        next_user = data["coffee_queue"][data["coffee_index"]]
        doer      = f"@{query.from_user.username}" if query.from_user.username else query.from_user.first_name
        phrase    = random.choice(coffee_phrases).format(doer=doer, next=next_user["mention"])
        await context.bot.send_message(chat_id=chat_id, text=phrase, parse_mode=ParseMode.HTML)

    await query.answer()

# ====== Точка входа ======
def main() -> None:
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("addmilk",   add_milk))
    app.add_handler(CommandHandler("addcoffee", add_coffee))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_webhook(
        listen      = "0.0.0.0",
        port        = PORT,
        url_path    = TOKEN,
        webhook_url = f"{BASE_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()

