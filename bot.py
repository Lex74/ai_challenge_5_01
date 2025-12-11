import logging
import requests
import re
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, OPENAI_API_URL, ADMIN_USER_ID

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Дефолтный системный промпт
DEFAULT_SYSTEM_PROMPT = "Ты успешный личный коуч. Клиент хочет поставить цель и достичь её. После каждого сообщения пользователя ты должен задавать ему вопросы, пока не получишь всю необходимую информацию, чтобы собрать цель по фреймворку SMART. SMART означает: S - Specific (Конкретная), M - Measurable (Измеримая), A - Achievable (Достижимая), R - Relevant (Релевантная), T - Time-bound (Ограниченная по времени). Задавай вопросы по одному, будь дружелюбным и поддерживающим. ВАЖНО: Когда соберёшь всю информацию и сформулируешь финальную цель по SMART, ОБЯЗАТЕЛЬНО добавь в конец своего ответа специальный маркер: [[ЦЕЛЬ_СФОРМУЛИРОВАНА]]. Этот маркер используй ТОЛЬКО когда формулируешь финальную цель, НИКОГДА не используй его в вопросах или промежуточных ответах. КРИТИЧЕСКИ ВАЖНО: Когда формулируешь финальную цель (когда добавляешь маркер [[ЦЕЛЬ_СФОРМУЛИРОВАНА]]), НЕ задавай никаких вопросов в этом сообщении. Просто сформулируй цель и заверши сообщение. Продолжай диалог с того места, где остановились."

# Дефолтная температура для запросов
DEFAULT_TEMPERATURE = 0.2

# Дефолтная модель OpenAI
DEFAULT_MODEL = "gpt-4o-mini"

# Максимальное количество токенов для ответа
MAX_TOKENS = 1000

# Таймаут для запросов к OpenAI API (в секундах)
API_TIMEOUT = 300  # 5 минут

# Специальный маркер, который модель должна использовать только при формулировке финальной цели
GOAL_FORMULATED_MARKER = "[[ЦЕЛЬ_СФОРМУЛИРОВАНА]]"

