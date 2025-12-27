"""Модуль для работы с RAG (Retrieval-Augmented Generation)"""
import logging
from typing import List, Dict, Any, Optional, Tuple

from document_indexer import load_index, search_index
from openai_client import query_openai

logger = logging.getLogger(__name__)

# Количество релевантных чанков для включения в контекст
DEFAULT_TOP_K = 5

# Порог релевантности для фильтрации результатов (косинусное сходство)
# Значения от -1 до 1, где 1 - полное совпадение, 0 - ортогональность, -1 - противоположность
DEFAULT_RELEVANCE_THRESHOLD = 0.0  # По умолчанию не фильтруем (принимаем все результаты)


def filter_by_relevance_threshold(
    results: List[Dict[str, Any]], 
    threshold: float = DEFAULT_RELEVANCE_THRESHOLD
) -> List[Dict[str, Any]]:
    """Фильтрует результаты поиска по порогу релевантности
    
    Args:
        results: Список результатов поиска с similarity
        threshold: Порог релевантности (косинусное сходство от -1 до 1)
    
    Returns:
        Отфильтрованный список результатов, где similarity >= threshold
    """
    if threshold is None or threshold <= -1.0:
        # Если порог не установлен или слишком низкий, возвращаем все результаты
        return results
    
    filtered = [r for r in results if r.get('similarity', -1.0) >= threshold]
    
    logger.info(
        f"Фильтрация по порогу {threshold:.3f}: "
        f"осталось {len(filtered)} из {len(results)} результатов"
    )
    
    return filtered


def rerank_results(
    results: List[Dict[str, Any]], 
    query: str,
    method: str = "similarity"
) -> List[Dict[str, Any]]:
    """Реранкинг результатов поиска
    
    Args:
        results: Список результатов поиска
        query: Исходный запрос
        method: Метод реранкинга:
            - "similarity": сортировка по similarity (уже отсортировано)
            - "diversity": разнообразие результатов (убирает дубликаты)
            - "hybrid": комбинация similarity и разнообразия
    
    Returns:
        Реранкированный список результатов
    """
    if not results:
        return results
    
    if method == "similarity":
        # Уже отсортировано по similarity, просто обновляем ранги
        for rank, result in enumerate(results, 1):
            result['rank'] = rank
        return results
    
    elif method == "diversity":
        # Убираем дубликаты по тексту чанка
        seen_texts = set()
        diverse_results = []
        
        for result in results:
            chunk = result.get('chunk', {})
            text = chunk.get('text', '').strip()
            # Нормализуем текст для сравнения (убираем пробелы, приводим к нижнему регистру)
            text_normalized = ' '.join(text.lower().split())
            
            if text_normalized not in seen_texts and len(text_normalized) > 0:
                seen_texts.add(text_normalized)
                diverse_results.append(result)
        
        # Обновляем ранги
        for rank, result in enumerate(diverse_results, 1):
            result['rank'] = rank
        
        logger.info(
            f"Реранкинг по разнообразию: осталось {len(diverse_results)} из {len(results)} уникальных результатов"
        )
        
        return diverse_results
    
    elif method == "hybrid":
        # Комбинация: сначала по similarity, потом убираем дубликаты
        diverse_results = rerank_results(results, query, method="diversity")
        # Сортируем по similarity среди уникальных
        diverse_results.sort(key=lambda x: x.get('similarity', 0.0), reverse=True)
        
        # Обновляем ранги
        for rank, result in enumerate(diverse_results, 1):
            result['rank'] = rank
        
        return diverse_results
    
    else:
        logger.warning(f"Неизвестный метод реранкинга: {method}, используем similarity")
        return rerank_results(results, query, method="similarity")


