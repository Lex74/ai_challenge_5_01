"""Модуль для работы с MCP сервером Kinopoisk (локальный Python-сервер)."""
import logging
import os
from typing import List, Dict, Any, Optional, Tuple

from mcp import StdioServerParameters

from config import MCP_KINOPOISK_COMMAND, MCP_KINOPOISK_ARGS
from mcp_base import BaseMCPClient

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения информации об ошибке
_last_kp_error: Optional[Tuple[str, str]] = None


def get_kinopoisk_last_error() -> Optional[Tuple[str, str]]:
    """Возвращает последнюю ошибку Kinopoisk MCP клиента."""
    return _last_kp_error


def _set_kp_last_error(error_type: Optional[str], error_msg: Optional[str]) -> None:
    """Устанавливает последнюю ошибку Kinopoisk MCP клиента."""
    global _last_kp_error
    _last_kp_error = (error_type, error_msg) if error_type and error_msg else None


def _get_kp_server_params() -> Tuple[Optional[StdioServerParameters], Optional[str]]:
    """Создает параметры сервера MCP Kinopoisk."""
    # Проверяем API ключ
    if not os.getenv("KINOPOISK_API_KEY"):
        error_msg = (
            "Переменная окружения KINOPOISK_API_KEY не задана.\n\n"
            "Для работы MCP сервера Kinopoisk необходимо:\n"
            "1. Получить API ключ на https://kinopoiskapiunofficial.tech/documentation/api/\n"
            "2. Добавить его в .env:\n"
            "   KINOPOISK_API_KEY=ваш_ключ\n"
            "3. Перезапустить бота."
        )
        _set_kp_last_error("NO_API_KEY", error_msg)
        logger.error("KINOPOISK_API_KEY не установлен в окружении")
        return None, error_msg

    try:
        command_parts = MCP_KINOPOISK_COMMAND.split()
        command = command_parts[0]
        args = command_parts[1:] + MCP_KINOPOISK_ARGS

        server_params = StdioServerParameters(
            command=command,
            args=args,
        )
        _set_kp_last_error(None, None)
        return server_params, None
    except Exception as e:
        error_msg = f"Ошибка при создании параметров сервера Kinopoisk MCP: {e}"
        _set_kp_last_error("CONFIG_ERROR", error_msg)
        return None, error_msg


# Создаем экземпляр клиента
_kinopoisk_client = BaseMCPClient(
    server_name="Kinopoisk",
    get_server_params_func=_get_kp_server_params,
    get_last_error_func=get_kinopoisk_last_error,
    set_last_error_func=_set_kp_last_error,
    init_timeout=20,
    tools_timeout=20,
    call_timeout=40,
)


async def list_kinopoisk_tools() -> List[Dict[str, Any]]:
    """Получает список доступных инструментов Kinopoisk через MCP сервер."""
    return await _kinopoisk_client.list_tools()

async def call_kinopoisk_tool(name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Вызывает указанный инструмент Kinopoisk MCP и возвращает текстовый результат (JSON-строку)."""
    return await _kinopoisk_client.call_tool(name, arguments)

