"""Модуль для интеграции MCP инструментов с LLM"""
import logging
from typing import List, Dict, Any, Optional

from mcp_client import list_notion_tools, call_notion_tool
from mcp_kinopoisk_client import list_kinopoisk_tools, call_kinopoisk_tool
from mcp_news_client import list_news_tools, call_news_tool
from mcp_logs_client import list_logs_tools, call_logs_tool
from mcp_git_client import list_git_tools, call_git_tool

logger = logging.getLogger(__name__)

# Кэш для инструментов (чтобы не запрашивать каждый раз)
_cached_tools: Optional[List[Dict[str, Any]]] = None


def _convert_mcp_tool_to_openai_format(mcp_tool: Dict[str, Any], server_prefix: str) -> Dict[str, Any]:
    """Преобразует MCP tool в формат OpenAI function calling"""
    name = mcp_tool.get('name', 'unknown')
    description = mcp_tool.get('description', '')
    input_schema = mcp_tool.get('inputSchema') or mcp_tool.get('input_schema', {})
    
    # Добавляем префикс сервера к имени, чтобы различать инструменты от разных серверов
    openai_name = f"{server_prefix}_{name}"
    
    # Улучшаем описание для Kinopoisk инструментов, чтобы LLM понимала, когда их использовать
    if server_prefix == "kinopoisk":
        if "search" in name.lower() or "поиск" in description.lower():
            description = f"Используй этот инструмент для поиска фильмов на Кинопоиске по названию или ключевому слову. {description}"
        elif "recommend" in name.lower() or "подборка" in description.lower() or "рекомендация" in description.lower():
            description = f"Используй этот инструмент для получения подборок фильмов по тематике или настроению. {description}"
        elif "detail" in name.lower() or "детали" in description.lower() or "информация" in description.lower():
            description = f"Используй этот инструмент для получения подробной информации о конкретном фильме по его ID. {description}"
    
    # Улучшаем описание для News инструментов
    if server_prefix == "news":
        if "news" in name.lower() or "новости" in description.lower() or "новость" in description.lower() or "get_today" in name.lower():
            description = (
                "ОБЯЗАТЕЛЬНО используй этот инструмент, когда пользователь спрашивает о новостях, текущих событиях, "
                "актуальной информации или последних новостях. Этот инструмент получает СВЕЖИЕ новости за последние 1-2 дня "
                "из реальных источников через NewsAPI. НИКОГДА не говори пользователю, что у тебя нет доступа к новостям - "
                f"всегда используй этот инструмент! {description}"
            )
    
    # Улучшаем описание для Notion инструментов
    if server_prefix == "notion":
        if "create" in name.lower() and "page" in name.lower():
            description = (
                f"КРИТИЧЕСКИ ВАЖНО: Для создания страницы ОБЯЗАТЕЛЬНО нужно указать параметр 'parent' с одним из полей: "
                f"'page_id', 'database_id' или 'data_source_id'. Если у тебя нет ID родительской страницы или базы данных, "
                f"сначала используй notion-search для поиска. Структура parent: {{'page_id': '...'}} или {{'database_id': '...'}}. "
                f"{description}"
            )
        elif "search" in name.lower():
            description = (
                f"Используй этот инструмент для поиска страниц, баз данных или других объектов в Notion. "
                f"Результаты поиска содержат page_id или database_id, которые можно использовать в параметре parent "
                f"при создании новых страниц через notion-create-pages. {description}"
            )
    
    # Улучшаем описание для Logs инструментов
    if server_prefix == "logs":
        if "log" in name.lower() or "лог" in description.lower():
            description = (
                "ОБЯЗАТЕЛЬНО используй этот инструмент, когда пользователь просит показать логи бота, "
                "посмотреть логи, проверить логи или любые запросы, связанные с логами telegram-бота. "
                f"Этот инструмент получает последние логи из journalctl для сервиса telegram-bot.service. {description}"
            )
 
    # Улучшаем описание для Git инструментов
    if server_prefix == "git":
        if "branch" in name.lower() or "ветка" in description.lower() or "get_current_branch" in name.lower():
            description = (
                "ОБЯЗАТЕЛЬНО используй этот инструмент, когда пользователь спрашивает о текущей ветке git, "
                "активной ветке, ветке репозитория или любых вопросах, связанных с ветками git. "
                "Этот инструмент получает название текущей ветки git репозитория. "
                f"{description}"
            )
        elif "status" in name.lower() or "статус" in description.lower() or "get_git_status" in name.lower():
            description = (
                "ОБЯЗАТЕЛЬНО используй этот инструмент, когда пользователь спрашивает о статусе git, "
                "измененных файлах, состоянии репозитория или любых вопросах о статусе git. "
                "Этот инструмент получает статус git репозитория (измененные, добавленные, удаленные файлы). "
                f"{description}"
            )
        elif "file" in name.lower() or "файл" in description.lower() or "get_file_content" in name.lower() or "get_open_files" in name.lower():
            description = (
                "ОБЯЗАТЕЛЬНО используй этот инструмент, когда пользователь спрашивает о файлах в репозитории, "
                "содержимом файлов, открытых файлах, измененных файлах или любых вопросах о файлах проекта. "
                "Этот инструмент получает информацию о файлах в git репозитории или их содержимое. "
                f"{description}"
            )
        elif "commit" in name.lower() or "коммит" in description.lower() or "get_recent_commits" in name.lower():
            description = (
                "ОБЯЗАТЕЛЬНО используй этот инструмент, когда пользователь спрашивает о коммитах, "
                "истории коммитов, последних коммитах или любых вопросах о коммитах git. "
                "Этот инструмент получает информацию о коммитах в git репозитории. "
                f"{description}"
            )
        elif "diff" in name.lower() or "get_diff" in name.lower():
            description = (
                "ОБЯЗАТЕЛЬНО используй этот инструмент, когда пользователь спрашивает о различиях в файлах, "
                "diff, изменениях в коде или любых вопросах о различиях в git репозитории. "
                "Этот инструмент получает различия (diff) в git репозитории. "
                f"{description}"
            )
    
    # Преобразуем inputSchema в parameters для OpenAI
    properties = input_schema.get('properties', {}) if isinstance(input_schema, dict) else {}
    required = input_schema.get('required', []) if isinstance(input_schema, dict) else []
    
    # Создаем OpenAI function format
    openai_tool = {
        "type": "function",
        "function": {
            "name": openai_name,
            "description": description or f"Инструмент {name} от {server_prefix}",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": required
            }
        }
    }
    
    # Преобразуем свойства параметров
    for param_name, param_info in properties.items():
        if isinstance(param_info, dict):
            param_type = param_info.get('type', 'string')
            param_desc = param_info.get('description', '')
            
            # OpenAI поддерживает: string, number, integer, boolean, array, object
            # MCP может использовать другие типы, приводим к поддерживаемым
            if param_type not in ['string', 'number', 'integer', 'boolean', 'array', 'object']:
                param_type = 'string'
            
            param_schema = {
                "type": param_type,
                "description": param_desc
            }
            
            # Для массивов OpenAI требует указать items
            if param_type == 'array':
                items_schema = param_info.get('items', {})
                if isinstance(items_schema, dict):
                    items_type = items_schema.get('type', 'string')
                    # OpenAI поддерживает только простые типы в items для массивов
                    if items_type not in ['string', 'number', 'integer', 'boolean']:
                        items_type = 'string'
                    param_schema["items"] = {"type": items_type}
                    # Если есть описание для items, добавляем его
                    if 'description' in items_schema:
                        param_schema["items"]["description"] = items_schema['description']
                else:
                    # Если items не указан, используем string по умолчанию
                    param_schema["items"] = {"type": "string"}
            
            # Для объектов обрабатываем вложенные свойства
            elif param_type == 'object':
                nested_properties = param_info.get('properties', {})
                if nested_properties:
                    param_schema["properties"] = {}
                    for nested_name, nested_info in nested_properties.items():
                        if isinstance(nested_info, dict):
                            nested_type = nested_info.get('type', 'string')
                            if nested_type not in ['string', 'number', 'integer', 'boolean', 'array', 'object']:
                                nested_type = 'string'
                            param_schema["properties"][nested_name] = {
                                "type": nested_type,
                                "description": nested_info.get('description', '')
                            }
                            # Для вложенных массивов тоже нужны items
                            if nested_type == 'array':
                                nested_items = nested_info.get('items', {})
                                if isinstance(nested_items, dict):
                                    nested_items_type = nested_items.get('type', 'string')
                                    if nested_items_type not in ['string', 'number', 'integer', 'boolean']:
                                        nested_items_type = 'string'
                                    param_schema["properties"][nested_name]["items"] = {"type": nested_items_type}
                                else:
                                    param_schema["properties"][nested_name]["items"] = {"type": "string"}
            
            # Если есть enum, добавляем его
            if 'enum' in param_info:
                param_schema["enum"] = param_info['enum']
            
            openai_tool["function"]["parameters"]["properties"][param_name] = param_schema
    
    return openai_tool


