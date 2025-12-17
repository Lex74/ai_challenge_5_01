"""Модуль для работы с OpenAI API"""
import time
import logging
import json
import requests
from typing import Optional, List, Dict, Any

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
    bot=None,
    tools: Optional[List[Dict[str, Any]]] = None
) -> tuple[str, list]:
    """Отправляет запрос в OpenAI API и возвращает ответ и обновленную историю
    
    Поддерживает function calling с MCP инструментами.
    Если LLM решает вызвать инструмент, он вызывается, и результат отправляется обратно в LLM.
    """
    from mcp_integration import call_mcp_tool
    
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
    
    # Добавляем tools, если они предоставлены
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"  # LLM решает, использовать ли инструменты
        logger.info(f"Передано {len(tools)} инструментов в OpenAI API для function calling")
        # Логируем названия инструментов для отладки
        tool_names = [t.get('function', {}).get('name', 'unknown') for t in tools]
        logger.info(f"Доступные инструменты: {', '.join(tool_names)}")
        # Проверяем наличие News инструментов
        news_tools = [name for name in tool_names if name.startswith('news_')]
        if news_tools:
            logger.info(f"⚠️ News инструменты доступны: {', '.join(news_tools)}")
        else:
            logger.warning("⚠️ News инструменты НЕ найдены в списке доступных инструментов!")
    
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
        
        # Обрабатываем ответ с поддержкой function calling
        max_iterations = 5  # Максимальное количество итераций вызовов инструментов
        iteration = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        answer = ""
        finish_reason = ""
        
        while iteration < max_iterations:
            iteration += 1
            
            # Извлекаем ответ из структуры ответа OpenAI
            if 'choices' in data and len(data['choices']) > 0:
                choice = data['choices'][0]
                message = choice.get('message', {})
                answer = message.get('content', '')
                finish_reason = choice.get('finish_reason', '')
                tool_calls = message.get('tool_calls', [])
                
                # Добавляем сообщение ассистента в историю для следующей итерации
                assistant_message = {"role": "assistant", "content": answer or ""}
                if tool_calls:
                    assistant_message["tool_calls"] = tool_calls
                messages.append(assistant_message)
                
                # Если LLM решила вызвать инструменты
                if tool_calls and finish_reason == 'tool_calls':
                    logger.info(f"LLM решила вызвать {len(tool_calls)} инструмент(ов)")
                    
                    # Вызываем все запрошенные инструменты
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_id = tool_call.get('id')
                        tool_name = tool_call.get('function', {}).get('name', '')
                        tool_args_str = tool_call.get('function', {}).get('arguments', '{}')
                        
                        # Парсим аргументы
                        try:
                            tool_args = json.loads(tool_args_str)
                        except json.JSONDecodeError:
                            logger.error(f"Не удалось распарсить аргументы инструмента {tool_name}: {tool_args_str}")
                            tool_args = {}
                        
                        # Вызываем MCP инструмент
                        logger.info(f"Вызываю MCP инструмент: {tool_name} с аргументами: {tool_args}")
                        tool_result = await call_mcp_tool(tool_name, tool_args)
                        
                        if tool_result is None:
                            tool_result = "Ошибка при вызове инструмента"
                        
                        # Добавляем результат в список
                        tool_results.append({
                            "tool_call_id": tool_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": str(tool_result)
                        })
                    
                    # Добавляем результаты инструментов в сообщения
                    messages.extend(tool_results)
                    
                    # Отправляем запрос снова с результатами инструментов
                    payload = {
                        "model": model,
                        "messages": messages
                    }
                    
                    if tools:
                        payload["tools"] = tools
                        payload["tool_choice"] = "auto"
                    
                    if model.startswith("gpt-5"):
                        payload["max_completion_tokens"] = max_tokens
                    else:
                        payload["max_tokens"] = max_tokens
                        payload["temperature"] = temperature
                    
                    # Делаем следующий запрос
                    response = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=API_TIMEOUT)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Накапливаем токены
                    usage = data.get('usage', {})
                    total_prompt_tokens += usage.get('prompt_tokens', 0)
                    total_completion_tokens += usage.get('completion_tokens', 0)
                    
                    # Продолжаем цикл для обработки следующего ответа
                    continue
                else:
                    # Если это не tool_calls, выходим из цикла
                    break
            else:
                # Если нет choices, выходим из цикла
                logger.warning("Нет choices в ответе API, выходим из цикла")
                break
        
        # Проверяем, достигли ли мы лимита итераций
        if iteration >= max_iterations and finish_reason == 'tool_calls':
            logger.warning(f"Достигнут лимит итераций ({max_iterations}) при обработке function calling")
            answer = "Извините, достигнут лимит вызовов инструментов. Попробуйте упростить запрос."
            updated_history = conversation_history.copy()
            updated_history.append({"role": "user", "content": question})
            return answer, updated_history
        
        # Если answer пустой и мы вышли из цикла, значит что-то пошло не так
        if not answer:
            logger.error("Получен пустой ответ после обработки function calling")
            answer = "Извините, не удалось получить ответ от модели."
            updated_history = conversation_history.copy()
            updated_history.append({"role": "user", "content": question})
            return answer, updated_history
        
        # Если это финальный ответ (не tool_calls)
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
        
        # Извлекаем информацию из ответа API (используем накопленные значения или последний ответ)
        usage = data.get('usage', {})
        if total_prompt_tokens == 0:
            total_prompt_tokens = usage.get('prompt_tokens', 0)
        if total_completion_tokens == 0:
            total_completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = total_prompt_tokens + total_completion_tokens
        
        # Проверяем наличие reasoning tokens
        completion_details = usage.get('completion_tokens_details', {})
        reasoning_tokens = completion_details.get('reasoning_tokens', 0)
        
        # Рассчитываем стоимость
        total_cost = calculate_cost(model, total_prompt_tokens, total_completion_tokens)
        
        # Логируем информацию о запросе
        log_message = (
            f"OpenAI API запрос - Модель: {model}, "
            f"Время ответа: {response_time:.3f}с, "
            f"Итераций: {iteration}, "
            f"Prompt tokens: {total_prompt_tokens}, Completion tokens: {total_completion_tokens}"
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
        
        # Добавляем все сообщения ассистента и инструментов из текущего запроса
        # messages содержит: [system_prompt, ...history..., user_question, assistant_msg, tool_results, ...]
        # Нам нужно добавить только новые сообщения после user_question
        # Находим индекс user_question в messages
        user_msg_index = len(messages) - 1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user" and msg.get("content") == question:
                user_msg_index = i
                break
        
        # Добавляем все сообщения после user_question (assistant и tool)
        for msg in messages[user_msg_index + 1:]:
            if msg.get("role") in ["assistant", "tool"]:
                updated_history.append(msg)
        
        return answer, updated_history
            
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
