"""Модуль для работы с задачами через Notion MCP"""
import logging
import json
import re
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from mcp_client import call_notion_tool, list_notion_tools
from config import NOTION_TASKS_DATABASE_ID

logger = logging.getLogger(__name__)

# Путь к файлу хранения ID задач
TASKS_STORAGE_FILE = os.path.join(os.path.dirname(__file__), "tasks_storage.json")


def _load_stored_tasks() -> Dict[str, Dict[str, Any]]:
    """Загружает сохранённые задачи из файла"""
    try:
        if os.path.exists(TASKS_STORAGE_FILE):
            with open(TASKS_STORAGE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Ошибка загрузки хранилища задач: {e}")
    return {}


def _save_stored_tasks(tasks: Dict[str, Dict[str, Any]]) -> None:
    """Сохраняет задачи в файл"""
    try:
        with open(TASKS_STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"Ошибка сохранения хранилища задач: {e}")


def save_task_to_storage(page_id: str, title: str, priority: str, status: str = "Not started") -> None:
    """Сохраняет информацию о задаче в локальное хранилище"""
    tasks = _load_stored_tasks()
    tasks[page_id] = {
        "title": title,
        "priority": _normalize_priority(priority),
        "status": status,
        "created_at": datetime.now().isoformat()
    }
    _save_stored_tasks(tasks)
    logger.info(f"Задача сохранена в хранилище: {page_id} - {title}")


def get_stored_tasks_by_priority(priority: str) -> List[Dict[str, Any]]:
    """Возвращает задачи с указанным приоритетом из локального хранилища"""
    tasks = _load_stored_tasks()
    result = []
    normalized_priority = _normalize_priority(priority)
    
    for page_id, task_info in tasks.items():
        if _normalize_priority(task_info.get("priority", "")) == normalized_priority:
            result.append({
                "id": page_id,
                "title": task_info.get("title", ""),
                "priority": task_info.get("priority", ""),
                "status": task_info.get("status", ""),
                "created_at": task_info.get("created_at", "")
            })
    
    return result


def get_all_stored_task_ids() -> List[str]:
    """Возвращает все сохранённые page_id задач"""
    tasks = _load_stored_tasks()
    return list(tasks.keys())


async def find_tasks_database() -> Optional[str]:
    """Ищет базу данных задач в Notion через поиск"""
    try:
        # Ищем базу данных задач
        search_query = "задачи"  # Можно расширить поиск
        search_result = await call_notion_tool("notion-search", {
            "query": search_query,
            "filter": {"property": "object", "value": "database"}
        })
        
        if not search_result:
            logger.warning("Не удалось найти базу данных задач через поиск")
            return None
        
        # Парсим результат поиска
        try:
            if isinstance(search_result, str):
                search_data = json.loads(search_result)
            else:
                search_data = search_result
            
            # Ищем базу данных с задачами
            results = search_data.get("results", []) if isinstance(search_data, dict) else []
            for result in results:
                if result.get("object") == "database":
                    db_id = result.get("id", "")
                    if db_id:
                        logger.info(f"Найдена база данных задач: {db_id}")
                        return db_id
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Ошибка при парсинге результата поиска: {e}")
        
        return None
    except Exception as e:
        logger.error(f"Ошибка при поиске базы данных задач: {e}", exc_info=True)
        return None


async def get_tasks_database_id() -> Optional[str]:
    """Получает ID базы данных задач (из конфига или через поиск)"""
    if NOTION_TASKS_DATABASE_ID:
        return NOTION_TASKS_DATABASE_ID
    
    logger.info("NOTION_TASKS_DATABASE_ID не установлен, ищу базу данных через поиск")
    return await find_tasks_database()


async def create_task_in_notion(
    title: str,
    description: str = "",
    priority: str = "medium",
    database_id: Optional[str] = None,
    parent_page_id: Optional[str] = None,
    notion_tools: Optional[List[Dict[str, Any]]] = None,
    model: str = "gpt-4o-mini",
    temperature: float = 0.3
) -> Optional[str]:
    """Создает задачу в Notion базе данных или как дочернюю страницу
    
    Args:
        title: Название задачи
        description: Описание задачи
        priority: Приоритет (low, medium, high)
        database_id: ID базы данных (если не указан, будет получен автоматически)
        parent_page_id: ID родительской страницы (если указан, страница создается как дочерняя)
        notion_tools: Список Notion инструментов для LLM (если не указан, будет получен автоматически)
        model: Модель LLM для создания задачи
        temperature: Температура для LLM
    
    Returns:
        ID созданной страницы или None при ошибке
    """
    try:
        # Получаем ID базы данных/родительской страницы
        if not database_id:
            database_id = await get_tasks_database_id()
            if not database_id:
                logger.error("Не удалось получить ID базы данных задач")
                return None
        
        # Форматируем database_id для Notion API (добавляем дефисы, если нужно)
        if len(database_id) == 32 and '-' not in database_id:
            formatted_db_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"
        else:
            formatted_db_id = database_id
        
        # Используем NOTION_TASKS_DATABASE_ID как parent_page_id по умолчанию
        # (задачи создаются как дочерние страницы)
        if not parent_page_id:
            parent_page_id = NOTION_TASKS_DATABASE_ID
        
        # Логируем информацию о родительской странице для отладки и определяем тип
        is_parent_database = False
        if parent_page_id:
            formatted_parent_id, is_parent_database = await log_page_info(parent_page_id)
            if is_parent_database:
                logger.warning(f"⚠️ Родительский объект - это БАЗА ДАННЫХ, а не страница!")
                logger.warning(f"⚠️ База данных не может быть родителем обычной страницы.")
                logger.warning(f"⚠️ Использую прямой вызов API для создания записи в базе данных.")
                # Если это база данных, используем прямой вызов API (создаем запись в базе данных)
                return await _create_task_with_proper_format(title, description, priority, formatted_db_id, None)
            else:
                logger.info(f"✅ Родительский объект - это СТРАНИЦА, создаю дочернюю страницу")
                # Если это страница, используем прямой вызов API для создания дочерней страницы
                return await _create_task_with_proper_format(title, description, priority, formatted_db_id, formatted_parent_id)
        
        # Используем LLM для создания задачи через Notion инструменты
        # Это более надежно, так как LLM знает правильный формат из описания инструментов
        if notion_tools is None:
            logger.warning("Notion инструменты не предоставлены, пытаемся создать задачу напрямую")
            return await _create_task_with_proper_format(title, description, priority, formatted_db_id, parent_page_id)
        
        # Фильтруем только инструменты для создания страниц
        create_tools = [
            tool for tool in notion_tools
            if 'create' in tool.get('function', {}).get('name', '').lower() 
            and 'page' in tool.get('function', {}).get('name', '').lower()
        ]
        
        if not create_tools:
            logger.warning("Инструменты для создания страниц не найдены, пытаемся создать задачу напрямую")
            return await _create_task_with_proper_format(title, description, priority, formatted_db_id, parent_page_id)
        
        notion_tools = create_tools
        
        # Получаем схему базы данных для правильных имен свойств
        schema = await _get_database_schema(formatted_db_id)
        
        # Определяем имена свойств из схемы
        title_prop_name = "title"
        desc_prop_name = "Описание"
        priority_prop_name = "Приоритет"
        
        if schema:
            for prop_name, prop_info in schema.items():
                prop_type = prop_info.get("type", "") if isinstance(prop_info, dict) else ""
                if prop_type == "title":
                    title_prop_name = prop_name
                elif prop_type == "rich_text" and desc_prop_name == "Описание":
                    desc_prop_name = prop_name
                elif prop_type == "select" and priority_prop_name == "Приоритет":
                    priority_prop_name = prop_name
        
        # Используем LLM для создания задачи
        from openai_client import query_openai
        
        # Получаем имя инструмента для создания страниц
        create_tool_name = create_tools[0].get('function', {}).get('name', 'notion_create-pages')
        
        # Форматируем parent_page_id для использования в промпте
        formatted_parent_id = None
        if parent_page_id:
            if len(parent_page_id) == 32 and '-' not in parent_page_id:
                formatted_parent_id = f"{parent_page_id[:8]}-{parent_page_id[8:12]}-{parent_page_id[12:16]}-{parent_page_id[16:20]}-{parent_page_id[20:]}"
            else:
                formatted_parent_id = parent_page_id
        
        # Определяем формат parent для промпта
        # Если нашли реальную родительскую страницу, используем её
        if actual_parent_page_id:
            # Форматируем actual_parent_page_id
            if len(actual_parent_page_id) == 32 and '-' not in actual_parent_page_id:
                formatted_actual_parent = f"{actual_parent_page_id[:8]}-{actual_parent_page_id[8:12]}-{actual_parent_page_id[12:16]}-{actual_parent_page_id[16:20]}-{actual_parent_page_id[20:]}"
            else:
                formatted_actual_parent = actual_parent_page_id
            parent_format = f"{{'page_id': '{formatted_actual_parent}'}}"
            parent_description = f"КРИТИЧЕСКИ ВАЖНО: Страница должна быть создана как ДОЧЕРНЯЯ СТРАНИЦА родительской страницы с ID: {formatted_actual_parent}. Используй 'page_id' в parent, НЕ 'database_id'!"
        elif formatted_parent_id and not is_parent_database:
            parent_format = f"{{'page_id': '{formatted_parent_id}'}}"
            parent_description = f"КРИТИЧЕСКИ ВАЖНО: Страница должна быть создана как ДОЧЕРНЯЯ СТРАНИЦА родительской страницы с ID: {formatted_parent_id}. Используй 'page_id' в parent, НЕ 'database_id'!"
        else:
            # Используем database_id (либо родитель - база данных, либо создаем в базе данных)
            parent_id_to_use = formatted_parent_id if (formatted_parent_id and is_parent_database) else formatted_db_id
            parent_format = f"{{'database_id': '{parent_id_to_use}'}}"
            parent_description = f"Страница создается в базе данных с ID: {parent_id_to_use}. ВАЖНО: Это создаст запись ВНУТРИ базы данных, а не дочернюю страницу!"
        
        # Для базы данных MCP Notion ожидает упрощенный формат (строки), для страниц - полный формат
        if is_parent_database or not formatted_parent_id:
            # Упрощенный формат для базы данных
            properties_format = (
                f"\nФОРМАТ СВОЙСТВ (УПРОЩЕННЫЙ для базы данных - MCP Notion ожидает строки!):\n"
                f"- Название (Title, имя свойства: '{title_prop_name}'):\n"
                f"  {{'{title_prop_name}': 'название'}}  # ПРОСТО СТРОКА, не объект!\n"
                f"- Описание (Rich Text, имя свойства: '{desc_prop_name}'):\n"
                f"  {{'{desc_prop_name}': 'текст'}}  # ПРОСТО СТРОКА, не объект!\n"
                f"- Приоритет (Select, имя свойства: '{priority_prop_name}'):\n"
                f"  {{'{priority_prop_name}': 'high'}}  # ПРОСТО СТРОКА, не объект!\n"
                f"\nКРИТИЧЕСКИ ВАЖНО:\n"
                f"1. Используй ТОЧНО эти имена свойств: '{title_prop_name}', '{desc_prop_name}', '{priority_prop_name}'\n"
                f"2. Используй УПРОЩЕННЫЙ формат - свойства должны быть СТРОКАМИ, не объектами!\n"
                f"3. НЕ используй формат Notion API с объектами типа {{'title': [{{'type': 'text', ...}}]}}\n"
                f"4. Для Title: {{'{title_prop_name}': 'текст'}} - просто строка\n"
                f"5. Для Rich Text: {{'{desc_prop_name}': 'текст'}} - просто строка\n"
                f"6. Для Select: {{'{priority_prop_name}': 'high'}} - просто строка\n"
            )
        else:
            # Полный формат для дочерних страниц
            properties_format = (
                f"\nФОРМАТ СВОЙСТВ (Notion API формат для дочерних страниц):\n"
                f"- Название (Title, имя свойства: '{title_prop_name}'):\n"
                f"  {{'{title_prop_name}': {{'title': [{{'type': 'text', 'text': {{'content': 'название'}}}}]}}}}\n"
                f"- Описание (Rich Text, имя свойства: '{desc_prop_name}'):\n"
                f"  {{'{desc_prop_name}': {{'rich_text': [{{'type': 'text', 'text': {{'content': 'текст'}}}}]}}}}\n"
                f"- Приоритет (Select, имя свойства: '{priority_prop_name}'):\n"
                f"  {{'{priority_prop_name}': {{'select': {{'name': 'high'}}}}}}\n"
                f"\nВАЖНО:\n"
                f"1. Используй ТОЧНО эти имена свойств: '{title_prop_name}', '{desc_prop_name}', '{priority_prop_name}'\n"
                f"2. Используй ТОЛЬКО формат Notion API с объектами\n"
                f"3. Все свойства должны быть объектами с правильной структурой\n"
            )
        
        system_prompt = (
            f"Ты помощник, который создает задачи в Notion через инструмент {create_tool_name}. "
            f"{parent_description}\n"
            f"\n\nИНСТРУКЦИИ ПО ИСПОЛЬЗОВАНИЮ {create_tool_name}:\n"
            f"Инструмент создает одну или несколько страниц Notion с указанными свойствами и содержимым. "
            f"Если родитель не указан, будет создана приватная страница.\n"
            f"\nКРИТИЧЕСКИ ВАЖНО - ФОРМАТ ВЫЗОВА:\n"
            f"ОБЯЗАТЕЛЬНО создавай ОДИН объект в массиве pages с ОБОИМИ полями: parent И properties!\n"
            f"ПРАВИЛЬНО:\n"
            f"{{\n"
            f"  'pages': [{{\n"
            f"    'parent': {parent_format},\n"
            f"    'properties': {{'title': '...', 'Описание': '...', 'Приоритет': '...'}}\n"
            f"  }}]\n"
            f"}}\n"
            f"\nНЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК!):\n"
            f"{{\n"
            f"  'pages': [{{'parent': {parent_format}}}, {{'properties': {{...}}}}]\n"
            f"}}\n"
            f"\nВАЖНО: parent и properties должны быть в ОДНОМ объекте внутри массива pages!\n"
            f"{properties_format}"
        )
        
        if formatted_parent_id and not is_parent_database:
            user_prompt = (
                f"Создай задачу в Notion как ДОЧЕРНЮЮ СТРАНИЦУ родительской страницы с ID {formatted_parent_id} используя инструмент {create_tool_name}:\n"
                f"Название: {title}\n"
                f"Описание: {description if description else ''}\n"
                f"Приоритет: {priority}\n\n"
                f"ВАЖНО: Используй parent: {{'page_id': '{formatted_parent_id}'}}, НЕ используй database_id!\n"
                f"Используй правильные имена свойств: '{title_prop_name}', '{desc_prop_name}', '{priority_prop_name}'. "
                f"Используй ТОЧНЫЙ формат Notion API для свойств."
            )
        else:
            # Для базы данных используем database_id
            db_id_to_use = formatted_parent_id if (formatted_parent_id and is_parent_database) else formatted_db_id
            user_prompt = (
                f"Создай задачу в Notion базе данных с ID {db_id_to_use} используя инструмент {create_tool_name}:\n"
                f"Название: {title}\n"
                f"Описание: {description if description else ''}\n"
                f"Приоритет: {priority}\n\n"
                f"КРИТИЧЕСКИ ВАЖНО:\n"
                f"1. Создай ОДИН объект в массиве pages с ОБОИМИ полями: parent И properties вместе!\n"
                f"2. Используй parent: {{'database_id': '{db_id_to_use}'}}, НЕ используй page_id!\n"
                f"3. Используй УПРОЩЕННЫЙ формат свойств - свойства должны быть СТРОКАМИ:\n"
                f"   - {{'{title_prop_name}': '{title}'}}  # просто строка\n"
                f"   - {{'{desc_prop_name}': '{description if description else ''}'}}  # просто строка\n"
                f"   - {{'{priority_prop_name}': '{priority}'}}  # просто строка\n"
                f"4. НЕ используй формат Notion API с объектами типа {{'title': [{{'type': 'text', ...}}]}}!\n"
                f"5. Используй правильные имена свойств: '{title_prop_name}', '{desc_prop_name}', '{priority_prop_name}'.\n"
                f"6. Структура должна быть: {{'pages': [{{'parent': {{'database_id': '{db_id_to_use}'}}, 'properties': {{'{title_prop_name}': '{title}', '{desc_prop_name}': '{description if description else ''}', '{priority_prop_name}': '{priority}'}}}}]}}"
            )
        
        answer, history = await query_openai(
            user_prompt,
            [],
            system_prompt,
            temperature,
            model,
            1000,
            None,  # bot
            notion_tools
        )
        
        # Извлекаем ID созданной страницы из ответа или истории
        page_id = None
        for msg in history:
            if msg.get("role") == "tool":
                tool_name = msg.get("name", "")
                if "notion" in tool_name.lower() and "create" in tool_name.lower():
                    content = msg.get("content", "")
                    try:
                        if isinstance(content, str):
                            result_data = json.loads(content)
                        else:
                            result_data = content
                        
                        # Извлекаем ID из результата
                        # MCP Notion возвращает результат в формате {"pages": [{"id": "...", ...}]}
                        if isinstance(result_data, dict):
                            if "pages" in result_data:
                                pages = result_data.get("pages", [])
                                if isinstance(pages, list) and len(pages) > 0:
                                    page_id = pages[0].get("id", "")
                            else:
                                page_id = result_data.get("id", "")
                        elif isinstance(result_data, list) and len(result_data) > 0:
                            page_id = result_data[0].get("id", "")
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
        
        if page_id:
            logger.info(f"Задача создана успешно через LLM: {page_id}")
            # Сохраняем задачу в локальное хранилище
            save_task_to_storage(page_id, title, priority)
            # Проверяем, где создалась страница
            await log_created_page_location(page_id)
            return page_id
        else:
            logger.warning("Не удалось извлечь ID созданной задачи из ответа LLM, пробуем прямой вызов")
            # Fallback: пробуем прямой вызов с правильным форматом
            return await _create_task_with_proper_format(title, description, priority, formatted_db_id, parent_page_id)
        
        # Получаем схему базы данных для правильных имен свойств
        schema = await _get_database_schema(formatted_db_id)
        
        # Определяем имена свойств из схемы
        title_prop_name = "title"
        desc_prop_name = "Описание"
        priority_prop_name = "Приоритет"
        
        if schema:
            for prop_name, prop_info in schema.items():
                prop_type = prop_info.get("type", "") if isinstance(prop_info, dict) else ""
                if prop_type == "title":
                    title_prop_name = prop_name
                elif prop_type == "rich_text" and desc_prop_name == "Описание":
                    desc_prop_name = prop_name
                elif prop_type == "select" and priority_prop_name == "Приоритет":
                    priority_prop_name = prop_name
        
        # Используем LLM для создания задачи
        from openai_client import query_openai
        
        # Получаем имя инструмента для создания страниц
        create_tool_name = create_tools[0].get('function', {}).get('name', 'notion_create-pages')
        
        # Формируем пример правильного формата свойств с правильными именами
        properties_example = {
            title_prop_name: {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        }
        if description:
            properties_example[desc_prop_name] = {
                "rich_text": [{"type": "text", "text": {"content": description}}]
            }
        properties_example[priority_prop_name] = {
            "select": {"name": priority}
        }
        
        system_prompt = (
            f"Ты помощник, который создает задачи в Notion базе данных через MCP инструмент. "
            f"База данных имеет ID: {formatted_db_id}. "
            f"\n\nКРИТИЧЕСКИ ВАЖНО - ФОРМАТ СВОЙСТВ:\n"
            f"Используй ТОЧНО такой формат для свойств (это формат Notion API):\n"
            f"- Название (Title, имя свойства: '{title_prop_name}'): {{'{title_prop_name}': {{'title': [{{'type': 'text', 'text': {{'content': 'название'}}}}]}}}}\n"
            f"- Описание (Rich Text, имя свойства: '{desc_prop_name}'): {{'{desc_prop_name}': {{'rich_text': [{{'type': 'text', 'text': {{'content': 'текст'}}}}]}}}}\n"
            f"- Приоритет (Select, имя свойства: '{priority_prop_name}'): {{'{priority_prop_name}': {{'select': {{'name': 'high'}}}}}}\n"
            f"\nПример правильного формата для этой задачи:\n"
            f"properties = {json.dumps(properties_example, ensure_ascii=False, indent=2)}\n"
            f"\nСтруктура вызова инструмента:\n"
            f"{{\n"
            f"  'pages': [{{\n"
            f"    'parent': {{'database_id': '{formatted_db_id}'}},\n"
            f"    'properties': <используй формат выше с правильными именами свойств>\n"
            f"  }}]\n"
            f"}}\n"
            f"\nВАЖНО: Используй ТОЧНО эти имена свойств: '{title_prop_name}', '{desc_prop_name}', '{priority_prop_name}'. "
            f"НЕ используй упрощенный формат! Используй ТОЛЬКО формат Notion API с объектами."
        )
        
        user_prompt = (
            f"Создай задачу в Notion базе данных с ID {formatted_db_id}:\n"
            f"Название: {title}\n"
            f"Описание: {description if description else ''}\n"
            f"Приоритет: {priority}\n\n"
            f"Используй инструмент {create_tool_name} с ТОЧНЫМ форматом свойств из инструкций выше. "
            f"Используй правильные имена свойств: '{title_prop_name}', '{desc_prop_name}', '{priority_prop_name}'."
        )
        
        answer, history = await query_openai(
            user_prompt,
            [],
            system_prompt,
            temperature,
            model,
            1000,
            None,  # bot
            notion_tools
        )
        
        # Извлекаем ID созданной страницы из ответа или истории
        # Проверяем историю на наличие вызовов инструментов
        page_id = None
        for msg in history:
            if msg.get("role") == "tool":
                tool_name = msg.get("name", "")
                if "notion" in tool_name.lower() and "create" in tool_name.lower():
                    content = msg.get("content", "")
                    try:
                        if isinstance(content, str):
                            result_data = json.loads(content)
                        else:
                            result_data = content
                        
                        # Извлекаем ID из результата
                        # MCP Notion возвращает результат в формате {"pages": [{"id": "...", ...}]}
                        if isinstance(result_data, dict):
                            if "pages" in result_data:
                                pages = result_data.get("pages", [])
                                if isinstance(pages, list) and len(pages) > 0:
                                    page_id = pages[0].get("id", "")
                            else:
                                page_id = result_data.get("id", "")
                        elif isinstance(result_data, list) and len(result_data) > 0:
                            page_id = result_data[0].get("id", "")
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
        
        if page_id:
            logger.info(f"Задача создана успешно через LLM: {page_id}")
            # Сохраняем задачу в локальное хранилище
            save_task_to_storage(page_id, title, priority)
            # Проверяем, где создалась страница
            await log_created_page_location(page_id)
            return page_id
        else:
            logger.warning("Не удалось извлечь ID созданной задачи из ответа LLM, пробуем прямой вызов с правильным форматом")
            # Fallback: пробуем прямой вызов с правильным форматом Notion API
            return await _create_task_with_proper_format(title, description, priority, formatted_db_id, parent_page_id)
            
    except Exception as e:
        logger.error(f"Ошибка при создании задачи в Notion: {e}", exc_info=True)
        # Fallback: пробуем прямой вызов с правильным форматом
        try:
            db_id = formatted_db_id if 'formatted_db_id' in locals() else database_id
            if db_id:
                # Форматируем database_id, если нужно
                if len(db_id) == 32 and '-' not in db_id:
                    db_id = f"{db_id[:8]}-{db_id[8:12]}-{db_id[12:16]}-{db_id[16:20]}-{db_id[20:]}"
                return await _create_task_with_proper_format(title, description, priority, db_id, parent_page_id)
        except Exception as e:
            logger.error(f"Ошибка в fallback создании задачи: {e}")
        return None


async def log_page_info(page_id: str) -> tuple[Optional[str], bool]:
    """Логирует информацию о странице Notion для отладки и определяет тип (database или page)
    
    Returns:
        tuple: (formatted_id, is_database) - отформатированный ID и флаг, является ли это базой данных
    """
    try:
        # Форматируем page_id для Notion API (добавляем дефисы, если нужно)
        if len(page_id) == 32 and '-' not in page_id:
            formatted_page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
        else:
            formatted_page_id = page_id
        
        logger.info(f"Получаю информацию о странице: {formatted_page_id}")
        
        fetch_result = await call_notion_tool("notion-fetch", {
            "id": formatted_page_id
        })
        
        if not fetch_result:
            logger.error(f"Не удалось получить информацию о странице {formatted_page_id}")
            return formatted_page_id, False
        
        try:
            if isinstance(fetch_result, str):
                page_data = json.loads(fetch_result)
            else:
                page_data = fetch_result
            
            # Проверяем тип объекта
            metadata = page_data.get('metadata', {})
            is_database = metadata.get('type') == 'database'
            
            logger.info("=" * 80)
            logger.info(f"ИНФОРМАЦИЯ О СТРАНИЦЕ {formatted_page_id}:")
            logger.info("=" * 80)
            logger.info(f"Тип: {'БАЗА ДАННЫХ' if is_database else 'СТРАНИЦА'}")
            
            # Основная информация
            logger.info(f"ID: {page_data.get('id', 'N/A')}")
            logger.info(f"URL: {page_data.get('url', 'N/A')}")
            logger.info(f"Title: {page_data.get('title', 'N/A')}")
            
            if is_database:
                # Для базы данных извлекаем схему из text
                text = page_data.get('text', '')
                logger.info(f"Схема базы данных извлечена из text")
            else:
                # Информация о родителе для обычной страницы
                parent = page_data.get('parent', {})
                logger.info(f"Parent type: {parent.get('type', 'N/A')}")
                if parent.get('type') == 'page_id':
                    logger.info(f"Parent page_id: {parent.get('page_id', 'N/A')}")
                elif parent.get('type') == 'database_id':
                    logger.info(f"Parent database_id: {parent.get('database_id', 'N/A')}")
                elif parent.get('type') == 'workspace':
                    logger.info("Parent: workspace (корневая страница)")
                
                # Свойства страницы
                properties = page_data.get('properties', {})
                logger.info(f"\nСвойства страницы (всего: {len(properties)}):")
                for prop_name, prop_info in properties.items():
                    prop_type = prop_info.get('type', 'unknown') if isinstance(prop_info, dict) else 'unknown'
                    logger.info(f"  - {prop_name}: {prop_type}")
            
            # Полный JSON для детального анализа
            logger.info("\n" + "=" * 80)
            logger.info("ПОЛНЫЙ JSON СТРАНИЦЫ:")
            logger.info("=" * 80)
            logger.info(json.dumps(page_data, ensure_ascii=False, indent=2))
            logger.info("=" * 80)
            
            return formatted_page_id, is_database
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Ошибка при парсинге информации о странице: {e}")
            logger.error(f"Сырой ответ: {fetch_result}")
            return formatted_page_id, False
    except Exception as e:
        logger.error(f"Ошибка при получении информации о странице: {e}", exc_info=True)
        return None, False


async def log_created_page_location(page_id: str) -> None:
    """Логирует информацию о том, где создалась страница (родитель)"""
    try:
        # Форматируем page_id для Notion API (добавляем дефисы, если нужно)
        if len(page_id) == 32 and '-' not in page_id:
            formatted_page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
        else:
            formatted_page_id = page_id
        
        logger.info("=" * 80)
        logger.info(f"ПРОВЕРКА МЕСТОПОЛОЖЕНИЯ СОЗДАННОЙ СТРАНИЦЫ: {formatted_page_id}")
        logger.info("=" * 80)
        
        fetch_result = await call_notion_tool("notion-fetch", {
            "id": formatted_page_id
        })
        
        if not fetch_result:
            logger.error(f"Не удалось получить информацию о созданной странице {formatted_page_id}")
            return
        
        try:
            if isinstance(fetch_result, str):
                page_data = json.loads(fetch_result)
            else:
                page_data = fetch_result
            
            # Информация о странице
            logger.info(f"ID созданной страницы: {formatted_page_id}")
            logger.info(f"URL: {page_data.get('url', 'N/A')}")
            logger.info(f"Title: {page_data.get('title', 'N/A')}")
            
            # Информация о родителе
            # Для страниц в базе данных notion-fetch может возвращать данные в другом формате
            parent = page_data.get('parent', {})
            parent_type = parent.get('type', 'N/A')
            
            # Если parent пустой, проверяем, может быть это страница в базе данных
            # В этом случае parent может быть в другом месте или формат ответа другой
            if not parent or parent_type == 'N/A':
                # Пробуем найти информацию о родителе в других полях
                # Для страниц в базе данных parent может быть в другом формате
                logger.info(f"\nРОДИТЕЛЬСКИЙ ОБЪЕКТ:")
                logger.info(f"  Тип: не определен в стандартном формате")
                logger.info(f"  Проверяю альтернативные форматы...")
                
                # Проверяем, может быть это страница в базе данных (по структуре данных)
                # Если есть properties с простыми значениями (строки), это скорее всего база данных
                properties = page_data.get('properties', {})
                if properties:
                    # Проверяем формат properties - если это простые строки, это база данных
                    sample_prop = next(iter(properties.values())) if properties else None
                    if isinstance(sample_prop, str):
                        logger.info(f"  ✅ Страница создана в БАЗЕ ДАННЫХ (определено по формату properties)")
                        logger.info(f"  Properties в упрощенном формате (строки) - это база данных")
                    else:
                        logger.info(f"  ✅ Страница создана как ДОЧЕРНЯЯ СТРАНИЦА (определено по формату properties)")
                        logger.info(f"  Properties в полном формате Notion API - это дочерняя страница")
            else:
                logger.info(f"\nРОДИТЕЛЬСКИЙ ОБЪЕКТ:")
                logger.info(f"  Тип: {parent_type}")
                
                if parent_type == 'page_id':
                    parent_id = parent.get('page_id', 'N/A')
                    logger.info(f"  Parent page_id: {parent_id}")
                    logger.info(f"  ✅ Страница создана как ДОЧЕРНЯЯ СТРАНИЦА страницы: {parent_id}")
                    
                    # Получаем информацию о родительской странице
                    try:
                        parent_info = await call_notion_tool("notion-fetch", {"id": parent_id})
                        if parent_info:
                            if isinstance(parent_info, str):
                                parent_data = json.loads(parent_info)
                            else:
                                parent_data = parent_info
                            parent_title = parent_data.get('title', 'N/A')
                            logger.info(f"  Название родительской страницы: {parent_title}")
                    except Exception as e:
                        logger.warning(f"  Не удалось получить информацию о родительской странице: {e}")
                        
                elif parent_type == 'database_id':
                    parent_id = parent.get('database_id', 'N/A')
                    logger.info(f"  Parent database_id: {parent_id}")
                    logger.info(f"  ✅ Страница создана в БАЗЕ ДАННЫХ: {parent_id}")
                    
                    # Получаем информацию о базе данных
                    try:
                        db_info = await call_notion_tool("notion-fetch", {"id": parent_id})
                        if db_info:
                            if isinstance(db_info, str):
                                db_data = json.loads(db_info)
                            else:
                                db_data = db_info
                            db_title = db_data.get('title', 'N/A')
                            logger.info(f"  Название базы данных: {db_title}")
                    except Exception as e:
                        logger.warning(f"  Не удалось получить информацию о базе данных: {e}")
                        
                elif parent_type == 'workspace':
                    logger.info(f"  ✅ Страница создана в КОРНЕ workspace (не имеет родителя)")
                else:
                    logger.warning(f"  ⚠️ Неизвестный тип родителя: {parent_type}")
            
            # Свойства созданной страницы
            properties = page_data.get('properties', {})
            logger.info(f"\nСВОЙСТВА СОЗДАННОЙ СТРАНИЦЫ (всего: {len(properties)}):")
            if properties:
                for prop_name, prop_value in properties.items():
                    # Проверяем формат свойства - упрощенный (строка) или полный (объект)
                    if isinstance(prop_value, str):
                        # Упрощенный формат для базы данных
                        logger.info(f"  - {prop_name}: строка (упрощенный формат)")
                        logger.info(f"    Значение: '{prop_value}'")
                    elif isinstance(prop_value, dict):
                        # Полный формат Notion API
                        prop_type = prop_value.get('type', 'unknown')
                        logger.info(f"  - {prop_name}: {prop_type} (полный формат Notion API)")
                        if prop_type == 'title':
                            title_array = prop_value.get('title', [])
                            if title_array:
                                title_text = title_array[0].get('plain_text', '') if isinstance(title_array[0], dict) else str(title_array[0])
                                logger.info(f"    Значение: '{title_text}'")
                        elif prop_type == 'rich_text':
                            rich_text_array = prop_value.get('rich_text', [])
                            if rich_text_array:
                                text_value = rich_text_array[0].get('plain_text', '') if isinstance(rich_text_array[0], dict) else str(rich_text_array[0])
                                logger.info(f"    Значение: '{text_value[:50]}...' (первые 50 символов)" if len(text_value) > 50 else f"    Значение: '{text_value}'")
                        elif prop_type == 'select':
                            select_obj = prop_value.get('select')
                            if select_obj:
                                logger.info(f"    Значение: {select_obj.get('name', 'N/A')}")
                    else:
                        logger.info(f"  - {prop_name}: {type(prop_value).__name__} = {prop_value}")
            else:
                logger.warning("  ⚠️ Свойства пустые! Страница создана без свойств.")
            
            logger.info("=" * 80)
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Ошибка при парсинге информации о созданной странице: {e}")
            logger.error(f"Сырой ответ: {fetch_result}")
    except Exception as e:
        logger.error(f"Ошибка при проверке местоположения созданной страницы: {e}", exc_info=True)


async def _get_database_schema(database_id: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Получает схему базы данных через notion-fetch
    
    Returns:
        tuple: (schema, collection_id) - схема и ID коллекции для создания записей
    """
    try:
        fetch_result = await call_notion_tool("notion-fetch", {
            "id": database_id
        })
        
        if not fetch_result:
            return None, None
        
        try:
            if isinstance(fetch_result, str):
                db_data = json.loads(fetch_result)
            else:
                db_data = fetch_result
            
            # Извлекаем свойства базы данных
            if isinstance(db_data, dict):
                # Сначала пробуем стандартные поля
                properties = db_data.get("properties") or db_data.get("schema", {}).get("properties")
                if properties:
                    logger.info(f"Получена схема базы данных (стандартный формат): {list(properties.keys())}")
                    return properties, None
                
                # Если не нашли, пробуем извлечь из поля text (MCP Notion формат)
                # Схема находится внутри <data-source-state>...</data-source-state>
                text = db_data.get("text", "")
                collection_id = None
                schema = None
                
                if text:
                    import re
                    
                    # Извлекаем ID коллекции из <data-source url="{{collection://...}}">
                    collection_match = re.search(r'<data-source url="\{\{collection://([^}]+)\}\}">', text)
                    if collection_match:
                        collection_id = collection_match.group(1)
                        logger.info(f"Найден ID коллекции: {collection_id}")
                    
                    # Извлекаем JSON из <data-source-state>
                    if "<data-source-state>" in text:
                        match = re.search(r'<data-source-state>\s*(\{.*?\})\s*</data-source-state>', text, re.DOTALL)
                        if match:
                            try:
                                data_source_state = json.loads(match.group(1))
                                schema = data_source_state.get("schema", {})
                                if schema:
                                    logger.info(f"Получена схема базы данных (из text/data-source-state): {list(schema.keys())}")
                                
                                # Также можем получить collection_id из url в data-source-state
                                if not collection_id:
                                    url = data_source_state.get("url", "")
                                    if url.startswith("collection://"):
                                        collection_id = url.replace("collection://", "")
                                        logger.info(f"Найден ID коллекции из data-source-state: {collection_id}")
                            except json.JSONDecodeError as e:
                                logger.warning(f"Ошибка при парсинге data-source-state: {e}")
                
                return schema, collection_id
                
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Ошибка при парсинге схемы базы данных: {e}")
        
        return None, None
    except Exception as e:
        logger.warning(f"Не удалось получить схему базы данных: {e}")
        return None, None


async def _create_task_with_proper_format(
    title: str,
    description: str,
    priority: str,
    formatted_db_id: str,
    parent_page_id: Optional[str] = None
) -> Optional[str]:
    """Прямой вызов создания задачи с правильным форматом Notion API
    
    Args:
        title: Название задачи
        description: Описание задачи
        priority: Приоритет (low, medium, high)
        formatted_db_id: ID базы данных (используется если parent_page_id не указан)
        parent_page_id: ID родительской страницы (если указан, страница создается как дочерняя)
    """
    try:
        # Определяем parent для создания страницы
        is_child_page = bool(parent_page_id)
        
        collection_id = None
        
        if parent_page_id:
            # Форматируем parent_page_id для Notion API (добавляем дефисы, если нужно)
            if len(parent_page_id) == 32 and '-' not in parent_page_id:
                formatted_parent_id = f"{parent_page_id[:8]}-{parent_page_id[8:12]}-{parent_page_id[12:16]}-{parent_page_id[16:20]}-{parent_page_id[20:]}"
            else:
                formatted_parent_id = parent_page_id
            parent = {"page_id": formatted_parent_id}
            logger.info(f"Создаю страницу как дочернюю страницу: {formatted_parent_id}")
            
            # Логируем информацию о родительской странице для отладки
            await log_page_info(parent_page_id)
            
            # Для дочерних страниц схему получаем из родительской страницы (если это база данных)
            schema, collection_id = await _get_database_schema(formatted_parent_id)
        else:
            logger.info(f"Создаю страницу в базе данных: {formatted_db_id}")
            # Пытаемся получить схему базы данных и ID коллекции
            schema, collection_id = await _get_database_schema(formatted_db_id)
            
            # Используем ID коллекции если найден, иначе ID базы данных
            if collection_id:
                # Форматируем collection_id (добавляем дефисы, если нужно)
                if len(collection_id) == 32 and '-' not in collection_id:
                    formatted_collection_id = f"{collection_id[:8]}-{collection_id[8:12]}-{collection_id[12:16]}-{collection_id[16:20]}-{collection_id[20:]}"
                else:
                    formatted_collection_id = collection_id
                parent = {"database_id": formatted_collection_id}
                logger.info(f"Используем ID коллекции для создания записи: {formatted_collection_id}")
            else:
                parent = {"database_id": formatted_db_id}
                logger.info(f"ID коллекции не найден, используем ID базы данных: {formatted_db_id}")
        
        # Определяем имена свойств
        # Для дочерних страниц (не в базе данных) используем стандартные имена
        if is_child_page:
            # Для дочерних страниц Notion использует стандартное имя "title"
            title_prop_name = "title"
            desc_prop_name = "Описание"  # Может не использоваться для обычных страниц
            priority_prop_name = "Приоритет"  # Может не использоваться для обычных страниц
        else:
            # Для страниц в базе данных получаем имена из схемы
            # Устанавливаем None по умолчанию - добавим только если найдем в схеме
            title_prop_name = None
            desc_prop_name = None
            priority_prop_name = None
            
            if schema:
                logger.info(f"Анализирую схему базы данных: {json.dumps(schema, ensure_ascii=False)}")
                # Ищем свойства по типу
                for prop_name, prop_info in schema.items():
                    prop_type = prop_info.get("type", "") if isinstance(prop_info, dict) else ""
                    logger.info(f"  Свойство '{prop_name}': тип '{prop_type}'")
                    if prop_type == "title":
                        title_prop_name = prop_name
                        logger.info(f"  → Используем '{prop_name}' как title")
                    elif prop_type in ("rich_text", "text") and desc_prop_name is None:
                        # Используем первое rich_text/text свойство как описание
                        desc_prop_name = prop_name
                        logger.info(f"  → Используем '{prop_name}' как описание (тип: {prop_type})")
                    elif prop_type == "select" and priority_prop_name is None:
                        # Используем первое select свойство как приоритет
                        priority_prop_name = prop_name
                        logger.info(f"  → Используем '{prop_name}' как приоритет")
            
            # Если title не найден в схеме, используем "title" по умолчанию
            if title_prop_name is None:
                title_prop_name = "title"
                logger.warning(f"Свойство title не найдено в схеме, используем 'title' по умолчанию")
        
        # Логируем какие свойства будут использованы
        logger.info(f"Определенные свойства из схемы:")
        logger.info(f"  - title: '{title_prop_name}'")
        logger.info(f"  - описание: '{desc_prop_name}' (будет добавлено: {bool(description and desc_prop_name)})")
        logger.info(f"  - приоритет: '{priority_prop_name}' (будет добавлено: {bool(priority_prop_name)})")
        
        # MCP сервер Notion ожидает упрощенный формат свойств
        # Пробуем сначала создать страницу только с названием (минимальная страница)
        # Затем обновим ее через notion-update-page с остальными свойствами
        logger.info("Создаю минимальную страницу только с названием")
        
        # MCP Notion сервер ожидает упрощенный формат (строки) для ВСЕХ страниц
        # И для дочерних страниц, и для страниц в базе данных
        minimal_properties = {
            title_prop_name: title  # Просто строка, не объект Notion API
        }
        
        # Если приоритет указан и мы знаем имя свойства, добавляем его
        # Для MCP Notion используем упрощенный формат (строка)
        if priority_prop_name:
            priority_map = {
                "low": "low",
                "medium": "medium",
                "high": "high"
            }
            priority_value = priority_map.get(priority.lower(), "medium")
            # Упрощенный формат для select (строка)
            minimal_properties[priority_prop_name] = priority_value
        
        try:
            # Логируем, что передаем в parent для отладки
            logger.info(f"Создаю страницу с parent: {json.dumps(parent, ensure_ascii=False)}")
            logger.info(f"Свойства: {json.dumps(minimal_properties, ensure_ascii=False)}")
            logger.info(f"Это дочерняя страница: {is_child_page}")
            logger.info(f"Collection ID для создания записи в БД: {collection_id}")
            
            # Формируем данные для создания страницы
            # Для записей в базе данных используем data_source_id и parent на верхнем уровне
            # Для обычных страниц используем page_id внутри каждой страницы
            if collection_id and not is_child_page:
                # Создание записи в базе данных - используем data_source_id
                # Parent на верхнем уровне, страницы содержат только properties
                create_payload = {
                    "parent": {
                        "data_source_id": collection_id
                    },
                    "pages": [{
                        "properties": minimal_properties
                    }]
                }
                logger.info(f"Используем формат с data_source_id для создания записи в БД")
            else:
                # Создание обычной страницы - parent внутри каждой страницы
                create_payload = {
                    "pages": [{
                        "parent": parent,
                        "properties": minimal_properties
                    }]
                }
                logger.info(f"Используем стандартный формат для создания страницы")
            
            logger.info(f"Payload для notion-create-pages: {json.dumps(create_payload, ensure_ascii=False)}")
            create_result = await call_notion_tool("notion-create-pages", create_payload)
            
            # Логируем сырой ответ от MCP
            logger.info(f"Ответ от notion-create-pages (тип: {type(create_result).__name__}): {create_result}")
            
            if not create_result:
                logger.error("Не удалось создать даже минимальную страницу (пустой ответ)")
                return None
            
            # Парсим результат создания
            page_id = None
            try:
                if isinstance(create_result, str):
                    result_data = json.loads(create_result)
                else:
                    result_data = create_result
                
                logger.info(f"Parsed result_data (тип: {type(result_data).__name__}): {json.dumps(result_data, ensure_ascii=False) if isinstance(result_data, (dict, list)) else result_data}")
                
                # MCP Notion может возвращать результат в разных форматах
                if isinstance(result_data, dict):
                    # Пробуем разные форматы ответа
                    if "pages" in result_data:
                        # Формат с ключом "pages"
                        pages = result_data.get("pages", [])
                        if isinstance(pages, list) and len(pages) > 0:
                            page_id = pages[0].get("id", "") or pages[0].get("url", "")
                            logger.info(f"Извлечен ID из pages[0]: {page_id}")
                    elif "id" in result_data:
                        # Прямой формат с "id" в корне
                        page_id = result_data.get("id", "")
                        logger.info(f"Извлечен ID из корня: {page_id}")
                    elif "url" in result_data:
                        # Формат с URL (извлекаем ID из URL)
                        url = result_data.get("url", "")
                        if url:
                            # URL может быть в формате https://www.notion.so/xxx или collection://xxx
                            page_id = url.split("/")[-1].replace("-", "")
                            logger.info(f"Извлечен ID из URL: {page_id}")
                    else:
                        logger.warning(f"Неизвестный формат ответа (dict): ключи = {list(result_data.keys())}")
                elif isinstance(result_data, list) and len(result_data) > 0:
                    # Формат как список страниц
                    first_item = result_data[0]
                    if isinstance(first_item, dict):
                        page_id = first_item.get("id", "") or first_item.get("url", "")
                    logger.info(f"Извлечен ID из списка: {page_id}")
                else:
                    logger.warning(f"Неизвестный формат ответа: {type(result_data)}")
            except (json.JSONDecodeError, KeyError, TypeError) as parse_error:
                logger.error(f"Ошибка при парсинге результата создания: {parse_error}")
                logger.error(f"Сырой результат: {create_result}")
                return None
            
            if not page_id:
                logger.error(f"Не удалось извлечь ID созданной страницы из ответа")
                return None
            
            logger.info(f"Минимальная страница создана: {page_id}")
            
            # Обновляем страницу с остальными свойствами через notion-update-page
            # MCP Notion ожидает упрощенный формат (строки) для свойств
            update_properties = {}
            if description and desc_prop_name:
                # Упрощенный формат - просто строка
                update_properties[desc_prop_name] = description
            # Обновляем приоритет в упрощенном формате
            if priority_prop_name:
                priority_map = {
                    "low": "low",
                    "medium": "medium",
                    "high": "high"
                }
                priority_value = priority_map.get(priority.lower(), "medium")
                # Упрощенный формат - просто строка
                update_properties[priority_prop_name] = priority_value
            
            # Всегда обновляем свойства (хотя бы приоритет), если они указаны
            if update_properties:
                # Форматируем page_id для Notion API
                if len(page_id) == 32 and '-' not in page_id:
                    formatted_page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
                else:
                    formatted_page_id = page_id
                
                logger.info(f"Обновляю страницу {formatted_page_id} с дополнительными свойствами")
                
                # Пробуем обновить через notion-update-page
                # ВАЖНО: MCP Notion требует поле "command": "update_properties" и упрощенный формат свойств
                try:
                    update_result = await call_notion_tool("notion-update-page", {
                        "data": {
                            "page_id": formatted_page_id,
                            "command": "update_properties",
                            "properties": update_properties
                        }
                    })
                    
                    if update_result:
                        logger.info(f"Задача создана и обновлена успешно: {page_id}")
                    else:
                        logger.warning(f"Страница создана, но обновление не удалось: {page_id}")
                except Exception as update_error:
                    logger.warning(f"Ошибка при обновлении страницы, но она создана: {update_error}")
                    # Возвращаем page_id даже если обновление не удалось
            else:
                logger.info(f"Задача создана только с названием (нет дополнительных свойств): {page_id}")
            
            # Проверяем, где создалась страница
            await log_created_page_location(page_id)
            return page_id
            
        except Exception as create_error:
            logger.error(f"Ошибка при создании минимальной страницы: {create_error}", exc_info=True)
            return None
        
        # Парсим результат
        try:
            if isinstance(create_result, str):
                result_data = json.loads(create_result)
            else:
                result_data = create_result
            
            # MCP Notion возвращает результат в формате {"pages": [{"id": "...", ...}]}
            if isinstance(result_data, dict):
                if "pages" in result_data:
                    pages = result_data.get("pages", [])
                    if isinstance(pages, list) and len(pages) > 0:
                        page_id = pages[0].get("id", "")
                else:
                    page_id = result_data.get("id", "")
            elif isinstance(result_data, list) and len(result_data) > 0:
                page_id = result_data[0].get("id", "")
            else:
                page_id = None
            
            if page_id:
                logger.info(f"Задача создана успешно через прямой вызов: {page_id}")
                # Сохраняем задачу в локальное хранилище
                save_task_to_storage(page_id, title, priority)
                # Проверяем, где создалась страница
                await log_created_page_location(page_id)
                return page_id
            else:
                logger.warning(f"Неожиданный формат результата: {create_result}")
                return None
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Ошибка при парсинге результата: {e}")
            return None
        
    except Exception as e:
        logger.error(f"Ошибка при прямом создании задачи: {e}", exc_info=True)
        return None


async def get_tasks_by_priority(
    priority: str,
    database_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Получает задачи с указанным приоритетом из Notion
    
    Args:
        priority: Приоритет (low, medium, high)
        database_id: ID базы данных (если не указан, будет получен автоматически)
    
    Returns:
        Список задач (словари с информацией о задаче)
    """
    try:
        normalized_priority = _normalize_priority(priority)
        logger.info(f"Запрашиваем задачи с приоритетом {priority} (нормализован: {normalized_priority})")
        
        # Сначала проверяем локальное хранилище
        stored_tasks = get_stored_tasks_by_priority(priority)
        if stored_tasks:
            logger.info(f"Найдено {len(stored_tasks)} задач в локальном хранилище")
            
            # Обновляем статус каждой задачи через fetch
            updated_tasks = []
            for task in stored_tasks:
                page_id = task.get("id", "")
                if page_id:
                    # Пробуем получить актуальный статус
                    page_result = await call_notion_tool("notion-fetch", {"id": page_id})
                    if page_result:
                        try:
                            if isinstance(page_result, str):
                                page_data = json.loads(page_result)
                            else:
                                page_data = page_result
                            
                            page_text = page_data.get("text", "") if isinstance(page_data, dict) else ""
                            
                            # Извлекаем актуальный статус
                            status_match = re.search(r'(?:Статус|status)["\s:=]+([^\n"<>,]+)', page_text, re.IGNORECASE)
                            if status_match:
                                task["status"] = status_match.group(1).strip().strip('"')
                            
                            # Извлекаем актуальный приоритет
                            priority_match = re.search(r'(?:Приоритет|priority)["\s:=]+([^\n"<>,]+)', page_text, re.IGNORECASE)
                            if priority_match:
                                found_priority = priority_match.group(1).strip().strip('"')
                                task["priority"] = _normalize_priority(found_priority)
                            
                            updated_tasks.append(task)
                        except (json.JSONDecodeError, KeyError, TypeError):
                            updated_tasks.append(task)
                    else:
                        updated_tasks.append(task)
            
            # Фильтруем по приоритету (на случай если он изменился)
            final_tasks = [t for t in updated_tasks if _normalize_priority(t.get("priority", "")) == normalized_priority]
            logger.info(f"После обновления: {len(final_tasks)} задач с приоритетом {priority}")
            return final_tasks
        
        logger.info("Локальное хранилище пусто, задачи не найдены")
        logger.info("Подсказка: создайте задачи через /task и они будут сохранены в хранилище")
        return []
        
        # Код ниже - fallback для поиска в Notion (не используется, т.к. MCP не поддерживает query)
        # Получаем ID базы данных
        if not database_id:
            database_id = await get_tasks_database_id()
            if not database_id:
                logger.error("Не удалось получить ID базы данных задач")
                return []
        
        # Форматируем database_id для Notion API
        if len(database_id) == 32 and '-' not in database_id:
            formatted_db_id = f"{database_id[:8]}-{database_id[8:12]}-{database_id[12:16]}-{database_id[16:20]}-{database_id[20:]}"
        else:
            formatted_db_id = database_id
        
        # Получаем содержимое базы данных напрямую
        logger.info(f"Запрашиваем задачи из базы {formatted_db_id} с приоритетом {priority}")
        
        fetch_result = await call_notion_tool("notion-fetch", {
            "id": formatted_db_id
        })
        
        if not fetch_result:
            logger.warning("notion-fetch не вернул результат для базы данных")
            return []
        
        try:
            if isinstance(fetch_result, str):
                fetch_data = json.loads(fetch_result)
            else:
                fetch_data = fetch_result
            
            db_text = fetch_data.get("text", "") if isinstance(fetch_data, dict) else str(fetch_result)
            
            # Логируем полный текст базы данных для анализа
            logger.info(f"Текст базы данных (первые 2000 символов):\n{db_text[:2000]}")
            
            # Извлекаем view ID
            view_match = re.search(r'view://([a-f0-9-]+)', db_text)
            if view_match:
                view_id = view_match.group(1)
                view_id_no_dashes = view_id.replace("-", "")
                logger.info(f"Найден view ID: {view_id} (без дефисов: {view_id_no_dashes})")
                
                # Пробуем разные варианты fetch view
                view_variants = [view_id, view_id_no_dashes]
                view_result = None
                view_text = ""
                
                for vid in view_variants:
                    logger.info(f"Пробуем fetch view с ID: {vid}")
                    view_result = await call_notion_tool("notion-fetch", {"id": vid})
                    
                    if view_result:
                        if isinstance(view_result, str):
                            try:
                                view_data = json.loads(view_result)
                            except:
                                view_data = {"raw": view_result}
                        else:
                            view_data = view_result
                        
                        logger.info(f"View ответ ключи: {list(view_data.keys()) if isinstance(view_data, dict) else 'not dict'}")
                        logger.info(f"View ответ полный: {json.dumps(view_data, ensure_ascii=False)[:2000]}")
                        
                        view_text = view_data.get("text", "") if isinstance(view_data, dict) else str(view_result)
                        if view_text and len(view_text) > 100:
                            logger.info(f"Текст view (первые 3000 символов):\n{view_text[:3000]}")
                            break
                        else:
                            logger.info(f"View text слишком короткий или пустой: {len(view_text)} символов")
                
                # Парсим задачи из view (после цикла)
                if view_text:
                    tasks = _parse_tasks_from_database_view(view_text, priority)
                    if tasks:
                        logger.info(f"Получено {len(tasks)} задач с приоритетом {priority} из view")
                        return tasks
            
            # Если view не сработал, парсим записи из текста базы данных
            logger.info("Пробуем парсить записи из текста базы данных")
            tasks = _parse_tasks_from_database_view(db_text, priority)
            if tasks:
                logger.info(f"Получено {len(tasks)} задач с приоритетом {priority} из текста БД")
                return tasks
            
            logger.warning("Не удалось найти записи в базе данных")
            return []
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Ошибка при парсинге базы данных: {e}")
            return []
            
    except Exception as e:
        logger.error(f"Ошибка при получении задач из Notion: {e}", exc_info=True)
        return []


def _normalize_priority(priority: str) -> str:
    """Нормализует значение приоритета (исправляет опечатки)"""
    priority_lower = priority.lower().strip()
    # Исправляем опечатку "hight" -> "high"
    if priority_lower == "hight":
        return "high"
    return priority_lower


def _priority_matches(found: str, search: str) -> bool:
    """Проверяет совпадение приоритетов с учётом опечаток"""
    found_norm = _normalize_priority(found)
    search_norm = _normalize_priority(search)
    return found_norm == search_norm


def _parse_tasks_from_database_view(text: str, priority: str) -> List[Dict[str, Any]]:
    """Парсит задачи из текстового представления view или базы данных Notion"""
    tasks = []
    
    try:
        # Ищем записи в формате <page> или <row>
        # Пример: <page url="...">...</page>
        page_blocks = re.findall(r'<page[^>]*>(.*?)</page>', text, re.DOTALL | re.IGNORECASE)
        
        if not page_blocks:
            # Пробуем найти записи в формате row
            page_blocks = re.findall(r'<row[^>]*>(.*?)</row>', text, re.DOTALL | re.IGNORECASE)
        
        logger.info(f"Найдено {len(page_blocks)} блоков записей в тексте")
        
        for block in page_blocks:
            # Ищем свойства в блоке
            name_match = re.search(r'(?:Имя|name|title)["\s:=]+([^\n"<>]+)', block, re.IGNORECASE)
            priority_match = re.search(r'(?:Приоритет|priority)["\s:=]+([^\n"<>,]+)', block, re.IGNORECASE)
            status_match = re.search(r'(?:Статус|status)["\s:=]+([^\n"<>,]+)', block, re.IGNORECASE)
            url_match = re.search(r'url="[^"]*([a-f0-9]{32})[^"]*"', block)
            
            found_priority = priority_match.group(1).strip().strip('"') if priority_match else ""
            
            if _priority_matches(found_priority, priority):
                task = {
                    "id": url_match.group(1) if url_match else "",
                    "title": name_match.group(1).strip().strip('"') if name_match else "Без названия",
                    "priority": found_priority.lower(),
                    "status": status_match.group(1).strip().strip('"') if status_match else ""
                }
                tasks.append(task)
                logger.info(f"Найдена задача: {task}")
        
        # Если не нашли через блоки, пробуем найти через JSON-подобные структуры
        if not tasks:
            # Ищем строки с приоритетом в JSON формате
            json_matches = re.findall(r'\{[^{}]*"Приоритет"[^{}]*\}', text, re.IGNORECASE)
            for match in json_matches:
                if _normalize_priority(priority) in match.lower() or "hight" in match.lower():
                    name_m = re.search(r'"Имя"[:\s]*"([^"]+)"', match)
                    status_m = re.search(r'"Статус"[:\s]*"([^"]+)"', match)
                    if name_m:
                        task = {
                            "id": "",
                            "title": name_m.group(1),
                            "priority": priority.lower(),
                            "status": status_m.group(1) if status_m else ""
                        }
                        tasks.append(task)
        
        return tasks
        
    except Exception as e:
        logger.warning(f"Ошибка парсинга view: {e}")
        return []


def _parse_task_from_page_text(text: str, page_id: str, priority: str) -> Optional[Dict[str, Any]]:
    """Парсит информацию о задаче из текстового представления страницы Notion"""
    try:
        # Ищем название (title)
        title_match = re.search(r'(?:title|Имя|name)["\s:=]+([^\n"]+)', text, re.IGNORECASE)
        title = title_match.group(1).strip().strip('"') if title_match else ""
        
        # Ищем приоритет
        priority_match = re.search(r'(?:Приоритет|priority)["\s:=]+([^\n",]+)', text, re.IGNORECASE)
        found_priority = priority_match.group(1).strip().strip('"') if priority_match else ""
        
        # Ищем статус
        status_match = re.search(r'(?:Статус|status)["\s:=]+([^\n",]+)', text, re.IGNORECASE)
        status = status_match.group(1).strip().strip('"') if status_match else ""
        
        # Ищем описание
        desc_match = re.search(r'(?:Описание|description)["\s:=]+([^\n"]+)', text, re.IGNORECASE)
        description = desc_match.group(1).strip().strip('"') if desc_match else ""
        
        if not title and not found_priority:
            return None
        
        return {
            "id": page_id,
            "title": title or "Без названия",
            "priority": found_priority.lower() if found_priority else "",
            "status": status,
            "description": description
        }
        
    except Exception as e:
        logger.warning(f"Ошибка парсинга текста страницы: {e}")
        return None


def _parse_tasks_from_view_text(text: str, priority: str) -> List[Dict[str, Any]]:
    """Парсит задачи из текстового представления view Notion"""
    tasks = []
    
    try:
        # Ищем записи в формате page или row
        # Пример: <page url="...">...</page> или строки таблицы
        
        # Пробуем найти JSON-подобные структуры с записями
        # Формат может быть: {"Имя": "...", "Приоритет": "high", ...}
        
        # Ищем строки с приоритетом
        lines = text.split('\n')
        current_task = {}
        
        for line in lines:
            # Ищем упоминания приоритета
            if _normalize_priority(priority) in line.lower() or "hight" in line.lower():
                # Пробуем извлечь название задачи
                # Формат может варьироваться
                
                # Попробуем найти имя/название рядом с приоритетом
                name_match = re.search(r'"(?:Имя|name|title)"[:\s]*"([^"]+)"', line, re.IGNORECASE)
                if name_match:
                    task_name = name_match.group(1)
                    tasks.append({
                        "title": task_name,
                        "priority": priority.lower(),
                        "id": "",
                        "status": ""
                    })
        
        # Альтернативный парсинг: ищем page URL и свойства
        page_matches = re.findall(r'<page[^>]*url="([^"]+)"[^>]*>(.*?)</page>', text, re.DOTALL)
        for url, content in page_matches:
            # Извлекаем свойства из содержимого
            priority_match = re.search(r'"?Приоритет"?\s*[:=]\s*"?(\w+)"?', content, re.IGNORECASE)
            if priority_match and _priority_matches(priority_match.group(1), priority):
                name_match = re.search(r'"?(?:Имя|name)"?\s*[:=]\s*"?([^"\n,]+)"?', content, re.IGNORECASE)
                status_match = re.search(r'"?Статус"?\s*[:=]\s*"?([^"\n,]+)"?', content, re.IGNORECASE)
                
                task = {
                    "title": name_match.group(1).strip() if name_match else "Без названия",
                    "priority": priority.lower(),
                    "id": url,
                    "status": status_match.group(1).strip() if status_match else ""
                }
                tasks.append(task)
        
        logger.info(f"Распарсено {len(tasks)} задач из текста view")
        return tasks
        
    except Exception as e:
        logger.warning(f"Ошибка парсинга текста view: {e}")
        return []


def _parse_task_from_notion_page(page_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Парсит информацию о задаче из данных страницы Notion"""
    try:
        properties = page_data.get("properties", {})
        
        # Извлекаем название
        title_prop = properties.get("title") or properties.get("Название")
        title = ""
        if title_prop:
            if title_prop.get("type") == "title":
                title_array = title_prop.get("title", [])
                if title_array:
                    title = title_array[0].get("plain_text", "")
        
        if not title:
            # Пробуем другие варианты
            for key, value in properties.items():
                if value.get("type") == "title":
                    title_array = value.get("title", [])
                    if title_array:
                        title = title_array[0].get("plain_text", "")
                        break
        
        # Извлекаем описание
        description = ""
        desc_prop = properties.get("Описание") or properties.get("description")
        if desc_prop:
            if desc_prop.get("type") == "rich_text":
                desc_array = desc_prop.get("rich_text", [])
                if desc_array:
                    description = desc_array[0].get("plain_text", "")
        
        # Извлекаем приоритет
        priority = ""
        priority_prop = properties.get("Приоритет") or properties.get("priority")
        if priority_prop:
            if priority_prop.get("type") == "select":
                priority_obj = priority_prop.get("select")
                if priority_obj:
                    priority = priority_obj.get("name", "")
        
        # Извлекаем статус (если есть)
        status = ""
        status_prop = properties.get("Статус") or properties.get("status")
        if status_prop:
            if status_prop.get("type") == "select":
                status_obj = status_prop.get("select")
                if status_obj:
                    status = status_obj.get("name", "")
        
        if not title:
            return None
        
        return {
            "id": page_data.get("id", ""),
            "title": title,
            "description": description,
            "priority": priority,
            "status": status,
            "url": page_data.get("url", "")
        }
    except Exception as e:
        logger.warning(f"Ошибка при парсинге задачи: {e}")
        return None


async def recommend_task_priority(
    tasks: List[Dict[str, Any]],
    project_context: str = "",
    model: str = "gpt-4o-mini",
    temperature: float = 0.7
) -> str:
    """Генерирует рекомендации по приоритетам задач с использованием LLM
    
    Args:
        tasks: Список задач
        project_context: Контекст проекта из RAG (опционально)
        model: Модель LLM для генерации рекомендаций
        temperature: Температура для генерации
    
    Returns:
        Текст с рекомендациями
    """
    from openai_client import query_openai
    
    if not tasks:
        return "Нет задач для анализа."
    
    # Форматируем список задач
    tasks_text = "\n".join([
        f"{i+1}. {task.get('title', 'Без названия')} "
        f"(приоритет: {task.get('priority', 'не указан')}, "
        f"статус: {task.get('status', 'не указан')})\n"
        f"   Описание: {task.get('description', 'нет описания')}"
        for i, task in enumerate(tasks)
    ])
    
    system_prompt = (
        "Ты опытный менеджер проектов. Проанализируй список задач и дай рекомендации, "
        "какую задачу следует выполнить первой, учитывая приоритеты, зависимости и контекст проекта. "
        "Будь конкретным и обоснуй свои рекомендации."
    )
    
    user_prompt = (
        f"Проанализируй следующие задачи и предложи, что делать первым:\n\n"
        f"{tasks_text}\n\n"
    )
    
    if project_context:
        user_prompt += (
            f"Контекст проекта:\n{project_context}\n\n"
        )
    
    user_prompt += (
        "Дай рекомендацию, какую задачу выполнить первой, и объясни почему. "
        "Учитывай приоритеты, сложность, зависимости между задачами и текущее состояние проекта."
    )
    
    try:
        answer, _ = await query_openai(
            user_prompt,
            [],
            system_prompt,
            temperature,
            model,
            2000,  # max_tokens
            None,  # bot
            None   # tools
        )
        return answer
    except Exception as e:
        logger.error(f"Ошибка при генерации рекомендаций: {e}", exc_info=True)
        return f"Ошибка при генерации рекомендаций: {str(e)}"
