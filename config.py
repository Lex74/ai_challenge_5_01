import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# OpenAI API
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions'

# Admin User ID для отправки логов
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID')

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

# Проверка наличия обязательных переменных
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не установлен в переменных окружения")