def format_sources_for_display(sources: List[Dict[str, Any]]) -> str:
    """Форматирует источники для отображения пользователю
    
    Args:
        sources: Список источников с ключами source_file, similarity, text
        
    Returns:
        Отформатированная строка с источниками в формате markdown
    """
    if not sources:
        return ""
    
    source_parts = []
    source_parts.append("📚 **Источники:**\n")
    
    # Группируем источники по файлам
    sources_by_file = {}
    for i, source in enumerate(sources, 1):
        file_name = source.get('source_file', 'Неизвестный источник')
        if file_name not in sources_by_file:
            sources_by_file[file_name] = []
        sources_by_file[file_name].append({
            'index': i,
            'similarity': source.get('similarity', 0.0),
            'text': source.get('text', '')
        })
    
    # Форматируем по файлам
    for file_name, file_sources in sources_by_file.items():
        source_parts.append(f"📄 **{file_name}**")
        for source_info in file_sources:
            similarity = source_info['similarity']
            source_parts.append(f"  • Релевантность: {similarity:.3f}")
    
    return "\n".join(source_parts)


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
    index_path: Optional[str] = None,
    relevance_threshold: Optional[float] = None,
    rerank_method: Optional[str] = None,
    use_filter: bool = True
) -> Tuple[str, list, List[Dict[str, Any]]]:
    """Отправляет запрос к LLM с использованием RAG
    
    Процесс:
    1. Загружает индекс документов
    2. Ищет релевантные чанки по вопросу
    3. Применяет фильтрацию по порогу релевантности (если включена)
    4. Применяет реранкинг результатов (если указан метод)
    5. Объединяет отфильтрованные чанки с вопросом
    6. Отправляет запрос к LLM
    
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
        relevance_threshold: Порог релевантности для фильтрации (None = не фильтровать)
        rerank_method: Метод реранкинга ("similarity", "diversity", "hybrid" или None)
        use_filter: Использовать ли фильтрацию по порогу
    
    Returns:
        Кортеж (ответ, обновленная история, источники)
        Источники - список словарей с ключами: source_file, similarity, text
    """
    # Загружаем индекс
    index = load_index(index_path)
    
    if not index:
        logger.warning("Индекс не найден, используем обычный запрос без RAG")
        answer, history = await query_openai(
            question,
            conversation_history,
            system_prompt,
            temperature,
            model,
            max_tokens,
            bot,
            tools
        )
        return answer, history, []
    
    # Ищем релевантные чанки
    logger.info(f"Ищу релевантные чанки для вопроса: {question[:100]}...")
    try:
        # Получаем больше результатов для фильтрации и реранкинга
        search_results = search_index(question, index, top_k=top_k * 2)  # Берем в 2 раза больше для фильтрации
    except Exception as e:
        logger.warning(f"Ошибка при поиске релевантных чанков: {e}, используем обычный запрос без RAG")
        search_results = []
    
    if not search_results:
        logger.info("Релевантные чанки не найдены или OLLama недоступен, используем обычный запрос без RAG")
        answer, history = await query_openai(
            question,
            conversation_history,
            system_prompt,
            temperature,
            model,
            max_tokens,
            bot,
            tools
        )
        return answer, history, []
    
    # Применяем фильтрацию по порогу релевантности, если включена
    if use_filter and relevance_threshold is not None:
        search_results = filter_by_relevance_threshold(search_results, relevance_threshold)
        logger.info(f"После фильтрации осталось {len(search_results)} результатов")
    
    # Применяем реранкинг, если указан метод
    if rerank_method:
        search_results = rerank_results(search_results, question, method=rerank_method)
        logger.info(f"После реранкинга ({rerank_method}): {len(search_results)} результатов")
    
    # Ограничиваем до top_k после фильтрации и реранкинга
    search_results = search_results[:top_k]
    
    if not search_results:
        logger.info("После фильтрации не осталось релевантных чанков, используем обычный запрос без RAG")
        answer, history = await query_openai(
            question,
            conversation_history,
            system_prompt,
            temperature,
            model,
            max_tokens,
            bot,
            tools
        )
        return answer, history, []
    
    # Форматируем контекст из чанков
    context = format_chunks_for_context(search_results)
    logger.info(f"Найдено {len(search_results)} релевантных чанков после фильтрации, длина контекста: {len(context)} символов")
    
    # Строим промпт с контекстом
    rag_prompt = build_rag_prompt(question, context)
    
    # Отправляем запрос к LLM
    answer, history = await query_openai(
        rag_prompt,
        conversation_history,
        system_prompt,
        temperature,
        model,
        max_tokens,
        bot,
        tools
    )
    
    # Формируем список источников из search_results
    sources = []
    for result in search_results:
        chunk = result.get('chunk', {})
        source_info = {
            'source_file': chunk.get('source_file', 'Неизвестный источник'),
            'similarity': result.get('similarity', 0.0),
            'text': chunk.get('text', '')[:200] + '...' if len(chunk.get('text', '')) > 200 else chunk.get('text', '')
        }
        sources.append(source_info)
    
    return answer, history, sources


