"""Модуль для работы с MCP сервером Kinopoisk (локальный Python-сервер)."""
import logging
import os
import asyncio
from typing import List, Dict, Any, Optional, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import MCP_KINOPOISK_COMMAND, MCP_KINOPOISK_ARGS

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения информации об ошибке
_last_kp_error: Optional[Tuple[str, str]] = None


def get_kinopoisk_last_error() -> Optional[Tuple[str, str]]:
    """Возвращает последнюю ошибку Kinopoisk MCP клиента."""
    return _last_kp_error


def _get_kp_server_params() -> Tuple[Optional[StdioServerParameters], Optional[str]]:
    """Создает параметры сервера MCP Kinopoisk."""
    global _last_kp_error

    try:
        command_parts = MCP_KINOPOISK_COMMAND.split()
        command = command_parts[0]
        args = command_parts[1:] + MCP_KINOPOISK_ARGS

        server_params = StdioServerParameters(
            command=command,
            args=args,
        )
        _last_kp_error = None
        return server_params, None
    except Exception as e:
        error_msg = f"Ошибка при создании параметров сервера Kinopoisk MCP: {e}"
        _last_kp_error = ("CONFIG_ERROR", error_msg)
        return None, error_msg


async def list_kinopoisk_tools() -> List[Dict[str, Any]]:
    """Получает список доступных инструментов Kinopoisk через MCP сервер."""
    global _last_kp_error

    try:
        # Быстрая проверка, что указан API ключ для Kinopoisk
        if not os.getenv("KINOPOISK_API_KEY"):
            error_msg = (
                "Переменная окружения KINOPOISK_API_KEY не задана.\n\n"
                "Для работы MCP сервера Kinopoisk необходимо:\n"
                "1. Получить API ключ на https://kinopoiskapiunofficial.tech/documentation/api/\n"
                "2. Добавить его в .env:\n"
                "   KINOPOISK_API_KEY=ваш_ключ\n"
                "3. Перезапустить бота."
            )
            _last_kp_error = ("NO_API_KEY", error_msg)
            logger.error("KINOPOISK_API_KEY не установлен в окружении")
            return []

        server_params, error_msg = _get_kp_server_params()
        if server_params is None:
            logger.error(f"Не удалось создать параметры сервера Kinopoisk MCP: {error_msg}")
            return []

        # Подключаемся к MCP серверу и получаем список инструментов
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Инициализируем сессию с таймаутом,
                # чтобы команда /kinopoisk_tools не "висела" бесконечно
                try:
                    await asyncio.wait_for(session.initialize(), timeout=20)
                except asyncio.TimeoutError:
                    error_msg = (
                        "Тайм-аут при инициализации MCP сервера Kinopoisk (более 20 секунд).\n\n"
                        "Возможные причины:\n"
                        "• Сервер kinopoisk-mcp завис или не отвечает\n"
                        "• Проблемы с Python/зависимостями в проекте kinopoisk-mcp\n\n"
                        "Проверьте логи процесса 'mcp_server.py' и попробуйте запустить его вручную:\n"
                        f"  {MCP_KINOPOISK_COMMAND} {' '.join(MCP_KINOPOISK_ARGS)}"
                    )
                    _last_kp_error = ("TIMEOUT_INIT", error_msg)
                    logger.error(error_msg)
                    return []

                logger.info("MCP сервер Kinopoisk успешно подключен")

                # Получаем список инструментов из MCP сервера с таймаутом
                try:
                    tools_result = await asyncio.wait_for(session.list_tools(), timeout=20)
                except asyncio.TimeoutError:
                    error_msg = (
                        "Тайм-аут при получении списка инструментов от MCP сервера Kinopoisk (более 20 секунд).\n\n"
                        "Проверьте, что сервер 'mcp_server.py' работает корректно и не зависает."
                    )
                    _last_kp_error = ("TIMEOUT_TOOLS", error_msg)
                    logger.error(error_msg)
                    return []

                tools_objects = tools_result.tools if tools_result else []

                # Преобразуем объекты Tool в словари
                tools: List[Dict[str, Any]] = []
                for tool_obj in tools_objects:
                    if hasattr(tool_obj, "model_dump"):
                        tool_dict = tool_obj.model_dump()
                    elif hasattr(tool_obj, "dict"):
                        tool_dict = tool_obj.dict()
                    elif hasattr(tool_obj, "__dict__"):
                        tool_dict = tool_obj.__dict__
                    else:
                        tool_dict = {
                            "name": getattr(tool_obj, "name", "Неизвестно"),
                            "description": getattr(tool_obj, "description", ""),
                            "inputSchema": getattr(tool_obj, "inputSchema", {}),
                        }
                    tools.append(tool_dict)

                logger.info(f"Получено {len(tools)} инструментов от MCP сервера Kinopoisk")
                _last_kp_error = None
                return tools

    except FileNotFoundError as e:
        error_msg = (
            f"Команда запуска MCP сервера Kinopoisk не найдена: {e}\n\n"
            f"Команда: '{MCP_KINOPOISK_COMMAND} {' '.join(MCP_KINOPOISK_ARGS)}'\n\n"
            f"Убедитесь, что Python установлен и путь к 'mcp_server.py' указан верно.\n"
            f"Текущий путь по умолчанию: /home/nizhegorodov.a8/PyhonProjects/kinopoisk-mcp/mcp_server.py"
        )
        _last_kp_error = ("FILE_NOT_FOUND", error_msg)
        logger.error(error_msg)
        return []
    except ImportError as import_err:
        error_msg = (
            "Библиотека mcp не установлена.\n\n"
            "Для установки выполните:\n"
            "```bash\n"
            "pip install mcp\n"
            "```\n\n"
            "Или установите все зависимости:\n"
            "```bash\n"
            "pip install -r requirements.txt\n"
            "```\n\n"
            f"Детали ошибки: {import_err}"
        )
        _last_kp_error = ("IMPORT_ERROR", error_msg)
        logger.error(f"Библиотека mcp не установлена: {import_err}")
        return []
    except Exception as e:
        error_msg = f"Ошибка при получении списка инструментов Kinopoisk MCP: {e}"
        _last_kp_error = ("GENERAL_ERROR", error_msg)
        logger.error(error_msg, exc_info=True)
        return []

