"""Обработчик текстовых сообщений"""
import logging
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from constants import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    DEFAULT_MODEL,
    MAX_TOKENS,
    MESSAGES_BEFORE_SUMMARY,
    MAX_RECENT_MESSAGES,
)
from memory import load_memory_from_disk, save_memory_to_disk, clear_memory
from openai_client import query_openai, summarize_conversation
from utils import (
    is_goal_formulated,
    remove_marker_from_answer,
    remove_source_numbers,
    convert_markdown_to_telegram,
)
from config import NOTION_NEWS_PAGE_ID

logger = logging.getLogger(__name__)


async def create_news_summary(news_text: str, model: str, bot) -> Optional[str]:
    """Создает саммари новостей используя ту же логику, что и для ежедневной рассылки"""
    from openai_client import query_openai
    
    system_prompt = (
        "Ты профессиональный ведущий новостей. Создай краткое саммари новостей в стиле "
        "вступительного слова ведущего новостей. Начни с приветствия и краткого обзора основных событий. "
        "Структурируй информацию по темам, выдели самые важные новости. "
        "Будь кратким, но информативным. Используй профессиональный, но понятный язык. "
        "Используй формат Markdown для заголовков и списков. "
        "В конце добавь фразу вроде 'Это были основные новости дня. Хорошего дня!'"
    )
    
    user_prompt = (
        f"Создай краткое саммари новостей в стиле ведущего новостей на основе следующей информации:\n\n"
        f"{news_text}\n\n"
        f"Создай профессиональное вступительное слово ведущего новостей."
    )
    
    logger.info("Создаю саммари новостей с помощью OpenAI...")
    summary, _ = await query_openai(
        user_prompt,
        [],
        system_prompt,
        temperature=0.7,
        model=model,
        max_tokens=2000,
        bot=bot,
        tools=None
    )
    
    if summary:
        logger.info(f"Создано саммари новостей длиной {len(summary)} символов")
        return summary
    else:
        logger.error("Не удалось создать саммари новостей")
        return None


