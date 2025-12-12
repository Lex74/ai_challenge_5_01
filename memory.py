"""Модуль для работы с памятью пользователей"""
import os
import json
import logging

from constants import MEMORY_DIR

logger = logging.getLogger(__name__)


def ensure_memory_dir():
    """Создает папку memory/ если её нет"""
    if not os.path.exists(MEMORY_DIR):
        os.makedirs(MEMORY_DIR)
        logger.info(f"Создана папка {MEMORY_DIR}/")


def get_memory_file_path(user_id: int) -> str:
    """Возвращает путь к файлу памяти пользователя"""
    return os.path.join(MEMORY_DIR, f"user_{user_id}.json")


def load_memory_from_disk(user_id: int) -> dict:
    """Загружает память с диска (возвращает структуру с summary, recent_messages, message_count)"""
    memory_path = get_memory_file_path(user_id)
    
    if os.path.exists(memory_path):
        try:
            with open(memory_path, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)
                logger.info(f"Загружена память для пользователя {user_id}")
                return memory_data
        except Exception as e:
            logger.error(f"Ошибка при загрузке памяти для пользователя {user_id}: {e}")
            return {"summary": "", "recent_messages": [], "message_count": 0}
    else:
        return {"summary": "", "recent_messages": [], "message_count": 0}


def save_memory_to_disk(user_id: int, memory_data: dict):
    """Сохраняет память на диск"""
    ensure_memory_dir()
    memory_path = get_memory_file_path(user_id)
    
    try:
        with open(memory_path, 'w', encoding='utf-8') as f:
            json.dump(memory_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Сохранена память для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении памяти для пользователя {user_id}: {e}")


def clear_memory(user_id: int):
    """Очищает память пользователя на диске"""
    memory_path = get_memory_file_path(user_id)
    if os.path.exists(memory_path):
        os.remove(memory_path)
        logger.info(f"Очищена память для пользователя {user_id}")
