import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN, PERPLEXITY_API_KEY, PERPLEXITY_API_URL

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "Привет! Я бот, который отвечает на вопросы с помощью Perplexity AI.\n"
        "Просто отправь мне свой вопрос, и я найду ответ!"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    await update.message.reply_text(
        "Использование:\n"
        "Просто отправь мне любой вопрос текстом, и я найду ответ с помощью Perplexity AI.\n\n"
        "Команды:\n"
        "/start - начать работу с ботом\n"
        "/help - показать эту справку"
    )


async def query_perplexity(question: str) -> str:
    """Отправляет запрос в Perplexity API и возвращает ответ"""
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "sonar-pro",
        "messages": [
            {
                "role": "system",
                "content": "Ты полезный ассистент, который отвечает на вопросы точно и информативно."
            },
            {
                "role": "user",
                "content": question
            }
        ],
        "temperature": 0.2,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(PERPLEXITY_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Извлекаем ответ из структуры ответа Perplexity
        if 'choices' in data and len(data['choices']) > 0:
            return data['choices'][0]['message']['content']
        else:
            return "Извините, не удалось получить ответ от API."
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к Perplexity API: {e}")
        return f"Произошла ошибка при обращении к API: {str(e)}"
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return f"Произошла неожиданная ошибка: {str(e)}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_message = update.message.text
    
    # Отправляем сообщение о том, что бот думает
    thinking_message = await update.message.reply_text("🤔 Думаю над ответом...")
    
    try:
        # Получаем ответ от Perplexity
        answer = await query_perplexity(user_message)
        
        # Удаляем сообщение "Думаю..."
        await thinking_message.delete()
        
        # Отправляем ответ пользователю
        # Разбиваем длинные ответы на части (Telegram имеет лимит 4096 символов)
        if len(answer) > 4000:
            # Отправляем первую часть
            await update.message.reply_text(answer[:4000])
            # Отправляем оставшуюся часть
            await update.message.reply_text(answer[4000:])
        else:
            await update.message.reply_text(answer)
            
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await thinking_message.delete()
        await update.message.reply_text(
            "Извините, произошла ошибка при обработке вашего запроса. "
            "Попробуйте еще раз позже."
        )


def main():
    """Основная функция для запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