async def save_news_to_notion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Получает новости из News MCP, создает саммари и сохраняет в Notion
    
    Returns:
        bool: True если успешно, False если ошибка
    """
    from mcp_news_client import call_news_tool
    from mcp_client import call_notion_tool, list_notion_tools
    
    try:
        # Шаг 1: Получаем новости из News MCP
        await update.message.reply_text("📰 Получаю свежие новости...")
        logger.info("Получаю новости из News MCP")
        
        news_result = await call_news_tool("get_today_news", {
            "query": "новости",
            "language": "ru",
            "page_size": 10,
            "sort_by": "publishedAt"
        })
        
        if not news_result:
            await update.message.reply_text(
                "❌ Не удалось получить новости. Проверьте настройки NEWS_API_KEY."
            )
            return False
        
        # News MCP возвращает текстовый формат, а не JSON
        # Проверяем, что есть новости
        if not news_result.strip():
            await update.message.reply_text("📰 Новости не найдены.")
            return False
        
        # Шаг 2: Создаем саммари новостей через OpenAI
        await update.message.reply_text("✍️ Создаю саммари новостей...")
        logger.info("Создаю саммари новостей")
        
        # Получаем модель из user_data или используем дефолтную
        model = context.user_data.get('model', DEFAULT_MODEL)
        
        # Используем существующую функцию для создания саммари
        summary = await create_news_summary(news_result, model, context.bot)
        
        if not summary:
            await update.message.reply_text("❌ Не удалось создать саммари новостей.")
            return False
        
        # Шаг 3: Сохраняем саммари в Notion через Notion MCP
        await update.message.reply_text("💾 Сохраняю в Notion...")
        logger.info("Сохраняю саммари в Notion")
        
        # Получаем доступные инструменты Notion
        notion_tools = await list_notion_tools()
        if not notion_tools:
            await update.message.reply_text(
                "❌ Не удалось получить инструменты Notion. Проверьте настройки MCP_NOTION_COMMAND."
            )
            return False
        
        # Ищем инструмент для создания страницы
        # Обычно это create_page или append_block
        tool_names = [tool.get('name', '') for tool in notion_tools]
        logger.info(f"Доступные инструменты Notion: {', '.join(tool_names)}")
        
        # Пробуем использовать create_page или похожий инструмент
        create_page_tool = None
        for tool_name in ['create_page', 'createPage', 'append_block', 'appendBlock']:
            if tool_name in tool_names:
                create_page_tool = tool_name
                break
        
        if not create_page_tool:
            # Если нет явного инструмента, используем LLM с доступными инструментами
            logger.info("Используем LLM для создания страницы в Notion")
            mcp_tools = context.bot_data.get('mcp_tools', [])
            notion_tools_for_llm = [t for t in mcp_tools if t.get('function', {}).get('name', '').startswith('notion_')]
            
            if not notion_tools_for_llm:
                await update.message.reply_text(
                    "❌ Не найдены инструменты Notion для создания страницы."
                )
                return False
            
            # Используем LLM для создания страницы
            # Форматируем page_id в формат с дефисами для Notion API (если нужно)
            # Notion API использует формат: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            # Но в URL может быть без дефисов: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
            news_page_id = NOTION_NEWS_PAGE_ID
            # Если page_id без дефисов (32 символа), добавляем дефисы
            if len(news_page_id) == 32 and '-' not in news_page_id:
                news_page_id = f"{news_page_id[:8]}-{news_page_id[8:12]}-{news_page_id[12:16]}-{news_page_id[16:20]}-{news_page_id[20:]}"
            
            notion_prompt = (
                f"Создай новую страницу в Notion со следующим содержимым:\n\n"
                f"Заголовок: Саммари новостей от {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Содержимое:\n{summary}\n\n"
                f"ВАЖНО: Страницу нужно создать внутри страницы 'Новости' в Notion. "
                f"Используй page_id страницы 'Новости': {news_page_id} "
                f"в параметре parent при создании страницы через notion-create-pages. "
                f"Параметр parent должен быть объектом: {{'page_id': '{news_page_id}'}}."
            )
            
            # Получаем температуру и модель
            temperature = context.user_data.get('temperature', DEFAULT_TEMPERATURE)
            
            # Системный промпт с подробными инструкциями
            system_prompt = (
                "Ты помощник, который создает страницы в Notion. "
                "КРИТИЧЕСКИ ВАЖНО: Для создания страницы в Notion через notion-create-pages ОБЯЗАТЕЛЬНО нужно указать параметр 'parent' "
                "с одним из полей: 'page_id', 'database_id' или 'data_source_id'. "
                f"Используй page_id страницы 'Новости': {news_page_id}. "
                "Структура параметра parent должна быть объектом: {'page_id': 'указанный_page_id'}. "
                "Используй доступные инструменты Notion для создания новой страницы с предоставленным содержимым внутри страницы 'Новости'. "
                "НЕ ищи страницу через search - используй предоставленный page_id напрямую."
            )
            
            # Вызываем LLM с Notion инструментами
            answer, _ = await query_openai(
                notion_prompt,
                [],
                system_prompt,
                temperature,
                model,
                MAX_TOKENS,
                context.bot,
                tools=notion_tools_for_llm
            )
            
            if "ошибка" in answer.lower() or "не удалось" in answer.lower():
                await update.message.reply_text(
                    f"❌ Ошибка при создании страницы в Notion: {answer}"
                )
                return False
            
            await update.message.reply_text(
                f"✅ Саммари новостей успешно сохранено в Notion!\n\n"
                f"📄 {answer}"
            )
            return True
        else:
            # Используем явный инструмент для создания страницы
            page_title = f"Саммари новостей от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            page_content = f"# {page_title}\n\n{summary}"
            
            # Формируем аргументы для создания страницы
            # Структура зависит от конкретного инструмента Notion MCP
            arguments = {
                "title": page_title,
                "content": page_content
            }
            
            result = await call_notion_tool(create_page_tool, arguments)
            
            if not result:
                await update.message.reply_text(
                    "❌ Не удалось создать страницу в Notion."
                )
                return False
            
            await update.message.reply_text(
                f"✅ Саммари новостей успешно сохранено в Notion!\n\n"
                f"📄 Страница создана: {page_title}"
            )
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при сохранении новостей в Notion: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Произошла ошибка: {str(e)}"
        )
        return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_message = update.message.text
    user_id = update.effective_user.id
    
    # Загружаем память с диска (если есть)
    memory_data = load_memory_from_disk(user_id)
    summary = memory_data.get("summary", "")
    recent_messages = memory_data.get("recent_messages", [])
    message_count = memory_data.get("message_count", 0)
    
    # Проверяем, хочет ли пользователь начать заново
    user_message_lower = user_message.lower().strip()
    if user_message_lower in ['стоп', 'стой']:
        # Очищаем память на диске
        clear_memory(user_id)
        logger.info("Пользователь запросил сброс истории диалога")
        await update.message.reply_text("Хорошо, тогда начнём с начала! 🎯")
        return
    
    # Проверяем, хочет ли пользователь сохранить новости в Notion
    save_news_keywords = ['сохрани новости в заметки', 'сохрани новости в notion', 
                         'сохрани новости', 'новости в заметки', 'новости в notion']
    if any(keyword in user_message_lower for keyword in save_news_keywords):
        logger.info(f"Пользователь {user_id} запросил сохранение новостей в Notion")
        success = await save_news_to_notion(update, context)
        if success:
            logger.info(f"Успешно сохранены новости в Notion для пользователя {user_id}")
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
        
        # Получаем доступные MCP инструменты из bot_data (загружены при старте)
        mcp_tools = context.bot_data.get('mcp_tools', [])
        if mcp_tools:
            logger.debug(f"Используется {len(mcp_tools)} MCP инструментов из bot_data")
            # Проверяем наличие News инструментов
            news_tools_available = [t for t in mcp_tools if t.get('function', {}).get('name', '').startswith('news_')]
            if news_tools_available:
                logger.info(f"Доступно {len(news_tools_available)} News инструментов для использования")
            else:
                logger.warning("News инструменты не найдены в списке доступных MCP инструментов")
        
        # Проверяем, спрашивает ли пользователь о новостях
        news_keywords = ['новости', 'новость', 'события', 'событие', 'актуально', 'последнее', 'свежее', 
                        'сегодня', 'вчера', 'происходит', 'случилось', 'произошло', 'что нового']
        user_message_lower_for_news = user_message.lower()
        is_news_question = any(keyword in user_message_lower_for_news for keyword in news_keywords)
        
        if is_news_question and mcp_tools:
            news_tools_available = [t for t in mcp_tools if t.get('function', {}).get('name', '').startswith('news_')]
            if news_tools_available:
                logger.info(f"Обнаружен вопрос о новостях. Доступно {len(news_tools_available)} News инструментов")
        
        # Формируем полную историю: summary (если есть) + recent_messages
        # Если есть summary, объединяем его с системным промптом
        full_system_prompt = system_prompt
        if summary:
            full_system_prompt = f"{system_prompt}\n\nКонтекст предыдущих диалогов:\n{summary}"
        
        # Добавляем информацию о доступных MCP инструментах в системный промпт
        if mcp_tools:
            kinopoisk_tools_info = []
            news_tools_info = []
            kinopoisk_tools_count = 0
            news_tools_count = 0
            
            for tool in mcp_tools:
                tool_func = tool.get('function', {})
                tool_name = tool_func.get('name', '')
                tool_desc = tool_func.get('description', '')
                if tool_name.startswith('kinopoisk_'):
                    kinopoisk_tools_info.append(f"- {tool_name}: {tool_desc}")
                    kinopoisk_tools_count += 1
                elif tool_name.startswith('news_'):
                    news_tools_info.append(f"- {tool_name}: {tool_desc}")
                    news_tools_count += 1
            
            # Добавляем информацию о Kinopoisk инструментах
            if kinopoisk_tools_info and kinopoisk_tools_count > 0:
                tools_prompt = (
                    "\n\n"
                    "КРИТИЧЕСКИ ВАЖНО: У тебя есть доступ к инструментам Kinopoisk для поиска актуальной информации о фильмах. "
                    "Если пользователь спрашивает о фильмах (включая фильмы 2025 года, будущие релизы, поиск фильмов, подборки, рекомендации), "
                    "ТЫ ОБЯЗАН использовать доступные инструменты Kinopoisk. "
                    "НИКОГДА не говори, что у тебя нет информации о фильмах - всегда используй инструменты для получения актуальных данных. "
                    f"Доступно {kinopoisk_tools_count} инструмент(ов) Kinopoisk:\n" + 
                    "\n".join(kinopoisk_tools_info) +
                    "\n\nИспользуй эти инструменты автоматически, когда пользователь спрашивает о фильмах!"
                )
                full_system_prompt += tools_prompt
            
            # Добавляем информацию о News инструментах
            if news_tools_info and news_tools_count > 0:
                news_prompt = (
                    "\n\n"
                    "⚠️ КРИТИЧЕСКИ ВАЖНО - ИНСТРУКЦИИ ПО ИСПОЛЬЗОВАНИЮ ИНСТРУМЕНТОВ NEWS:\n\n"
                    "У тебя ЕСТЬ доступ к инструментам News для получения СВЕЖИХ новостей в реальном времени!\n\n"
                    "ЗАПРЕЩЕНО говорить пользователю, что у тебя нет доступа к новостям или интернету. "
                    "Это НЕПРАВДА - у тебя ЕСТЬ доступ через инструменты News!\n\n"
                    "ОБЯЗАТЕЛЬНО используй инструменты News, если пользователь:\n"
                    "- Спрашивает о новостях, текущих событиях, актуальной информации\n"
                    "- Интересуется последними событиями в мире, политике, технологиях, экономике, спорте\n"
                    "- Просит рассказать о чем-то актуальном, свежем, последнем\n"
                    "- Использует слова: новости, события, актуально, последнее, свежее, сегодня, вчера\n\n"
                    "АЛГОРИТМ ДЕЙСТВИЙ:\n"
                    "1. Когда пользователь спрашивает о новостях - СРАЗУ вызывай инструмент News\n"
                    "2. Извлекай ключевые слова из вопроса пользователя для параметра 'query'\n"
                    "3. Если пользователь не указал язык, используй 'ru' для русскоязычных запросов\n"
                    "4. Получив результаты, сформируй краткое саммари новостей для пользователя\n\n"
                    f"Доступно {news_tools_count} инструмент(ов) News:\n" + 
                    "\n".join(news_tools_info) +
                    "\n\n"
                    "ПРИМЕРЫ:\n"
                    "- Пользователь: 'Какие новости о технологиях?' → Вызывай news_get_today_news с query='технологии', language='ru'\n"
                    "- Пользователь: 'Что происходит в мире?' → Вызывай news_get_today_news с query='мир', language='ru'\n"
                    "- Пользователь: 'Расскажи новости' → Вызывай news_get_today_news с query='новости', language='ru'\n\n"
                    "ПОМНИ: НИКОГДА не говори, что не можешь получить новости. ВСЕГДА используй инструменты!"
                )
                full_system_prompt += news_prompt
        
        full_conversation_history = recent_messages.copy()
        
        # Если это вопрос о новостях и есть News инструменты, добавляем явное указание в сообщение
        enhanced_user_message = user_message
        if is_news_question and mcp_tools:
            news_tools_available = [t for t in mcp_tools if t.get('function', {}).get('name', '').startswith('news_')]
            if news_tools_available:
                # Добавляем явное указание использовать инструмент News
                enhanced_user_message = (
                    f"{user_message}\n\n"
                    "ВАЖНО: Используй доступный инструмент News для получения актуальных новостей. "
                    "НЕ говори, что у тебя нет доступа к новостям - используй инструмент!"
                )
                logger.info("Добавлено явное указание использовать News инструмент в запросе пользователя")
        
        # Получаем ответ от OpenAI с полной историей диалога и MCP инструментами
        answer, updated_history = await query_openai(
            enhanced_user_message,
            full_conversation_history,
            full_system_prompt,
            temperature,
            model,
            max_tokens,
            context.bot,
            tools=mcp_tools if mcp_tools else None
        )
        
        # Удаляем сообщение "Думаю..."
        await thinking_message.delete()
        
        # Обрабатываем ответ для всех моделей
        # Проверяем, сформулировал ли бот финальную цель
        goal_formulated = is_goal_formulated(answer)
        
        if goal_formulated:
            # Очищаем память на диске после формулировки цели
            clear_memory(user_id)
            logger.info("Цель сформулирована, память очищена")
            # Удаляем маркер из ответа перед отправкой пользователю
            answer = remove_marker_from_answer(answer)
        else:
            # Добавляем новое сообщение в recent_messages
            recent_messages.append({"role": "user", "content": user_message})
            recent_messages.append({"role": "assistant", "content": answer})
            
            # Увеличиваем счетчик сообщений
            message_count += 1
            
            # Если достигли порога саммаризации
            if message_count >= MESSAGES_BEFORE_SUMMARY:
                # Саммаризируем текущую историю (summary + recent_messages)
                # Формируем полную историю для саммаризации
                history_to_summarize = []
                if summary:
                    # Добавляем старый summary как контекст
                    history_to_summarize.append({
                        "role": "user",
                        "content": f"Контекст предыдущих диалогов: {summary}"
                    })
                    history_to_summarize.append({
                        "role": "assistant",
                        "content": "Понял, продолжаю диалог с учетом этого контекста."
                    })
                # Добавляем недавние сообщения
                history_to_summarize.extend(recent_messages)
                
                # Создаем саммари всей истории
                new_summary = await summarize_conversation(history_to_summarize, model, context.bot)
                
                # Очищаем recent_messages и сбрасываем счетчик только если саммаризация успешна
                if new_summary and new_summary.strip():
                    # Объединяем новый саммари со старым (накопление)
                    if summary:
                        combined_summary = f"{summary}\n\n{new_summary}"
                    else:
                        combined_summary = new_summary
                    
                    # Обновляем память только при успешной саммаризации
                    summary = combined_summary
                    recent_messages = []
                    message_count = 0
                    
                    logger.info(f"Выполнена саммаризация для пользователя {user_id}")
                else:
                    # Если саммаризация не удалась, сохраняем сообщения и продолжаем накапливать
                    logger.warning(f"Саммаризация не удалась для пользователя {user_id}, сообщения сохранены")
                    
                    # Защита от неограниченного роста: если recent_messages слишком большой,
                    # принудительно очищаем старые сообщения, оставляя только последние
                    if len(recent_messages) > MAX_RECENT_MESSAGES:
                        # Оставляем только последние MAX_RECENT_MESSAGES сообщений
                        recent_messages = recent_messages[-MAX_RECENT_MESSAGES:]
                        logger.warning(
                            f"Превышен лимит recent_messages для пользователя {user_id}. "
                            f"Оставлены только последние {MAX_RECENT_MESSAGES} сообщений."
                        )
                    
                    # Сбрасываем message_count на 0, чтобы не пытаться саммаризировать при каждом сообщении
                    # Будем пытаться снова, когда накопится еще MESSAGES_BEFORE_SUMMARY сообщений
                    message_count = 0
            
            # Сохраняем память на диск сразу после обработки сообщений и саммаризации
            # Это гарантирует сохранение даже если произойдет ошибка при форматировании или отправке
            memory_data = {
                "summary": summary,
                "recent_messages": recent_messages,
                "message_count": message_count
            }
            save_memory_to_disk(user_id, memory_data)
        
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
        
        # Сохраняем память даже при ошибке, если сообщения были добавлены
        # Это защита от потери данных при ошибках форматирования или отправки
        try:
            # Проверяем, были ли добавлены новые сообщения до ошибки
            # Если goal_formulated был False, значит сообщения должны были быть добавлены
            # Загружаем текущее состояние и проверяем, нужно ли сохранить
            current_memory = load_memory_from_disk(user_id)
            current_recent_messages = current_memory.get("recent_messages", [])
            current_message_count = current_memory.get("message_count", 0)
            
            # Если в локальных переменных есть recent_messages с новыми сообщениями,
            # и они отличаются от сохраненных, значит нужно сохранить
            if 'recent_messages' in locals() and 'message_count' in locals():
                # Проверяем, были ли добавлены новые сообщения (сравниваем длины)
                if len(recent_messages) > len(current_recent_messages) or message_count > current_message_count:
                    memory_data = {
                        "summary": summary if 'summary' in locals() else current_memory.get("summary", ""),
                        "recent_messages": recent_messages,
                        "message_count": message_count
                    }
                    save_memory_to_disk(user_id, memory_data)
                    logger.info(f"Сохранена память после ошибки для пользователя {user_id}")
        except Exception as save_error:
            logger.error(f"Ошибка при сохранении памяти после исключения: {save_error}")
        
        await update.message.reply_text(
            "Извините, произошла ошибка при обработке вашего запроса. "
            "Попробуйте еще раз позже."
        )