async def get_all_mcp_tools() -> List[Dict[str, Any]]:
    """Получает все доступные MCP инструменты и преобразует их в формат OpenAI tools"""
    global _cached_tools
    
    # Используем кэш, если он есть
    if _cached_tools is not None:
        return _cached_tools
    
    openai_tools = []
    
    # Получаем инструменты Notion
    try:
        notion_tools = await list_notion_tools()
        logger.info(f"Получено {len(notion_tools)} инструментов Notion")
        for tool in notion_tools:
            openai_tool = _convert_mcp_tool_to_openai_format(tool, "notion")
            openai_tools.append(openai_tool)
    except Exception as e:
        logger.warning(f"Не удалось получить инструменты Notion: {e}")
    
    # Получаем инструменты Kinopoisk
    try:
        kinopoisk_tools = await list_kinopoisk_tools()
        logger.info(f"Получено {len(kinopoisk_tools)} инструментов Kinopoisk MCP")
        for tool in kinopoisk_tools:
            tool_name = tool.get('name', 'unknown')
            logger.debug(f"Обрабатываю Kinopoisk инструмент: {tool_name}")
            openai_tool = _convert_mcp_tool_to_openai_format(tool, "kinopoisk")
            openai_tools.append(openai_tool)
            logger.debug(f"Kinopoisk инструмент {tool_name} преобразован в OpenAI формат как kinopoisk_{tool_name}")
    except Exception as e:
        logger.warning(f"Не удалось получить инструменты Kinopoisk MCP: {e}", exc_info=True)
    
    # Получаем инструменты News
    try:
        news_tools = await list_news_tools()
        logger.info(f"Получено {len(news_tools)} инструментов News MCP")
        if news_tools:
            for tool in news_tools:
                tool_name = tool.get('name', 'unknown')
                logger.info(f"Обрабатываю News инструмент: {tool_name}")
                openai_tool = _convert_mcp_tool_to_openai_format(tool, "news")
                openai_tools.append(openai_tool)
                logger.info(f"News инструмент {tool_name} преобразован в OpenAI формат как news_{tool_name}")
        else:
            logger.warning("Список инструментов News MCP пуст. Проверьте настройки NEWS_API_KEY и путь к серверу.")
    except Exception as e:
        logger.error(f"Не удалось получить инструменты News MCP: {e}", exc_info=True)
    
    # Получаем инструменты Logs
    try:
        logs_tools = await list_logs_tools()
        logger.info(f"Получено {len(logs_tools)} инструментов Logs MCP")
        if logs_tools:
            for tool in logs_tools:
                tool_name = tool.get('name', 'unknown')
                logger.info(f"Обрабатываю Logs инструмент: {tool_name}")
                openai_tool = _convert_mcp_tool_to_openai_format(tool, "logs")
                openai_tools.append(openai_tool)
                logger.info(f"Logs инструмент {tool_name} преобразован в OpenAI формат как logs_{tool_name}")
        else:
            logger.warning("Список инструментов Logs MCP пуст. Проверьте путь к серверу.")
    except Exception as e:
        logger.error(f"Не удалось получить инструменты Logs MCP: {e}", exc_info=True)
    
    # Получаем инструменты Git
    try:
        git_tools = await list_git_tools()
        logger.info(f"Получено {len(git_tools)} инструментов Git MCP")
        if git_tools:
            for tool in git_tools:
                tool_name = tool.get('name', 'unknown')
                logger.info(f"Обрабатываю Git инструмент: {tool_name}")
                openai_tool = _convert_mcp_tool_to_openai_format(tool, "git")
                openai_tools.append(openai_tool)
                logger.info(f"Git инструмент {tool_name} преобразован в OpenAI формат как git_{tool_name}")
        else:
            logger.warning("Список инструментов Git MCP пуст. Проверьте путь к серверу.")
    except Exception as e:
        logger.error(f"Не удалось получить инструменты Git MCP: {e}", exc_info=True)
    
    # Кэшируем результат
    _cached_tools = openai_tools
    logger.info(f"Всего доступно {len(openai_tools)} MCP инструментов для LLM")
    
    return openai_tools


