"""Обработчики команд бота"""
import logging
import json
from typing import Optional, Tuple, List, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from constants import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    DEFAULT_MODEL,
    MAX_TOKENS,
)
from memory import clear_memory
from utils import format_tools_list, split_long_message

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
    """Обработчик команды /help - использует RAG для ответов на вопросы о проекте"""
    user_id = update.effective_user.id
    
    # Если пользователь задал вопрос после /help, используем RAG для ответа
    if context.args:
        question = ' '.join(context.args)
        await update.message.reply_text(f"🔍 Ищу информацию о проекте по запросу: {question}")
        
        # Используем RAG для поиска информации в документации проекта
        from rag import query_with_rag, format_sources_for_display
        from constants import DEFAULT_TEMPERATURE, DEFAULT_MODEL, MAX_TOKENS
        from memory import load_memory_from_disk
        from utils import convert_markdown_to_telegram, split_long_message
        
        # Загружаем память
        memory_data = load_memory_from_disk(user_id)
        conversation_history = memory_data.get("recent_messages", [])
        
        # Получаем доступные MCP инструменты (включая Git)
        mcp_tools = context.bot_data.get('mcp_tools', [])
        
        # Собираем информацию о Git инструментах
        git_tools_info = []
        git_tools_available = False
        if mcp_tools:
            for tool in mcp_tools:
                tool_func = tool.get('function', {})
                tool_name = tool_func.get('name', '')
                tool_desc = tool_func.get('description', '')
                if tool_name.startswith('git_'):
                    git_tools_info.append(f"- {tool_name}: {tool_desc}")
                    git_tools_available = True
        
        # Специальный системный промпт для ассистента разработчика
        system_prompt = (
            "Ты ассистент разработчика, который помогает пользователям работать с проектом. "
            "У тебя есть доступ к:\n"
            "1. Документации проекта через RAG (README, API, схемы данных)\n"
        )
        
        if git_tools_available:
            system_prompt += (
                "2. Git репозиторию через MCP инструменты (ветки, файлы, статус, diff, коммиты)\n"
                "3. Коду проекта через чтение файлов\n\n"
                "КРИТИЧЕСКИ ВАЖНО - ПРАВИЛА ИСПОЛЬЗОВАНИЯ ИНСТРУМЕНТОВ:\n\n"
                "КОГДА ПОЛЬЗОВАТЕЛЬ СПРАШИВАЕТ О:\n"
                "- Git репозитории (ветка, текущая ветка, активная ветка, статус, файлы, коммиты, diff) - "
                "ОБЯЗАТЕЛЬНО используй git инструменты СРАЗУ, БЕЗ использования RAG!\n"
                "- Содержимом файлов из репозитория - используй git инструменты для получения содержимого\n"
                "- Документации проекта (как работает что-то, API, структура) - используй информацию из RAG\n"
                "- Структуре проекта - используй RAG и git инструменты\n\n"
                "Доступные Git инструменты:\n" + "\n".join(git_tools_info) + "\n\n"
                "ВАЖНО: Если вопрос касается git (ветка, статус, файлы, коммиты), "
                "НЕ ищи информацию в документации через RAG - используй git инструменты напрямую!\n"
                "Например, если пользователь спрашивает 'какая сейчас активная ветка', "
                "используй git_get_current_branch, а НЕ ищи в документации.\n\n"
            )
        else:
            system_prompt += (
                "2. Коду проекта через чтение файлов\n\n"
            )
        
        system_prompt += (
            "Будь конкретным, показывай примеры кода, ссылайся на файлы. Отвечай на русском языке."
        )
        
        # Используем RAG для поиска в документации проекта
        answer, updated_history, sources = await query_with_rag(
            question,
            conversation_history,
            system_prompt,
            DEFAULT_TEMPERATURE,
            DEFAULT_MODEL,
            MAX_TOKENS,
            context.bot,
            tools=mcp_tools if mcp_tools else None,
            index_path=None,  # Используем дефолтный индекс
            relevance_threshold=0.2,
            rerank_method="diversity"
        )
        
        # Форматируем ответ
        formatted_answer = convert_markdown_to_telegram(answer)
        
        # Отправляем ответ
        message_parts = split_long_message(formatted_answer, max_length=4000)
        for part in message_parts:
            await update.message.reply_text(part, parse_mode='HTML')
        
        # Отправляем источники, если есть
        if sources:
            sources_text = format_sources_for_display(sources)
            if sources_text:
                sources_formatted = convert_markdown_to_telegram(sources_text)
                await update.message.reply_text(sources_formatted, parse_mode='HTML')
        
        # Обновляем историю диалога
        conversation_history.append({"role": "user", "content": question})
        conversation_history.append({"role": "assistant", "content": answer})
        
        # Сохраняем память
        from memory import save_memory_to_disk
        memory_data = {
            "summary": memory_data.get("summary", ""),
            "recent_messages": conversation_history[-10:],  # Сохраняем последние 10 сообщений
            "message_count": memory_data.get("message_count", 0)
        }
        save_memory_to_disk(user_id, memory_data)
    else:
        # Показываем стандартную справку
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
            "/help [вопрос] - показать справку или ответить на вопрос о проекте (ассистент разработчика)\n\n"
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
            "/notion_tools - показать список доступных инструментов Notion\n"
            "/kinopoisk_tools - показать список доступных инструментов Kinopoisk MCP\n"
            "/news_tools - показать список доступных инструментов News MCP\n\n"
            "/rag_mode - установить режим RAG (off/on/compare/compare_filter)\n"
            "/getragmode - показать текущий режим RAG\n"
            "/setragthreshold - установить порог релевантности (0.0-1.0)\n"
            "/getragthreshold - показать текущий порог релевантности\n"
            "/setragrerank - установить метод реранкинга (similarity/diversity/hybrid/off)\n\n"
            "Температура влияет на креативность ответов (диапазон: 0.0-2.0)\n\n"
            "💡 Примеры использования ассистента разработчика:\n"
            "/help как работает RAG?\n"
            "/help покажи текущую ветку git\n"
            "/help какие файлы изменены?\n"
            "/help покажи содержимое файла bot.py\n"
            "/help объясни структуру проекта"
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


