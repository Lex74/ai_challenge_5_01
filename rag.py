"""Модуль для работы с RAG (Retrieval-Augmented Generation)"""
import logging
from typing import List, Dict, Any, Optional, Tuple

from document_indexer import load_index, search_index
from openai_client import query_openai

logger = logging.getLogger(__name__)

# Количество релевантных чанков для включения в контекст
DEFAULT_TOP_K = 5


def format_chunks_for_context(chunks: List[Dict[str, Any]]) -> str:
    """Форматирует найденные чанки для включения в контекст LLM
    
    Args:
        chunks: Список результатов поиска с чанками
        
    Returns:
        Отформатированная строка с контекстом из чанков
    """
    if not chunks:
        return ""
    
    context_parts = []
    for i, result in enumerate(chunks, 1):
        chunk = result.get('chunk', {})
        similarity = result.get('similarity', 0.0)
        text = chunk.get('text', '')
        source = chunk.get('source_file', 'Неизвестный источник')
        
        if text:
            context_parts.append(
                f"[Источник {i} (релевантность: {similarity:.3f}) из {source}]:\n{text}"
            )
    
    return "\n\n".join(context_parts)


def build_rag_prompt(question: str, context: str) -> str:
    """Строит промпт для LLM с контекстом из RAG
    
    Args:
        question: Вопрос пользователя
        context: Контекст из релевантных чанков
        
    Returns:
        Промпт с вопросом и контекстом
    """
    if context:
        prompt = (
            f"Используй следующую информацию из документов для ответа на вопрос:\n\n"
            f"{context}\n\n"
            f"Вопрос: {question}\n\n"
            f"Ответь на вопрос, используя предоставленную информацию. "
            f"Если информации недостаточно, укажи это. "
            f"Если информация противоречива, укажи это."
        )
    else:
        prompt = question
    
    return prompt


async def query_with_rag(
    question: str,
    conversation_history: list,
    system_prompt: str,
    temperature: float,
    model: str,
    max_tokens: int,
    bot=None,
    tools: Optional[List[Dict[str, Any]]] = None,
    top_k: int = DEFAULT_TOP_K,
    index_path: Optional[str] = None
) -> Tuple[str, list]:
    """Отправляет запрос к LLM с использованием RAG
    
    Процесс:
    1. Загружает индекс документов
    2. Ищет релевантные чанки по вопросу
    3. Объединяет чанки с вопросом
    4. Отправляет запрос к LLM
    
    Args:
        question: Вопрос пользователя
        conversation_history: История диалога
        system_prompt: Системный промпт
        temperature: Температура для генерации
        model: Модель LLM
        max_tokens: Максимальное количество токенов
        bot: Экземпляр бота (для логирования)
        tools: Список доступных инструментов
        top_k: Количество релевантных чанков для поиска
        index_path: Путь к файлу индекса (по умолчанию используется дефолтный)
    
    Returns:
        Кортеж (ответ, обновленная история)
    """
    # Загружаем индекс
    index = load_index(index_path)
    
    if not index:
        logger.warning("Индекс не найден, используем обычный запрос без RAG")
        return await query_openai(
            question,
            conversation_history,
            system_prompt,
            temperature,
            model,
            max_tokens,
            bot,
            tools
        )
    
    # Ищем релевантные чанки
    logger.info(f"Ищу релевантные чанки для вопроса: {question[:100]}...")
    try:
        search_results = search_index(question, index, top_k=top_k)
    except Exception as e:
        logger.warning(f"Ошибка при поиске релевантных чанков: {e}, используем обычный запрос без RAG")
        search_results = []
    
    if not search_results:
        logger.info("Релевантные чанки не найдены или OLLama недоступен, используем обычный запрос без RAG")
        return await query_openai(
            question,
            conversation_history,
            system_prompt,
            temperature,
            model,
            max_tokens,
            bot,
            tools
        )
    
    # Форматируем контекст из чанков
    context = format_chunks_for_context(search_results)
    logger.info(f"Найдено {len(search_results)} релевантных чанков, длина контекста: {len(context)} символов")
    
    # Строим промпт с контекстом
    rag_prompt = build_rag_prompt(question, context)
    
    # Отправляем запрос к LLM
    return await query_openai(
        rag_prompt,
        conversation_history,
        system_prompt,
        temperature,
        model,
        max_tokens,
        bot,
        tools
    )