# Цены на модели OpenAI (за 1 миллион токенов в долларах)
# Формат: (input_price_per_1M, output_price_per_1M)
MODEL_PRICING = {
    "gpt-4o-mini": (0.15, 0.60),  # $0.15/$0.60 per 1M tokens
    "gpt-4o": (2.50, 10.00),  # $2.50/$10.00 per 1M tokens
    "gpt-4-turbo": (10.00, 30.00),  # $10.00/$30.00 per 1M tokens
    "gpt-4": (30.00, 60.00),  # $30.00/$60.00 per 1M tokens
    "gpt-3.5-turbo": (0.50, 1.50),  # $0.50/$1.50 per 1M tokens
    "gpt-5": (1.25, 10.00),  # $1.25/$10.00 per 1M tokens
    "gpt-5-mini": (0.25, 2.00),  # $0.25/$2.00 per 1M tokens
    "gpt-5-nano": (0.05, 0.40),  # $0.05/$0.40 per 1M tokens
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Рассчитывает стоимость запроса на основе модели и количества токенов"""
    if model not in MODEL_PRICING:
        # Используем цены gpt-4o-mini как дефолтные для неизвестных моделей
        input_price, output_price = MODEL_PRICING["gpt-4o-mini"]
        logger.warning(f"Неизвестная модель {model}, используются дефолтные цены")
    else:
        input_price, output_price = MODEL_PRICING[model]
    
    # Цены указаны за 1 миллион токенов, поэтому делим на 1_000_000
    cost = (prompt_tokens / 1_000_000 * input_price) + (completion_tokens / 1_000_000 * output_price)
    return cost


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    # Очищаем историю диалога при старте
    context.user_data['conversation_history'] = []
    # Сбрасываем промпт к дефолтному при старте
    if 'system_prompt' in context.user_data:
        del context.user_data['system_prompt']
    # Сбрасываем температуру к дефолтной при старте
    if 'temperature' in context.user_data:
        del context.user_data['temperature']
    # Сбрасываем модель к дефолтной при старте
    if 'model' in context.user_data:
        del context.user_data['model']
    # Сбрасываем max_tokens к дефолтному при старте
    if 'max_tokens' in context.user_data:
        del context.user_data['max_tokens']
    
    await update.message.reply_text(
        "Привет! Я твой личный коуч 🤝\n\n"
        "Я помогу тебе поставить цель и достичь её, используя фреймворк SMART.\n\n"
        "Просто расскажи мне, какую цель ты хочешь поставить, и я задам тебе вопросы, "
        "чтобы мы вместе сформулировали её правильно!\n\n"
        "/help - показать справку\n"
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
        "/help - показать эту справку\n\n"
        "/setprompt - установить новый системный промпт\n"
        "/getprompt - показать текущий системный промпт\n"
        "/resetprompt - сбросить системный промпт к дефолтному\n\n"
        "/settemp - установить температуру запроса (0.0-2.0)\n"
        "/gettemp - показать текущую температуру\n"
        "/resettemp - сбросить температуру к дефолтной (0.2)\n\n"
        "/setmodel - установить модель OpenAI (например: gpt-4o-mini, gpt-4o, gpt-3.5-turbo)\n"
        "/getmodel - показать текущую модель\n"
        "/resetmodel - сбросить модель к дефолтной (gpt-4o-mini)\n\n"
        "/setmaxtokens - установить максимальное количество токенов (например: 2000)\n"
        "/getmaxtokens - показать текущее максимальное количество токенов\n"
        "/resetmaxtokens - сбросить к дефолтному значению (1000)\n\n"
        "Температура влияет на креативность ответов (диапазон: 0.0-2.0)"
    )


async def setprompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /setprompt для установки нового системного промпта"""
    if not context.args:
        await update.message.reply_text(
            "Использование: /setprompt <новый промпт>\n\n"
            "Пример: /setprompt Ты помощник, который отвечает кратко и по делу."
        )
        return
    
    # Объединяем все аргументы в один промпт
    new_prompt = ' '.join(context.args)
    
    # Сохраняем промпт в user_data
    context.user_data['system_prompt'] = new_prompt
    
    await update.message.reply_text(
        f"✅ Системный промпт обновлён!\n\n"
        f"Новый промпт:\n{new_prompt[:500]}{'...' if len(new_prompt) > 500 else ''}"
    )
    logger.info(f"Пользователь {update.effective_user.id} установил новый системный промпт")


async def getprompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /getprompt для просмотра текущего системного промпта"""
    # Получаем текущий промпт или используем дефолтный
    current_prompt = context.user_data.get('system_prompt', DEFAULT_SYSTEM_PROMPT)
    is_default = 'system_prompt' not in context.user_data
    
    prompt_text = f"Текущий системный промпт{' (дефолтный)' if is_default else ''}:\n\n{current_prompt}"
    
    # Если промпт слишком длинный, разбиваем на части
    if len(prompt_text) > 4000:
        await update.message.reply_text(prompt_text[:4000], parse_mode='HTML')
        await update.message.reply_text(prompt_text[4000:], parse_mode='HTML')
    else:
        await update.message.reply_text(prompt_text, parse_mode='HTML')


async def resetprompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /resetprompt для сброса системного промпта к дефолтному"""
    # Удаляем кастомный промпт
    if 'system_prompt' in context.user_data:
        del context.user_data['system_prompt']
    
    await update.message.reply_text(
        "✅ Системный промпт сброшен к дефолтному значению."
    )
    logger.info(f"Пользователь {update.effective_user.id} сбросил системный промпт к дефолтному")


async def settemp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /settemp для установки температуры запроса"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Использование: /settemp <температура>\n\n"
            "Температура должна быть числом от 0.0 до 2.0.\n"
            "Пример: /settemp 0.7\n\n"
            "Чем выше температура, тем более креативными и случайными будут ответы.\n"
            "Чем ниже температура, тем более детерминированными и точными."
        )
        return
    
    try:
        new_temp = float(context.args[0])
        
        # Проверяем диапазон температуры (OpenAI API поддерживает 0.0-2.0)
        if new_temp < 0.0 or new_temp > 2.0:
            await update.message.reply_text(
                "❌ Температура должна быть в диапазоне от 0.0 до 2.0."
            )
            return
        
        # Сохраняем температуру в user_data
        context.user_data['temperature'] = new_temp
        
        await update.message.reply_text(
            f"✅ Температура установлена: {new_temp}"
        )
        logger.info(f"Пользователь {update.effective_user.id} установил температуру: {new_temp}")
        
    except ValueError:
        await update.message.reply_text(
            "❌ Ошибка: температура должна быть числом.\n"
            "Пример: /settemp 0.7"
        )


