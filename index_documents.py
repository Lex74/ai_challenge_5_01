#!/usr/bin/env python3
"""Скрипт для индексации документов: разбивка на чанки + генерация эмбеддингов через OLLama"""
import os
import sys
import logging
import argparse
from pathlib import Path

from document_indexer import (
    index_documents,
    save_index,
    get_default_documents,
    INDEX_FILE
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Основная функция для запуска индексации"""
    parser = argparse.ArgumentParser(
        description='Индексация документов: разбивка на чанки + генерация эмбеддингов через OLLama'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='Пути к файлам для индексации (если не указаны, используются файлы по умолчанию)'
    )
    parser.add_argument(
        '--source-name',
        type=str,
        default=None,
        help='Имя источника для индекса (по умолчанию берется из имени первого файла)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=INDEX_FILE,
        help=f'Путь к файлу для сохранения индекса (по умолчанию: {INDEX_FILE})'
    )
    parser.add_argument(
        '--chunk-size',
        type=int,
        default=None,
        help='Размер чанка в символах (по умолчанию: 100, можно изменить через CHUNK_SIZE)'
    )
    parser.add_argument(
        '--chunk-overlap',
        type=int,
        default=None,
        help='Размер перекрытия между чанками (по умолчанию: 20, можно изменить через CHUNK_OVERLAP)'
    )
    parser.add_argument(
        '--no-store-text',
        action='store_true',
        help='Не сохранять текст чанков в индексе (экономия памяти, но результаты поиска будут без текста)'
    )
    parser.add_argument(
        '--use-openai',
        action='store_true',
        help='Использовать OpenAI эмбеддинги вместо OLLama (требует OPENAI_API_KEY)'
    )
    
    args = parser.parse_args()
    
    # Определяем список файлов для индексации
    if args.files:
        file_paths = args.files
        # Проверяем существование файлов
        existing_files = []
        for file_path in file_paths:
            if Path(file_path).exists():
                existing_files.append(file_path)
            else:
                logger.warning(f"Файл не найден: {file_path}, пропускаю...")
        
        if not existing_files:
            logger.error("Не найдено ни одного существующего файла для индексации")
            sys.exit(1)
        
        file_paths = existing_files
    else:
        # Используем файлы по умолчанию
        file_paths = get_default_documents()
        if not file_paths:
            logger.error("Не найдено файлов по умолчанию для индексации")
            sys.exit(1)
        logger.info(f"Используются файлы по умолчанию: {file_paths}")
    
    logger.info(f"Начинаю индексацию {len(file_paths)} файлов...")
    logger.info(f"Файлы: {', '.join(file_paths)}")
    
    # Проверяем доступность эмбеддинг провайдера
    use_openai = args.use_openai
    
    if use_openai:
        # Проверяем наличие OPENAI_API_KEY
        from config import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            print("\n❌ OPENAI_API_KEY не установлен!")
            print("   Добавьте OPENAI_API_KEY в файл .env")
            sys.exit(1)
        print(f"\n✅ Используем OpenAI эмбеддинги (text-embedding-3-small)")
    else:
        # Проверяем доступность OLLama
        try:
            from document_indexer import check_ollama_available
            logger.info("Проверяю доступность OLLama...")
            if not check_ollama_available():
                print("\n❌ OLLama недоступен или модель не установлена!")
                print(f"   Проверьте: curl {os.getenv('OLLAMA_API_URL', 'http://localhost:11434')}/api/tags")
                print(f"   Установите модель: ollama pull nomic-embed-text")
                print(f"\n   Или используйте флаг --use-openai для индексации через OpenAI")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Ошибка при проверке OLLama: {e}")
            print(f"\n❌ Ошибка при проверке OLLama: {e}")
            print(f"   Или используйте флаг --use-openai для индексации через OpenAI")
            sys.exit(1)
    
    try:
        # Индексируем документы
        logger.info("Начинаю индексацию документов...")
        # Используем переданные параметры размера чанка или значения по умолчанию
        chunk_size = args.chunk_size
        chunk_overlap = args.chunk_overlap
        if chunk_size:
            logger.info(f"Используется размер чанка: {chunk_size} символов")
        if chunk_overlap:
            logger.info(f"Используется перекрытие чанков: {chunk_overlap} символов")
        
        index = index_documents(
            file_paths, 
            source_name=args.source_name, 
            process_in_batches=True, 
            batch_size=20,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            store_text=not args.no_store_text,
            use_openai=use_openai
        )
        
        # Сохраняем индекс
        save_index(index, file_path=args.output)
        
        # Выводим статистику
        metadata = index.get('metadata', {})
        total_chunks = metadata.get('total_chunks', 0)
        source_files = metadata.get('source_files', [])
        
        print("\n" + "="*60)
        print("✅ Индексация завершена успешно!")
        print("="*60)
        print(f"\n📊 Статистика:")
        print(f"  • Проиндексировано файлов: {len(source_files)}")
        print(f"  • Создано чанков: {total_chunks}")
        print(f"  • Модель эмбеддингов: {metadata.get('embedding_model', 'N/A')}")
        print(f"  • Размерность эмбеддинга: {metadata.get('embedding_dim', 'N/A')}")
        print(f"  • Размер чанка: {metadata.get('chunk_size', 'N/A')} символов")
        print(f"  • Перекрытие чанков: {metadata.get('chunk_overlap', 'N/A')} символов")
        print(f"\n📁 Файлы:")
        for i, file_path in enumerate(source_files, 1):
            print(f"  {i}. {file_path}")
        print(f"\n💾 Индекс сохранен в: {args.output}")
        print("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"Ошибка при индексации документов: {e}", exc_info=True)
        print(f"\n❌ Ошибка при индексации: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()

