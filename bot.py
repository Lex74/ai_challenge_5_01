"""Основной файл для запуска Telegram бота"""
import asyncio
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
    notion_tools_command,
    kinopoisk_tools_command,
    news_tools_command,
)
from handlers.messages import handle_message
from mcp_integration import get_all_mcp_tools
from scheduler import setup_daily_news_scheduler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Инициализация после создания приложения - загружаем MCP инструменты"""
    logger.info("Загружаю MCP инструменты при старте бота...")
    try:
        mcp_tools = await get_all_mcp_tools()
        application.bot_data['mcp_tools'] = mcp_tools
        logger.info(f"Успешно загружено {len(mcp_tools)} MCP инструментов при старте бота")
        
        # Логируем детали о загруженных инструментах
        tool_names = [t.get('function', {}).get('name', 'unknown') for t in mcp_tools]
        logger.info(f"Загруженные инструменты: {', '.join(tool_names)}")
        
        # Проверяем наличие News инструментов
        news_tools = [name for name in tool_names if name.startswith('news_')]
        if news_tools:
            logger.info(f"✅ News инструменты загружены: {', '.join(news_tools)}")
        else:
            logger.warning("⚠️ News инструменты НЕ загружены! Проверьте настройки NEWS_API_KEY и путь к news-mcp серверу.")
    except Exception as e:
        logger.error(f"Ошибка при загрузке MCP инструментов при старте: {e}", exc_info=True)
        application.bot_data['mcp_tools'] = []


def main():
    """Основная функция для запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
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
    application.add_handler(CommandHandler("notion_tools", notion_tools_command))
    application.add_handler(CommandHandler("kinopoisk_tools", kinopoisk_tools_command))
    application.add_handler(CommandHandler("news_tools", news_tools_command))
    
    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Настраиваем планировщик для ежедневной рассылки новостей
    setup_daily_news_scheduler(application)
    
    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
