"""Модуль для индексации документов: разбивка на чанки, генерация эмбеддингов, сохранение индекса"""
import os
import json
import logging
import requests
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
import math

logger = logging.getLogger(__name__)

# Константы для индексации
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "100"))  # Размер чанка в символах (по умолчанию 100 для экономии памяти)
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "20"))  # Перекрытие между чанками (20% от размера чанка)
EMBEDDING_MODEL = "nomic-embed-text"  # Модель для эмбеддингов OLLama
EMBEDDING_DIM = 768  # Размерность эмбеддинга для nomic-embed-text
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/embeddings")

# Путь для сохранения индекса
INDEX_DIR = "document_index"
INDEX_FILE = os.path.join(INDEX_DIR, "index.json")


def ensure_index_dir():
    """Создает директорию для индекса, если её нет"""
    os.makedirs(INDEX_DIR, exist_ok=True)


def load_text_file(file_path: str) -> str:
    """Загружает текст из файла"""
    try:
        logger.debug(f"Открываю файл {file_path}...")
        with open(file_path, 'r', encoding='utf-8') as f:
            logger.debug("Читаю содержимое файла...")
            content = f.read()
            logger.debug(f"Файл прочитан, размер: {len(content)} символов")
            return content
    except Exception as e:
        logger.error(f"Ошибка при загрузке файла {file_path}: {e}", exc_info=True)
        raise


def split_text_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    """Разбивает текст на чанки с перекрытием
    
    Args:
        text: Текст для разбивки
        chunk_size: Размер чанка в символах
        overlap: Размер перекрытия между чанками
    
    Returns:
        Список словарей с чанками, каждый содержит:
        - text: текст чанка
        - start: начальная позиция в исходном тексте
        - end: конечная позиция в исходном тексте
        - chunk_index: индекс чанка
    """
    chunks = []
    text_length = len(text)
    
    logger.info(f"Начинаю разбивку текста: размер текста {text_length} символов, размер чанка {chunk_size}, перекрытие {overlap}")
    
    if text_length <= chunk_size:
        # Если текст короче размера чанка, возвращаем его целиком
        logger.info(f"Текст короче размера чанка ({text_length} <= {chunk_size}), создаю один чанк")
        return [{
            "text": text,
            "start": 0,
            "end": text_length,
            "chunk_index": 0
        }]
    
    start = 0
    chunk_index = 0
    step = chunk_size - overlap  # Шаг для следующего чанка
    
    if step <= 0:
        logger.error(f"Некорректный шаг: {step} (chunk_size={chunk_size}, overlap={overlap}), невозможно разбить текст")
        raise ValueError(f"Шаг должен быть положительным, но получен: {step}")
    
    # Оцениваем примерное количество чанков для логирования
    estimated_chunks = (text_length + step - 1) // step if step > 0 else 1
    logger.info(f"Ожидаемое количество чанков: ~{estimated_chunks}, шаг: {step}")
    
    # Логируем прогресс каждые N чанков (10% или минимум каждый 10-й)
    log_interval = max(1, estimated_chunks // 10) if estimated_chunks > 10 else 1
    
    prev_start = -1  # Для отслеживания предыдущей позиции
    
    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk_text_length = end - start
        
        # Проверяем, что мы не создаем дубликаты
        if start == prev_start:
            logger.warning(f"Обнаружена попытка создать дублирующий чанк на позиции {start}, прерываю разбивку")
            break
        
        # Проверяем, что чанк не пустой
        if chunk_text_length <= 0:
            logger.warning(f"Обнаружен пустой чанк на позиции {start}, прерываю разбивку")
            break
        
        chunks.append({
            "text": text[start:end],
            "start": start,
            "end": end,
            "chunk_index": chunk_index
        })
        
        # Логируем прогресс
        if chunk_index % log_interval == 0 or chunk_index == 0:
            progress = (start / text_length * 100) if text_length > 0 else 0
            logger.info(f"Создан чанк #{chunk_index + 1}: позиции {start}-{end} ({chunk_text_length} символов), прогресс: {progress:.1f}%")
        
        # Сохраняем текущую позицию для проверки на следующей итерации
        prev_start = start
        
        # Если достигли конца текста, завершаем (проверяем ДО вычисления следующей позиции)
        if end >= text_length:
            logger.info(f"Достигнут конец текста на позиции {end}, завершаю разбивку")
            break
        
        # Переходим к следующему чанку с учетом перекрытия
        new_start = end - overlap
        
        # Проверяем, что мы действительно продвинулись вперед
        if new_start <= start:
            logger.warning(f"Шаг слишком маленький: new_start={new_start} <= start={start}, завершаю разбивку")
            break
        
        start = new_start
        chunk_index += 1
        
        # Дополнительная защита от бесконечного цикла - ограничиваем максимальное количество чанков
        if chunk_index > estimated_chunks * 2:
            logger.error(f"Превышено ожидаемое количество чанков ({chunk_index} > {estimated_chunks * 2}), возможна бесконечная петля, прерываю")
            break
    
    logger.info(f"Разбивка завершена: создано {len(chunks)} чанков (размер чанка: {chunk_size}, перекрытие: {overlap}, шаг: {step})")
    return chunks


def get_embedding(text: str, model: str = EMBEDDING_MODEL) -> Optional[List[float]]:
    """Получает эмбеддинг для текста через OLLama API
    
    Args:
        text: Текст для получения эмбеддинга
        model: Модель для генерации эмбеддинга
    
    Returns:
        Список чисел (вектор эмбеддинга) или None в случае ошибки
    """
    # Проверяем размер текста
    if len(text) == 0:
        logger.warning("Получен пустой текст для эмбеддинга")
        return None
    
    if len(text) > 8192:  # Ограничение для безопасности
        logger.warning(f"Текст слишком длинный ({len(text)} символов), обрезаю до 8192")
        text = text[:8192]
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "prompt": text
    }
    
    try:
        logger.debug(f"Отправляю запрос к OLLama для текста длиной {len(text)} символов")
        response = requests.post(
            OLLAMA_API_URL,
            json=payload,
            headers=headers,
            timeout=120  # Увеличиваем таймаут
        )
        response.raise_for_status()
        
        data = response.json()
        
        if 'embedding' in data:
            embedding = data['embedding']
            logger.debug(f"Получен эмбеддинг размерности {len(embedding)} для текста длиной {len(text)} символов")
            return embedding
        else:
            logger.error(f"Не удалось получить эмбеддинг из ответа API. Ответ: {data}")
            return None
            
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Не удалось подключиться к OLLama: {e}")
        logger.error("Убедитесь, что OLLama запущен: ollama serve")
        return None
    except requests.exceptions.Timeout:
        logger.error("Таймаут при запросе к OLLama (возможно, модель не установлена или не загружена)")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP ошибка от OLLama: {e}")
        if hasattr(e.response, 'text'):
            logger.error(f"Детали ошибки: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка при получении эмбеддинга: {e}", exc_info=True)
        return None