def _handle_tools_command_error(error_info: Optional[Tuple[str, str]], default_msg: str) -> str:
    """Обрабатывает ошибки при получении списка инструментов"""
    if not error_info:
        return default_msg
    
    error_type, error_msg = error_info
    
    error_messages = {
        "NODE_VERSION_ERROR": f"❌ {error_msg}\n\n💡 После обновления Node.js перезапустите бота.",
        "COMMAND_NOT_FOUND": f"❌ {error_msg}\n\n💡 Совет: После установки Node.js перезапустите бота.",
        "FILE_NOT_FOUND": f"❌ {error_msg}\n\n💡 Убедитесь, что Node.js версии 18+ установлен и команда 'npx' доступна.",
        "PERMISSION_ERROR": f"❌ {error_msg}",
        "IMPORT_ERROR": f"❌ {error_msg}",
        "NO_API_KEY": f"❌ {error_msg}\n\nПроверьте настройки и переменную окружения KINOPOISK_API_KEY.",
        "TIMEOUT_INIT": f"❌ {error_msg}\n\n💡 Команда прервана по тайм-ауту, чтобы бот не зависал.",
        "TIMEOUT_TOOLS": f"❌ {error_msg}\n\n💡 Команда прервана по тайм-ауту, чтобы бот не зависал.",
    }
    
    return error_messages.get(error_type, f"❌ Ошибка: {error_msg}\n\nПроверьте логи для получения дополнительной информации.")


