"""Модуль для работы с MCP сервером логов (локальный Python-сервер)."""
import logging
import os
from typing import List, Dict, Any, Optional, Tuple

from mcp import StdioServerParameters

from config import MCP_LOGS_COMMAND, MCP_LOGS_ARGS
from mcp_base import BaseMCPClient

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения информации об ошибке
_last_logs_error: Optional[Tuple[str, str]] = None


def get_logs_last_error() -> Optional[Tuple[str, str]]:
    """Возвращает последнюю ошибку Logs MCP клиента."""
    return _last_logs_error


def _set_logs_last_error(error_type: Optional[str], error_msg: Optional[str]) -> None:
    """Устанавливает последнюю ошибку Logs MCP клиента."""
    global _last_logs_error
    _last_logs_error = (error_type, error_msg) if error_type and error_msg else None


def _get_logs_server_params() -> Tuple[Optional[StdioServerParameters], Optional[str]]:
    """Создает параметры сервера MCP Logs."""
    try:
        # Если MCP_LOGS_COMMAND - это абсолютный путь, используем его как есть
        # Иначе разбиваем на части
        if os.path.isabs(MCP_LOGS_COMMAND):
            command = MCP_LOGS_COMMAND
            args = MCP_LOGS_ARGS
            logger.debug(f"Используется абсолютный путь к Python: {command}")
        else:
            command_parts = MCP_LOGS_COMMAND.split()
            command = command_parts[0]
            args = command_parts[1:] + MCP_LOGS_ARGS
        
        # Проверяем существование команды (если это абсолютный путь к файлу)
        # Если это системная команда (например, 'python3'), не проверяем существование
        if os.path.isabs(command):
            if not os.path.exists(command):
                error_msg = (
                    f"Python интерпретатор не найден: {command}\n\n"
                    f"Проверьте путь к Python интерпретатору.\n"
                    f"Ожидаемый путь: {command}\n\n"
                    f"Или используйте системный Python: MCP_LOGS_COMMAND=python3"
                )
                _set_logs_last_error("FILE_NOT_FOUND", error_msg)
                logger.error(f"Python интерпретатор не найден: {command}")
                return None, error_msg
            else:
                logger.info(f"Используется Python из указанного пути: {command}")
        else:
            # Системная команда (например, 'python3')
            logger.info(f"Используется системный Python: {command}")
        
        # Проверяем существование server.py
        if args and os.path.isabs(args[0]) and not os.path.exists(args[0]):
            error_msg = (
                f"Файл server.py не найден: {args[0]}\n\n"
                f"Проверьте путь к logs_mcp/server.py.\n"
                f"Ожидаемый путь: {args[0]}"
            )
            _set_logs_last_error("FILE_NOT_FOUND", error_msg)
            logger.error(f"Файл server.py не найден: {args[0]}")
            return None, error_msg
        
        logger.info(f"Создаю параметры сервера Logs MCP: command={command}, args={args}")
        server_params = StdioServerParameters(
            command=command,
            args=args,
        )
        _set_logs_last_error(None, None)
        return server_params, None
    except Exception as e:
        error_msg = f"Ошибка при создании параметров сервера Logs MCP: {e}"
        _set_logs_last_error("CONFIG_ERROR", error_msg)
        logger.error(error_msg, exc_info=True)
        return None, error_msg


# Создаем экземпляр клиента
_logs_client = BaseMCPClient(
    server_name="Logs",
    get_server_params_func=_get_logs_server_params,
    get_last_error_func=get_logs_last_error,
    set_last_error_func=_set_logs_last_error,
    init_timeout=20,
    tools_timeout=20,
    call_timeout=40,
)


async def list_logs_tools() -> List[Dict[str, Any]]:
    """Получает список доступных инструментов Logs через MCP сервер."""
    return await _logs_client.list_tools()


async def call_logs_tool(name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Вызывает указанный инструмент Logs MCP и возвращает текстовый результат."""
    return await _logs_client.call_tool(name, arguments)

