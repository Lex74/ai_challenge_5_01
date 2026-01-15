"""Локальный MCP-адаптер для CRM JSON."""
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from config import CRM_DATA_PATH

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения информации об ошибке
_last_crm_error: Optional[Tuple[str, str]] = None


def get_crm_last_error() -> Optional[Tuple[str, str]]:
    """Возвращает последнюю ошибку CRM клиента."""
    return _last_crm_error


def _set_crm_last_error(error_type: Optional[str], error_msg: Optional[str]) -> None:
    """Устанавливает последнюю ошибку CRM клиента."""
    global _last_crm_error
    _last_crm_error = (error_type, error_msg) if error_type and error_msg else None


def load_crm_data() -> Optional[Dict[str, Any]]:
    """Загружает CRM JSON из файла."""
    if not os.path.exists(CRM_DATA_PATH):
        error_msg = f"CRM JSON не найден: {CRM_DATA_PATH}"
        _set_crm_last_error("FILE_NOT_FOUND", error_msg)
        logger.error(error_msg)
        return None

    try:
        with open(CRM_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _set_crm_last_error(None, None)
        return data
    except json.JSONDecodeError as e:
        error_msg = f"Ошибка парсинга CRM JSON: {e}"
        _set_crm_last_error("JSON_PARSE_ERROR", error_msg)
        logger.error(error_msg, exc_info=True)
        return None
    except Exception as e:
        error_msg = f"Ошибка чтения CRM JSON: {e}"
        _set_crm_last_error("READ_ERROR", error_msg)
        logger.error(error_msg, exc_info=True)
        return None


def get_ticket_by_id(ticket_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает тикет по ID."""
    data = load_crm_data()
    if not data:
        return None

    for ticket in data.get("tickets", []):
        if ticket.get("id") == ticket_id:
            return ticket
    return None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает пользователя по ID."""
    data = load_crm_data()
    if not data:
        return None

    for user in data.get("users", []):
        if user.get("id") == user_id:
            return user
    return None


def _filter_tickets(
    tickets: List[Dict[str, Any]],
    status: Optional[str],
    user_id: Optional[str],
    tag: Optional[str],
) -> List[Dict[str, Any]]:
    filtered = []
    for ticket in tickets:
        if status and ticket.get("status") != status:
            continue
        if user_id and ticket.get("user_id") != user_id:
            continue
        if tag:
            tags = ticket.get("tags") or []
            if tag not in tags:
                continue
        filtered.append(ticket)
    return filtered


async def list_crm_tools() -> List[Dict[str, Any]]:
    """Возвращает список доступных CRM инструментов (MCP-формат)."""
    return [
        {
            "name": "get_ticket",
            "description": "Получить тикет по ID из CRM JSON.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "ID тикета (например: t-501).",
                    }
                },
                "required": ["ticket_id"],
            },
        },
        {
            "name": "get_user",
            "description": "Получить пользователя по ID из CRM JSON.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "ID пользователя (например: u-1001).",
                    }
                },
                "required": ["user_id"],
            },
        },
        {
            "name": "list_tickets",
            "description": "Список тикетов с фильтрами по статусу/пользователю/тегу.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Фильтр по статусу (open/pending/closed).",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Фильтр по ID пользователя.",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Фильтр по тегу.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Ограничение количества результатов.",
                    },
                },
                "required": [],
            },
        },
    ]


async def call_crm_tool(name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Вызывает CRM инструмент и возвращает JSON-строку результата."""
    data = load_crm_data()
    if not data:
        return None

    try:
        if name == "get_ticket":
            ticket_id = arguments.get("ticket_id")
            ticket = get_ticket_by_id(ticket_id) if ticket_id else None
            return json.dumps(ticket, ensure_ascii=False) if ticket else None
        if name == "get_user":
            user_id = arguments.get("user_id")
            user = get_user_by_id(user_id) if user_id else None
            return json.dumps(user, ensure_ascii=False) if user else None
        if name == "list_tickets":
            status = arguments.get("status")
            user_id = arguments.get("user_id")
            tag = arguments.get("tag")
            limit = arguments.get("limit")
            tickets = data.get("tickets", [])
            filtered = _filter_tickets(tickets, status, user_id, tag)
            if isinstance(limit, int) and limit > 0:
                filtered = filtered[:limit]
            return json.dumps(filtered, ensure_ascii=False)

        _set_crm_last_error("UNKNOWN_TOOL", f"Неизвестный инструмент: {name}")
        return None
    except Exception as e:
        error_msg = f"Ошибка при выполнении CRM инструмента {name}: {e}"
        _set_crm_last_error("CALL_ERROR", error_msg)
        logger.error(error_msg, exc_info=True)
        return None