def check_ollama_available() -> bool:
    """Проверяет доступность OLLama API и наличие нужной модели
    
    Returns:
        True если OLLama доступен и модель установлена, False иначе
    """
    try:
        # Проверяем доступность OLLama через простой запрос
        base_url = OLLAMA_API_URL.replace('/api/embeddings', '')
        response = requests.get(
            f"{base_url}/api/tags",
            timeout=5
        )
        if response.status_code != 200:
            logger.warning(f"OLLama вернул статус {response.status_code}")
            return False
        
        # Проверяем наличие нужной модели
        try:
            data = response.json()
            models = data.get('models', [])
            model_names = [m.get('name', '') for m in models]
            
            # Проверяем наличие модели (может быть с :latest или без)
            model_found = False
            base_model_name = EMBEDDING_MODEL.split(':')[0]  # Базовое имя без версии
            
            for model_name in model_names:
                # Проверяем точное совпадение или совпадение базового имени
                if model_name == EMBEDDING_MODEL or model_name.startswith(base_model_name + ':'):
                    model_found = True
                    logger.info(f"OLLama доступен, модель {model_name} найдена (ищем {EMBEDDING_MODEL})")
                    break
            
            if not model_found:
                logger.warning(f"Модель {EMBEDDING_MODEL} не найдена в списке установленных моделей")
                logger.info(f"Доступные модели: {', '.join(model_names) if model_names else 'нет'}")
                logger.info(f"Для установки выполните: ollama pull {EMBEDDING_MODEL}")
                return False
            
            return True
        except (KeyError, ValueError) as e:
            logger.warning(f"Не удалось проверить список моделей: {e}")
            # Если не удалось проверить модели, продолжаем (модель может быть доступна)
            logger.info("OLLama доступен (проверка моделей пропущена)")
            return True
            
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Не удалось подключиться к OLLama по адресу {OLLAMA_API_URL}")
        logger.error(f"Убедитесь, что OLLama запущен: ollama serve")
        return False
    except requests.exceptions.Timeout:
        logger.error("Таймаут при подключении к OLLama")
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке OLLama: {e}")
        return False


