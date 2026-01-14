#!/usr/bin/env python3
"""Скрипт для автоматического ревью Pull Requests с использованием RAG и MCP Git"""
import argparse
import asyncio
import logging
import os
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
        
        # Публикуем комментарий в PR
        logger.info("Публикую комментарий в PR...")
        success = await post_review_comment(github, repo_name, args.pr_number, review_text)
        
        if success:
            logger.info("✅ Ревью успешно завершено и опубликовано")
        else:
            logger.error("❌ Не удалось опубликовать ревью")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