async def compare_rag_vs_no_rag(
    question: str,
    conversation_history: list,
    system_prompt: str,
    temperature: float,
    model: str,
    max_tokens: int,
    bot=None,
    tools: Optional[List[Dict[str, Any]]] = None,
    top_k: int = DEFAULT_TOP_K,
    index_path: Optional[str] = None
) -> Dict[str, Any]:
    """Сравнивает ответы модели с RAG и без RAG
    
    Args:
        question: Вопрос пользователя
        conversation_history: История диалога
        system_prompt: Системный промпт
        temperature: Температура для генерации
        model: Модель LLM
        max_tokens: Максимальное количество токенов
        bot: Экземпляр бота (для логирования)
        tools: Список доступных инструментов
        top_k: Количество релевантных чанков для поиска
        index_path: Путь к файлу индекса
    
    Returns:
        Словарь с результатами сравнения:
        - answer_with_rag: ответ с RAG
        - answer_without_rag: ответ без RAG
        - rag_context: контекст из RAG
        - comparison: анализ сравнения
    """
    logger.info("Начинаю сравнение ответов с RAG и без RAG")
    
    # Получаем ответ без RAG
    logger.info("Получаю ответ без RAG...")
    answer_without_rag, history_without_rag = await query_openai(
        question,
        conversation_history,
        system_prompt,
        temperature,
        model,
        max_tokens,
        bot,
        tools
    )
    
    # Получаем ответ с RAG
    logger.info("Получаю ответ с RAG...")
    answer_with_rag, history_with_rag = await query_with_rag(
        question,
        conversation_history,
        system_prompt,
        temperature,
        model,
        max_tokens,
        bot,
        tools,
        top_k,
        index_path
    )
    
    # Получаем контекст RAG для анализа
    rag_context = ""
    index = load_index(index_path)
    if index:
        search_results = search_index(question, index, top_k=top_k)
        if search_results:
            rag_context = format_chunks_for_context(search_results)
    
    # Анализируем результаты
    comparison = analyze_comparison(
        question,
        answer_without_rag,
        answer_with_rag,
        rag_context
    )
    
    return {
        "answer_with_rag": answer_with_rag,
        "answer_without_rag": answer_without_rag,
        "rag_context": rag_context,
        "comparison": comparison
    }


