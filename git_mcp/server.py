#!/usr/bin/env python3
"""MCP сервер для работы с Git репозиторием"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Определяем корневую директорию проекта (где находится .git)
# Ищем .git директорию, начиная с текущей директории и поднимаясь вверх
def find_git_root(start_path: str = None) -> str:
    """Находит корень git репозитория"""
    if start_path is None:
        start_path = os.getcwd()
    
    path = Path(start_path).resolve()
    
    # Проверяем текущую директорию и все родительские
    for parent in [path] + list(path.parents):
        if (parent / '.git').exists():
            return str(parent)
    
    # Если не нашли, возвращаем текущую директорию
    return str(path)

# Определяем GIT_ROOT относительно расположения server.py
# server.py находится в git_mcp/, а репозиторий на уровень выше
_config_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_config_dir)  # Поднимаемся на уровень выше от git_mcp/
GIT_ROOT = find_git_root(_project_root)

app = Server("git-mcp-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Возвращает список доступных инструментов Git"""
    return [
        Tool(
            name="get_current_branch",
            description="Получает название текущей ветки git репозитория",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_git_status",
            description="Получает статус git репозитория (измененные, добавленные, удаленные файлы)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_open_files",
            description="Получает список открытых/измененных файлов в git репозитории",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_file_content",
            description="Получает содержимое файла из git репозитория",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Путь к файлу относительно корня репозитория"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_recent_commits",
            description="Получает список последних коммитов",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Количество коммитов для получения (по умолчанию 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_diff",
            description="Получает diff (различия) для указанного файла или всех измененных файлов",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Путь к файлу относительно корня репозитория (опционально, если не указан - показывает diff всех измененных файлов)"
                    }
                },
                "required": []
            }
        ),
    ]


