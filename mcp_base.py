"""Базовый класс для работы с MCP серверами"""
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class BaseMCPClient:
    """Базовый класс для работы с MCP серверами"""
    
    def __init__(
        self,
        server_name: str,
        get_server_params_func: Callable[[], Tuple[Optional[StdioServerParameters], Optional[str]]],
        get_last_error_func: Callable[[], Optional[Tuple[str, str]]],
        set_last_error_func: Callable[[Optional[str], Optional[str]], None],
        init_timeout: Optional[int] = 20,
        tools_timeout: Optional[int] = 20,
        call_timeout: Optional[int] = 40,
    ):
        """
        Инициализация базового MCP клиента
        
        Args:
            server_name: Имя сервера (для логирования)
            get_server_params_func: Функция для получения параметров сервера
            get_last_error_func: Функция для получения последней ошибки
            set_last_error_func: Функция для установки ошибки
            init_timeout: Таймаут инициализации (секунды)
            tools_timeout: Таймаут получения списка инструментов (секунды)
            call_timeout: Таймаут вызова инструмента (секунды)
        """
        self.server_name = server_name
        self._get_server_params = get_server_params_func
        self._get_last_error = get_last_error_func
        self._set_last_error = set_last_error_func
        self.init_timeout = init_timeout
        self.tools_timeout = tools_timeout
        self.call_timeout = call_timeout
    
    def _convert_tool_to_dict(self, tool_obj: Any) -> Dict[str, Any]:
        """Преобразует объект Tool в словарь"""
        if hasattr(tool_obj, "model_dump"):
            return tool_obj.model_dump()
        elif hasattr(tool_obj, "dict"):
            return tool_obj.dict()
        elif hasattr(tool_obj, "__dict__"):
            return tool_obj.__dict__
        else:
            return {
                "name": getattr(tool_obj, "name", "Неизвестно"),
                "description": getattr(tool_obj, "description", ""),
                "inputSchema": getattr(tool_obj, "inputSchema", {}),
            }
    
    def _extract_text_from_result(self, tool_result: Any) -> str:
        """Извлекает текст из результата вызова инструмента"""
        texts: List[str] = []
        
        if tool_result is None:
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
        
        return "\n\n".join(texts)
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """Получает список доступных инструментов через MCP сервер"""
        try:
            logger.info(f"Запрос к MCP {self.server_name}: list_tools()")
            
            server_params, error_msg = self._get_server_params()
            if server_params is None:
                logger.error(f"Не удалось создать параметры сервера {self.server_name} MCP: {error_msg}")
                return []
            
            # Подключаемся к MCP серверу и получаем список инструментов
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Инициализируем сессию с таймаутом
                    try:
                        if self.init_timeout is not None:
                            await asyncio.wait_for(session.initialize(), timeout=self.init_timeout)
                        else:
                            await session.initialize()
                    except asyncio.TimeoutError:
                        error_msg = (
                            f"Тайм-аут при инициализации MCP сервера {self.server_name} "
                            f"(более {self.init_timeout} секунд)."
                        )
                        self._set_last_error("TIMEOUT_INIT", error_msg)
                        logger.error(error_msg)
                        return []
                    
                    logger.info(f"MCP сервер {self.server_name} успешно подключен")
                    
                    # Получаем список инструментов из MCP сервера с таймаутом
                    try:
                        if self.tools_timeout is not None:
                            tools_result = await asyncio.wait_for(
                                session.list_tools(), timeout=self.tools_timeout
                            )
                        else:
                            tools_result = await session.list_tools()
                    except asyncio.TimeoutError:
                        error_msg = (
                            f"Тайм-аут при получении списка инструментов от MCP сервера {self.server_name} "
                            f"(более {self.tools_timeout} секунд)."
                        )
                        self._set_last_error("TIMEOUT_TOOLS", error_msg)
                        logger.error(error_msg)
                        return []
                    
                    tools_objects = tools_result.tools if tools_result else []
                    
                    # Преобразуем объекты Tool в словари
                    tools: List[Dict[str, Any]] = []
                    for tool_obj in tools_objects:
                        tool_dict = self._convert_tool_to_dict(tool_obj)
                        tools.append(tool_dict)
                    
                    logger.info(f"Получено {len(tools)} инструментов от MCP сервера {self.server_name}")
                    self._set_last_error(None, None)  # type: ignore
                    return tools
                    
        except FileNotFoundError as e:
            error_msg = (
                f"Команда запуска MCP сервера {self.server_name} не найдена: {e}\n\n"
                f"Убедитесь, что команда указана верно в конфигурации."
            )
            self._set_last_error("FILE_NOT_FOUND", error_msg)
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
            self._set_last_error("IMPORT_ERROR", error_msg)
            logger.error(f"Библиотека mcp не установлена: {import_err}")
            return []
        except Exception as e:
            error_msg = f"Ошибка при получении списка инструментов {self.server_name} MCP: {e}"
            self._set_last_error("GENERAL_ERROR", error_msg)
            logger.error(error_msg, exc_info=True)
            return []
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """Вызывает указанный инструмент MCP и возвращает текстовый результат"""
        try:
            logger.info(
                f"Запрос к MCP {self.server_name}: call_tool(name=%r, arguments=%r)",
                name,
                arguments,
            )
            
            server_params, error_msg = self._get_server_params()
            if server_params is None:
                logger.error(f"Не удалось создать параметры сервера {self.server_name} MCP: {error_msg}")
                return None
            
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Инициализация с таймаутом
                    try:
                        if self.init_timeout is not None:
                            await asyncio.wait_for(session.initialize(), timeout=self.init_timeout)
                        else:
                            await session.initialize()
                    except asyncio.TimeoutError:
                        error_msg = (
                            f"Тайм-аут при инициализации MCP сервера {self.server_name} "
                            f"(более {self.init_timeout} секунд)."
                        )
                        self._set_last_error("TIMEOUT_INIT", error_msg)
                        logger.error(error_msg)
                        return None
                    
                    logger.info(f"MCP сервер {self.server_name} подключен, вызываю инструмент '{name}'")
                    
                    # Вызов инструмента с таймаутом
                    try:
                        if self.call_timeout is not None:
                            tool_result = await asyncio.wait_for(
                                session.call_tool(name=name, arguments=arguments),
                                timeout=self.call_timeout,
                            )
                        else:
                            tool_result = await session.call_tool(name=name, arguments=arguments)
                    except asyncio.TimeoutError:
                        error_msg = (
                            f"Тайм-аут при вызове инструмента '{name}' MCP сервера {self.server_name} "
                            f"(более {self.call_timeout} секунд)."
                        )
                        self._set_last_error("TIMEOUT_CALL", error_msg)
                        logger.error(error_msg)
                        return None
                    
                    result_text = self._extract_text_from_result(tool_result)
                    self._set_last_error(None, None)  # type: ignore
                    return result_text
                    
        except FileNotFoundError as e:
            error_msg = (
                f"Команда запуска MCP сервера {self.server_name} не найдена: {e}\n\n"
                f"Убедитесь, что команда указана верно в конфигурации."
            )
            self._set_last_error("FILE_NOT_FOUND", error_msg)
            logger.error(error_msg)
            return None
        except ImportError as import_err:
            error_msg = (
                "Библиотека mcp не установлена.\n\n"
                "Для установки выполните: pip install mcp"
            )
            self._set_last_error("IMPORT_ERROR", error_msg)
            logger.error(f"Библиотека mcp не установлена: {import_err}")
            return None
        except Exception as e:
            error_msg = f"Ошибка при вызове инструмента '{name}' {self.server_name} MCP: {e}"
            self._set_last_error("GENERAL_ERROR", error_msg)
            logger.error(error_msg, exc_info=True)
            return None