def analyze_comparison(
    question: str,
    answer_without_rag: str,
    answer_with_rag: str,
    rag_context: str
) -> str:
    """Анализирует сравнение ответов и делает выводы
    
    Args:
        question: Исходный вопрос
        answer_without_rag: Ответ без RAG
        answer_with_rag: Ответ с RAG
        rag_context: Контекст из RAG
    
    Returns:
        Текстовый анализ сравнения
    """
    analysis_parts = []
    
    # Базовые метрики
    len_without = len(answer_without_rag)
    len_with = len(answer_with_rag)
    word_count_without = len(answer_without_rag.split())
    word_count_with = len(answer_with_rag.split())
    
    analysis_parts.append("=== АНАЛИЗ СРАВНЕНИЯ ===")
    analysis_parts.append(f"\n📏 Длина ответов:")
    analysis_parts.append(f"  • Без RAG: {len_without} символов, {word_count_without} слов")
    analysis_parts.append(f"  • С RAG: {len_with} символов, {word_count_with} слов")
    analysis_parts.append(f"  • Разница: {len_with - len_without:+d} символов ({word_count_with - word_count_without:+d} слов)\n")
    
    # Проверяем наличие конкретной информации
    if rag_context:
        analysis_parts.append("✅ RAG предоставил контекст из документов")
        analysis_parts.append(f"📄 Размер контекста: {len(rag_context)} символов")
        
        # Проверяем, используется ли контекст в ответе
        context_keywords = set(rag_context.lower().split()[:30])  # Первые 30 слов
        answer_keywords = set(answer_with_rag.lower().split())
        overlap = len(context_keywords & answer_keywords)
        
        if overlap > 0:
            analysis_parts.append(f"✅ В ответе с RAG используются слова из контекста ({overlap} совпадений)")
        else:
            analysis_parts.append("⚠️ В ответе с RAG не обнаружено явного использования контекста")
        
        # Проверяем наличие специфических терминов из контекста
        context_terms = [w for w in rag_context.lower().split() if len(w) > 5]
        answer_terms = answer_with_rag.lower()
        specific_terms_used = sum(1 for term in context_terms[:10] if term in answer_terms)
        if specific_terms_used > 0:
            analysis_parts.append(f"✅ Использованы специфические термины из контекста ({specific_terms_used} терминов)")
    else:
        analysis_parts.append("❌ RAG не предоставил контекст (индекс не найден или нет релевантных чанков)")
    
    # Выводы
    analysis_parts.append("\n=== ВЫВОДЫ ===")
    
    if not rag_context:
        analysis_parts.append("❌ RAG не помог: нет доступа к документам")
        analysis_parts.append("💡 Рекомендация: проверьте наличие индекса документов (document_index/index.json)")
    else:
        # Анализируем качество ответов
        len_ratio = len_with / len_without if len_without > 0 else 1.0
        
        if len_ratio > 1.3:
            analysis_parts.append("✅ RAG помог: ответ с RAG значительно более детальный (на 30%+ длиннее)")
        elif len_ratio > 1.1:
            analysis_parts.append("✅ RAG помог: ответ с RAG более детальный (на 10-30% длиннее)")
        elif len_ratio < 0.7:
            analysis_parts.append("⚠️ RAG не помог: ответ с RAG значительно короче (на 30%+), возможно, модель ограничилась контекстом")
        elif len_ratio < 0.9:
            analysis_parts.append("⚠️ RAG не помог: ответ с RAG короче (на 10-30%), возможно, модель ограничилась контекстом")
        else:
            analysis_parts.append("➡️ RAG оказал умеренное влияние: ответы сопоставимы по длине")
        
        # Проверяем релевантность
        question_keywords = set(question.lower().split())
        answer_without_keywords = set(answer_without_rag.lower().split())
        answer_with_keywords = set(answer_with_rag.lower().split())
        
        relevance_without = len(question_keywords & answer_without_keywords)
        relevance_with = len(question_keywords & answer_with_keywords)
        
        if relevance_with > relevance_without:
            analysis_parts.append(f"✅ RAG помог: ответ более релевантен вопросу (больше совпадений ключевых слов: {relevance_with} vs {relevance_without})")
        elif relevance_with == relevance_without and relevance_with > 0:
            analysis_parts.append(f"➡️ Релевантность сопоставима: {relevance_with} совпадений ключевых слов в обоих ответах")
        
        # Проверяем наличие конкретных деталей
        if "источник" in answer_with_rag.lower() or "документ" in answer_with_rag.lower():
            analysis_parts.append("✅ RAG помог: ответ содержит ссылки на источники информации")
        
        # Проверяем, есть ли в ответе с RAG информация, которой нет в ответе без RAG
        answer_without_words = set(answer_without_rag.lower().split())
        answer_with_words = set(answer_with_rag.lower().split())
        unique_words = answer_with_words - answer_without_words
        if len(unique_words) > 10:
            analysis_parts.append(f"✅ RAG помог: ответ содержит уникальную информацию ({len(unique_words)} уникальных слов)")
    
    return "\n".join(analysis_parts)