async def call_kinopoisk_tool(name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Вызывает указанный инструмент Kinopoisk MCP и возвращает текстовый результат (JSON-строку)."""
    global _last_kp_error

    try:
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
            _last_kp_error = ("NO_API_KEY", error_msg)
            logger.error("KINOPOISK_API_KEY не установлен в окружении")
            return None

        server_params, error_msg = _get_kp_server_params()
        if server_params is None:
            logger.error(f"Не удалось создать параметры сервера Kinopoisk MCP: {error_msg}")
            return None

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Инициализация с таймаутом
                try:
                    await asyncio.wait_for(session.initialize(), timeout=20)
                except asyncio.TimeoutError:
                    error_msg = (
                        "Тайм-аут при инициализации MCP сервера Kinopoisk (более 20 секунд).\n\n"
                        f"Проверьте сервер 'mcp_server.py': {MCP_KINOPOISK_COMMAND} {' '.join(MCP_KINOPOISK_ARGS)}"
                    )
                    _last_kp_error = ("TIMEOUT_INIT", error_msg)
                    logger.error(error_msg)
                    return None

                logger.info(f"MCP сервер Kinopoisk подключен, вызываю инструмент '{name}'")

                # Вызов инструмента с таймаутом
                try:
                    tool_result = await asyncio.wait_for(
                        session.call_tool(name=name, arguments=arguments),
                        timeout=40,
                    )
                except asyncio.TimeoutError:
                    error_msg = (
                        f"Тайм-аут при вызове инструмента '{name}' MCP сервера Kinopoisk (более 40 секунд).\n\n"
                        "Проверьте, не завис ли сервер и не слишком ли тяжёлый запрос."
                    )
                    _last_kp_error = ("TIMEOUT_CALL", error_msg)
                    logger.error(error_msg)
                    return None

                # Извлекаем текст из результата (ожидаем список TextContent)
                texts: List[str] = []
                if tool_result is None:
                    _last_kp_error = None
                    return ""

                contents = getattr(tool_result, "content", None) or getattr(
                    tool_result, "contents", None
                )

                if isinstance(contents, list):
                    for item in contents:
                        if hasattr(item, "text"):
                            texts.append(str(item.text))
                        elif isinstance(item, dict) and "text" in item:
                            texts.append(str(item["text"]))
                        else:
                            texts.append(str(item))
                else:
                    texts.append(str(tool_result))

                _last_kp_error = None
                # Обычно сервер Kinopoisk возвращает один JSON-текст
                return "\n\n".join(texts)

    except FileNotFoundError as e:
        error_msg = (
            f"Команда запуска MCP сервера Kinopoisk не найдена: {e}\n\n"
            f"Команда: '{MCP_KINOPOISK_COMMAND} {' '.join(MCP_KINOPOISK_ARGS)}'\n\n"
            f"Убедитесь, что Python установлен и путь к 'mcp_server.py' указан верно."
        )
        _last_kp_error = ("FILE_NOT_FOUND", error_msg)
        logger.error(error_msg)
        return None
    except ImportError as import_err:
        error_msg = (
            "Библиотека mcp не установлена.\n\n"
            "Для установки выполните:\n"
            "```bash\n"
            "pip install mcp\n"
            "```\n\n"
            "Или установите все зависимости:\n"
            "```bash\n"
            "pip install -r requirements.txt\n"
            "```\n\n"
            f"Детали ошибки: {import_err}"
        )
        _last_kp_error = ("IMPORT_ERROR", error_msg)
        logger.error(f"Библиотека mcp не установлена: {import_err}")
        return None
    except Exception as e:
        error_msg = f"Ошибка при вызове инструмента '{name}' Kinopoisk MCP: {e}"
        _last_kp_error = ("GENERAL_ERROR", error_msg)
        logger.error(error_msg, exc_info=True)
        return None

