#!/usr/bin/env python3
"""
CLI агент для работы с моделями OLLama
Позволяет общаться с моделями через командную строку
"""

import os
import sys
import json
import requests
import argparse
from typing import List, Optional, Dict, Any

# URL OLLama API
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://localhost:11434')
OLLAMA_API_BASE = f"{OLLAMA_API_URL}/api"

# Цвета для терминала
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_colored(text: str, color: str = Colors.END, end: str = '\n', flush: bool = False):
    """Печатает цветной текст"""
    print(f"{color}{text}{Colors.END}", end=end, flush=flush)


def get_available_models() -> List[str]:
    """Получает список доступных моделей"""
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/tags", timeout=5)
        response.raise_for_status()
        data = response.json()
        return [model['name'] for model in data.get('models', [])]
    except Exception as e:
        print_colored(f"Ошибка при получении списка моделей: {e}", Colors.RED)
        return []


def check_ollama_available() -> bool:
    """Проверяет доступность OLLama сервера"""
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/tags", timeout=5)
        return response.status_code == 200
    except:
        return False


def generate_response(model: str, prompt: str, stream: bool = True) -> str:
    """Генерирует ответ от модели"""
    url = f"{OLLAMA_API_BASE}/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream
    }
    
    try:
        response = requests.post(url, json=payload, stream=stream, timeout=300)
        response.raise_for_status()
        
        if stream:
            full_response = ""
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if 'response' in data:
                            chunk = data['response']
                            print(chunk, end='', flush=True)
                            full_response += chunk
                        if data.get('done', False):
                            break
                    except json.JSONDecodeError:
                        continue
            print()  # Новая строка после ответа
            return full_response
        else:
            data = response.json()
            return data.get('response', '')
    except requests.exceptions.RequestException as e:
        print_colored(f"Ошибка при запросе к модели: {e}", Colors.RED)
        return ""


def chat_with_model(model: str, messages: List[Dict[str, str]], stream: bool = True) -> str:
    """Отправляет сообщения в модель через chat API"""
    url = f"{OLLAMA_API_BASE}/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream
    }
    
    try:
        response = requests.post(url, json=payload, stream=stream, timeout=300)
        response.raise_for_status()
        
        if stream:
            full_response = ""
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if 'message' in data and 'content' in data['message']:
                            chunk = data['message']['content']
                            print(chunk, end='', flush=True)
                            full_response += chunk
                        if data.get('done', False):
                            break
                    except json.JSONDecodeError:
                        continue
            print()  # Новая строка после ответа
            return full_response
        else:
            data = response.json()
            return data.get('message', {}).get('content', '')
    except requests.exceptions.RequestException as e:
        print_colored(f"Ошибка при запросе к модели: {e}", Colors.RED)
        return ""


def show_models():
    """Показывает список доступных моделей"""
    models = get_available_models()
    if not models:
        print_colored("Нет доступных моделей или OLLama сервер недоступен", Colors.RED)
        return
    
    print_colored("\n📋 Доступные модели:", Colors.BOLD)
    for i, model in enumerate(models, 1):
        print_colored(f"  {i}. {model}", Colors.CYAN)
    print()


