import logging
import requests
import re
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
    # Очищаем историю диалога при старте
    context.user_data['conversation_history'] = []
    
    await update.message.reply_text(
        "Привет! Я твой личный коуч 🤝\n\n"
        "Я помогу тебе поставить цель и достичь её, используя фреймворк SMART.\n\n"
        "Просто расскажи мне, какую цель ты хочешь поставить, и я задам тебе вопросы, "
        "чтобы мы вместе сформулировали её правильно!"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    await update.message.reply_text(
        "Я помогу тебе поставить цель по фреймворку SMART:\n\n"
        "📌 S - Specific (Конкретная)\n"
        "📊 M - Measurable (Измеримая)\n"
        "🎯 A - Achievable (Достижимая)\n"
        "💡 R - Relevant (Релевантная)\n"
        "⏰ T - Time-bound (Ограниченная по времени)\n\n"
        "Просто расскажи мне о своей цели, и я задам вопросы, "
        "чтобы помочь тебе сформулировать её правильно!\n\n"
        "Команды:\n"
        "/start - начать работу с ботом\n"
        "/help - показать эту справку"
    )


# Специальный маркер, который модель должна использовать только при формулировке финальной цели
GOAL_FORMULATED_MARKER = "[[ЦЕЛЬ_СФОРМУЛИРОВАНА]]"

def is_goal_formulated(answer: str) -> bool:
    """Проверяет, сформулировал ли бот финальную цель по наличию специального маркера"""
    return GOAL_FORMULATED_MARKER in answer


def remove_marker_from_answer(answer: str) -> str:
    """Удаляет маркер формулировки цели из ответа перед отправкой пользователю"""
    return answer.replace(GOAL_FORMULATED_MARKER, "").strip()


def remove_source_numbers(text: str) -> str:
    """Удаляет номера источников информации из текста"""
    # Удаляем ссылки на источники в квадратных скобках: [1], [2], [3] и т.д.
    text = re.sub(r'\[\d+\]', '', text)
    
    # Удаляем ссылки на источники в круглых скобках: (1), (2), (3) и т.д.
    text = re.sub(r'\(\d+\)', '', text)
    
    # Удаляем ссылки вида [source 1], [source 2] и т.д.
    text = re.sub(r'\[source\s+\d+\]', '', text, flags=re.IGNORECASE)
    
    # Удаляем ссылки вида [источник 1], [источник 2] и т.д.
    text = re.sub(r'\[источник\s+\d+\]', '', text, flags=re.IGNORECASE)
    
    # Удаляем множественные пробелы в пределах одной строки (но сохраняем переносы строк)
    # Заменяем множественные пробелы на один пробел, но не трогаем \n
    lines = text.split('\n')
    cleaned_lines = [re.sub(r'[ \t]+', ' ', line) for line in lines]
    text = '\n'.join(cleaned_lines)
    
    # Удаляем пробелы в начале и конце каждой строки, но сохраняем пустые строки
    lines = text.split('\n')
    cleaned_lines = [line.strip() if line.strip() else '' for line in lines]
    text = '\n'.join(cleaned_lines)
    
    return text.strip()


def convert_markdown_to_telegram(text: str) -> str:
    """Преобразует markdown разметку в HTML форматирование для Telegram"""
    # Экранируем специальные символы HTML
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    
    # Преобразуем ## текст в <u>текст</u> (подчёркнутый)
    # Обрабатываем строки, начинающиеся с ##
    lines = text.split('\n')
    result_lines = []
    for line in lines:
        if line.strip().startswith('##'):
            # Убираем ## и пробелы после них, оборачиваем в <u>
            content = line.replace('##', '').strip()
            if content:
                result_lines.append(f'<u>{content}</u>')
            else:
                result_lines.append(line)
        else:
            result_lines.append(line)
    text = '\n'.join(result_lines)
    
    # Преобразуем **текст** в <b>текст</b> (жирный)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    
    return text


async def query_perplexity(question: str, conversation_history: list) -> tuple[str, list]:
    """Отправляет запрос в Perplexity API и возвращает ответ и обновленную историю"""
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Формируем список сообщений: системный промпт + история + текущий вопрос
    messages = [
        {
            "role": "system",
            "content": "Ты успешный личный коуч. Клиент хочет поставить цель и достичь её. После каждого сообщения пользователя ты должен задавать ему вопросы, пока не получишь всю необходимую информацию, чтобы собрать цель по фреймворку SMART. SMART означает: S - Specific (Конкретная), M - Measurable (Измеримая), A - Achievable (Достижимая), R - Relevant (Релевантная), T - Time-bound (Ограниченная по времени). Задавай вопросы по одному, будь дружелюбным и поддерживающим. ВАЖНО: Когда соберёшь всю информацию и сформулируешь финальную цель по SMART, ОБЯЗАТЕЛЬНО добавь в конец своего ответа специальный маркер: [[ЦЕЛЬ_СФОРМУЛИРОВАНА]]. Этот маркер используй ТОЛЬКО когда формулируешь финальную цель, НИКОГДА не используй его в вопросах или промежуточных ответах. КРИТИЧЕСКИ ВАЖНО: Когда формулируешь финальную цель (когда добавляешь маркер [[ЦЕЛЬ_СФОРМУЛИРОВАНА]]), НЕ задавай никаких вопросов в этом сообщении. Просто сформулируй цель и заверши сообщение. Продолжай диалог с того места, где остановились."
        }
    ]
    
    # Добавляем историю диалога
    messages.extend(conversation_history)
    
    # Добавляем текущий вопрос пользователя
    messages.append({
        "role": "user",
        "content": question
    })
    
    payload = {
        "model": "sonar-pro",
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(PERPLEXITY_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Извлекаем ответ из структуры ответа Perplexity
        if 'choices' in data and len(data['choices']) > 0:
            answer = data['choices'][0]['message']['content']
            
            # Обновляем историю: добавляем вопрос пользователя и ответ бота
            updated_history = conversation_history.copy()
            updated_history.append({"role": "user", "content": question})
            updated_history.append({"role": "assistant", "content": answer})
            
            # Ограничиваем историю последними 10 сообщениями (5 пар вопрос-ответ)
            # чтобы не превышать лимиты токенов
            if len(updated_history) > 10:
                updated_history = updated_history[-10:]
            
            return answer, updated_history
        else:
            return "Извините, не удалось получить ответ от API.", conversation_history
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к Perplexity API: {e}")
        return f"Произошла ошибка при обращении к API: {str(e)}", conversation_history
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return f"Произошла неожиданная ошибка: {str(e)}", conversation_history


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_message = update.message.text
    
    # Получаем или создаем историю диалога для пользователя
    if 'conversation_history' not in context.user_data:
        context.user_data['conversation_history'] = []
    
    conversation_history = context.user_data['conversation_history']
    
    # Проверяем, хочет ли пользователь начать заново
    user_message_lower = user_message.lower().strip()
    if user_message_lower in ['стоп', 'стой']:
        # Очищаем историю диалога
        context.user_data['conversation_history'] = []
        logger.info("Пользователь запросил сброс истории диалога")
        await update.message.reply_text("Хорошо, тогда начнём с начала! 🎯")
        return
    
    # Отправляем сообщение о том, что бот думает
    thinking_message = await update.message.reply_text("🤔 Думаю над ответом...")
    
    try:
        # Получаем ответ от Perplexity с историей диалога
        answer, updated_history = await query_perplexity(user_message, conversation_history)
        
        # Проверяем, сформулировал ли бот финальную цель
        goal_formulated = is_goal_formulated(answer)
        
        if goal_formulated:
            # Очищаем историю диалога после формулировки цели
            context.user_data['conversation_history'] = []
            logger.info("Цель сформулирована, история диалога очищена")
            # Удаляем маркер из ответа перед отправкой пользователю
            answer = remove_marker_from_answer(answer)
        else:
            # Сохраняем обновленную историю
            context.user_data['conversation_history'] = updated_history
        
        # Удаляем номера источников из ответа
        answer = remove_source_numbers(answer)
        
        # Удаляем сообщение "Думаю..."
        await thinking_message.delete()
        
        # Преобразуем markdown в форматирование Telegram
        formatted_answer = convert_markdown_to_telegram(answer)
        
        # Отправляем ответ пользователю с HTML форматированием
        # Разбиваем длинные ответы на части (Telegram имеет лимит 4096 символов)
        if len(formatted_answer) > 4000:
            # Отправляем первую часть
            await update.message.reply_text(formatted_answer[:4000], parse_mode='HTML')
            # Отправляем оставшуюся часть
            await update.message.reply_text(formatted_answer[4000:], parse_mode='HTML')
        else:
            await update.message.reply_text(formatted_answer, parse_mode='HTML')
            
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

