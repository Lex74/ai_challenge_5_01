#!/usr/bin/env python3
"""Скрипт для автоматического ревью Pull Requests с использованием RAG и MCP Git"""
import argparse
import asyncio
import logging
import os
import re
import sys
from typing import List, Dict, Any, Optional

from github import Github
from github.GithubException import GithubException

from config import GITHUB_TOKEN, GITHUB_REPOSITORY, OPENAI_API_KEY
from constants import PR_REVIEW_SYSTEM_PROMPT, DEFAULT_MODEL, DEFAULT_TEMPERATURE, MAX_TOKENS
from mcp_git_client import list_git_tools, call_git_tool
from rag import query_with_rag, format_chunks_for_context
from openai_client import query_openai

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

_REGEX_FLAGS = re.IGNORECASE | re.UNICODE

# Компилируем паттерны один раз для производительности
_CRITICAL_PATTERNS = [
    ("critical_phrase", re.compile(r"\bкритическ\w*\s+проблем\w*\b", _REGEX_FLAGS)),
    ("critical_word", re.compile(r"\bкритичн\w*\b", _REGEX_FLAGS)),
    ("critical_emoji", re.compile(r"⚠️\s*критическ\w*", _REGEX_FLAGS)),
    ("must_fix", re.compile(r"\bобязательно\s+исправить\b", _REGEX_FLAGS)),
    ("requires_fix", re.compile(r"\bтребует\s+исправлен\w*\b", _REGEX_FLAGS)),
    ("blocking", re.compile(r"\bблокир\w*\b", _REGEX_FLAGS)),
    ("security_en", re.compile(r"\bsecurity\b", _REGEX_FLAGS)),
    ("security_ru", re.compile(r"\bбезопасност\w*\b", _REGEX_FLAGS)),
    ("vulnerability", re.compile(r"\bуязвимост\w*\b", _REGEX_FLAGS)),
    ("bug", re.compile(r"\bbug\b", _REGEX_FLAGS)),
    ("exception", re.compile(r"\bexception\b", _REGEX_FLAGS)),
    ("crash", re.compile(r"\bcrash\b", _REGEX_FLAGS)),
]

_ISSUE_PATTERNS = [
    re.compile(r"\bпроблем\w*\b", _REGEX_FLAGS),
    re.compile(r"\bзамечан\w*\b", _REGEX_FLAGS),
    re.compile(r"\bулучшен\w*\b", _REGEX_FLAGS),
    re.compile(r"\bпредложен\w*\b", _REGEX_FLAGS),
    re.compile(r"⚠️", _REGEX_FLAGS),
    re.compile(r"❌", _REGEX_FLAGS),
]


async def get_pr_info(github: Github, repo_name: str, pr_number: int) -> Dict[str, Any]:
    """Получает информацию о PR через GitHub API"""
    try:
        repo = github.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        
        return {
            "title": pr.title,
            "body": pr.body or "",
            "number": pr.number,
            "base": pr.base.ref,
            "head": pr.head.ref,
            "base_sha": pr.base.sha,
            "head_sha": pr.head.sha,
            "user": pr.user.login,
            "state": pr.state,
            "files": [f.filename for f in pr.get_files()],
            "changed_files": pr.changed_files,
            "additions": pr.additions,
            "deletions": pr.deletions,
        }
    except GithubException as e:
        logger.error(f"Ошибка при получении информации о PR: {e}")
        raise


async def get_pr_diff_via_mcp(base: str, head: str) -> Optional[str]:
    """Получает diff PR через MCP Git"""
    try:
        logger.info(f"Получаю diff через MCP Git: base={base}, head={head}")
        result = await call_git_tool("get_pr_diff", {"base": base, "head": head})
        if result:
            logger.info(f"Получен diff длиной {len(result)} символов")
            return result
        else:
            logger.warning("MCP Git не вернул diff")
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении diff через MCP Git: {e}", exc_info=True)
        return None


