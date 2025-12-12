"""Утилиты для форматирования и обработки текста"""
import re

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
