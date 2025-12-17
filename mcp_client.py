"""Модуль для работы с MCP сервером Notion"""
import logging
import shutil
import subprocess
from typing import List, Dict, Any, Optional, Tuple

from mcp import StdioServerParameters

from config import MCP_NOTION_COMMAND, MCP_NOTION_ARGS
from mcp_base import BaseMCPClient

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения информации об ошибке
_last_error: Optional[Tuple[str, str]] = None


def _check_node_version() -> Tuple[bool, Optional[str]]:
    """Проверяет версию Node.js (требуется >= 18)"""
    try:
        result = subprocess.run(
            ['node', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version_str = result.stdout.strip()
            # Извлекаем номер версии (например, "v12.22.9" -> 12)
            try:
                major_version = int(version_str.lstrip('v').split('.')[0])
                if major_version < 18:
                    return False, (
                        f"Требуется Node.js версии 18 или выше, установлена версия {version_str}.\n\n"
                        f"Для обновления Node.js:\n\n"
                        f"1. Если была ошибка dpkg, сначала исправьте:\n"
                        f"   sudo apt-get clean\n"
                        f"   sudo apt-get update\n"
                        f"   sudo dpkg --configure -a\n"
                        f"   sudo apt-get install -f\n\n"
                        f"2. Затем установите через nvm (рекомендуется):\n"
                        f"   curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash\n"
                        f"   source ~/.bashrc\n"
                        f"   nvm install 20\n"
                        f"   nvm use 20\n"
                        f"   nvm alias default 20\n\n"
                        f"Или через NodeSource:\n"
                        f"   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -\n"
                        f"   sudo apt-get install -y nodejs\n\n"
                        f"После обновления перезапустите бота."
                    )
                return True, None
            except (ValueError, IndexError):
                return False, f"Не удалось определить версию Node.js: {version_str}"
        return False, "Не удалось проверить версию Node.js"
    except FileNotFoundError:
        return False, "Node.js не установлен"
    except Exception as e:
        return False, f"Ошибка при проверке версии Node.js: {e}"


def _check_command_available(command: str) -> Tuple[bool, Optional[str]]:
    """Проверяет, доступна ли команда в системе"""
    command_name = command.split()[0] if command else ""
    if not command_name:
        return False, "Команда не указана"
    
    # Проверяем наличие команды в PATH
    if shutil.which(command_name) is None:
        if command_name == "npx":
            return False, (
                f"Команда 'npx' не найдена. Node.js не установлен или не добавлен в PATH.\n\n"
                f"Для установки Node.js (требуется версия 18 или выше):\n"
                f"• Ubuntu/Debian: \n"
                f"  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -\n"
                f"  sudo apt-get install -y nodejs\n"
                f"• Или через nvm:\n"
                f"  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash\n"
                f"  nvm install 20\n"
                f"  nvm use 20\n"
                f"• macOS: brew install node\n"
                f"• Windows: скачайте LTS версию с https://nodejs.org/\n\n"
                f"После установки Node.js, команда 'npx' будет доступна."
            )
        else:
            return False, f"Команда '{command_name}' не найдена в системе. Убедитесь, что она установлена и доступна в PATH."
    
    return True, None


def _get_server_params() -> Tuple[Optional[StdioServerParameters], Optional[str]]:
    """Создает параметры сервера MCP и проверяет доступность команды"""
    # Проверяем версию Node.js (требуется >= 18)
    if MCP_NOTION_COMMAND.split()[0] == "npx":
        version_ok, version_error = _check_node_version()
        if not version_ok:
            _set_last_error("NODE_VERSION_ERROR", version_error or "Неверная версия Node.js")
            return None, version_error
    
    # Проверяем доступность команды
    is_available, error_msg = _check_command_available(MCP_NOTION_COMMAND)
    if not is_available:
        _set_last_error("COMMAND_NOT_FOUND", error_msg or "Команда не найдена")
        return None, error_msg
    
    try:
        command_parts = MCP_NOTION_COMMAND.split()
        command = command_parts[0]
        args = command_parts[1:] + MCP_NOTION_ARGS
        
        server_params = StdioServerParameters(
            command=command,
            args=args
        )
        _set_last_error(None, None)
        return server_params, None
    except Exception as e:
        error_msg = f"Ошибка при создании параметров сервера: {e}"
        _set_last_error("CONFIG_ERROR", error_msg)
        return None, error_msg


def get_last_error() -> Optional[Tuple[str, str]]:
    """Возвращает последнюю ошибку"""
    return _last_error


def _set_last_error(error_type: Optional[str], error_msg: Optional[str]) -> None:
    """Устанавливает последнюю ошибку"""
    global _last_error
    _last_error = (error_type, error_msg) if error_type and error_msg else None


# Создаем экземпляр клиента
_notion_client = BaseMCPClient(
    server_name="Notion",
    get_server_params_func=_get_server_params,
    get_last_error_func=get_last_error,
    set_last_error_func=_set_last_error,
    init_timeout=20,
    tools_timeout=20,
    call_timeout=40,
)


async def list_notion_tools() -> List[Dict[str, Any]]:
    """Получает список доступных инструментов Notion через MCP сервер"""
    try:
        return await _notion_client.list_tools()
    except PermissionError as e:
        error_msg = (
            f"Ошибка прав доступа при выполнении MCP команды: {e}\n\n"
            f"Возможные решения:\n"
            f"• Убедитесь, что Node.js установлен правильно\n"
            f"• Попробуйте очистить кэш npm: npm cache clean --force\n"
            f"• Переустановите mcp-remote: npx clear-npx-cache\n"
            f"• Проверьте права доступа к директории npm"
        )
        _set_last_error("PERMISSION_ERROR", error_msg)
        logger.error(error_msg)
        return []


async def call_notion_tool(name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Вызывает указанный инструмент Notion MCP и возвращает текстовый результат"""
    try:
        return await _notion_client.call_tool(name, arguments)
    except PermissionError as e:
        error_msg = (
            f"Ошибка прав доступа при выполнении MCP команды: {e}\n\n"
            f"Возможные решения:\n"
            f"• Убедитесь, что Node.js установлен правильно\n"
            f"• Попробуйте очистить кэш npm: npm cache clean --force\n"
        )
        _set_last_error("PERMISSION_ERROR", error_msg)
        logger.error(error_msg)
        return None