def get_embeddings_batch(texts: List[str], model: str = EMBEDDING_MODEL, batch_size: int = 10) -> List[Optional[List[float]]]:
    """Получает эмбеддинги для списка текстов через OLLama API
    
    OLLama не поддерживает батч-обработку, поэтому обрабатываем последовательно порциями
    
    Args:
        texts: Список текстов для получения эмбеддингов
        model: Модель для генерации эмбеддингов
        batch_size: Размер порции для обработки (для логирования прогресса)
    
    Returns:
        Список эмбеддингов (может содержать None для текстов, для которых не удалось получить эмбеддинг)
    """
    embeddings = []
    total = len(texts)
    
    logger.info(f"Начинаю генерацию эмбеддингов для {total} текстов...")
    
    for i, text in enumerate(texts):
        # Логируем прогресс каждые batch_size элементов
        if i % batch_size == 0 or i == total - 1:
            logger.info(f"Обработано {i+1}/{total} текстов ({(i+1)/total*100:.1f}%)")
        
        embedding = get_embedding(text, model)
        embeddings.append(embedding)
        
        # Небольшая задержка между запросами, чтобы не перегружать OLLama
        if i < total - 1:
            time.sleep(0.1)
    
    successful = sum(1 for e in embeddings if e is not None)
    logger.info(f"Получено {successful} эмбеддингов из {total} текстов")
    return embeddings


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Вычисляет косинусное сходство между двумя векторами
    
    Args:
        vec1: Первый вектор
        vec2: Второй вектор
    
    Returns:
        Косинусное сходство (от -1 до 1)
    """
    if len(vec1) != len(vec2):
        raise ValueError("Векторы должны иметь одинаковую размерность")
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)


def index_documents(file_paths: List[str], source_name: Optional[str] = None, process_in_batches: bool = True, batch_size: int = 50, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None, store_text: bool = True) -> Dict[str, Any]:
    """Индексирует документы: разбивает на чанки и генерирует эмбеддинги
    
    Args:
        file_paths: Список путей к файлам для индексации
        source_name: Имя источника (если None, используется имя первого файла)
        process_in_batches: Обрабатывать чанки порциями для экономии памяти
        batch_size: Размер порции для обработки эмбеддингов
    
    Returns:
        Словарь с индексом:
        - chunks: список чанков с текстом, метаданными и эмбеддингами
        - metadata: метаданные индекса (дата создания, количество чанков и т.д.)
    """
    ensure_index_dir()
    
    # Проверяем доступность OLLama перед началом
    logger.info("Проверяю доступность OLLama...")
    if not check_ollama_available():
        error_msg = (
            f"\n❌ OLLama недоступен по адресу {OLLAMA_API_URL}\n\n"
            f"Для решения проблемы:\n"
            f"1. Убедитесь, что OLLama запущен: ollama serve\n"
            f"2. Проверьте, что модель установлена: ollama pull {EMBEDDING_MODEL}\n"
            f"3. Проверьте доступность: curl {OLLAMA_API_URL.replace('/api/embeddings', '/api/tags')}\n"
        )
        logger.error(error_msg)
        raise ConnectionError(error_msg)
    
    # Предварительно загружаем модель в память OLLama, чтобы избежать задержек и проблем с памятью
    logger.info("Предзагружаю модель в память OLLama (тестовый запрос)...")
    import sys
    sys.stdout.flush()
    try:
        logger.info("Отправляю тестовый запрос к OLLama...")
        sys.stdout.flush()
        test_embedding = get_embedding("test", EMBEDDING_MODEL)
        sys.stdout.flush()
        if test_embedding:
            logger.info(f"Модель успешно загружена, размерность эмбеддинга: {len(test_embedding)}")
        else:
            logger.warning("Не удалось получить тестовый эмбеддинг, но продолжаю работу")
        sys.stdout.flush()
    except MemoryError as e:
        logger.error(f"Нехватка памяти при предзагрузке модели: {e}")
        raise
    except Exception as e:
        logger.warning(f"Не удалось предзагрузить модель: {e}, но продолжаю работу")
        sys.stdout.flush()
    
    if not file_paths:
        raise ValueError("Не указаны файлы для индексации")
    
    all_chunks = []
    source_name = source_name or Path(file_paths[0]).stem
    
    logger.info(f"Начинаю индексацию {len(file_paths)} файлов...")
    
    # Загружаем и разбиваем все файлы
    for file_path in file_paths:
        logger.info(f"Обрабатываю файл: {file_path}")
        try:
            # Проверяем размер файла
            logger.info("Проверяю размер файла...")
            file_size = os.path.getsize(file_path)
            logger.info(f"Размер файла: {file_size / 1024:.2f} KB")
            
            logger.info("Загружаю содержимое файла...")
            import sys
            sys.stdout.flush()  # Принудительно выводим буфер
            
            text = load_text_file(file_path)
            logger.info(f"Файл загружен, размер текста: {len(text)} символов")
            sys.stdout.flush()
            
            logger.info("Разбиваю текст на чанки...")
            sys.stdout.flush()
            # Используем переданные параметры или значения по умолчанию
            current_chunk_size = chunk_size if chunk_size is not None else CHUNK_SIZE
            current_chunk_overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP
            chunks = split_text_into_chunks(text, chunk_size=current_chunk_size, overlap=current_chunk_overlap)
            logger.info(f"Создано {len(chunks)} чанков")
            sys.stdout.flush()
            
            logger.info("Добавляю метаданные к чанкам...")
            sys.stdout.flush()
            # Добавляем метаданные о файле к каждому чанку
            for i, chunk in enumerate(chunks):
                chunk['source_file'] = file_path
                chunk['source_name'] = source_name
                all_chunks.append(chunk)
                if (i + 1) % 10 == 0:
                    logger.debug(f"Обработано {i + 1}/{len(chunks)} чанков")
            
            logger.info(f"Метаданные добавлены к {len(chunks)} чанкам из файла {file_path}")
            logger.info(f"Всего чанков после обработки файла {file_path}: {len(all_chunks)}")
            sys.stdout.flush()
                
        except MemoryError as e:
            logger.error(f"Нехватка памяти при обработке файла {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка при обработке файла {file_path}: {e}", exc_info=True)
            continue
    
    if not all_chunks:
        raise ValueError("Не удалось создать чанки из указанных файлов")
    
    logger.info(f"Создано {len(all_chunks)} чанков. Генерирую эмбеддинги...")
    logger.info(f"Общий размер всех чанков: {sum(len(chunk['text']) for chunk in all_chunks)} символов")
    
    # Обрабатываем эмбеддинги порциями для экономии памяти
    indexed_chunks = []
    
    if process_in_batches and len(all_chunks) > batch_size:
        total_batches = (len(all_chunks) + batch_size - 1) // batch_size
        logger.info(f"Обрабатываю чанки порциями по {batch_size} элементов (всего порций: {total_batches})...")
        
        for batch_start in range(0, len(all_chunks), batch_size):
            batch_end = min(batch_start + batch_size, len(all_chunks))
            batch_chunks = all_chunks[batch_start:batch_end]
            batch_num = batch_start // batch_size + 1
            
            logger.info(f"Обрабатываю порцию {batch_num}/{total_batches}: чанки {batch_start+1}-{batch_end} из {len(all_chunks)}")
            
            # Генерируем эмбеддинги для порции
            chunk_texts = [chunk['text'] for chunk in batch_chunks]
            embeddings = get_embeddings_batch(chunk_texts, batch_size=10)
            
            # Добавляем эмбеддинги к чанкам
            batch_indexed = 0
            for chunk, embedding in zip(batch_chunks, embeddings):
                if embedding is not None:
                    chunk['embedding'] = embedding
                    # Удаляем текст из чанка, если не нужно его хранить (для экономии памяти)
                    if not store_text:
                        chunk.pop('text', None)
                    indexed_chunks.append(chunk)
                    batch_indexed += 1
                else:
                    logger.warning(f"Не удалось получить эмбеддинг для чанка {chunk.get('chunk_index')}")
            
            logger.info(f"Порция {batch_num}/{total_batches} обработана: проиндексировано {batch_indexed}/{len(batch_chunks)} чанков. Всего проиндексировано: {len(indexed_chunks)}/{len(all_chunks)}")
            
            # Освобождаем память
            del batch_chunks
            del chunk_texts
            del embeddings
    else:
        # Обрабатываем все сразу (для небольших объемов)
        chunk_texts = [chunk['text'] for chunk in all_chunks]
        embeddings = get_embeddings_batch(chunk_texts)
        
        # Добавляем эмбеддинги к чанкам
        for chunk, embedding in zip(all_chunks, embeddings):
            if embedding is not None:
                chunk['embedding'] = embedding
                # Удаляем текст из чанка, если не нужно его хранить (для экономии памяти)
                if not store_text:
                    chunk.pop('text', None)
                indexed_chunks.append(chunk)
            else:
                logger.warning(f"Не удалось получить эмбеддинг для чанка {chunk.get('chunk_index')}")
    
    logger.info(f"Успешно проиндексировано {len(indexed_chunks)} чанков из {len(all_chunks)}")
    
    # Создаем структуру индекса
    index = {
        "chunks": indexed_chunks,
        "metadata": {
            "source_name": source_name,
            "source_files": file_paths,
            "total_chunks": len(indexed_chunks),
            "chunk_size": chunk_size if chunk_size is not None else CHUNK_SIZE,
            "chunk_overlap": chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dim": EMBEDDING_DIM
        }
    }
    
    return index


def save_index(index: Dict[str, Any], file_path: str = INDEX_FILE) -> None:
    """Сохраняет индекс в JSON файл
    
    Args:
        index: Словарь с индексом
        file_path: Путь к файлу для сохранения
    """
    ensure_index_dir()
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        logger.info(f"Индекс сохранен в {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении индекса: {e}")
        raise


def load_index(file_path: str = INDEX_FILE) -> Optional[Dict[str, Any]]:
    """Загружает индекс из JSON файла
    
    Args:
        file_path: Путь к файлу с индексом
    
    Returns:
        Словарь с индексом или None, если файл не найден
    """
    try:
        if not os.path.exists(file_path):
            logger.warning(f"Файл индекса не найден: {file_path}")
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            index = json.load(f)
        logger.info(f"Индекс загружен из {file_path}")
        return index
    except Exception as e:
        logger.error(f"Ошибка при загрузке индекса: {e}")
        return None


def search_index(query: str, index: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
    """Ищет в индексе похожие чанки по запросу
    
    Args:
        query: Текст запроса
        index: Словарь с индексом
        top_k: Количество лучших результатов для возврата
    
    Returns:
        Список словарей с результатами поиска, отсортированный по релевантности
        Каждый результат содержит:
        - chunk: исходный чанк
        - similarity: косинусное сходство
        - rank: ранг результата
    """
    if not index or 'chunks' not in index:
        logger.warning("Индекс пуст или некорректен")
        return []
    
    # Получаем эмбеддинг для запроса
    query_embedding = get_embedding(query)
    if query_embedding is None:
        logger.error("Не удалось получить эмбеддинг для запроса")
        return []
    
    # Вычисляем сходство с каждым чанком
    results = []
    chunks = index['chunks']
    
    for chunk in chunks:
        if 'embedding' not in chunk:
            continue
        
        similarity = cosine_similarity(query_embedding, chunk['embedding'])
        results.append({
            'chunk': chunk,
            'similarity': similarity,
            'rank': 0  # Заполним позже после сортировки
        })
    
    # Сортируем по убыванию сходства
    results.sort(key=lambda x: x['similarity'], reverse=True)
    
    # Присваиваем ранги
    for rank, result in enumerate(results[:top_k], 1):
        result['rank'] = rank
    
    logger.info(f"Найдено {len(results)} результатов, возвращаю топ-{top_k}")
    return results[:top_k]


def get_default_documents() -> List[str]:
    """Возвращает список документов по умолчанию для индексации
    
    Возвращает пути к README.md и всем .py файлам в текущей директории
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    default_files = []
    
    # Добавляем README.md, если существует
    readme_path = os.path.join(base_dir, "README.md")
    if os.path.exists(readme_path):
        default_files.append(readme_path)
    
    # Находим все .py файлы в текущей директории (не рекурсивно)
    for filename in os.listdir(base_dir):
        if filename.endswith('.py') and os.path.isfile(os.path.join(base_dir, filename)):
            # Исключаем __pycache__ и другие служебные файлы
            if not filename.startswith('__'):
                py_file_path = os.path.join(base_dir, filename)
                default_files.append(py_file_path)
    
    # Сортируем для предсказуемого порядка
    default_files.sort()
    
    logger.info(f"Найдено {len(default_files)} файлов по умолчанию для индексации")
    return default_files