def run_git_command(command: list[str], cwd: str = None) -> tuple[str, int]:
    """Выполняет git команду и возвращает результат"""
    if cwd is None:
        cwd = GIT_ROOT
    
    # Проверяем, что директория существует и это git репозиторий
    if not os.path.exists(cwd):
        return f"Ошибка: директория {cwd} не существует", 1
    
    if not os.path.exists(os.path.join(cwd, '.git')):
        return f"Ошибка: {cwd} не является git репозиторием (нет .git директории)", 1
    
    try:
        result = subprocess.run(
            ['git'] + command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Если команда вернула ошибку, возвращаем stderr вместо stdout
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Неизвестная ошибка"
            return error_msg, result.returncode
        
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "Timeout: команда git выполнилась слишком долго", 1
    except FileNotFoundError:
        return "Ошибка: git не найден в системе", 1
    except Exception as e:
        return f"Ошибка: {str(e)}", 1


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> Sequence[TextContent]:
    """Обрабатывает вызовы инструментов Git"""
    if arguments is None:
        arguments = {}
    
    if name == "get_current_branch":
        # Сначала проверяем, что мы в git репозитории
        check_output, check_code = run_git_command(['rev-parse', '--git-dir'], GIT_ROOT)
        if check_code != 0:
            return [TextContent(type="text", text=f"Ошибка: {GIT_ROOT} не является git репозиторием. {check_output}")]
        
        # Проверяем, есть ли коммиты в репозитории
        commit_check, commit_check_code = run_git_command(['rev-parse', 'HEAD'], GIT_ROOT)
        if commit_check_code != 0:
            # Нет коммитов в репозитории
            return [TextContent(type="text", text=f"Репозиторий не содержит коммитов. Это новый или пустой репозиторий. Git директория: {GIT_ROOT}")]
        
        # Пробуем получить текущую ветку через branch --show-current (более надежный способ)
        output, code = run_git_command(['branch', '--show-current'], GIT_ROOT)
        if code == 0:
            branch_name = output.strip()
            if branch_name:
                return [TextContent(type="text", text=f"Текущая активная ветка git репозитория: {branch_name}")]
            else:
                # Если ветка пустая, возможно репозиторий в detached HEAD состоянии
                # Пробуем получить коммит
                commit_output, commit_code = run_git_command(['rev-parse', '--short', 'HEAD'], GIT_ROOT)
                if commit_code == 0:
                    commit_hash = commit_output.strip()
                    return [TextContent(type="text", text=f"Репозиторий находится в состоянии detached HEAD (нет активной ветки). Текущий коммит: {commit_hash}")]
                else:
                    return [TextContent(type="text", text="Ошибка: не удалось определить текущую ветку или коммит.")]
        else:
            # Если команда не сработала, пробуем альтернативный способ
            alt_output, alt_code = run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'], GIT_ROOT)
            if alt_code == 0:
                branch_name = alt_output.strip()
                if branch_name and branch_name != "HEAD":
                    return [TextContent(type="text", text=f"Текущая активная ветка git репозитория: {branch_name}")]
                else:
                    # Detached HEAD
                    commit_output, commit_code = run_git_command(['rev-parse', '--short', 'HEAD'], GIT_ROOT)
                    if commit_code == 0:
                        commit_hash = commit_output.strip()
                        return [TextContent(type="text", text=f"Репозиторий находится в состоянии detached HEAD (нет активной ветки). Текущий коммит: {commit_hash}")]
            
            return [TextContent(type="text", text=f"Ошибка при получении текущей ветки. Git репозиторий: {GIT_ROOT}. Ошибка: {output or alt_output}")]
    
    elif name == "get_git_status":
        output, code = run_git_command(['status', '--short'])
        if code == 0:
            if output:
                return [TextContent(type="text", text=f"Статус git:\n{output}")]
            else:
                return [TextContent(type="text", text="Рабочая директория чистая, нет изменений")]
        else:
            return [TextContent(type="text", text=f"Ошибка: {output}")]
    
    elif name == "get_open_files":
        # Получаем список измененных файлов
        output, code = run_git_command(['diff', '--name-only', 'HEAD'])
        if code == 0:
            modified = output.split('\n') if output else []
        else:
            modified = []
        
        # Получаем список неотслеживаемых файлов
        output, code = run_git_command(['ls-files', '--others', '--exclude-standard'])
        if code == 0:
            untracked = output.split('\n') if output else []
        else:
            untracked = []
        
        # Получаем список файлов в staging area
        output, code = run_git_command(['diff', '--cached', '--name-only'])
        if code == 0:
            staged = output.split('\n') if output else []
        else:
            staged = []
        
        result = {
            "modified": [f for f in modified if f],
            "untracked": [f for f in untracked if f],
            "staged": [f for f in staged if f]
        }
        
        result_text = "Открытые/измененные файлы:\n\n"
        if result["modified"]:
            result_text += f"Измененные файлы ({len(result['modified'])}):\n"
            for f in result["modified"]:
                result_text += f"  - {f}\n"
        if result["staged"]:
            result_text += f"\nФайлы в staging area ({len(result['staged'])}):\n"
            for f in result["staged"]:
                result_text += f"  - {f}\n"
        if result["untracked"]:
            result_text += f"\nНеотслеживаемые файлы ({len(result['untracked'])}):\n"
            for f in result["untracked"]:
                result_text += f"  - {f}\n"
        
        if not result["modified"] and not result["staged"] and not result["untracked"]:
            result_text = "Нет измененных или открытых файлов"
        
        return [TextContent(type="text", text=result_text)]
    
    elif name == "get_file_content":
        file_path = arguments.get("file_path")
        if not file_path:
            return [TextContent(type="text", text="Ошибка: не указан путь к файлу")]
        
        # Проверяем, что файл находится внутри репозитория
        full_path = Path(GIT_ROOT) / file_path
        if not str(full_path).startswith(str(Path(GIT_ROOT).resolve())):
            return [TextContent(type="text", text="Ошибка: файл находится вне репозитория")]
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return [TextContent(type="text", text=f"Содержимое файла {file_path}:\n\n{content}")]
        except FileNotFoundError:
            return [TextContent(type="text", text=f"Ошибка: файл {file_path} не найден")]
        except Exception as e:
            return [TextContent(type="text", text=f"Ошибка при чтении файла: {str(e)}")]
    
    elif name == "get_recent_commits":
        count = arguments.get("count", 10)
        output, code = run_git_command(['log', f'-{count}', '--oneline', '--decorate'])
        if code == 0:
            return [TextContent(type="text", text=f"Последние {count} коммитов:\n\n{output}")]
        else:
            return [TextContent(type="text", text=f"Ошибка: {output}")]
    
    elif name == "get_diff":
        file_path = arguments.get("file_path")
        if file_path:
            output, code = run_git_command(['diff', file_path])
        else:
            output, code = run_git_command(['diff'])
        
        if code == 0:
            if output:
                return [TextContent(type="text", text=f"Diff:\n\n{output}")]
            else:
                return [TextContent(type="text", text="Нет изменений")]
        else:
            return [TextContent(type="text", text=f"Ошибка: {output}")]
    
    else:
        return [TextContent(type="text", text=f"Неизвестный инструмент: {name}")]


async def main():
    """Главная функция для запуска MCP сервера"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
