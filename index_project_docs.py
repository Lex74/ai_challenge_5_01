#!/usr/bin/env python3
"""Скрипт для индексации документации проекта (README, API, схемы данных)"""
import os
import sys
import logging
from pathlib import Path

from document_indexer import (
    index_documents,
    save_index,
    INDEX_FILE
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_project_docs() -> list[str]:
    """Возвращает список файлов документации проекта для индексации"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    docs = []
    
    # Добавляем README.md
    readme_path = os.path.join(base_dir, "README.md")
    if os.path.exists(readme_path):
        docs.append(readme_path)
    
    # Добавляем UPGRADE_INSTRUCTIONS.md
    upgrade_path = os.path.join(base_dir, "UPGRADE_INSTRUCTIONS.md")
    if os.path.exists(upgrade_path):
        docs.append(upgrade_path)
    
    # Ищем другие .md файлы в корне проекта
    for filename in os.listdir(base_dir):
        if filename.endswith('.md') and filename not in ['README.md', 'UPGRADE_INSTRUCTIONS.md']:
            md_path = os.path.join(base_dir, filename)
            if os.path.isfile(md_path):
                docs.append(md_path)
    
    # Добавляем основные Python файлы с документацией (docstrings)
    # Это поможет ассистенту понимать API проекта
    important_files = [
        "bot.py",
        "config.py",
        "constants.py",
        "rag.py",
        "openai_client.py",
        "document_indexer.py",
        "mcp_integration.py",
    ]
    
    for filename in important_files:
        file_path = os.path.join(base_dir, filename)
        if os.path.exists(file_path):
            docs.append(file_path)
    
    return sorted(docs)


def main():
    """Основная функция для индексации документации проекта"""
    print("="*60)
    print("📚 Индексация документации проекта")
    print("="*60)
    
    # Получаем список файлов документации
    file_paths = get_project_docs()
    
    if not file_paths:
        print("\n❌ Не найдено файлов документации для индексации")
        sys.exit(1)
    
    print(f"\n📄 Найдено файлов для индексации: {len(file_paths)}")
    for i, file_path in enumerate(file_paths, 1):
        print(f"  {i}. {file_path}")
    
    # Проверяем доступность эмбеддинг провайдера
    use_openai = os.getenv('USE_OPENAI_EMBEDDINGS', '').lower() == 'true'
    
    if use_openai:
        from config import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            print("\n❌ OPENAI_API_KEY не установлен!")
            print("   Добавьте OPENAI_API_KEY в файл .env")
            sys.exit(1)
        print(f"\n✅ Используем OpenAI эмбеддинги (text-embedding-3-small)")
    else:
        try:
            from document_indexer import check_ollama_available
            logger.info("Проверяю доступность OLLama...")
            if not check_ollama_available():
                print("\n❌ OLLama недоступен или модель не установлена!")
                print(f"   Проверьте: curl {os.getenv('OLLAMA_API_URL', 'http://localhost:11434')}/api/tags")
                print(f"   Установите модель: ollama pull nomic-embed-text")
                print(f"\n   Или установите USE_OPENAI_EMBEDDINGS=true для использования OpenAI")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Ошибка при проверке OLLama: {e}")
            print(f"\n❌ Ошибка при проверке OLLama: {e}")
            print(f"   Или установите USE_OPENAI_EMBEDDINGS=true для использования OpenAI")
            sys.exit(1)
    
    try:
        # Индексируем документы
        logger.info("Начинаю индексацию документации проекта...")
        
        index = index_documents(
            file_paths,
            source_name="project_documentation",
            process_in_batches=True,
            batch_size=20,
            chunk_size=200,  # Увеличиваем размер чанка для документации
            chunk_overlap=40,  # Увеличиваем перекрытие для лучшего контекста
            store_text=True,  # Сохраняем текст для RAG
            use_openai=use_openai
        )
        
        # Сохраняем индекс
        save_index(index, file_path=INDEX_FILE)
        
        # Выводим статистику
        metadata = index.get('metadata', {})
        total_chunks = metadata.get('total_chunks', 0)
        source_files = metadata.get('source_files', [])
        
        print("\n" + "="*60)
        print("✅ Индексация документации завершена успешно!")
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
        print(f"\n💾 Индекс сохранен в: {INDEX_FILE}")
        print("="*60)
        print("\n💡 Теперь ассистент разработчика может использовать эту документацию!")
        print("   Попробуйте: /assistant как работает RAG в этом проекте?")
        print("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"Ошибка при индексации документации: {e}", exc_info=True)
        print(f"\n❌ Ошибка при индексации: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