async def gettemp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /gettemp для просмотра текущей температуры"""
    # Получаем текущую температуру или используем дефолтную
    current_temp = context.user_data.get('temperature', DEFAULT_TEMPERATURE)
    is_default = 'temperature' not in context.user_data
    
    temp_text = f"Текущая температура: {current_temp}{' (дефолтная)' if is_default else ''}"
    
    await update.message.reply_text(temp_text)


async def resettemp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /resettemp для сброса температуры к дефолтной"""
    # Удаляем кастомную температуру
    if 'temperature' in context.user_data:
        del context.user_data['temperature']
    
    await update.message.reply_text(
        f"✅ Температура сброшена к дефолтному значению: {DEFAULT_TEMPERATURE}"
    )
    logger.info(f"Пользователь {update.effective_user.id} сбросил температуру к дефолтной")


async def setmodel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /setmodel для установки модели OpenAI"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Использование: /setmodel <модель>\n\n"
            "Примеры моделей:\n"
            "• gpt-4o-mini (быстрая и экономичная)\n"
            "• gpt-4o (более мощная)\n"
            "• gpt-3.5-turbo (старая версия)\n\n"
            "Пример: /setmodel gpt-4o"
        )
        return
    
    new_model = context.args[0].strip()
    
    # Проверяем, меняется ли модель
    old_model = context.user_data.get('model', DEFAULT_MODEL)
    model_changed = old_model != new_model
    
    # Сохраняем модель в user_data
    context.user_data['model'] = new_model
    
    # Сбрасываем историю диалога при переключении модели
    if model_changed:
        context.user_data['conversation_history'] = []
        logger.info(f"Пользователь {update.effective_user.id} переключил модель с {old_model} на {new_model}, история диалога очищена")
        await update.message.reply_text(
            f"✅ Модель установлена: {new_model}\n"
            f"📝 История диалога очищена"
        )
    else:
        await update.message.reply_text(
            f"✅ Модель установлена: {new_model}"
        )
    logger.info(f"Пользователь {update.effective_user.id} установил модель: {new_model}")


async def getmodel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /getmodel для просмотра текущей модели"""
    # Получаем текущую модель или используем дефолтную
    current_model = context.user_data.get('model', DEFAULT_MODEL)
    is_default = 'model' not in context.user_data
    
    model_text = f"Текущая модель: {current_model}{' (дефолтная)' if is_default else ''}"
    
    await update.message.reply_text(model_text)


async def resetmodel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /resetmodel для сброса модели к дефолтной"""
    # Удаляем кастомную модель
    if 'model' in context.user_data:
        del context.user_data['model']
    
    await update.message.reply_text(
        f"✅ Модель сброшена к дефолтному значению: {DEFAULT_MODEL}"
    )
    logger.info(f"Пользователь {update.effective_user.id} сбросил модель к дефолтной")


