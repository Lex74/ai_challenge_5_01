"""Модуль для работы с MCP сервером News (локальный Python-сервер)."""
import logging
import os
from typing import List, Dict, Any, Optional, Tuple

from mcp import StdioServerParameters

from config import MCP_NEWS_COMMAND, MCP_NEWS_ARGS
from mcp_base import BaseMCPClient

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения информации об ошибке
_last_news_error: Optional[Tuple[str, str]] = None


def get_news_last_error() -> Optional[Tuple[str, str]]:
    """Возвращает последнюю ошибку News MCP клиента."""
    return _last_news_error


def _set_news_last_error(error_type: Optional[str], error_msg: Optional[str]) -> None:
    """Устанавливает последнюю ошибку News MCP клиента."""
    global _last_news_error
    _last_news_error = (error_type, error_msg) if error_type and error_msg else None


def _get_news_server_params() -> Tuple[Optional[StdioServerParameters], Optional[str]]:
    """Создает параметры сервера MCP News."""
    # Проверяем API ключ
    if not os.getenv("NEWS_API_KEY"):
        error_msg = (
            "Переменная окружения NEWS_API_KEY не задана.\n\n"
            "Для работы MCP сервера News необходимо:\n"
            "1. Получить API ключ на https://newsapi.org/\n"
            "2. Добавить его в .env:\n"
            "   NEWS_API_KEY=ваш_ключ\n"
            "3. Перезапустить бота."
        )
        _set_news_last_error("NO_API_KEY", error_msg)
        logger.error("NEWS_API_KEY не установлен в окружении")
        return None, error_msg

    try:
        # Если MCP_NEWS_COMMAND - это абсолютный путь, используем его как есть
        # Иначе разбиваем на части
        if os.path.isabs(MCP_NEWS_COMMAND):
            command = MCP_NEWS_COMMAND
            args = MCP_NEWS_ARGS
            logger.debug(f"Используется абсолютный путь к Python: {command}")
        else:
            command_parts = MCP_NEWS_COMMAND.split()
            command = command_parts[0]
            args = command_parts[1:] + MCP_NEWS_ARGS
        
        # Проверяем существование команды (если это абсолютный путь к файлу)
        # Если это системная команда (например, 'python3'), не проверяем существование
        if os.path.isabs(command):
            if not os.path.exists(command):
                error_msg = (
                    f"Python интерпретатор не найден: {command}\n\n"
                    f"Проверьте путь к виртуальному окружению news-mcp.\n"
                    f"Ожидаемый путь: {command}\n\n"
                    f"Если виртуальное окружение находится в другом месте, установите переменную окружения:\n"
                    f"MCP_NEWS_COMMAND=/полный/путь/к/news-mcp/venv/bin/python3\n\n"
                    f"Или используйте системный Python: MCP_NEWS_COMMAND=python3"
                )
                _set_news_last_error("FILE_NOT_FOUND", error_msg)
                logger.error(f"Python интерпретатор не найден: {command}")
                return None, error_msg
            else:
                logger.info(f"Используется Python из venv: {command}")
        else:
            # Системная команда (например, 'python3')
            logger.info(f"Используется системный Python: {command}")
        
        # Проверяем существование server.py
        if args and os.path.isabs(args[0]) and not os.path.exists(args[0]):
            error_msg = (
                f"Файл server.py не найден: {args[0]}\n\n"
                f"Проверьте путь к news-mcp/server.py.\n"
                f"Ожидаемый путь: {args[0]}"
            )
            _set_news_last_error("FILE_NOT_FOUND", error_msg)
            logger.error(f"Файл server.py не найден: {args[0]}")
            return None, error_msg
        
        logger.info(f"Создаю параметры сервера News MCP: command={command}, args={args}")
        server_params = StdioServerParameters(
            command=command,
            args=args,
        )
        _set_news_last_error(None, None)
        return server_params, None
    except Exception as e:
        error_msg = f"Ошибка при создании параметров сервера News MCP: {e}"
        _set_news_last_error("CONFIG_ERROR", error_msg)
        logger.error(error_msg, exc_info=True)
        return None, error_msg


# Создаем экземпляр клиента
_news_client = BaseMCPClient(
    server_name="News",
    get_server_params_func=_get_news_server_params,
    get_last_error_func=get_news_last_error,
    set_last_error_func=_set_news_last_error,
    init_timeout=20,
    tools_timeout=20,
    call_timeout=40,
)


async def list_news_tools() -> List[Dict[str, Any]]:
    """Получает список доступных инструментов News через MCP сервер."""
    return await _news_client.list_tools()


async def call_news_tool(name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Вызывает указанный инструмент News MCP и возвращает текстовый результат."""
    return await _news_client.call_tool(name, arguments)

