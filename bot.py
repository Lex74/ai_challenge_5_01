"""Основной файл для запуска Telegram бота"""
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN
from handlers.commands import (
    start,
    help_command,
    setprompt_command,
    getprompt_command,
    resetprompt_command,
    settemp_command,
    gettemp_command,
    resettemp_command,
    setmodel_command,
    getmodel_command,
    resetmodel_command,
    setmaxtokens_command,
    getmaxtokens_command,
    resetmaxtokens_command,
)
from handlers.messages import handle_message

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Основная функция для запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setprompt", setprompt_command))
    application.add_handler(CommandHandler("getprompt", getprompt_command))
    application.add_handler(CommandHandler("resetprompt", resetprompt_command))
    application.add_handler(CommandHandler("settemp", settemp_command))
    application.add_handler(CommandHandler("gettemp", gettemp_command))
    application.add_handler(CommandHandler("resettemp", resettemp_command))
    application.add_handler(CommandHandler("setmodel", setmodel_command))
    application.add_handler(CommandHandler("getmodel", getmodel_command))
    application.add_handler(CommandHandler("resetmodel", resetmodel_command))
    application.add_handler(CommandHandler("setmaxtokens", setmaxtokens_command))
    application.add_handler(CommandHandler("getmaxtokens", getmaxtokens_command))
    application.add_handler(CommandHandler("resetmaxtokens", resetmaxtokens_command))
    
    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