async def get_pr_files_via_mcp(base: str, head: str) -> List[str]:
    """Получает список измененных файлов через MCP Git"""
    try:
        logger.info(f"Получаю список файлов через MCP Git: base={base}, head={head}")
        result = await call_git_tool("get_pr_files", {"base": base, "head": head})
        if result:
            # Парсим результат (формат: "Измененные файлы между ... (N файлов):\n\n  - file1\n  - file2\n")
            lines = result.split('\n')
            files = []
            for line in lines:
                line = line.strip()
                if line.startswith('- '):
                    files.append(line[2:])  # Убираем "- "
            logger.info(f"Найдено {len(files)} измененных файлов")
            return files
        else:
            logger.warning("MCP Git не вернул список файлов")
            return []
    except Exception as e:
        logger.error(f"Ошибка при получении списка файлов через MCP Git: {e}", exc_info=True)
        return []


async def get_rag_context(pr_info: Dict[str, Any], changed_files: List[str]) -> str:
    """Получает релевантный контекст через RAG на основе изменений в PR"""
    try:
        # Формируем запрос для RAG на основе измененных файлов и описания PR
        query_parts = []
        
        if pr_info.get("title"):
            query_parts.append(f"PR: {pr_info['title']}")
        if pr_info.get("body"):
            query_parts.append(f"Описание: {pr_info['body'][:200]}")  # Первые 200 символов
        
        if changed_files:
            query_parts.append(f"Измененные файлы: {', '.join(changed_files[:10])}")  # Первые 10 файлов
        
        query = " ".join(query_parts)
        if not query:
            query = "Изменения в коде проекта"
        
        logger.info(f"Ищу контекст через RAG для запроса: {query[:100]}...")
        
        # Используем RAG для поиска релевантной документации
        answer, history, sources = await query_with_rag(
            question=query,
            conversation_history=[],
            system_prompt="Ты помощник, который находит релевантную документацию и код для анализа изменений.",
            temperature=0.2,
            model=DEFAULT_MODEL,
            max_tokens=2000,
            bot=None,
            tools=None,
            top_k=5,
            index_path=None,
            relevance_threshold=0.2,
            rerank_method="similarity",
            use_filter=True
        )
        
        # Форматируем контекст из источников
        if sources:
            context_parts = ["Релевантная документация и код из проекта:"]
            for i, source in enumerate(sources[:5], 1):  # Берем топ-5 источников
                context_parts.append(f"\n[Источник {i} из {source.get('source_file', 'unknown')}]:")
                context_parts.append(source.get('text', '')[:500])  # Первые 500 символов
            return "\n".join(context_parts)
        else:
            logger.info("RAG не нашел релевантного контекста")
            return ""
    except Exception as e:
        logger.error(f"Ошибка при получении контекста через RAG: {e}", exc_info=True)
        return ""


async def generate_review(
    pr_info: Dict[str, Any],
    diff: str,
    rag_context: str
) -> str:
    """Генерирует ревью PR через OpenAI API"""
    try:
        # Формируем промпт для ревью
        review_prompt_parts = [
            f"Проведи ревью следующего Pull Request:\n\n",
            f"**Заголовок PR:** {pr_info.get('title', 'N/A')}\n",
            f"**Описание PR:** {pr_info.get('body', 'Нет описания')}\n",
            f"**Автор:** {pr_info.get('user', 'N/A')}\n",
            f"**Статистика:** +{pr_info.get('additions', 0)} / -{pr_info.get('deletions', 0)} строк, "
            f"{pr_info.get('changed_files', 0)} файлов изменено\n",
        ]
        
        if rag_context:
            review_prompt_parts.append(f"\n**Контекст из документации проекта:**\n{rag_context}\n")
        
        review_prompt_parts.append(f"\n**Изменения в коде (diff):**\n```\n{diff}\n```\n")
        review_prompt_parts.append(
            "\nПроведи детальный анализ изменений согласно инструкциям в системном промпте. "
            "Укажи конкретные проблемы, предложения по улучшению и положительные моменты."
        )
        
        review_prompt = "".join(review_prompt_parts)
        
        logger.info("Генерирую ревью через OpenAI...")
        
        # Генерируем ревью
        answer, history = await query_openai(
            question=review_prompt,
            conversation_history=[],
            system_prompt=PR_REVIEW_SYSTEM_PROMPT,
            temperature=DEFAULT_TEMPERATURE,
            model=DEFAULT_MODEL,
            max_tokens=MAX_TOKENS * 3,  # Увеличиваем лимит для детального ревью
            bot=None,
            tools=None
        )
        
        logger.info(f"Ревью сгенерировано, длина: {len(answer)} символов")
        return answer
        
    except Exception as e:
        logger.error(f"Ошибка при генерации ревью: {e}", exc_info=True)
        raise