def _format_film_search_results(films: List[Dict[str, Any]], keyword: str, page: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Форматирует результаты поиска фильмов для отправки в Telegram"""
    from html import escape
    
    lines = ["📽 <b>Результаты поиска</b>:\n"]
    
    for i, film in enumerate(films[:5], 1):
        if not isinstance(film, dict):
            continue
        title = (
            film.get("nameRu")
            or film.get("nameEn")
            or film.get("nameOriginal")
            or film.get("name")
            or "Без названия"
        )
        year = film.get("year") or ""
        rating = (
            film.get("ratingKinopoisk")
            or film.get("ratingImdb")
            or film.get("rating")
            or ""
        )
        film_id = (
            film.get("filmId")
            or film.get("kinopoiskId")
            or film.get("id")
        )
        description = (
            film.get("description")
            or film.get("shortDescription")
            or ""
        )
        
        title_e = escape(str(title))
        year_e = escape(str(year)) if year else ""
        rating_e = escape(str(rating)) if rating else ""
        id_e = escape(str(film_id)) if film_id is not None else ""
        desc_e = escape(str(description)) if description else ""
        
        line = f"{i}. <b>{title_e}</b>"
        if year_e:
            line += f" ({year_e})"
        if rating_e:
            line += f" — рейтинг: {rating_e}"
        if id_e:
            line += f" — ID: <code>{id_e}</code>"
        if desc_e:
            max_len = 200
            short_desc = desc_e if len(desc_e) <= max_len else desc_e[: max_len - 1] + "…"
            line += f"\n    {short_desc}"
        
        lines.append(line)
    
    # Кнопка "Следующая" для перехода на следующую страницу
    next_page = page + 1
    callback_data = f"kp_search:{keyword}:{next_page}"
    keyboard = [[InlineKeyboardButton("Следующая", callback_data=callback_data)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = "\n".join(lines)
    return message, reply_markup


async def notion_tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /notion_tools для вывода списка доступных инструментов Notion"""
    logger.info(
        "Пользователь %s запросил использование MCP Notion (list_notion_tools)",
        update.effective_user.id,
    )
    await update.message.reply_text("🔍 Получаю список инструментов Notion...")
    
    try:
        from mcp_client import list_notion_tools, get_last_error
        
        tools = await list_notion_tools()
        
        if not tools:
            error_info = get_last_error()
            error_msg = _handle_tools_command_error(
                error_info,
                "❌ Не удалось получить список инструментов Notion.\n\n"
                "Возможные причины:\n"
                "• MCP сервер Notion не установлен или не настроен\n"
                "• Команда MCP_NOTION_COMMAND неверна в .env файле\n"
                "• Ошибка подключения к MCP серверу\n\n"
                "Проверьте логи для получения дополнительной информации."
            )
            await update.message.reply_text(error_msg)
            return
        
        # Форматируем список инструментов
        full_message = format_tools_list(tools, "Notion")
        
        # Разбиваем на части, если нужно
        message_parts = split_long_message(full_message)
        for part in message_parts:
            await update.message.reply_text(part, parse_mode='HTML')
        
        logger.info(f"Пользователь {update.effective_user.id} запросил список инструментов Notion, получено {len(tools)} инструментов")
        
    except ImportError as e:
        error_msg = str(e)
        if 'mcp' in error_msg:
            logger.error(f"Ошибка импорта mcp: {e}")
            await update.message.reply_text(
                "❌ Библиотека mcp не установлена.\n\n"
                "Для установки выполните:\n"
                "```\n"
                "pip install mcp\n"
                "```\n\n"
                "Или установите все зависимости:\n"
                "```\n"
                "pip install -r requirements.txt\n"
                "```"
            )
        else:
            logger.error(f"Ошибка импорта mcp_client: {e}")
            await update.message.reply_text(
                f"❌ Ошибка импорта: {e}\n\n"
                "Установите зависимости: pip install -r requirements.txt"
            )
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /notion_tools: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка при получении списка инструментов:\n{str(e)}"
        )


