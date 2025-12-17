"""Модуль для планирования задач"""
import logging
from datetime import datetime, time
from typing import Optional

import pytz
from telegram import Bot
from telegram.ext import ContextTypes

from config import ADMIN_USER_ID
from mcp_news_client import call_news_tool
from openai_client import query_openai

logger = logging.getLogger(__name__)

# Московское время
MSK_TZ = pytz.timezone('Europe/Moscow')


async def get_daily_news_summary(bot: Bot) -> Optional[str]:
    """Получает новости и создает саммари как ведущий новостей"""
    try:
        logger.info("Начинаю получение ежедневных новостей...")
        
        # Получаем новости по разным темам
        news_topics = [
            {"query": "Россия", "language": "ru"},
            {"query": "технологии", "language": "ru"},
            {"query": "мир", "language": "ru"},
        ]
        
        all_news_text = ""
        
        for topic in news_topics:
            try:
                logger.info(f"Получаю новости по теме: {topic['query']}")
                news_result = await call_news_tool("get_today_news", {
                    "query": topic["query"],
                    "language": topic["language"],
                    "sort_by": "publishedAt",
                    "page_size": 5
                })
                
                if news_result:
                    all_news_text += f"\n\n=== Новости: {topic['query']} ===\n{news_result}\n"
                    logger.info(f"Получено {len(news_result)} символов новостей по теме {topic['query']}")
                else:
                    logger.warning(f"Не удалось получить новости по теме {topic['query']}")
            except Exception as e:
                logger.error(f"Ошибка при получении новостей по теме {topic['query']}: {e}", exc_info=True)
        
        if not all_news_text.strip():
            logger.warning("Не удалось получить новости для саммари")
            return None
        
        # Создаем саммари с помощью OpenAI
        system_prompt = (
            "Ты профессиональный ведущий новостей. Создай краткое саммари новостей дня в стиле "
            "вступительного слова ведущего новостей. Начни с приветствия и краткого обзора основных событий. "
            "Структурируй информацию по темам, выдели самые важные новости. "
            "Будь кратким, но информативным. Используй профессиональный, но понятный язык. "
            "В конце добавь фразу вроде 'Это были основные новости дня. Хорошего дня!'"
        )
        
        user_prompt = (
            f"Создай краткое саммари новостей дня в стиле ведущего новостей на основе следующей информации:\n\n"
            f"{all_news_text}\n\n"
            f"Создай профессиональное вступительное слово ведущего новостей."
        )
        
        logger.info("Создаю саммари новостей с помощью OpenAI...")
        summary, _ = await query_openai(
            user_prompt,
            [],
            system_prompt,
            temperature=0.7,
            model="gpt-4o-mini",
            max_tokens=1500,
            bot=bot,
            tools=None
        )
        
        if summary:
            logger.info(f"Создано саммари новостей длиной {len(summary)} символов")
            return summary
        else:
            logger.error("Не удалось создать саммари новостей")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при создании саммари новостей: {e}", exc_info=True)
        return None


async def send_daily_news(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет ежедневные новости пользователю"""
    if not ADMIN_USER_ID:
        logger.error("ADMIN_USER_ID не установлен. Невозможно отправить новости.")
        return
    
    bot = context.bot
    
    try:
        logger.info("Запуск задачи отправки ежедневных новостей...")
        
        # Получаем саммари новостей
        news_summary = await get_daily_news_summary(bot)
        
        if not news_summary:
            error_message = (
                "❌ Не удалось получить новости для ежедневной рассылки.\n\n"
                "Проверьте:\n"
                "• Настройки NEWS_API_KEY\n"
                "• Доступность MCP сервера News\n"
                "• Логи для деталей"
            )
            await bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=error_message
            )
            logger.error("Не удалось получить новости для ежедневной рассылки")
            return
        
        # Форматируем сообщение
        current_date = datetime.now(MSK_TZ).strftime("%d.%m.%Y")
        message = (
            f"📰 <b>Ежедневные новости</b>\n"
            f"📅 {current_date}\n"
            f"🕐 06:00 МСК\n\n"
            f"{news_summary}"
        )
        
        # Отправляем сообщение
        await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=message,
            parse_mode='HTML'
        )
        
        logger.info(f"Ежедневные новости успешно отправлены пользователю {ADMIN_USER_ID}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневных новостей: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"❌ Произошла ошибка при отправке ежедневных новостей: {str(e)}"
            )
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")


def setup_daily_news_scheduler(application) -> None:
    """Настраивает планировщик для ежедневной рассылки новостей"""
    if not ADMIN_USER_ID:
        logger.warning("ADMIN_USER_ID не установлен в .env. Ежедневная рассылка новостей отключена.")
        return
    
    # Используем встроенный JobQueue от python-telegram-bot
    # Настраиваем задачу на 6:00 МСК каждый день
    # МСК = UTC+3, поэтому 6:00 МСК = 3:00 UTC
    job_queue = application.job_queue
    
    job_queue.run_daily(
        send_daily_news,
        time=time(hour=3, minute=0),  # 3:00 UTC соответствует 6:00 МСК (UTC+3)
        name='Ежедневная рассылка новостей'
    )
    
    logger.info(f"Планировщик ежедневных новостей настроен: 6:00 МСК (3:00 UTC) каждый день для пользователя {ADMIN_USER_ID}")