def analyze_review_for_critical_issues(review_text: str) -> Dict[str, Any]:
    """Анализирует ревью на наличие критических проблем
    
    Returns:
        dict с ключами:
        - has_critical_issues: bool - есть ли критические проблемы
        - has_issues: bool - есть ли любые проблемы
        - critical_count: int - количество критических проблем
    """
    if review_text is None:
        return {
            "has_critical_issues": False,
            "has_issues": False,
            "critical_count": 0
        }
    if not isinstance(review_text, str):
        review_text = str(review_text)
    if not review_text:
        return {
            "has_critical_issues": False,
            "has_issues": False,
            "critical_count": 0
        }
    
    # Ищем индикаторы критических проблем (regex для точности и нормализации)
    has_critical = any(pattern.search(review_text) for _, pattern in _CRITICAL_PATTERNS)
    has_issues = any(pattern.search(review_text) for pattern in _ISSUE_PATTERNS)
    
    # Подсчитываем количество уникальных категорий критических проблем
    matched_categories = {name for name, pattern in _CRITICAL_PATTERNS if pattern.search(review_text)}
    critical_count = len(matched_categories)
    
    # Проверяем наличие раздела "Критические проблемы"
    if "## ⚠️ критические проблемы" in review_text or "## ⚠️ Критические проблемы" in review_text:
        has_critical = True
        # Подсчитываем количество пунктов в разделе
        critical_section = ""
        if "## ⚠️ критические проблемы" in review_text:
            start = review_text.find("## ⚠️ критические проблемы")
        else:
            start = review_text.find("## ⚠️ Критические проблемы")
        
        if start != -1:
            # Берем текст до следующего раздела
            next_section = review_text.find("\n## ", start + 1)
            if next_section != -1:
                critical_section = review_text[start:next_section]
            else:
                critical_section = review_text[start:]
            
            # Подсчитываем количество пунктов (маркеры списка)
            critical_count = critical_section.count("- ") + critical_section.count("* ")
            if critical_count == 0:
                # Если секция есть, но списков нет, считаем минимум 1 проблему
                critical_count = 1
    
    return {
        "has_critical_issues": has_critical,
        "has_issues": has_issues,
        "critical_count": critical_count
    }


async def create_status_check(
    github: Github,
    repo_name: str,
    head_sha: str,
    state: str,
    description: str,
    context: str = "pr-review/ai-reviewer"
) -> bool:
    """Создает статус проверки (status check) для коммита
    
    Args:
        github: Экземпляр Github API
        repo_name: Имя репозитория (owner/repo)
        head_sha: SHA коммита
        state: Состояние (success, failure, error, pending)
        description: Описание статуса
        context: Контекст статуса (по умолчанию "pr-review/ai-reviewer")
    
    Returns:
        True если успешно, False в противном случае
    """
    try:
        if not repo_name or not head_sha:
            logger.error("repo_name или head_sha не указаны при создании статуса проверки")
            return False
        repo = github.get_repo(repo_name)
        repo.get_commit(head_sha).create_status(
            state=state,
            target_url="",
            description=description,
            context=context
        )
        logger.info(f"Статус проверки создан: {state} - {description}")
        return True
    except GithubException as e:
        status_code = getattr(e, "status", None)
        if status_code == 401:
            logger.error(
                "Нет авторизации для создания статуса проверки. "
                "Проверьте GITHUB_TOKEN."
            )
        elif status_code == 403:
            logger.error(
                "Нет прав на создание статуса проверки. "
                "Проверьте permissions workflow и права GITHUB_TOKEN."
            )
        elif status_code == 404:
            logger.error(
                "Репозиторий или коммит не найден при создании статуса проверки. "
                "Проверьте repo_name и head_sha."
            )
        elif status_code == 422:
            logger.error(
                "Невалидные данные для статуса проверки. "
                "Проверьте state/description/context."
            )
        elif status_code == 429:
            logger.error("Слишком много запросов к GitHub API (rate limit).")
        else:
            logger.error(f"Ошибка при создании статуса проверки: {e}")
        return False
    except Exception as e:
        logger.error(f"Неожиданная ошибка при создании статуса проверки: {e}", exc_info=True)
        return False


