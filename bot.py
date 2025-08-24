import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes
)

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ Не найден TELEGRAM_BOT_TOKEN в переменных окружения!")

# === ОБРАБОТЧИКИ КОМАНД ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие при /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name or 'друг'}! 🤖\n"
        "Я готов к работе. Напиши что-нибудь или используй /help."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка по командам"""
    await update.message.reply_text(
        "Доступные команды:\n"
        "/start — запустить бота\n"
        "/help — список команд\n"
        "/about — информация о боте"
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о боте"""
    await update.message.reply_text(
        "Я бот, созданный на python-telegram-bot v20+, "
        "умею отвечать на команды и реагировать на ключевые слова."
    )

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на текстовые сообщения"""
    text = update.message.text.lower()

    # Ключевые слова
    if "привет" in text:
        await update.message.reply_text("Привет! 👋 Рад тебя видеть.")
    elif "пока" in text:
        await update.message.reply_text("До встречи! 👋")
    elif "как дела" in text:
        await update.message.reply_text("У меня всё отлично, спасибо что спросил!")
    else:
        # Эхо-ответ
        await update.message.reply_text(f"Ты написал: {update.message.text}")

# === ОБРАБОТКА ОШИБОК ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Произошла ошибка:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ Произошла ошибка. Мы уже работаем над этим.")

# === ЗАПУСК БОТА ===
def main():
    app = Application.builder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about))

    # Сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Логирование ошибок
    app.add_error_handler(error_handler)

    logger.info("✅ Бот запущен. Ожидаю сообщения...")
    app.run_polling()

if __name__ == "__main__":
    main()