async def kinopoisk_tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /kinopoisk_tools для вывода списка инструментов Kinopoisk MCP"""
    logger.info(
        "Пользователь %s запросил использование MCP Kinopoisk (list_kinopoisk_tools)",
        update.effective_user.id,
    )
    await update.message.reply_text("🔍 Получаю список инструментов Kinopoisk...")
    
    try:
        from mcp_kinopoisk_client import list_kinopoisk_tools, get_kinopoisk_last_error
        
        tools = await list_kinopoisk_tools()
        
        if not tools:
            error_info = get_kinopoisk_last_error()
            error_msg = _handle_tools_command_error(
                error_info,
                "❌ Не удалось получить список инструментов Kinopoisk.\n\n"
                "Возможные причины:\n"
                "• MCP сервер Kinopoisk не найден или не запускается\n"
                "• Неверно указан путь в MCP_KINOPOISK_ARGS\n"
                "• Не указан KINOPOISK_API_KEY\n\n"
                "Проверьте логи для получения дополнительной информации."
            )
            await update.message.reply_text(error_msg)
            return
        
        # Форматируем список инструментов
        full_message = format_tools_list(tools, "Kinopoisk MCP")
        
        # Разбиваем на части, если нужно
        message_parts = split_long_message(full_message)
        for part in message_parts:
            await update.message.reply_text(part, parse_mode='HTML')
        
        logger.info(
            f"Пользователь {update.effective_user.id} запросил список инструментов Kinopoisk MCP, "
            f"получено {len(tools)} инструментов"
        )
    
    except ImportError as e:
        error_msg = str(e)
        if 'mcp' in error_msg:
            logger.error(f"Ошибка импорта mcp: {e}")
            await update.message.reply_text(
                "❌ Библиотека mcp не установлена.\n\n"
                "Для установки выполните:\n"
                "```\n"
                "pip install mcp\n"
                "```\n\n"
                "Или установите все зависимости:\n"
                "```\n"
                "pip install -r requirements.txt\n"
                "```"
            )
        else:
            logger.error(f"Ошибка импорта mcp_kinopoisk_client: {e}")
            await update.message.reply_text(
                f"❌ Ошибка импорта: {e}\n\n"
                "Установите зависимости: pip install -r requirements.txt"
            )
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /kinopoisk_tools: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка при получении списка инструментов Kinopoisk:\n{str(e)}"
        )


async def news_tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /news_tools для вывода списка инструментов News MCP"""
    logger.info(
        "Пользователь %s запросил использование MCP News (list_news_tools)",
        update.effective_user.id,
    )
    await update.message.reply_text("🔍 Получаю список инструментов News...")
    
    try:
        from mcp_news_client import list_news_tools, get_news_last_error
        
        tools = await list_news_tools()
        
        if not tools:
            error_info = get_news_last_error()
            error_msg = _handle_tools_command_error(
                error_info,
                "❌ Не удалось получить список инструментов News.\n\n"
                "Возможные причины:\n"
                "• MCP сервер News не найден или не запускается\n"
                "• Неверно указан путь в MCP_NEWS_ARGS\n"
                "• Не указан NEWS_API_KEY\n\n"
                "Проверьте логи для получения дополнительной информации."
            )
            await update.message.reply_text(error_msg)
            return
        
        # Форматируем список инструментов
        full_message = format_tools_list(tools, "News MCP")
        
        # Разбиваем на части, если нужно
        message_parts = split_long_message(full_message)
        for part in message_parts:
            await update.message.reply_text(part, parse_mode='HTML')
        
        logger.info(
            f"Пользователь {update.effective_user.id} запросил список инструментов News MCP, "
            f"получено {len(tools)} инструментов"
        )
    
    except ImportError as e:
        error_msg = str(e)
        if 'mcp' in error_msg:
            logger.error(f"Ошибка импорта mcp: {e}")
            await update.message.reply_text(
                "❌ Библиотека mcp не установлена.\n\n"
                "Для установки выполните:\n"
                "```\n"
                "pip install mcp\n"
                "```\n\n"
                "Или установите все зависимости:\n"
                "```\n"
                "pip install -r requirements.txt\n"
                "```"
            )
        else:
            logger.error(f"Ошибка импорта mcp_news_client: {e}")
            await update.message.reply_text(
                f"❌ Ошибка импорта: {e}\n\n"
                "Установите зависимости: pip install -r requirements.txt"
            )
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /news_tools: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка при получении списка инструментов News:\n{str(e)}"
        )


