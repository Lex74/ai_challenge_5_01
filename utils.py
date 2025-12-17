"""Утилиты для форматирования и обработки текста"""
import re
from typing import List, Dict, Any
from html import escape

from constants import GOAL_FORMULATED_MARKER


def is_goal_formulated(answer: str) -> bool:
    """Проверяет, сформулировал ли бот финальную цель по наличию специального маркера"""
    return GOAL_FORMULATED_MARKER in answer


def remove_marker_from_answer(answer: str) -> str:
    """Удаляет маркер формулировки цели из ответа перед отправкой пользователю"""
    return answer.replace(GOAL_FORMULATED_MARKER, "").strip()


def remove_source_numbers(text: str) -> str:
    """Удаляет номера источников информации из текста"""
    # Удаляем ссылки на источники в квадратных скобках: [1], [2], [3] и т.д.
    text = re.sub(r'\[\d+\]', '', text)
    
    # Удаляем ссылки на источники в круглых скобках: (1), (2), (3) и т.д.
    text = re.sub(r'\(\d+\)', '', text)
    
    # Удаляем ссылки вида [source 1], [source 2] и т.д.
    text = re.sub(r'\[source\s+\d+\]', '', text, flags=re.IGNORECASE)
    
    # Удаляем ссылки вида [источник 1], [источник 2] и т.д.
    text = re.sub(r'\[источник\s+\d+\]', '', text, flags=re.IGNORECASE)
    
    # Удаляем множественные пробелы в пределах одной строки (но сохраняем переносы строк)
    # Заменяем множественные пробелы на один пробел, но не трогаем \n
    lines = text.split('\n')
    cleaned_lines = [re.sub(r'[ \t]+', ' ', line) for line in lines]
    text = '\n'.join(cleaned_lines)
    
    # Удаляем пробелы в начале и конце каждой строки, но сохраняем пустые строки
    lines = text.split('\n')
    cleaned_lines = [line.strip() if line.strip() else '' for line in lines]
    text = '\n'.join(cleaned_lines)
    
    return text.strip()


def convert_markdown_to_telegram(text: str) -> str:
    """Преобразует markdown разметку в HTML форматирование для Telegram"""
    # Экранируем специальные символы HTML
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    
    # Преобразуем ## текст в <u>текст</u> (подчёркнутый)
    # Обрабатываем строки, начинающиеся с ##
    lines = text.split('\n')
    result_lines = []
    for line in lines:
        if line.strip().startswith('##'):
            # Убираем ## и пробелы после них, оборачиваем в <u>
            content = line.replace('##', '').strip()
            if content:
                result_lines.append(f'<u>{content}</u>')
            else:
                result_lines.append(line)
        else:
            result_lines.append(line)
    text = '\n'.join(result_lines)
    
    # Преобразуем **текст** в <b>текст</b> (жирный)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    
    return text


def clean_html_text(text: str) -> str:
    """Удаляет недопустимые HTML-теги и экранирует специальные символы"""
    if not text:
        return ""
    # Удаляем недопустимые HTML-теги (например, <data-source>)
    text = re.sub(r'<[^>]+>', '', str(text))
    # Экранируем оставшиеся HTML-символы
    text = escape(text)
    return text


def format_tools_list(tools: List[Dict[str, Any]], server_name: str) -> str:
    """Форматирует список инструментов для отправки в Telegram"""
    message_parts = [f"📋 Доступные инструменты {server_name}:\n"]
    
    for i, tool in enumerate(tools, 1):
        # Ожидаем словарь после преобразования в MCP клиенте
        if isinstance(tool, dict):
            name = tool.get('name', 'Неизвестно')
            input_schema = tool.get('inputSchema', {}) or tool.get('input_schema', {})
            if isinstance(input_schema, dict):
                properties = input_schema.get('properties', {})
            else:
                properties = {}
        else:
            name = getattr(tool, 'name', 'Неизвестно')
            input_schema = getattr(tool, 'inputSchema', None) or getattr(tool, 'input_schema', None)
            if input_schema and hasattr(input_schema, 'get'):
                properties = input_schema.get('properties', {}) if isinstance(input_schema, dict) else {}
            else:
                properties = {}
        
        name_cleaned = clean_html_text(name)
        
        tool_info = f"\n{i}. <b>{name_cleaned}</b>\n"
        
        if properties:
            tool_info += "   Параметры:\n"
            for param_name, param_info in properties.items():
                param_type = param_info.get('type', 'unknown') if isinstance(param_info, dict) else 'unknown'
                param_name_cleaned = clean_html_text(param_name)
                param_type_cleaned = clean_html_text(param_type)
                tool_info += f"   • {param_name_cleaned} ({param_type_cleaned})\n"
        
        message_parts.append(tool_info)
    
    return "".join(message_parts)


def split_long_message(message: str, max_length: int = 4000) -> List[str]:
    """Разбивает длинное сообщение на части для Telegram (лимит 4096 символов)"""
    if len(message) <= max_length:
        return [message]
    
    # Пытаемся разбить по строкам
    lines = message.split('\n')
    parts = []
    current_part = ""
    
    for line in lines:
        if len(current_part) + len(line) + 1 > max_length:
            if current_part:
                parts.append(current_part)
                current_part = line
            else:
                # Если одна строка слишком длинная, обрезаем её
                parts.append(line[:max_length])
                current_part = line[max_length:]
        else:
            current_part += ('\n' if current_part else '') + line
    
    if current_part:
        parts.append(current_part)
    
    return parts
