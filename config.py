import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# OpenAI API
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions'

# Admin User ID для отправки логов и ежедневной рассылки новостей
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')
if ADMIN_USER_ID:
    ADMIN_USER_ID = int(ADMIN_USER_ID)

# MCP Server Configuration
# Согласно официальной документации: https://developers.notion.com/docs/get-started-with-mcp
# Для STDIO Notion используется: npx -y mcp-remote https://mcp.notion.com/mcp
MCP_NOTION_COMMAND = os.getenv('MCP_NOTION_COMMAND', 'npx')
MCP_NOTION_ARGS = os.getenv('MCP_NOTION_ARGS', '-y mcp-remote https://mcp.notion.com/mcp').split() if os.getenv('MCP_NOTION_ARGS') else ['-y', 'mcp-remote', 'https://mcp.notion.com/mcp']

# Локальный MCP сервер Kinopoisk (Python)
# По умолчанию используем системную команду python и абсолютный путь к mcp_server.py
MCP_KINOPOISK_COMMAND = os.getenv('MCP_KINOPOISK_COMMAND', 'python3')
MCP_KINOPOISK_ARGS = (
    os.getenv(
        'MCP_KINOPOISK_ARGS',
        '../kinopoisk-mcp/mcp_server.py',
    ).split()
    if os.getenv('MCP_KINOPOISK_ARGS')
    else ['../kinopoisk-mcp/mcp_server.py']
)

# Локальный MCP сервер News (Python)
# Используем Python из виртуального окружения news-mcp, если оно есть
# Иначе используем системный python3
# Вычисляем абсолютный путь относительно текущего файла
_config_dir = os.path.dirname(os.path.abspath(__file__))
_news_mcp_venv_python = os.path.abspath(os.path.join(_config_dir, '..', 'news-mcp', 'venv', 'bin', 'python3'))
_news_mcp_server = os.path.abspath(os.path.join(_config_dir, '..', 'news-mcp', 'server.py'))

# Проверяем существование venv, если нет - используем системный python3
# На VPS без venv будет использоваться системный python3
if os.path.exists(_news_mcp_venv_python):
    _default_news_command = _news_mcp_venv_python
else:
    # Используем системный python3
    _default_news_command = 'python3'

MCP_NEWS_COMMAND = os.getenv('MCP_NEWS_COMMAND', _default_news_command)
MCP_NEWS_ARGS = (
    os.getenv('MCP_NEWS_ARGS', _news_mcp_server).split()
    if os.getenv('MCP_NEWS_ARGS')
    else [_news_mcp_server]
)

# Локальный MCP сервер Logs (Python)
# Вычисляем абсолютный путь относительно текущего файла
_logs_mcp_server = os.path.abspath(os.path.join(_config_dir, '..', 'logs_mcp', 'server.py'))

# Используем системный python3 по умолчанию
MCP_LOGS_COMMAND = os.getenv('MCP_LOGS_COMMAND', 'python3')
MCP_LOGS_ARGS = (
    os.getenv('MCP_LOGS_ARGS', _logs_mcp_server).split()
    if os.getenv('MCP_LOGS_ARGS')
    else [_logs_mcp_server]
)

# Notion страница для сохранения новостей
# Page ID извлекается из URL: https://www.notion.so/2ceb45610e4e808984b8d8131d3ccc61
# Формат: 2ceb45610e4e808984b8d8131d3ccc61 (без дефисов, как в URL)
NOTION_NEWS_PAGE_ID = os.getenv('NOTION_NEWS_PAGE_ID', '2ceb45610e4e808984b8d8131d3ccc61')

# Проверка наличия обязательных переменных
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не установлен в переменных окружения")