def clear_tools_cache():
    """Очищает кэш инструментов (полезно при изменении конфигурации)"""
    global _cached_tools
    _cached_tools = None


async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Вызывает MCP инструмент на основе имени в формате OpenAI (с префиксом сервера)"""
    logger.info(f"Вызов MCP инструмента: {tool_name} с аргументами: {arguments}")
    
    # Парсим имя инструмента: server_name_tool_name
    if '_' not in tool_name:
        logger.error(f"Некорректное имя инструмента (нет префикса сервера): {tool_name}")
        return None
    
    parts = tool_name.split('_', 1)
    if len(parts) != 2:
        logger.error(f"Некорректное имя инструмента (не удалось распарсить): {tool_name}")
        return None
    
    server_prefix, actual_tool_name = parts
    logger.info(f"Распарсено: сервер={server_prefix}, инструмент={actual_tool_name}")
    
    try:
        if server_prefix == "notion":
            logger.info(f"Вызываю Notion MCP инструмент: {actual_tool_name}")
            result = await call_notion_tool(actual_tool_name, arguments)
            logger.info(f"Notion MCP инструмент {actual_tool_name} вернул результат (длина: {len(str(result)) if result else 0})")
            return result
        elif server_prefix == "kinopoisk":
            logger.info(f"Вызываю Kinopoisk MCP инструмент: {actual_tool_name}")
            result = await call_kinopoisk_tool(actual_tool_name, arguments)
            logger.info(f"Kinopoisk MCP инструмент {actual_tool_name} вернул результат (длина: {len(str(result)) if result else 0})")
            return result
        elif server_prefix == "news":
            logger.info(f"Вызываю News MCP инструмент: {actual_tool_name}")
            result = await call_news_tool(actual_tool_name, arguments)
            logger.info(f"News MCP инструмент {actual_tool_name} вернул результат (длина: {len(str(result)) if result else 0})")
            return result
        elif server_prefix == "logs":
            logger.info(f"Вызываю Logs MCP инструмент: {actual_tool_name}")
            result = await call_logs_tool(actual_tool_name, arguments)
            logger.info(f"Logs MCP инструмент {actual_tool_name} вернул результат (длина: {len(str(result)) if result else 0})")
            return result
        elif server_prefix == "git":
            logger.info(f"Вызываю Git MCP инструмент: {actual_tool_name}")
            result = await call_git_tool(actual_tool_name, arguments)
            logger.info(f"Git MCP инструмент {actual_tool_name} вернул результат (длина: {len(str(result)) if result else 0})")
            return result
        else:
            logger.error(f"Неизвестный префикс сервера: {server_prefix}. Ожидается 'notion', 'kinopoisk', 'news', 'logs' или 'git'")
            return None
    except Exception as e:
        logger.error(f"Ошибка при вызове MCP инструмента {tool_name}: {e}", exc_info=True)
        return None