async def setmaxtokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /setmaxtokens для установки максимального количества токенов"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Использование: /setmaxtokens <количество>\n\n"
            "Количество должно быть положительным числом.\n"
            "Пример: /setmaxtokens 2000\n\n"
            "Максимальное количество токенов определяет длину ответа модели."
        )
        return
    
    try:
        new_max_tokens = int(context.args[0])
        
        # Проверяем, что значение положительное
        if new_max_tokens <= 0:
            await update.message.reply_text(
                "❌ Количество токенов должно быть положительным числом."
            )
            return
        
        # Сохраняем max_tokens в user_data
        context.user_data['max_tokens'] = new_max_tokens
        
        await update.message.reply_text(
            f"✅ Максимальное количество токенов установлено: {new_max_tokens}"
        )
        logger.info(f"Пользователь {update.effective_user.id} установил max_tokens: {new_max_tokens}")
        
    except ValueError:
        await update.message.reply_text(
            "❌ Ошибка: количество токенов должно быть числом.\n"
            "Пример: /setmaxtokens 2000"
        )


async def getmaxtokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /getmaxtokens для просмотра текущего максимального количества токенов"""
    # Получаем текущее значение или используем дефолтное
    current_max_tokens = context.user_data.get('max_tokens', MAX_TOKENS)
    is_default = 'max_tokens' not in context.user_data
    
    max_tokens_text = f"Текущее максимальное количество токенов: {current_max_tokens}{' (дефолтное)' if is_default else ''}"
    
    await update.message.reply_text(max_tokens_text)


async def resetmaxtokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /resetmaxtokens для сброса максимального количества токенов к дефолтному"""
    # Удаляем кастомное значение
    if 'max_tokens' in context.user_data:
        del context.user_data['max_tokens']
    
    await update.message.reply_text(
        f"✅ Максимальное количество токенов сброшено к дефолтному значению: {MAX_TOKENS}"
    )
    logger.info(f"Пользователь {update.effective_user.id} сбросил max_tokens к дефолтному")

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


async def send_log_to_admin(bot, log_message: str):
    """Отправляет лог админу в Telegram"""
    if ADMIN_USER_ID:
        try:
            await bot.send_message(chat_id=int(ADMIN_USER_ID), text=log_message)
        except Exception as e:
            logger.error(f"Ошибка при отправке лога админу: {e}")