async def compare_rag_with_and_without_filter(
    question: str,
    conversation_history: list,
    system_prompt: str,
    temperature: float,
    model: str,
    max_tokens: int,
    bot=None,
    tools: Optional[List[Dict[str, Any]]] = None,
    top_k: int = DEFAULT_TOP_K,
    index_path: Optional[str] = None,
    relevance_threshold: float = 0.3,
    rerank_method: Optional[str] = None
) -> Dict[str, Any]:
    """Сравнивает ответы модели с фильтром релевантности и без фильтра
    
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
        relevance_threshold: Порог релевантности для фильтрации
        rerank_method: Метод реранкинга
    
    Returns:
        Словарь с результатами сравнения:
        - answer_without_filter: ответ без фильтрации
        - answer_with_filter: ответ с фильтрацией
        - chunks_without_filter: чанки без фильтрации
        - chunks_with_filter: чанки с фильтрацией
        - comparison: анализ сравнения
    """
    logger.info("Начинаю сравнение ответов с фильтром и без фильтра")
    
    # Получаем ответ без фильтра
    logger.info("Получаю ответ без фильтрации...")
    answer_without_filter, history_without_filter, _ = await query_with_rag(
        question,
        conversation_history,
        system_prompt,
        temperature,
        model,
        max_tokens,
        bot,
        tools,
        top_k,
        index_path,
        relevance_threshold=None,
        rerank_method=None,
        use_filter=False
    )
    
    # Получаем ответ с фильтром
    logger.info(f"Получаю ответ с фильтрацией (порог: {relevance_threshold})...")
    answer_with_filter, history_with_filter, _ = await query_with_rag(
        question,
        conversation_history,
        system_prompt,
        temperature,
        model,
        max_tokens,
        bot,
        tools,
        top_k,
        index_path,
        relevance_threshold=relevance_threshold,
        rerank_method=rerank_method,
        use_filter=True
    )
    
    # Получаем чанки для анализа
    chunks_without_filter = []
    chunks_with_filter = []
    index = load_index(index_path)
    if index:
        try:
            search_results_no_filter = search_index(question, index, top_k=top_k * 2)
            chunks_without_filter = search_results_no_filter[:top_k]
            
            if relevance_threshold is not None:
                search_results_filtered = filter_by_relevance_threshold(
                    search_results_no_filter, 
                    relevance_threshold
                )
                if rerank_method:
                    search_results_filtered = rerank_results(
                        search_results_filtered, 
                        question, 
                        method=rerank_method
                    )
                chunks_with_filter = search_results_filtered[:top_k]
            else:
                chunks_with_filter = chunks_without_filter
        except Exception as e:
            logger.warning(f"Не удалось получить чанки для анализа: {e}")
    
    # Анализируем результаты
    comparison = analyze_filter_comparison(
        question,
        answer_without_filter,
        answer_with_filter,
        chunks_without_filter,
        chunks_with_filter,
        relevance_threshold
    )
    
    return {
        "answer_without_filter": answer_without_filter,
        "answer_with_filter": answer_with_filter,
        "chunks_without_filter": chunks_without_filter,
        "chunks_with_filter": chunks_with_filter,
        "comparison": comparison
    }


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
    answer_with_rag, history_with_rag, _ = await query_with_rag(
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


def analyze_filter_comparison(
    question: str,
    answer_without_filter: str,
    answer_with_filter: str,
    chunks_without_filter: List[Dict[str, Any]],
    chunks_with_filter: List[Dict[str, Any]],
    threshold: float
) -> str:
    """Анализирует сравнение ответов с фильтром и без фильтра
    
    Args:
        question: Исходный вопрос
        answer_without_filter: Ответ без фильтрации
        answer_with_filter: Ответ с фильтрацией
        chunks_without_filter: Чанки без фильтрации
        chunks_with_filter: Чанки с фильтрацией
        threshold: Использованный порог релевантности
    
    Returns:
        Текстовый анализ сравнения
    """
    analysis_parts = []
    
    # Базовые метрики
    len_without = len(answer_without_filter)
    len_with = len(answer_with_filter)
    word_count_without = len(answer_without_filter.split())
    word_count_with = len(answer_with_filter.split())
    
    chunks_count_without = len(chunks_without_filter)
    chunks_count_with = len(chunks_with_filter)
    
    # Вычисляем среднюю релевантность чанков
    avg_similarity_without = 0.0
    if chunks_without_filter:
        similarities = [r.get('similarity', 0.0) for r in chunks_without_filter]
        avg_similarity_without = sum(similarities) / len(similarities) if similarities else 0.0
    
    avg_similarity_with = 0.0
    if chunks_with_filter:
        similarities = [r.get('similarity', 0.0) for r in chunks_with_filter]
        avg_similarity_with = sum(similarities) / len(similarities) if similarities else 0.0
    
    analysis_parts.append("=== АНАЛИЗ СРАВНЕНИЯ С ФИЛЬТРОМ И БЕЗ ===")
    analysis_parts.append(f"\n📊 Статистика ответов:")
    analysis_parts.append(f"  • Без фильтра: {len_without} символов, {word_count_without} слов")
    analysis_parts.append(f"  • С фильтром (порог {threshold:.3f}): {len_with} символов, {word_count_with} слов")
    analysis_parts.append(f"  • Разница: {len_with - len_without:+d} символов ({word_count_with - word_count_without:+d} слов)\n")
    
    analysis_parts.append(f"📚 Статистика чанков:")
    analysis_parts.append(f"  • Без фильтра: {chunks_count_without} чанков, средняя релевантность: {avg_similarity_without:.3f}")
    analysis_parts.append(f"  • С фильтром: {chunks_count_with} чанков, средняя релевантность: {avg_similarity_with:.3f}")
    if chunks_count_without > 0:
        filtered_out = chunks_count_without - chunks_count_with
        filter_rate = (filtered_out / chunks_count_without) * 100
        analysis_parts.append(f"  • Отфильтровано: {filtered_out} чанков ({filter_rate:.1f}%)\n")
    
    # Выводы
    analysis_parts.append("=== ВЫВОДЫ ===")
    
    if chunks_count_with == 0:
        analysis_parts.append("❌ Фильтр слишком строгий: все чанки отфильтрованы")
        analysis_parts.append(f"💡 Рекомендация: уменьшите порог релевантности (текущий: {threshold:.3f})")
    elif chunks_count_with < chunks_count_without * 0.5:
        analysis_parts.append("⚠️ Фильтр очень строгий: отфильтровано более 50% чанков")
        analysis_parts.append(f"💡 Рекомендация: рассмотрите уменьшение порога до {threshold * 0.7:.3f}")
    elif chunks_count_with == chunks_count_without:
        analysis_parts.append("➡️ Фильтр не отфильтровал ни одного чанка")
        analysis_parts.append(f"💡 Рекомендация: увеличьте порог до {threshold * 1.5:.3f} для более строгой фильтрации")
    else:
        analysis_parts.append(f"✅ Фильтр работает: отфильтровано {chunks_count_without - chunks_count_with} нерелевантных чанков")
    
    # Анализ качества ответов
    if avg_similarity_with > avg_similarity_without:
        analysis_parts.append(f"✅ Фильтр улучшил качество: средняя релевантность чанков выросла с {avg_similarity_without:.3f} до {avg_similarity_with:.3f}")
    elif avg_similarity_with < avg_similarity_without:
        analysis_parts.append(f"⚠️ Фильтр снизил среднюю релевантность: с {avg_similarity_without:.3f} до {avg_similarity_with:.3f}")
        analysis_parts.append("💡 Возможно, фильтр слишком строгий и отфильтровал полезные чанки")
    else:
        analysis_parts.append("➡️ Средняя релевантность чанков не изменилась")
    
    # Анализ длины ответов
    len_ratio = len_with / len_without if len_without > 0 else 1.0
    if len_ratio > 1.1:
        analysis_parts.append("✅ Ответ с фильтром более детальный (на 10%+ длиннее)")
    elif len_ratio < 0.9:
        analysis_parts.append("⚠️ Ответ с фильтром короче (на 10%+), возможно, потеряна информация")
    else:
        analysis_parts.append("➡️ Длина ответов сопоставима")
    
    return "\n".join(analysis_parts)


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