async def create_pr_review(
    github: Github,
    repo_name: str,
    pr_number: int,
    review_text: str,
    event: str = "COMMENT"
) -> bool:
    """Создает PR review (approve/request changes/comment)
    
    Args:
        github: Экземпляр Github API
        repo_name: Имя репозитория (owner/repo)
        pr_number: Номер PR
        review_text: Текст ревью
        event: Тип ревью (APPROVE, REQUEST_CHANGES, COMMENT)
    
    Returns:
        True если успешно, False в противном случае
    """
    if not repo_name:
        logger.error("repo_name не указан при создании PR review")
        return False
    if not pr_number or not isinstance(pr_number, int) or pr_number <= 0:
        logger.error("Номер PR не указан при создании PR review")
        return False
    if event not in {"APPROVE", "REQUEST_CHANGES", "COMMENT"}:
        logger.error(f"Некорректный тип PR review: {event}")
        return False
    if not review_text:
        logger.warning("Пустой текст ревью при создании PR review")
        review_text = "Автоматическое ревью не содержит текста."

    try:
        repo = github.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        
        # Ограничиваем длину ревью для PR review (65536 символов)
        max_review_length = 60000
        if len(review_text) > max_review_length:
            review_text = review_text[:max_review_length] + "\n\n... (текст обрезан, полное ревью в комментариях)"
        
        pr.create_review(
            body=review_text,
            event=event
        )
        logger.info(f"PR review создан: {event}")
        return True
    except GithubException as e:
        logger.error(f"Ошибка при создании PR review: {e}")
        return False


async def post_review_comment(github: Github, repo_name: str, pr_number: int, review_text: str) -> bool:
    """Публикует комментарий с ревью в PR"""
    try:
        repo = github.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        
        # GitHub API имеет лимит на длину комментария (65536 символов)
        # Если ревью слишком длинное, разбиваем на части
        max_comment_length = 60000  # Оставляем запас
        
        if len(review_text) <= max_comment_length:
            pr.create_issue_comment(review_text)
            logger.info("Комментарий с ревью успешно опубликован")
            return True
        else:
            # Разбиваем на части
            parts = []
            current_part = ""
            
            # Разбиваем по разделам (по заголовкам ##)
            sections = review_text.split("\n## ")
            if len(sections) > 1:
                # Первый раздел без заголовка
                current_part = sections[0]
                for section in sections[1:]:
                    section_with_header = f"## {section}"
                    if len(current_part) + len(section_with_header) + 10 > max_comment_length:
                        parts.append(current_part)
                        current_part = section_with_header
                    else:
                        current_part += f"\n\n## {section}"
                if current_part:
                    parts.append(current_part)
            else:
                # Если нет разделов, разбиваем по абзацам
                paragraphs = review_text.split("\n\n")
                for para in paragraphs:
                    if len(current_part) + len(para) + 10 > max_comment_length:
                        if current_part:
                            parts.append(current_part)
                        current_part = para
                    else:
                        current_part += f"\n\n{para}" if current_part else para
                if current_part:
                    parts.append(current_part)
            
            # Публикуем части
            for i, part in enumerate(parts, 1):
                comment_text = f"## Часть {i} из {len(parts)}\n\n{part}"
                if i < len(parts):
                    comment_text += f"\n\n---\n*Продолжение следует...*"
                pr.create_issue_comment(comment_text)
                logger.info(f"Опубликована часть {i} из {len(parts)}")
            
            logger.info(f"Ревью разбито на {len(parts)} частей и опубликовано")
            return True
            
    except GithubException as e:
        logger.error(f"Ошибка при публикации комментария: {e}")
        return False