def interactive_mode(model: str):
    """Интерактивный режим общения с моделью"""
    if not check_ollama_available():
        print_colored("❌ OLLama сервер недоступен. Убедитесь, что он запущен.", Colors.RED)
        print_colored("   Запустите: ollama serve", Colors.YELLOW)
        return
    
    models = get_available_models()
    if not models:
        print_colored("❌ Нет доступных моделей", Colors.RED)
        return
    
    # Проверяем, что выбранная модель существует
    if model not in models:
        print_colored(f"❌ Модель '{model}' не найдена", Colors.RED)
        print_colored("Доступные модели:", Colors.YELLOW)
        for m in models:
            print_colored(f"  - {m}", Colors.CYAN)
        return
    
    print_colored(f"\n🤖 Интерактивный режим с моделью: {model}", Colors.BOLD)
    print_colored("Команды:", Colors.YELLOW)
    print_colored("  /help - показать справку", Colors.CYAN)
    print_colored("  /models - показать список моделей", Colors.CYAN)
    print_colored("  /switch <model> - переключиться на другую модель", Colors.CYAN)
    print_colored("  /clear - очистить историю диалога", Colors.CYAN)
    print_colored("  /exit или /quit - выйти", Colors.CYAN)
    print_colored("  /history - показать историю диалога", Colors.CYAN)
    print()
    
    conversation_history = []
    
    while True:
        try:
            # Показываем промпт
            print_colored(f"[{model}]", Colors.GREEN, end=" ")
            user_input = input().strip()
            
            if not user_input:
                continue
            
            # Обработка команд
            if user_input.startswith('/'):
                command = user_input.split()[0]
                
                if command in ['/exit', '/quit', '/q']:
                    print_colored("👋 До свидания!", Colors.YELLOW)
                    break
                
                elif command == '/help':
                    print_colored("\n📖 Справка по командам:", Colors.BOLD)
                    print_colored("  /help - показать эту справку", Colors.CYAN)
                    print_colored("  /models - показать список доступных моделей", Colors.CYAN)
                    print_colored("  /switch <model> - переключиться на другую модель", Colors.CYAN)
                    print_colored("  /clear - очистить историю диалога", Colors.CYAN)
                    print_colored("  /history - показать историю диалога", Colors.CYAN)
                    print_colored("  /exit, /quit, /q - выйти из программы", Colors.CYAN)
                    print()
                
                elif command == '/models':
                    show_models()
                
                elif command == '/switch':
                    parts = user_input.split()
                    if len(parts) < 2:
                        print_colored("❌ Укажите модель: /switch <model_name>", Colors.RED)
                        continue
                    new_model = parts[1]
                    if new_model in models:
                        model = new_model
                        conversation_history = []  # Очищаем историю при смене модели
                        print_colored(f"✅ Переключено на модель: {model}", Colors.GREEN)
                    else:
                        print_colored(f"❌ Модель '{new_model}' не найдена", Colors.RED)
                        show_models()
                
                elif command == '/clear':
                    conversation_history = []
                    print_colored("✅ История диалога очищена", Colors.GREEN)
                
                elif command == '/history':
                    if not conversation_history:
                        print_colored("История диалога пуста", Colors.YELLOW)
                    else:
                        print_colored("\n📜 История диалога:", Colors.BOLD)
                        for i, msg in enumerate(conversation_history, 1):
                            role = msg['role']
                            content = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
                            color = Colors.CYAN if role == 'user' else Colors.GREEN
                            print_colored(f"  {i}. [{role}]: {content}", color)
                        print()
                
                else:
                    print_colored(f"❌ Неизвестная команда: {command}. Используйте /help", Colors.RED)
                
                continue
            
            # Добавляем сообщение пользователя в историю
            conversation_history.append({
                "role": "user",
                "content": user_input
            })
            
            # Показываем индикатор загрузки
            print_colored(f"[{model}]", Colors.BLUE, end=" ")
            
            # Отправляем запрос
            response = chat_with_model(model, conversation_history, stream=True)
            
            # Добавляем ответ модели в историю
            if response:
                conversation_history.append({
                    "role": "assistant",
                    "content": response
                })
            
            print()  # Пустая строка после ответа
            
        except KeyboardInterrupt:
            print_colored("\n\n👋 Прервано пользователем. До свидания!", Colors.YELLOW)
            break
        except EOFError:
            print_colored("\n\n👋 До свидания!", Colors.YELLOW)
            break
        except Exception as e:
            print_colored(f"\n❌ Ошибка: {e}", Colors.RED)


def single_query(model: str, prompt: str):
    """Одноразовый запрос к модели"""
    if not check_ollama_available():
        print_colored("❌ OLLama сервер недоступен. Убедитесь, что он запущен.", Colors.RED)
        print_colored("   Запустите: ollama serve", Colors.YELLOW)
        return
    
    models = get_available_models()
    if not models:
        print_colored("❌ Нет доступных моделей", Colors.RED)
        return
    
    if model not in models:
        print_colored(f"❌ Модель '{model}' не найдена", Colors.RED)
        print_colored("Доступные модели:", Colors.YELLOW)
        for m in models:
            print_colored(f"  - {m}", Colors.CYAN)
        return
    
    print_colored(f"🤖 Модель: {model}", Colors.BOLD)
    print_colored(f"💬 Запрос: {prompt}\n", Colors.CYAN)
    print_colored("📝 Ответ:", Colors.BOLD)
    
    messages = [{"role": "user", "content": prompt}]
    chat_with_model(model, messages, stream=True)
    print()


def main():
    parser = argparse.ArgumentParser(
        description='CLI агент для работы с моделями OLLama',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Интерактивный режим с моделью по умолчанию
  python ollama_cli.py
  
  # Интерактивный режим с конкретной моделью
  python ollama_cli.py -m qwen2.5:7b
  
  # Одноразовый запрос
  python ollama_cli.py -m qwen2.5:7b -p "Привет! Расскажи о себе"
  
  # Показать список моделей
  python ollama_cli.py --list-models
        """
    )
    
    parser.add_argument(
        '-m', '--model',
        type=str,
        help='Название модели для использования (по умолчанию: qwen2.5:7b)'
    )
    
    parser.add_argument(
        '-p', '--prompt',
        type=str,
        help='Одноразовый запрос к модели (не запускает интерактивный режим)'
    )
    
    parser.add_argument(
        '--list-models',
        action='store_true',
        help='Показать список доступных моделей и выйти'
    )
    
    parser.add_argument(
        '--api-url',
        type=str,
        default=None,
        help=f'URL OLLama API (по умолчанию: {OLLAMA_API_URL})'
    )
    
    args = parser.parse_args()
    
    # Обновляем URL API, если указан
    global OLLAMA_API_BASE
    if args.api_url:
        OLLAMA_API_BASE = f"{args.api_url}/api"
    
    # Показываем список моделей и выходим
    if args.list_models:
        show_models()
        return
    
    # Проверяем доступность OLLama
    if not check_ollama_available():
        print_colored("❌ OLLama сервер недоступен", Colors.RED)
        print_colored("   Убедитесь, что OLLama запущен: ollama serve", Colors.YELLOW)
        sys.exit(1)
    
    # Определяем модель по умолчанию
    default_model = args.model or 'qwen2.5:7b'
    
    # Если указан промпт, делаем одноразовый запрос
    if args.prompt:
        single_query(default_model, args.prompt)
    else:
        # Иначе запускаем интерактивный режим
        interactive_mode(default_model)


if __name__ == '__main__':
    main()