async def kp_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск фильмов на Кинопоиске по ключевому слову через MCP."""
    from mcp_kinopoisk_client import call_kinopoisk_tool, get_kinopoisk_last_error

    if not context.args:
        await update.message.reply_text(
            "Использование:\n"
            "/kp_search <ключевое_слово> [страница]\n\n"
            "Примеры:\n"
            "/kp_search Интерстеллар\n"
            "/kp_search Гарри Поттер 2"
        )
        return

    # Последний аргумент можно трактовать как номер страницы, если это число
    *keyword_parts, last_arg = context.args if len(context.args) > 1 else (context.args[0],)
    page = 1
    if isinstance(last_arg, str) and last_arg.isdigit() and len(context.args) > 1:
        page = int(last_arg)
        keyword = " ".join(keyword_parts).strip()
    else:
        keyword = " ".join(context.args).strip()

    if not keyword:
        await update.message.reply_text(
            "Пожалуйста, укажи ключевое слово для поиска.\n"
            "Пример: /kp_search Интерстеллар"
        )
        return

    user_id = update.effective_user.id
    logger.info(
        "Пользователь %s инициировал MCP Kinopoisk поиск (search_movie): keyword=%r, page=%s",
        user_id,
        keyword,
        page,
    )
    await update.message.reply_text(f"🎬 Ищу фильмы по запросу: {keyword!r} (страница {page})...")

    try:
        raw_result = await call_kinopoisk_tool(
            "search_movie",
            {"keyword": keyword, "page": page},
        )

        if not raw_result:
            error_info = get_kinopoisk_last_error()
            if error_info:
                _, error_msg = error_info
                await update.message.reply_text(f"❌ Ошибка при вызове MCP Kinopoisk:\n{error_msg}")
            else:
                await update.message.reply_text(
                    "❌ Не удалось получить результаты поиска от MCP Kinopoisk."
                )
            return

        # Логируем сырой ответ MCP Kinopoisk (с обрезкой, чтобы не раздуть логи)
        logger.info(
            "Raw MCP Kinopoisk response for keyword=%r, page=%s: %s",
            keyword,
            page,
            str(raw_result)[:2000],
        )

        # Пытаемся распарсить JSON-ответ
        try:
            data = json.loads(raw_result)
        except Exception:
            # Логируем полный (но обрезанный) сырой ответ при ошибке парсинга
            logger.error(
                "Не удалось распарсить JSON от MCP Kinopoisk. raw_result=%s",
                str(raw_result)[:2000],
                exc_info=True,
            )
            # Если формат неожиданный — просто выводим часть сырого ответа
            await update.message.reply_text(
                "⚠️ Не удалось распарсить ответ как JSON. Показываю сырой ответ:\n\n"
                f"{str(raw_result)[:3500]}"
            )
            return

        # В ответе Кинопоиска обычно есть список фильмов в полях films / items / results
        films = (
            data.get("films")
            or data.get("items")
            or data.get("results")
            or []
        )

        if not films:
            # Логируем случай, когда фильмов нет, но ответ формально корректный
            logger.info(
                "По запросу к MCP Kinopoisk ничего не найдено. keyword=%r, page=%s, raw_result=%s",
                keyword,
                page,
                str(raw_result)[:2000],
            )
            await update.message.reply_text("Ничего не найдено по этому запросу 😔")
            return

        # Формируем компактный список (топ-5 результатов)
        message, reply_markup = _format_film_search_results(films, keyword, page)
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /kp_search: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Произошла ошибка при поиске фильмов:\n{str(e)}"
        )


async def kp_search_pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для листания результатов /kp_search по страницам."""
    from mcp_kinopoisk_client import call_kinopoisk_tool, get_kinopoisk_last_error

    query = update.callback_query
    if query is None:
        return

    data = query.data or ""
    if not data.startswith("kp_search:"):
        return

    await query.answer()

    try:
        _, keyword, page_str = data.split(":", 2)
    except ValueError:
        logger.error("Некорректный формат callback_data для kp_search: %r", data)
        return

    try:
        page = int(page_str)
    except ValueError:
        page = 1

    user_id = query.from_user.id if query.from_user else None
    chat_id = query.message.chat_id if query.message else update.effective_chat.id

    logger.info(
        "Пользователь %s инициировал MCP Kinopoisk пагинацию (search_movie): keyword=%r, page=%s",
        user_id,
        keyword,
        page,
    )

    try:
        raw_result = await call_kinopoisk_tool(
            "search_movie",
            {"keyword": keyword, "page": page},
        )

        if not raw_result:
            error_info = get_kinopoisk_last_error()
            if error_info:
                _, error_msg = error_info
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка при вызове MCP Kinopoisk:\n{error_msg}",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Не удалось получить результаты поиска от MCP Kinopoisk.",
                )
            return

        logger.info(
            "Raw MCP Kinopoisk response (callback) for keyword=%r, page=%s: %s",
            keyword,
            page,
            str(raw_result)[:2000],
        )

        # Пытаемся распарсить JSON-ответ
        try:
            data = json.loads(raw_result)
        except Exception:
            logger.error(
                "Не удалось распарсить JSON от MCP Kinopoisk (callback). raw_result=%s",
                str(raw_result)[:2000],
                exc_info=True,
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ Не удалось распарсить ответ как JSON. "
                    "Показываю сырой ответ:\n\n"
                    f"{str(raw_result)[:3500]}"
                ),
            )
            return

        # В ответе Кинопоиска обычно есть список фильмов в полях films / items / results
        films = (
            data.get("films")
            or data.get("items")
            or data.get("results")
            or []
        )

        if not films:
            logger.info(
                "По запросу к MCP Kinopoisk (callback) ничего не найдено. "
                "keyword=%r, page=%s, raw_result=%s",
                keyword,
                page,
                str(raw_result)[:2000],
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="Ничего не найдено по этому запросу 😔",
            )
            return

        # Формируем компактный список (топ-5 результатов)
        message, reply_markup = _format_film_search_results(films, keyword, page)
        
        # Обновляем существующее сообщение, если оно есть, иначе отправляем новое
        if query.message:
            await query.message.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

    except Exception as e:
        logger.error(
            "Ошибка при обработке callback пагинации /kp_search: %s",
            e,
            exc_info=True,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Произошла ошибка при поиске фильмов:\n{str(e)}",
        )