async def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description="Автоматическое ревью Pull Request")
    parser.add_argument("--pr-number", type=int, required=True, help="Номер PR")
    parser.add_argument("--repo", type=str, help="Репозиторий (owner/repo). Если не указан, используется GITHUB_REPOSITORY из env")
    parser.add_argument("--base", type=str, help="Base SHA коммита (опционально)")
    parser.add_argument("--head", type=str, help="Head SHA коммита (опционально)")
    parser.add_argument("--skip-rag", action="store_true", help="Пропустить поиск контекста через RAG")
    
    args = parser.parse_args()
    
    # Проверяем наличие токена
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN не установлен в переменных окружения")
        sys.exit(1)
    
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY не установлен в переменных окружения")
        sys.exit(1)
    
    # Определяем репозиторий
    repo_name = args.repo or GITHUB_REPOSITORY
    if not repo_name:
        logger.error("Репозиторий не указан. Используйте --repo или установите GITHUB_REPOSITORY")
        sys.exit(1)
    
    logger.info(f"Начинаю ревью PR #{args.pr_number} в репозитории {repo_name}")
    
    try:
        # Инициализируем GitHub API
        github = Github(GITHUB_TOKEN)
        
        # Получаем информацию о PR
        logger.info("Получаю информацию о PR...")
        pr_info = await get_pr_info(github, repo_name, args.pr_number)
        logger.info(f"PR: {pr_info['title']} ({pr_info['changed_files']} файлов изменено)")
        
        # Определяем base и head
        base = args.base or pr_info.get("base_sha") or pr_info.get("base", "main")
        head = args.head or pr_info.get("head_sha") or pr_info.get("head", "HEAD")
        
        # Получаем diff через MCP Git
        logger.info("Получаю diff изменений...")
        diff = await get_pr_diff_via_mcp(base, head)
        if not diff:
            logger.warning("Не удалось получить diff через MCP Git, пробую через GitHub API...")
            # Fallback: получаем diff через GitHub API
            repo = github.get_repo(repo_name)
            pr = repo.get_pull(args.pr_number)
            diff_parts = []
            for file in pr.get_files():
                diff_parts.append(f"--- {file.filename}\n+++ {file.filename}\n{file.patch or 'Нет изменений'}\n")
            diff = "\n".join(diff_parts)
        
        if not diff or len(diff.strip()) == 0:
            logger.error("Не удалось получить diff изменений")
            sys.exit(1)
        
        logger.info(f"Получен diff длиной {len(diff)} символов")
        
        # Получаем список измененных файлов
        changed_files = await get_pr_files_via_mcp(base, head)
        if not changed_files:
            changed_files = pr_info.get("files", [])
        
        # Получаем контекст через RAG (если не пропущен)
        rag_context = ""
        if not args.skip_rag:
            logger.info("Ищу релевантный контекст через RAG...")
            rag_context = await get_rag_context(pr_info, changed_files)
            if rag_context:
                logger.info(f"Найден контекст длиной {len(rag_context)} символов")
            else:
                logger.info("Контекст через RAG не найден")
        
        # Генерируем ревью
        logger.info("Генерирую ревью...")
        review_text = await generate_review(pr_info, diff, rag_context)
        
        # Анализируем ревью на наличие критических проблем
        logger.info("Анализирую ревью на наличие критических проблем...")
        analysis = analyze_review_for_critical_issues(review_text)
        
        # Определяем статус проверки и тип ревью
        if analysis["has_critical_issues"]:
            status_state = "failure"
            status_description = f"Найдено {analysis['critical_count']} критических проблем(ы)"
            review_event = "REQUEST_CHANGES"
            logger.warning(f"⚠️ Обнаружены критические проблемы: {analysis['critical_count']}")
        elif analysis["has_issues"]:
            status_state = "success"
            status_description = "Ревью завершено, есть замечания"
            review_event = "COMMENT"
            logger.info("ℹ️ Обнаружены замечания, но нет критических проблем")
        else:
            status_state = "success"
            status_description = "Ревью пройдено успешно"
            review_event = "APPROVE"
            logger.info("✅ Критических проблем не обнаружено")
        
        # Создаем статус проверки
        logger.info(f"Создаю статус проверки: {status_state}")
        await create_status_check(
            github,
            repo_name,
            pr_info["head_sha"],
            status_state,
            status_description
        )
        
        # Создаем PR review (approve/request changes/comment)
        logger.info(f"Создаю PR review: {review_event}")
        review_success = await create_pr_review(
            github,
            repo_name,
            args.pr_number,
            review_text,
            review_event
        )
        
        # Также публикуем комментарий для удобства просмотра
        logger.info("Публикую комментарий в PR...")
        comment_success = await post_review_comment(github, repo_name, args.pr_number, review_text)
        
        if review_success and comment_success:
            logger.info("✅ Ревью успешно завершено и опубликовано")
            if analysis["has_critical_issues"]:
                logger.warning(f"⚠️ PR требует изменений из-за {analysis['critical_count']} критических проблем")
        else:
            logger.error("❌ Не удалось опубликовать ревью полностью")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
