#!/usr/bin/env python3
"""
REST API сервер для работы с моделями Ollama
Предназначен для использования мобильными клиентами
"""

import os
import json
import requests
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# URL OLLama API
OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://localhost:11434')
OLLAMA_API_BASE = f"{OLLAMA_API_URL}/api"

# Создаем FastAPI приложение
app = FastAPI(
    title="Ollama REST API",
    description="REST API для общения с моделями Ollama",
    version="1.0.0"
)

# Настройка CORS для мобильных клиентов
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене лучше указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic модели для запросов и ответов
class ChatMessage(BaseModel):
    role: str  # "user" или "assistant"
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: Optional[bool] = False


class ChatResponse(BaseModel):
    response: str
    model: str
    done: bool


class ModelInfo(BaseModel):
    name: str


class ModelsResponse(BaseModel):
    models: List[ModelInfo]


class HealthResponse(BaseModel):
    status: str
    ollama_available: bool


def check_ollama_available() -> bool:
    """Проверяет доступность Ollama сервера"""
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/tags", timeout=5)
        return response.status_code == 200
    except:
        return False


def get_available_models() -> List[str]:
    """Получает список доступных моделей"""
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/tags", timeout=5)
        response.raise_for_status()
        data = response.json()
        return [model['name'] for model in data.get('models', [])]
    except Exception as e:
        return []


def chat_with_model(model: str, messages: List[Dict[str, str]], stream: bool = False) -> Dict[str, Any]:
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
                            full_response += chunk
                        if data.get('done', False):
                            break
                    except json.JSONDecodeError:
                        continue
            return {
                "response": full_response,
                "model": model,
                "done": True
            }
        else:
            data = response.json()
            return {
                "response": data.get('message', {}).get('content', ''),
                "model": model,
                "done": data.get('done', False)
            }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при запросе к модели: {str(e)}")


@app.get("/", tags=["General"])
async def root():
    """Корневой endpoint"""
    return {
        "message": "Ollama REST API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "models": "/models",
            "chat": "/chat"
        }
    }


@app.get("/health", response_model=HealthResponse, tags=["General"])
async def health_check():
    """Проверка здоровья сервера и доступности Ollama"""
    ollama_available = check_ollama_available()
    return {
        "status": "ok" if ollama_available else "degraded",
        "ollama_available": ollama_available
    }


@app.get("/models", response_model=ModelsResponse, tags=["Models"])
async def list_models():
    """Получить список доступных моделей"""
    if not check_ollama_available():
        raise HTTPException(
            status_code=503,
            detail="Ollama сервер недоступен. Убедитесь, что он запущен."
        )
    
    models = get_available_models()
    if not models:
        raise HTTPException(
            status_code=404,
            detail="Нет доступных моделей"
        )
    
    return {
        "models": [{"name": model} for model in models]
    }


@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: ChatRequest):
    """Отправить сообщение в модель и получить ответ"""
    if not check_ollama_available():
        raise HTTPException(
            status_code=503,
            detail="Ollama сервер недоступен. Убедитесь, что он запущен."
        )
    
    # Проверяем, что модель существует
    available_models = get_available_models()
    if request.model not in available_models:
        raise HTTPException(
            status_code=404,
            detail=f"Модель '{request.model}' не найдена. Доступные модели: {', '.join(available_models)}"
        )
    
    # Преобразуем Pydantic модели в словари
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    
    # Отправляем запрос к модели
    result = chat_with_model(request.model, messages, stream=request.stream)
    
    return result


if __name__ == "__main__":
    import uvicorn
    
    # Получаем порт из переменной окружения или используем 8000 по умолчанию
    port = int(os.getenv("API_PORT", 8000))
    host = os.getenv("API_HOST", "0.0.0.0")  # 0.0.0.0 для доступа с других устройств
    
    print(f"🚀 Запуск Ollama REST API на http://{host}:{port}")
    print(f"📖 Документация: http://{host}:{port}/docs")
    print(f"🔍 Health check: http://{host}:{port}/health")
    
    uvicorn.run(app, host=host, port=port)
