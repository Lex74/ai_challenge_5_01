"""Обработчики команд бота"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from constants import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    DEFAULT_MODEL,
    MAX_TOKENS,
)
from memory import clear_memory

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Очищаем память на диске при старте
    clear_memory(user_id)
    logger.info(f"Очищена память для пользователя {user_id} при /start")
    
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
        user_id = update.effective_user.id
        # Очищаем память на диске при переключении модели
        clear_memory(user_id)
        context.user_data['conversation_history'] = []
        logger.info(f"Пользователь {user_id} переключил модель с {old_model} на {new_model}, история диалога и память очищены")
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
    user_id = update.effective_user.id
    old_model = context.user_data.get('model', DEFAULT_MODEL)
    
    # Удаляем кастомную модель
    if 'model' in context.user_data:
        del context.user_data['model']
        # Очищаем память на диске при сбросе модели (если модель менялась)
        if old_model != DEFAULT_MODEL:
            clear_memory(user_id)
            logger.info(f"Пользователь {user_id} сбросил модель с {old_model} на {DEFAULT_MODEL}, память очищена")
    
    await update.message.reply_text(
        f"✅ Модель сброшена к дефолтному значению: {DEFAULT_MODEL}"
    )
    logger.info(f"Пользователь {user_id} сбросил модель к дефолтной")


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