async def rag_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /rag_mode для переключения режима RAG"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Использование: /rag_mode <режим>\n\n"
            "Доступные режимы:\n"
            "• off - без RAG (обычный режим)\n"
            "• on - с RAG (используется контекст из документов)\n"
            "• compare - сравнение ответов с RAG и без RAG\n"
            "• compare_filter - сравнение ответов с фильтром и без фильтра\n\n"
            "Пример: /rag_mode compare_filter"
        )
        return
    
    mode = context.args[0].strip().lower()
    
    if mode not in ['off', 'on', 'compare', 'compare_filter']:
        await update.message.reply_text(
            "❌ Неверный режим. Используйте: off, on, compare или compare_filter\n\n"
            "Пример: /rag_mode compare_filter"
        )
        return
    
    # Сохраняем режим в user_data
    context.user_data['rag_mode'] = mode
    
    mode_names = {
        'off': 'без RAG',
        'on': 'с RAG',
        'compare': 'сравнение (RAG vs без RAG)',
        'compare_filter': 'сравнение (с фильтром vs без фильтра)'
    }
    
    await update.message.reply_text(
        f"✅ Режим RAG установлен: {mode_names.get(mode, mode)}"
    )
    logger.info(f"Пользователь {update.effective_user.id} установил режим RAG: {mode}")