async def query_openai(question: str, conversation_history: list, system_prompt: str, temperature: float, model: str, max_tokens: int, bot=None) -> tuple[str, list]:
    """Отправляет запрос в OpenAI API и возвращает ответ и обновленную историю"""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Формируем список сообщений: системный промпт + история + текущий вопрос
    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]
    
    # Добавляем историю диалога
    messages.extend(conversation_history)
    
    # Добавляем текущий вопрос пользователя
    messages.append({
        "role": "user",
        "content": question
    })
    
    # Для моделей GPT-5 используется max_completion_tokens вместо max_tokens
    # Для GPT-5 не поддерживается параметр temperature
    payload = {
        "model": model,
        "messages": messages
    }
    
    if model.startswith("gpt-5"):
        payload["max_completion_tokens"] = max_tokens
        # GPT-5 не поддерживает параметр temperature
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = temperature
    
    try:
        # Засекаем время начала запроса
        start_time = time.time()
        
        response = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=API_TIMEOUT)
        response.raise_for_status()
        
        # Засекаем время окончания запроса
        end_time = time.time()
        response_time = end_time - start_time
        
        data = response.json()
        
        # Извлекаем ответ из структуры ответа OpenAI
        if 'choices' in data and len(data['choices']) > 0:
            choice = data['choices'][0]
            answer = choice.get('message', {}).get('content', '')
            finish_reason = choice.get('finish_reason', '')
            
            # Для GPT-5 проверяем, если content пустой из-за лимита токенов
            if model.startswith("gpt-5") and not answer and finish_reason == "length":
                usage = data.get('usage', {})
                completion_tokens = usage.get('completion_tokens', 0)
                completion_details = usage.get('completion_tokens_details', {})
                reasoning_tokens = completion_details.get('reasoning_tokens', 0)
                
                answer = (
                    f"⚠️ Достигнут лимит токенов. Все {completion_tokens} токенов ушли на рассуждения (reasoning tokens: {reasoning_tokens}). "
                    f"Модель не успела сгенерировать финальный ответ.\n\n"
                    f"Рекомендуется увеличить max_tokens (текущее значение: {max_tokens}) для получения полного ответа."
                )
                
                logger.warning(
                    f"GPT-5 вернул пустой content. Finish reason: {finish_reason}, "
                    f"Reasoning tokens: {reasoning_tokens}/{completion_tokens}"
                )
            
            # Если ответ все еще пустой, возвращаем сообщение об ошибке
            if not answer:
                answer = "Извините, не удалось получить ответ от модели."
            
            # Извлекаем информацию из ответа API
            usage = data.get('usage', {})
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', 0)
            
            # Проверяем наличие reasoning tokens
            completion_details = usage.get('completion_tokens_details', {})
            reasoning_tokens = completion_details.get('reasoning_tokens', 0)
            
            # Рассчитываем стоимость
            total_cost = calculate_cost(model, prompt_tokens, completion_tokens)
            
            # Логируем информацию о запросе
            log_message = (
                f"OpenAI API запрос - Модель: {model}, "
                f"Время ответа: {response_time:.3f}с, "
                f"Prompt tokens: {prompt_tokens}, Completion tokens: {completion_tokens}"
            )
            
            # Добавляем reasoning tokens, если они есть
            if reasoning_tokens > 0:
                log_message += f", Reasoning tokens: {reasoning_tokens}"
            
            log_message += f", Total cost: ${total_cost:.6f}"
            
            logger.info(log_message)
            
            # Отправляем лог админу
            if bot:
                await send_log_to_admin(bot, log_message)
            
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
            
    except requests.exceptions.HTTPError as e:
        # Логируем детали ошибки для диагностики
        error_details = ""
        try:
            error_response = e.response.json()
            error_details = f" Детали: {error_response}"
            logger.error(f"HTTP ошибка от OpenAI API: {e.response.status_code} - {error_response}")
        except:
            logger.error(f"HTTP ошибка от OpenAI API: {e.response.status_code} - {e.response.text}")
        return f"Произошла ошибка при обращении к API: {str(e)}{error_details}", conversation_history
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к OpenAI API: {e}")
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
        # Получаем системный промпт из user_data или используем дефолтный
        system_prompt = context.user_data.get('system_prompt', DEFAULT_SYSTEM_PROMPT)
        # Получаем температуру из user_data или используем дефолтную
        temperature = context.user_data.get('temperature', DEFAULT_TEMPERATURE)
        # Получаем модель из user_data или используем дефолтную
        model = context.user_data.get('model', DEFAULT_MODEL)
        # Получаем max_tokens из user_data или используем дефолтное
        max_tokens = context.user_data.get('max_tokens', MAX_TOKENS)
        
        # Получаем ответ от OpenAI с историей диалога
        answer, updated_history = await query_openai(user_message, conversation_history, system_prompt, temperature, model, max_tokens, context.bot)
        
        # Удаляем сообщение "Думаю..."
        await thinking_message.delete()
        
        # Обрабатываем ответ для всех моделей
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
        
        # Преобразуем markdown в форматирование Telegram
        formatted_answer = convert_markdown_to_telegram(answer)
        
        # Проверяем, что ответ не пустой
        if not formatted_answer or not formatted_answer.strip():
            await update.message.reply_text(
                "Извините, не удалось получить ответ от модели. Попробуйте еще раз."
            )
            logger.warning(f"Получен пустой ответ от модели {model}")
            return
        
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

