"""Обработчик текстовых сообщений"""
import logging
import re
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
    split_long_message,
)
import utils  # Импортируем модуль целиком для надежности
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
        
        # Проверяем режим RAG (по умолчанию включен)
        rag_mode = context.user_data.get('rag_mode', 'on')
        
        # Получаем настройки фильтрации и реранкинга
        relevance_threshold = context.user_data.get('rag_relevance_threshold')
        rerank_method = context.user_data.get('rag_rerank_method')
        
        # Получаем ответ в зависимости от режима RAG
        if rag_mode == 'compare_filter':
            # Режим сравнения с фильтром и без фильтра
            from rag import compare_rag_with_and_without_filter
            
            # Используем порог по умолчанию, если не установлен
            if relevance_threshold is None:
                relevance_threshold = 0.3  # Порог по умолчанию
            
            await thinking_message.edit_text("🤔 Получаю ответы с фильтром и без фильтра для сравнения...")
            
            comparison_result = await compare_rag_with_and_without_filter(
                enhanced_user_message,
                full_conversation_history,
                full_system_prompt,
                temperature,
                model,
                max_tokens,
                context.bot,
                tools=mcp_tools if mcp_tools else None,
                relevance_threshold=relevance_threshold,
                rerank_method=rerank_method
            )
            
            answer_without_filter = comparison_result['answer_without_filter']
            answer_with_filter = comparison_result['answer_with_filter']
            comparison = comparison_result['comparison']
            
            # Форматируем ответы
            answer_without_filter_formatted = utils.convert_markdown_to_telegram(answer_without_filter)
            answer_with_filter_formatted = utils.convert_markdown_to_telegram(answer_with_filter)
            comparison_formatted = utils.convert_markdown_to_telegram(comparison)
            
            # Отправляем результаты сравнения
            await thinking_message.delete()
            
            # Отправляем ответ без фильтра
            await update.message.reply_text(
                "<b>📝 Ответ БЕЗ фильтра:</b>\n\n" + answer_without_filter_formatted,
                parse_mode='HTML'
            )
            
            # Отправляем ответ с фильтром
            await update.message.reply_text(
                f"<b>🔍 Ответ С фильтром (порог: {relevance_threshold:.3f}):</b>\n\n" + answer_with_filter_formatted,
                parse_mode='HTML'
            )
            
            # Отправляем анализ сравнения
            comparison_parts = split_long_message(comparison_formatted, max_length=4000)
            for i, part in enumerate(comparison_parts, 1):
                if len(comparison_parts) > 1:
                    header = f"<b>📊 Анализ сравнения (часть {i} из {len(comparison_parts)}):</b>\n\n"
                else:
                    header = "<b>📊 Анализ сравнения:</b>\n\n"
                await update.message.reply_text(header + part, parse_mode='HTML')
            
            # Используем ответ с фильтром для обновления истории
            answer = answer_with_filter
            updated_history = full_conversation_history.copy()
            updated_history.append({"role": "user", "content": enhanced_user_message})
            updated_history.append({"role": "assistant", "content": answer_with_filter})
            
            # Обрабатываем историю для сохранения памяти (аналогично режиму compare)
            goal_formulated = is_goal_formulated(answer)
            
            if goal_formulated:
                clear_memory(user_id)
                logger.info("Цель сформулирована, память очищена (режим сравнения с фильтром)")
            else:
                recent_messages.append({"role": "user", "content": user_message})
                recent_messages.append({"role": "assistant", "content": answer})
                message_count += 1
                
                if message_count >= MESSAGES_BEFORE_SUMMARY:
                    history_to_summarize = []
                    if summary:
                        history_to_summarize.append({
                            "role": "user",
                            "content": f"Контекст предыдущих диалогов: {summary}"
                        })
                        history_to_summarize.append({
                            "role": "assistant",
                            "content": "Понял, продолжаю диалог с учетом этого контекста."
                        })
                    history_to_summarize.extend(recent_messages)
                    
                    new_summary = await summarize_conversation(history_to_summarize, model, context.bot)
                    
                    if new_summary and new_summary.strip():
                        if summary:
                            combined_summary = f"{summary}\n\n{new_summary}"
                        else:
                            combined_summary = new_summary
                        summary = combined_summary
                        recent_messages = []
                        message_count = 0
                        logger.info(f"Выполнена саммаризация для пользователя {user_id}")
                    else:
                        if len(recent_messages) > MAX_RECENT_MESSAGES:
                            recent_messages = recent_messages[-MAX_RECENT_MESSAGES:]
                        message_count = 0
                
                memory_data = {
                    "summary": summary,
                    "recent_messages": recent_messages,
                    "message_count": message_count
                }
                save_memory_to_disk(user_id, memory_data)
            
            return  # Выходим, так как уже отправили все результаты
            
        elif rag_mode == 'compare':
            # Режим сравнения: получаем оба ответа и сравниваем
            from rag import compare_rag_vs_no_rag
            
            await thinking_message.edit_text("🤔 Получаю ответы с RAG и без RAG для сравнения...")
            
            comparison_result = await compare_rag_vs_no_rag(
                enhanced_user_message,
                full_conversation_history,
                full_system_prompt,
                temperature,
                model,
                max_tokens,
                context.bot,
                tools=mcp_tools if mcp_tools else None
            )
            
            answer_without_rag = comparison_result['answer_without_rag']
            answer_with_rag = comparison_result['answer_with_rag']
            comparison = comparison_result['comparison']
            
            # Форматируем ответы
            answer_without_rag_formatted = utils.convert_markdown_to_telegram(answer_without_rag)
            answer_with_rag_formatted = utils.convert_markdown_to_telegram(answer_with_rag)
            comparison_formatted = utils.convert_markdown_to_telegram(comparison)
            
            # Отправляем результаты сравнения
            await thinking_message.delete()
            
            # Отправляем ответ без RAG
            await update.message.reply_text(
                "<b>📝 Ответ БЕЗ RAG:</b>\n\n" + answer_without_rag_formatted,
                parse_mode='HTML'
            )
            
            # Отправляем ответ с RAG
            await update.message.reply_text(
                "<b>📚 Ответ С RAG:</b>\n\n" + answer_with_rag_formatted,
                parse_mode='HTML'
            )
            
            # Отправляем анализ сравнения
            comparison_parts = split_long_message(comparison_formatted, max_length=4000)
            for i, part in enumerate(comparison_parts, 1):
                if len(comparison_parts) > 1:
                    header = f"<b>📊 Анализ сравнения (часть {i} из {len(comparison_parts)}):</b>\n\n"
                else:
                    header = "<b>📊 Анализ сравнения:</b>\n\n"
                await update.message.reply_text(header + part, parse_mode='HTML')
            
            # Используем ответ с RAG для обновления истории
            answer = answer_with_rag
            updated_history = full_conversation_history.copy()
            updated_history.append({"role": "user", "content": enhanced_user_message})
            updated_history.append({"role": "assistant", "content": answer_with_rag})
            
            # В режиме сравнения сообщение "Думаю..." уже удалено выше
            # Пропускаем обычную обработку ответа, так как уже отправили результаты
            # Но нужно обработать историю для сохранения памяти
            goal_formulated = is_goal_formulated(answer)
            
            if goal_formulated:
                # Очищаем память на диске после формулировки цели
                clear_memory(user_id)
                logger.info("Цель сформулирована, память очищена (режим сравнения)")
            else:
                # Добавляем новое сообщение в recent_messages
                recent_messages.append({"role": "user", "content": user_message})
                recent_messages.append({"role": "assistant", "content": answer})
                
                # Увеличиваем счетчик сообщений
                message_count += 1
                
                # Если достигли порога саммаризации
                if message_count >= MESSAGES_BEFORE_SUMMARY:
                    # Саммаризируем текущую историю
                    history_to_summarize = []
                    if summary:
                        history_to_summarize.append({
                            "role": "user",
                            "content": f"Контекст предыдущих диалогов: {summary}"
                        })
                        history_to_summarize.append({
                            "role": "assistant",
                            "content": "Понял, продолжаю диалог с учетом этого контекста."
                        })
                    history_to_summarize.extend(recent_messages)
                    
                    new_summary = await summarize_conversation(history_to_summarize, model, context.bot)
                    
                    if new_summary and new_summary.strip():
                        if summary:
                            combined_summary = f"{summary}\n\n{new_summary}"
                        else:
                            combined_summary = new_summary
                        summary = combined_summary
                        recent_messages = []
                        message_count = 0
                        logger.info(f"Выполнена саммаризация для пользователя {user_id}")
                    else:
                        if len(recent_messages) > MAX_RECENT_MESSAGES:
                            recent_messages = recent_messages[-MAX_RECENT_MESSAGES:]
                        message_count = 0
                
                # Сохраняем память
                memory_data = {
                    "summary": summary,
                    "recent_messages": recent_messages,
                    "message_count": message_count
                }
                save_memory_to_disk(user_id, memory_data)
            
            return  # Выходим, так как уже отправили все результаты
            
        elif rag_mode == 'on':
            # Режим с RAG: используем query_with_rag
            from rag import query_with_rag, format_sources_for_display
            
            answer, updated_history, sources = await query_with_rag(
                enhanced_user_message,
                full_conversation_history,
                full_system_prompt,
                temperature,
                model,
                max_tokens,
                context.bot,
                tools=mcp_tools if mcp_tools else None,
                relevance_threshold=relevance_threshold,
                rerank_method=rerank_method,
                use_filter=(relevance_threshold is not None)
            )
        else:
            # Режим без RAG (off или не установлен): используем обычный запрос
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
            sources = []  # Нет источников в режиме без RAG
        
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
        
        # Проверяем, использовался ли logs инструмент в этом запросе
        # Проверяем историю на наличие вызовов logs инструментов и их результаты
        logs_tool_used = False
        logs_tool_result = None
        if updated_history:
            for msg in updated_history:
                tool_name = msg.get("name", "")
                if msg.get("role") == "tool" and tool_name.startswith("logs_"):
                    logs_tool_used = True
                    logs_tool_result = msg.get("content", "")
                    logger.info(f"Обнаружен вызов logs инструмента: {tool_name}, длина результата: {len(str(logs_tool_result)) if logs_tool_result else 0}")
                    # Логируем первые 200 символов результата для отладки
                    if logs_tool_result:
                        preview = str(logs_tool_result)[:200]
                        logger.debug(f"Превью результата logs инструмента: {preview}...")
                    break
        
        # Логируем ответ для отладки
        logger.debug(f"Ответ от LLM (первые 300 символов): {answer[:300] if len(answer) > 300 else answer}")
        
        # Если использовался logs инструмент, проверяем, есть ли реальные логи
        # Паттерн для определения логов: timestamp формата "Dec 19 06:59:56" или "MMM DD HH:MM:SS"
        # Используем один паттерн для всех проверок
        log_pattern = r'[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}'
        
        # Проверяем, содержит ли результат инструмента реальные логи
        logs_tool_has_logs = False
        if logs_tool_result:
            # Убираем markdown code блоки из результата инструмента для проверки
            tool_result_clean = str(logs_tool_result).replace("```", "").strip()
            logs_tool_has_logs = bool(re.search(log_pattern, tool_result_clean))
            logger.info(f"Проверка результата logs инструмента: содержит логи={logs_tool_has_logs}, длина={len(tool_result_clean)}")
        
        # Проверяем, содержит ли ответ LLM реальные логи
        answer_has_logs = bool(re.search(log_pattern, answer))
        
        # Если использовался logs инструмент и в ответе нет code блоков, добавляем их
        # НО только если есть реальные логи (либо в результате инструмента, либо в ответе LLM)
        if logs_tool_used and "```" not in answer and (logs_tool_has_logs or answer_has_logs):
            if answer_has_logs:
                # Если ответ содержит логи, оборачиваем их в code блок
                # Но сначала убираем возможные предисловия от LLM
                lines = answer.split('\n')
                log_start = None
                for i, line in enumerate(lines):
                    if re.search(log_pattern, line):
                        log_start = i
                        break
                
                if log_start is not None and log_start > 0:
                    # Есть предисловие от LLM
                    preface = '\n'.join(lines[:log_start])
                    log_content = '\n'.join(lines[log_start:])
                    answer = f"{preface}\n\n```\n{log_content}\n```"
                elif log_start == 0:
                    # Весь ответ - это логи
                    answer = f"```\n{answer}\n```"
            elif logs_tool_has_logs:
                # Если логи есть в результате инструмента, но LLM их переформатировала,
                # оборачиваем весь ответ в code блок
                logger.info("Logs инструмент вернул логи, но LLM переформатировала ответ. Оборачиваю весь ответ в code блок.")
                answer = f"```\n{answer}\n```"
        elif logs_tool_used and not logs_tool_has_logs and not answer_has_logs:
            # Инструмент использован, но реальных логов нет (пустой результат или ошибка)
            logger.info("Logs инструмент использован, но реальных логов не обнаружено. Не оборачиваю ответ в code блок.")
        
        # Проверяем наличие паттерна логов в исходном ответе ДО форматирования
        # Используем тот же паттерн, что был определен выше
        has_log_pattern_in_answer = bool(re.search(log_pattern, answer))
        
        # Преобразуем markdown в форматирование Telegram
        # Используем полный путь для надежности
        formatted_answer = utils.convert_markdown_to_telegram(answer)
        
        # Проверяем, что ответ не пустой
        if not formatted_answer or not formatted_answer.strip():
            await update.message.reply_text(
                "Извините, не удалось получить ответ от модели. Попробуйте еще раз."
            )
            logger.warning(f"Получен пустой ответ от модели {model}")
            return
        
        # Проверяем, содержит ли ответ логи (по наличию <pre> блоков или паттернов логов)
        # Ищем паттерн как в исходном ответе, так и внутри <pre> блоков в отформатированном ответе
        has_pre_tag = '<pre>' in formatted_answer
        
        # Ищем паттерн внутри <pre> блоков (после экранирования HTML)
        # Извлекаем содержимое всех <pre> блоков и ищем паттерн там
        pre_blocks = re.findall(r'<pre>(.*?)</pre>', formatted_answer, re.DOTALL)
        has_log_pattern_in_pre = False
        for pre_content in pre_blocks:
            # Декодируем HTML entities для поиска паттерна
            pre_content_decoded = pre_content.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            if re.search(log_pattern, pre_content_decoded):
                has_log_pattern_in_pre = True
                break
        
        # Также ищем паттерн во всем отформатированном ответе (на случай, если логи не в <pre>)
        has_log_pattern_in_formatted = bool(re.search(log_pattern, formatted_answer))
        
        # Объединяем все проверки
        # Учитываем, что если инструмент logs вернул пустой результат, то не считаем ответ логами
        has_log_pattern = has_log_pattern_in_answer or has_log_pattern_in_pre or has_log_pattern_in_formatted
        # has_logs = True только если есть реальные логи (паттерн или <pre> с логами), 
        # или если инструмент logs использован И вернул непустой результат с логами
        has_logs = has_pre_tag or has_log_pattern or (logs_tool_used and logs_tool_has_logs)
        
        logger.info(f"Проверка логов: logs_tool_used={logs_tool_used}, logs_tool_has_logs={logs_tool_has_logs}, has_pre_tag={has_pre_tag}, has_log_pattern={has_log_pattern}, has_logs={has_logs}, длина ответа={len(formatted_answer)}")
        
        # Если использовался logs инструмент, но нет <pre> блоков, значит LLM убрала форматирование
        # В этом случае нужно найти логи в ответе и обернуть их в <pre>
        if logs_tool_used and '<pre>' not in formatted_answer:
            logger.info("Logs инструмент использован, но <pre> блоков нет. Ищу логи в ответе...")
            # Ищем логи по паттерну timestamp
            log_match = re.search(log_pattern, formatted_answer)
            if log_match:
                # Находим начало логов
                log_start_pos = log_match.start()
                # Разделяем на предисловие и логи
                preface = formatted_answer[:log_start_pos].strip()
                log_content = formatted_answer[log_start_pos:].strip()
                
                # Экранируем HTML в содержимом логов
                log_content_escaped = log_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                # Формируем новый ответ с <pre> блоками
                if preface:
                    formatted_answer = f"{preface}\n\n<pre>{log_content_escaped}</pre>"
                else:
                    formatted_answer = f"<pre>{log_content_escaped}</pre>"
                has_logs = True
                logger.info(f"Логи найдены и обернуты в <pre>. Длина: {len(formatted_answer)}")
            else:
                # Если паттерн не найден, но logs инструмент использован, 
                # значит весь ответ - это логи (LLM могла переформатировать)
                logger.info("Паттерн логов не найден, но logs инструмент использован. Оборачиваю весь ответ в <pre>.")
                log_content_escaped = formatted_answer.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                formatted_answer = f"<pre>{log_content_escaped}</pre>"
                has_logs = True
        
        # Отправляем ответ пользователю с HTML форматированием
        if has_logs:
            # Для логов разбиваем на части по 3500 символов (с запасом для HTML тегов)
            # Используем функцию split_long_message для правильного разбиения
            message_parts = split_long_message(formatted_answer, max_length=3500)
            
            logger.info(f"Логи обнаружены, разбиваю на {len(message_parts)} частей. Длина исходного сообщения: {len(formatted_answer)}")
            for i, part in enumerate(message_parts, 1):
                logger.info(f"Часть {i}: длина = {len(part)} символов")
            
            # Отправляем каждую часть отдельным сообщением
            for i, part in enumerate(message_parts, 1):
                try:
                    if len(message_parts) > 1:
                        # Добавляем номер части, если сообщений несколько
                        part_with_header = f"<i>Часть {i} из {len(message_parts)}</i>\n\n{part}"
                    else:
                        part_with_header = part
                    
                    logger.info(f"Отправляю часть {i} из {len(message_parts)} (длина: {len(part_with_header)} символов)")
                    await update.message.reply_text(part_with_header, parse_mode='HTML')
                    logger.info(f"Часть {i} успешно отправлена")
                except Exception as e:
                    logger.error(f"Ошибка при отправке части {i} из {len(message_parts)}: {e}", exc_info=True)
                    # Пытаемся отправить без заголовка, если была ошибка
                    try:
                        await update.message.reply_text(part, parse_mode='HTML')
                        logger.info(f"Часть {i} отправлена без заголовка")
                    except Exception as e2:
                        logger.error(f"Ошибка при отправке части {i} без заголовка: {e2}", exc_info=True)
        else:
            # Для обычных ответов используем стандартное разбиение
            if len(formatted_answer) > 4000:
                # Отправляем первую часть
                await update.message.reply_text(formatted_answer[:4000], parse_mode='HTML')
                # Отправляем оставшуюся часть
                await update.message.reply_text(formatted_answer[4000:], parse_mode='HTML')
            else:
                await update.message.reply_text(formatted_answer, parse_mode='HTML')
        
        # Выводим источники, если они есть (только для режима RAG)
        if sources and rag_mode == 'on':
            sources_text = format_sources_for_display(sources)
            if sources_text:
                sources_formatted = utils.convert_markdown_to_telegram(sources_text)
                await update.message.reply_text(sources_formatted, parse_mode='HTML')
            
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