async def getragmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /getragmode для просмотра текущего режима RAG"""
    # Получаем текущий режим или используем дефолтный (on)
    current_mode = context.user_data.get('rag_mode', 'on')
    is_default = 'rag_mode' not in context.user_data
    
    mode_names = {
        'off': 'без RAG',
        'on': 'с RAG',
        'compare': 'сравнение (RAG vs без RAG)',
        'compare_filter': 'сравнение (с фильтром vs без фильтра)'
    }
    
    mode_text = (
        f"Текущий режим RAG: {mode_names.get(current_mode, current_mode)}"
        f"{' (дефолтный)' if is_default else ''}"
    )
    
    # Добавляем информацию о пороге релевантности, если установлен
    threshold = context.user_data.get('rag_relevance_threshold')
    if threshold is not None:
        mode_text += f"\nПорог релевантности: {threshold:.3f}"
    
    # Добавляем информацию о методе реранкинга, если установлен
    rerank_method = context.user_data.get('rag_rerank_method')
    if rerank_method:
        mode_text += f"\nМетод реранкинга: {rerank_method}"
    
    await update.message.reply_text(mode_text)


async def setragthreshold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /setragthreshold для установки порога релевантности"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Использование: /setragthreshold <порог>\n\n"
            "Порог релевантности должен быть числом от -1.0 до 1.0.\n"
            "Примеры:\n"
            "• /setragthreshold 0.3 - средний порог (рекомендуется)\n"
            "• /setragthreshold 0.5 - высокий порог (строгая фильтрация)\n"
            "• /setragthreshold 0.0 - низкий порог (мягкая фильтрация)\n"
            "• /setragthreshold -1 - отключить фильтрацию\n\n"
            "Чем выше порог, тем более релевантные чанки будут использоваться."
        )
        return
    
    try:
        new_threshold = float(context.args[0])
        
        # Проверяем диапазон
        if new_threshold < -1.0 or new_threshold > 1.0:
            await update.message.reply_text(
                "❌ Порог должен быть в диапазоне от -1.0 до 1.0."
            )
            return
        
        # Сохраняем порог в user_data
        if new_threshold <= -1.0:
            # Отключаем фильтрацию
            if 'rag_relevance_threshold' in context.user_data:
                del context.user_data['rag_relevance_threshold']
            await update.message.reply_text(
                "✅ Фильтрация по порогу релевантности отключена"
            )
        else:
            context.user_data['rag_relevance_threshold'] = new_threshold
            await update.message.reply_text(
                f"✅ Порог релевантности установлен: {new_threshold:.3f}"
            )
        
        logger.info(f"Пользователь {update.effective_user.id} установил порог релевантности: {new_threshold}")
        
    except ValueError:
        await update.message.reply_text(
            "❌ Ошибка: порог должен быть числом.\n"
            "Пример: /setragthreshold 0.3"
        )


async def getragthreshold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /getragthreshold для просмотра текущего порога релевантности"""
    threshold = context.user_data.get('rag_relevance_threshold')
    
    if threshold is None:
        threshold_text = "Порог релевантности не установлен (фильтрация отключена)"
    else:
        threshold_text = f"Текущий порог релевантности: {threshold:.3f}"
    
    await update.message.reply_text(threshold_text)


async def setragrerank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /setragrerank для установки метода реранкинга"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Использование: /setragrerank <метод>\n\n"
            "Доступные методы:\n"
            "• similarity - сортировка по релевантности (по умолчанию)\n"
            "• diversity - убирает дубликаты, оставляет уникальные чанки\n"
            "• hybrid - комбинация similarity и diversity\n"
            "• off - отключить реранкинг\n\n"
            "Пример: /setragrerank diversity"
        )
        return
    
    method = context.args[0].strip().lower()
    
    valid_methods = ['similarity', 'diversity', 'hybrid', 'off', 'none']
    
    if method not in valid_methods:
        await update.message.reply_text(
            f"❌ Неверный метод. Используйте: {', '.join(valid_methods)}\n\n"
            "Пример: /setragrerank diversity"
        )
        return
    
    # Сохраняем метод в user_data
    if method in ['off', 'none']:
        if 'rag_rerank_method' in context.user_data:
            del context.user_data['rag_rerank_method']
        await update.message.reply_text("✅ Реранкинг отключен")
    else:
        context.user_data['rag_rerank_method'] = method
        await update.message.reply_text(f"✅ Метод реранкинга установлен: {method}")
    
    logger.info(f"Пользователь {update.effective_user.id} установил метод реранкинга: {method}")

