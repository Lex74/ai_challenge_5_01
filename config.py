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

# Локальный MCP сервер Git (Python)
# Вычисляем абсолютный путь относительно текущего файла
_git_mcp_server = os.path.abspath(os.path.join(_config_dir, 'git_mcp', 'server.py'))

# Используем системный python3 по умолчанию
MCP_GIT_COMMAND = os.getenv('MCP_GIT_COMMAND', 'python3')
MCP_GIT_ARGS = (
    os.getenv('MCP_GIT_ARGS', _git_mcp_server).split()
    if os.getenv('MCP_GIT_ARGS')
    else [_git_mcp_server]
)

# Notion страница для сохранения новостей
# Page ID извлекается из URL: https://www.notion.so/2ceb45610e4e808984b8d8131d3ccc61
# Формат: 2ceb45610e4e808984b8d8131d3ccc61 (без дефисов, как в URL)
NOTION_NEWS_PAGE_ID = os.getenv('NOTION_NEWS_PAGE_ID', '2ceb45610e4e808984b8d8131d3ccc61')

# Notion база данных/страница для задач команды
# ID извлекается из URL базы данных или страницы в Notion
# Формат: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx (32 символа, без дефисов)
# Задачи создаются как дочерние страницы этой страницы/базы данных
# Структура базы данных (если это база данных):
# - Название (Title) - название задачи
# - Описание (Text) - описание задачи
# - Приоритет (Select) - low, medium, high
# - Статус (Select) - todo, in_progress, done (опционально)
NOTION_TASKS_DATABASE_ID = os.getenv('NOTION_TASKS_DATABASE_ID', '2eab45610e4e80e7b1e6c495c02d9d38')

# GitHub API Configuration (для CI/CD ревью PR)
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')  # Формат: owner/repo

# Проверка наличия обязательных переменных
# TELEGRAM_BOT_TOKEN требуется только для бота, не для CI скриптов
# Проверяем только если мы запускаем бота (проверка через наличие bot.py в импортах)
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не установлен в переменных окружения")

