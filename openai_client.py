"""Модуль для работы с OpenAI API"""
import time
import logging
import requests

from config import OPENAI_API_KEY, OPENAI_API_URL, ADMIN_USER_ID
from constants import (
    API_TIMEOUT,
    MODEL_PRICING,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    MAX_TOKENS,
)

logger = logging.getLogger(__name__)


async def send_log_to_admin(bot, log_message: str):
    """Отправляет лог админу в Telegram"""
    if ADMIN_USER_ID:
        try:
            await bot.send_message(chat_id=int(ADMIN_USER_ID), text=log_message)
        except Exception as e:
            logger.error(f"Ошибка при отправке лога админу: {e}")


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


async def summarize_conversation(conversation_history: list, model: str, bot=None) -> str:
    """Отправляет запрос к OpenAI API для саммаризации истории диалога, возвращает саммари"""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Формируем список сообщений для саммаризации
    messages = [
        {
            "role": "system",
            "content": "Ты помощник, который создает краткое саммари диалога. Создай краткое саммари основных моментов разговора, сохраняя важные детали и контекст для продолжения диалога."
        }
    ]
    
    # Добавляем историю диалога для саммаризации
    messages.extend(conversation_history)
    
    # Добавляем инструкцию для создания саммари
    messages.append({
        "role": "user",
        "content": "Создай краткое саммари этого диалога, сохраняя важные детали и контекст."
    })
    
    payload = {
        "model": model,
        "messages": messages
    }
    
    if model.startswith("gpt-5"):
        payload["max_completion_tokens"] = 500  # Для саммари используем меньше токенов
    else:
        payload["max_tokens"] = 500
        payload["temperature"] = 0.3  # Немного выше для саммари
    
    try:
        response = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=API_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        
        if 'choices' in data and len(data['choices']) > 0:
            summary = data['choices'][0].get('message', {}).get('content', '')
            if summary:
                logger.info(f"Создано саммари для диалога (модель: {model})")
                return summary
            else:
                logger.warning("Получено пустое саммари от API")
                return ""
        else:
            logger.error("Не удалось получить саммари от API")
            return ""
            
    except Exception as e:
        logger.error(f"Ошибка при создании саммари: {e}")
        return ""


async def query_openai(
    question: str,
    conversation_history: list,
    system_prompt: str,
    temperature: float,
    model: str,
    max_tokens: int,
    bot=None
) -> tuple[str, list]:
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
