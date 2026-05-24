#!/usr/bin/env python3
"""
Knowledge Wiki MCP Server — универсальный MCP-сервер для базы знаний knowledge-wiki.
Поддерживает два транспорта:
1. stdio (для локальных ИИ-клиентов: Cursor, Claude Desktop, Cline)
2. SSE (для внешних подключений, например, облачного Perplexity на порту 8000)
"""

import os
import re
import sys
import argparse
import datetime
import yaml
from fastapi import FastAPI, Request
from starlette.routing import Mount
import uvicorn

# Определяем корень репозитория
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mcp_guards import sanitize_content, normalize_tags, validate_content_length, auto_git_commit
from mcp_templates import build_letter, build_court_decision, build_article, build_law, build_topic, build_flexible_topic
from migration_guard import migration_precheck

# Импортируем официальный SDK
try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.sse import SseServerTransport
except ImportError:
    print("[!] Ошибка: Не установлена библиотека mcp. Запустите 'pip install mcp fastapi uvicorn pyyaml'")
    sys.exit(1)

# Инициализируем FastMCP сервер
mcp = FastMCP("knowledge-wiki-mcp")

# ===========================================================================
# РЕСУРСЫ (Resources)
# ===========================================================================

@mcp.resource("file://INDEX.md")
def get_index_resource() -> str:
    """Главный индекс базы знаний (INDEX.md)."""
    with open(os.path.join(ROOT, "INDEX.md"), "r", encoding="utf-8") as f:
        return f.read()

@mcp.resource("file://tags-registry.md")
def get_tags_resource() -> str:
    """Реестр зарегистрированных тегов (tags-registry.md)."""
    with open(os.path.join(ROOT, "tags-registry.md"), "r", encoding="utf-8") as f:
        return f.read()

@mcp.resource("file://inbox/sources_to_ingest.md")
def get_inbox_resource() -> str:
    """Бэклог источников для импорта (Karpathy Ingestion workflow)."""
    path = os.path.join(ROOT, "inbox", "sources_to_ingest.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "Файл sources_to_ingest.md отсутствует."

# ===========================================================================
# ИНСТРУМЕНТЫ (Tools)
# ===========================================================================

@mcp.tool()
def get_wiki_stats() -> dict:
    """Получить общую статистику базы знаний (число доменов, тем, источников verified/draft, тегов)."""
    from wiki_tool import calculate_stats
    return calculate_stats()


@mcp.tool()
def run_diagnostics() -> dict:
    """Запустить полную проверку целостности вики с помощью линтера.
    Проверяет YAML-шапки, битые ссылки, tags-registry.md, ограничение вложенности.
    Возвращает отчет об ошибках (errors) и предупреждениях (warnings).
    """
    from wiki_lint import run_linter
    errors, warnings = run_linter(quiet=True)
    return {
        "is_valid": len(errors) == 0,
        "errors_count": len(errors),
        "warnings_count": len(warnings),
        "errors": errors,
        "warnings": warnings
    }


@mcp.tool()
def search_wiki(query: str) -> list[dict]:
    """Полнотекстовый поиск по всей базе знаний (включая темы, источники, индекс).
    Возвращает список совпавших файлов с фрагментами текста (snippet).
    """
    from wiki_tool import get_all_markdown_files
    
    results = []
    query_lower = query.lower()
    md_files = get_all_markdown_files(ROOT)
    
    for filepath in md_files:
        rel_path = os.path.relpath(filepath, ROOT).replace("\\", "/")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if query_lower in content.lower():
                idx = content.lower().find(query_lower)
                start = max(0, idx - 100)
                end = min(len(content), idx + len(query) + 100)
                snippet = content[start:end].strip().replace("\n", " ")
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content):
                    snippet = snippet + "..."
                    
                results.append({
                    "file": rel_path,
                    "snippet": snippet
                })
        except Exception:
            pass
            
    return results[:30]  # Лимит 30 совпадений


@mcp.tool()
def read_file(path: str) -> str:
    """Безопасное чтение любого markdown-файла базы знаний по его относительному пути (например, 'topics/zemelnoe-pravo/vri.md')."""
    normalized_path = os.path.normpath(path)
    if normalized_path.startswith("..") or os.path.isabs(normalized_path):
        return "Ошибка: Недопустимый путь к файлу. Путь должен быть относительным внутри репозитория."
        
    full_path = os.path.join(ROOT, normalized_path)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        return f"Ошибка: Файл '{path}' не найден."
        
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Ошибка при чтении файла: {e}"


def _post_write_pipeline(
    filename: str,
    title: str,
    doc_type: str,
    related_topics: list[str],
    tag_warnings: list[str]
) -> tuple[list[str], dict]:
    """Общий пайплайн после записи источника: связывание с темами, CHANGELOG, INDEX, линтер, git.

    Возвращает кортеж (link_reports, linter_results).
    """
    date_str = datetime.date.today().isoformat()
    link_reports: list[str] = []

    # 1. Связывание с темами
    if related_topics:
        for topic in related_topics:
            topic_path = os.path.join(ROOT, topic)
            if os.path.exists(topic_path):
                try:
                    with open(topic_path, "r", encoding="utf-8") as f:
                        topic_content = f.read()

                    source_rel_path = f"sources/{filename}"
                    if source_rel_path not in topic_content:
                        link_line = f"\n\n- [{title}]({source_rel_path})"

                        if "## Источники" in topic_content:
                            topic_content = topic_content.replace("## Источники", f"## Источники{link_line}")
                        elif "## Связанные источники" in topic_content:
                            topic_content = topic_content.replace("## Связанные источники", f"## Связанные источники{link_line}")
                        else:
                            topic_content += f"\n\n### Связанные источники{link_line}"

                        with open(topic_path, "w", encoding="utf-8", newline="\n") as f:
                            f.write(topic_content)
                        link_reports.append(f"Связан с темой {topic}")
                except Exception as e:
                    link_reports.append(f"Ошибка связывания с {topic}: {e}")
            else:
                link_reports.append(f"Тема не найдена: {topic}")

    # 2. Обновление CHANGELOG.md
    changelog_path = os.path.join(ROOT, "CHANGELOG.md")
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path, "r", encoding="utf-8") as f:
                changelog_content = f.read()

            new_entry = f"\n\n## [{date_str}]\n\n### Добавлено:\n- **Источник ({doc_type}):** [{title}](sources/{filename})\n"
            if related_topics:
                new_entry += "- **Обновлены темы:**\n"
                for topic in related_topics:
                    new_entry += f"  - [{os.path.basename(topic)}](file:///{topic})\n"

            if "# История изменений" in changelog_content:
                parts = changelog_content.split("# История изменений", 1)
                if "## [" in parts[1]:
                    subparts = parts[1].split("## [", 1)
                    updated_changelog = parts[0] + "# История изменений" + subparts[0] + new_entry.strip() + "\n\n## [" + subparts[1]
                else:
                    updated_changelog = changelog_content + new_entry
            else:
                updated_changelog = changelog_content + new_entry

            with open(changelog_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(updated_changelog)
            link_reports.append("CHANGELOG.md обновлен")
        except Exception as e:
            link_reports.append(f"Ошибка обновления CHANGELOG.md: {e}")

    # 3. Обновление INDEX.md и статистики
    index_path = os.path.join(ROOT, "INDEX.md")
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_content = f.read()

            source_link = f"- [{title}](sources/{filename}) — добавлен {date_str}."
            if "## Источники" in index_content:
                parts = index_content.split("## Источники", 1)
                updated_index = parts[0] + "## Источники\n\n" + source_link + "\n" + parts[1].lstrip()
                with open(index_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(updated_index)

            from wiki_tool import update_index_stats
            update_index_stats()
            link_reports.append("INDEX.md обновлен и статистика пересчитана")
        except Exception as e:
            link_reports.append(f"Ошибка обновления INDEX.md: {e}")

    # 4. Запуск линтера
    from wiki_lint import run_linter
    errors, warnings = run_linter(quiet=True)

    # 5. Автоматический Git-коммит
    committed_files = [f"sources/{filename}"]
    if related_topics:
        committed_files.extend(related_topics)
    committed_files.extend(["CHANGELOG.md", "INDEX.md", "_sidebar.md"])
    git_result = auto_git_commit(ROOT, committed_files, f"[MCP] Импорт {doc_type}: {title}")
    link_reports.append(f"Git: {git_result.get('output', git_result.get('error', 'неизвестно'))}")

    if tag_warnings:
        link_reports.append(f"Теги нормализованы: {'; '.join(tag_warnings)}")

    linter_results = {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }
    return link_reports, linter_results


def _validate_and_prepare_source(
    filename: str,
    full_text: str,
    tags: list[str]
) -> tuple[str, str, list[str], list[str], str | None]:
    """Общая валидация для всех ingest-инструментов.

    Возвращает (filename, sanitized_text, validated_tags, tag_warnings, error_message).
    Если error_message не None — нужно прервать операцию.
    """
    if not filename.endswith(".md"):
        filename += ".md"

    sources_dir = os.path.join(ROOT, "sources")
    os.makedirs(sources_dir, exist_ok=True)

    filepath = os.path.join(sources_dir, filename)
    if os.path.exists(filepath):
        return filename, full_text, tags, [], f"Файл источника '{filename}' уже существует."

    # Санитайзер контента
    full_text = sanitize_content(full_text)

    # Валидация минимальной длины
    is_valid_len, len_error = validate_content_length(full_text, min_chars=200)
    if not is_valid_len:
        return filename, full_text, tags, [], len_error

    # Нормализация и валидация тегов
    from wiki_lint import load_allowed_tags
    allowed_tags = load_allowed_tags()
    tags, tag_warnings = normalize_tags(tags, allowed_tags)
    if not tags:
        return filename, full_text, tags, tag_warnings, (
            "Ни один из переданных тегов не удалось сопоставить с реестром tags-registry.md. "
            "Передайте корректные теги."
        )

    return filename, full_text, tags, tag_warnings, None


@mcp.tool()
def ingest_letter(
    filename: str,
    title: str,
    number: str,
    date: str,
    author_org: str,
    full_text: str,
    key_conclusions: list[str],
    practical_significance: str,
    tags: list[str],
    source_url: str = "",
    related_topics: list[str] = None
) -> dict:
    """Импорт письма органа власти (Росреестра, Минстроя, Минэнерго и др.).

    Модель ОБЯЗАНА заполнить все структурированные поля. Сервер сам соберёт
    качественный markdown по шаблону.

    ВАЖНО: В параметре full_text ОБЯЗАТЕЛЬНО передавать ПОЛНЫЙ текст без сокращений!
    """
    # Валидация
    filename, full_text, tags, tag_warnings, error = _validate_and_prepare_source(filename, full_text, tags)
    if error:
        return {"success": False, "error": error}

    # Сборка markdown через шаблон
    params = {
        "title": title,
        "number": number,
        "date": date,
        "author_org": author_org,
        "full_text": full_text,
        "key_conclusions": key_conclusions,
        "practical_significance": practical_significance,
        "tags": tags,
        "source_url": source_url,
        "related_topics": related_topics or [],
    }
    content = build_letter(params)

    # Запись файла
    filepath = os.path.join(ROOT, "sources", filename)
    try:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "error": f"Не удалось записать файл источника: {e}"}

    # Пост-обработка
    link_reports, linter_results = _post_write_pipeline(
        filename, title, "письмо органа", related_topics or [], tag_warnings
    )

    return {
        "success": linter_results["is_valid"],
        "imported_file": f"sources/{filename}",
        "logs": link_reports,
        "linter_results": linter_results
    }


@mcp.tool()
def ingest_court_decision(
    filename: str,
    title: str,
    case_number: str,
    court: str,
    date: str,
    fabula: str,
    full_text: str,
    court_position: str,
    practical_conclusions: list[str],
    tags: list[str],
    source_url: str = "",
    related_topics: list[str] = None
) -> dict:
    """Импорт судебного акта (решение, определение, постановление).

    Модель ОБЯЗАНА извлечь фабулу, позицию суда и практические выводы.

    ВАЖНО: В параметре full_text ОБЯЗАТЕЛЬНО передавать ПОЛНЫЙ текст без сокращений!
    """
    # Валидация
    filename, full_text, tags, tag_warnings, error = _validate_and_prepare_source(filename, full_text, tags)
    if error:
        return {"success": False, "error": error}

    # Сборка markdown через шаблон
    params = {
        "title": title,
        "case_number": case_number,
        "court": court,
        "date": date,
        "fabula": fabula,
        "full_text": full_text,
        "court_position": court_position,
        "practical_conclusions": practical_conclusions,
        "tags": tags,
        "source_url": source_url,
        "related_topics": related_topics or [],
    }
    content = build_court_decision(params)

    # Запись файла
    filepath = os.path.join(ROOT, "sources", filename)
    try:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "error": f"Не удалось записать файл источника: {e}"}

    # Пост-обработка
    link_reports, linter_results = _post_write_pipeline(
        filename, title, "судебный акт", related_topics or [], tag_warnings
    )

    return {
        "success": linter_results["is_valid"],
        "imported_file": f"sources/{filename}",
        "logs": link_reports,
        "linter_results": linter_results
    }


@mcp.tool()
def ingest_article(
    filename: str,
    title: str,
    author: str,
    source_name: str,
    full_text: str,
    key_theses: list[str],
    tags: list[str],
    source_url: str = "",
    related_topics: list[str] = None
) -> dict:
    """Импорт статьи, комментария, аналитического обзора.

    Модель ОБЯЗАНА выделить ключевые тезисы автора.

    ВАЖНО: В параметре full_text ОБЯЗАТЕЛЬНО передавать ПОЛНЫЙ текст без сокращений!
    """
    # Валидация
    filename, full_text, tags, tag_warnings, error = _validate_and_prepare_source(filename, full_text, tags)
    if error:
        return {"success": False, "error": error}

    # Сборка markdown через шаблон
    params = {
        "title": title,
        "author": author,
        "source_name": source_name,
        "full_text": full_text,
        "key_theses": key_theses,
        "tags": tags,
        "source_url": source_url,
        "related_topics": related_topics or [],
    }
    content = build_article(params)

    # Запись файла
    filepath = os.path.join(ROOT, "sources", filename)
    try:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "error": f"Не удалось записать файл источника: {e}"}

    # Пост-обработка
    link_reports, linter_results = _post_write_pipeline(
        filename, title, "статья", related_topics or [], tag_warnings
    )

    return {
        "success": linter_results["is_valid"],
        "imported_file": f"sources/{filename}",
        "logs": link_reports,
        "linter_results": linter_results
    }


@mcp.tool()
def ingest_law(
    filename: str,
    title: str,
    law_number: str,
    date_adopted: str,
    full_text: str,
    what_changes: str,
    commentary: str,
    tags: list[str],
    source_url: str = "",
    related_topics: list[str] = None
) -> dict:
    """Импорт нормативного акта (федеральный закон, постановление Правительства и др.).

    Модель ОБЯЗАНА описать что меняет закон и дать комментарий.

    ВАЖНО: В параметре full_text допускается извлечение релевантных статей, а не полный текст закона.
    """
    # Валидация
    filename, full_text, tags, tag_warnings, error = _validate_and_prepare_source(filename, full_text, tags)
    if error:
        return {"success": False, "error": error}

    # Сборка markdown через шаблон
    params = {
        "title": title,
        "law_number": law_number,
        "date_adopted": date_adopted,
        "full_text": full_text,
        "what_changes": what_changes,
        "commentary": commentary,
        "tags": tags,
        "source_url": source_url,
        "related_topics": related_topics or [],
    }
    content = build_law(params)

    # Запись файла
    filepath = os.path.join(ROOT, "sources", filename)
    try:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "error": f"Не удалось записать файл источника: {e}"}

    # Пост-обработка
    link_reports, linter_results = _post_write_pipeline(
        filename, title, "нормативный акт", related_topics or [], tag_warnings
    )

    return {
        "success": linter_results["is_valid"],
        "imported_file": f"sources/{filename}",
        "logs": link_reports,
        "linter_results": linter_results
    }


@mcp.tool()
def update_topic(
    topic_path: str,
    title: str,
    normativnaya_osnova: str,
    klyuchevye_pozitsii: list[dict],
    prakticheskie_riski: str,
    svodnaya_tablitsa: list[dict],
    tags: list[str] = None,
    related_topics: list[str] = None
) -> dict:
    """Создать или обновить тему в папке topics/.

    Тема — это СИНТЕЗ из нескольких источников, а НЕ копия одного источника.

    Параметры:
    - topic_path: Относительный путь, например 'topics/zemelnoe-pravo/vri.md'
    - title: Название темы
    - normativnaya_osnova: Какие нормы регулируют этот институт
    - klyuchevye_pozitsii: Список позиций, каждая: {"tezis": "...", "istochnik": "...", "vyvod": "..."}
    - prakticheskie_riski: Что может пойти не так на практике
    - svodnaya_tablitsa: Список для сводки: {"istochnik": "...", "tip": "...", "klyuchevoy_vyvod": "..."}
    - tags: Теги
    - related_topics: Связанные темы
    """
    normalized_path = os.path.normpath(topic_path)
    if normalized_path.startswith("..") or os.path.isabs(normalized_path):
        return {"success": False, "error": "Недопустимый путь. Путь должен быть относительным внутри репозитория."}

    if not (normalized_path.startswith("topics" + os.sep) or normalized_path.startswith("topics/")):
        return {"success": False, "error": "Темы должны располагаться строго в папке 'topics/'."}

    parts = normalized_path.split(os.sep)
    if len(parts) > 3:
        return {"success": False, "error": "Превышена глубина вложенности! Допустимо максимум: topics/<домен>/<тема>.md"}

    full_path = os.path.join(ROOT, normalized_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # === ЗАЩИТА: Санитайзер текстовых полей ===
    normativnaya_osnova = sanitize_content(normativnaya_osnova)
    prakticheskie_riski = sanitize_content(prakticheskie_riski)

    # === ЗАЩИТА: Нормализация и валидация тегов ===
    tag_warnings = []
    if tags:
        from wiki_lint import load_allowed_tags
        allowed_tags = load_allowed_tags()
        tags, tag_warnings = normalize_tags(tags, allowed_tags)

    date_str = datetime.date.today().isoformat()

    # Сохраняем date_added из существующего файла
    date_added = date_str
    existing_meta = None
    if os.path.exists(full_path):
        from wiki_tool import parse_yaml_front
        existing_meta = parse_yaml_front(full_path)
        if existing_meta and "date_added" in existing_meta:
            date_added = existing_meta["date_added"]

    # Формируем итоговые теги (приоритет: переданные > существующие > пустой список)
    final_tags = tags if tags else (existing_meta.get("tags", []) if existing_meta else [])
    final_related = related_topics if related_topics else (existing_meta.get("related_topics", []) if existing_meta else [])

    # Сборка markdown через шаблон
    template_params = {
        "title": title,
        "normativnaya_osnova": normativnaya_osnova,
        "klyuchevye_pozitsii": klyuchevye_pozitsii,
        "prakticheskie_riski": prakticheskie_riski,
        "svodnaya_tablitsa": svodnaya_tablitsa,
        "tags": final_tags,
        "related_topics": final_related,
        "date_added": date_added,
        "date_updated": date_str,
    }
    full_content = build_topic(template_params)

    try:
        with open(full_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(full_content)
    except Exception as e:
        return {"success": False, "error": f"Не удалось записать тему: {e}"}

    link_reports = [f"Файл {normalized_path} успешно сохранен"]

    # Обновление INDEX.md
    index_path = os.path.join(ROOT, "INDEX.md")
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_content = f.read()

            topic_rel_path = normalized_path.replace("\\", "/")
            if topic_rel_path not in index_content:
                topic_link = f"- [{title}]({topic_rel_path}) — обзор правового института."
                if "## Темы" in index_content:
                    idx_parts = index_content.split("## Темы", 1)
                    updated_index = idx_parts[0] + "## Темы\n\n" + topic_link + "\n" + idx_parts[1].lstrip()
                    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(updated_index)

            from wiki_tool import update_index_stats
            update_index_stats()
            link_reports.append("INDEX.md обновлен и статистика пересчитана")
        except Exception as e:
            link_reports.append(f"Ошибка обновления INDEX.md: {e}")

    # Запуск линтера
    from wiki_lint import run_linter
    errors, warnings = run_linter(quiet=True)

    # Автоматический Git-коммит
    topic_rel_path = normalized_path.replace("\\", "/")
    git_result = auto_git_commit(ROOT, [topic_rel_path, "INDEX.md", "_sidebar.md"], f"[MCP] Обновление темы: {title}")
    link_reports.append(f"Git: {git_result.get('output', git_result.get('error', 'неизвестно'))}")

    if tag_warnings:
        link_reports.append(f"Теги нормализованы: {'; '.join(tag_warnings)}")

    return {
        "success": len(errors) == 0,
        "topic_file": topic_rel_path,
        "logs": link_reports,
        "linter_results": {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    }

@mcp.tool()
def migrate_topic(
    old_path: str,
    new_topic_path: str,
    title: str,
    normativnaya_osnova: str,
    klyuchevye_pozitsii: list[dict],
    prakticheskie_riski: str,
    svodnaya_tablitsa: list[dict],
    extra_sections: list[dict] = None,
    tags: list[str] = None,
    related_topics: list[str] = None,
    source_files: list[str] = None,
    force: bool = False
) -> dict:
    """Миграция темы из archive_v1 в новый формат с автоматическим пре-чеком.

    ОБЯЗАТЕЛЬНЫЙ WORKFLOW:
    1. Читает old_path (архивный файл) и извлекает юридические сущности
    2. Собирает новый контент через build_flexible_topic()
    3. Запускает migration_precheck() — сравнивает сущности old vs new
    4. Если coverage < 90% и force=False → ОТКЛОНЯЕТ с отчётом о пропусках
    5. При успехе: записывает файл, обновляет INDEX, запускает линтер, git commit

    ПРАВИЛА СИНТЕЗА (встроены в workflow):
    - Запрет на сокращение судебных дел до одной строки
    - Запрет на удаление таблиц и перечней
    - Запрет на обобщение числовых порогов

    Параметры:
    - old_path: путь к старому файлу (например, 'archive_v1/topics/gradostroitelstvo/gpzu.md')
    - new_topic_path: путь к новому файлу (например, 'topics/gradostroitelstvo/gpzu.md')
    - extra_sections: дополнительные секции [{"title": "...", "content": "...", "position": "after_osnova|after_pozitsii|after_riski|end"}]
    - source_files: список source-файлов, использованных при синтезе (для frontmatter)
    - force: пропустить пре-чек (использовать с осторожностью)
    """
    # === 1. Валидация путей ===
    normalized_new = os.path.normpath(new_topic_path)
    if normalized_new.startswith("..") or os.path.isabs(normalized_new):
        return {"success": False, "error": "Недопустимый путь new_topic_path. Должен быть относительным."}

    if not (normalized_new.startswith("topics" + os.sep) or normalized_new.startswith("topics/")):
        return {"success": False, "error": "Темы должны располагаться строго в папке 'topics/'."}

    parts = normalized_new.split(os.sep)
    if len(parts) > 3:
        return {"success": False, "error": "Превышена глубина вложенности! Допустимо: topics/<домен>/<тема>.md"}

    # Проверяем существование old_path
    old_full_path = os.path.join(ROOT, os.path.normpath(old_path))
    if not os.path.exists(old_full_path):
        return {"success": False, "error": f"Архивный файл не найден: {old_path}"}

    new_full_path = os.path.join(ROOT, normalized_new)
    os.makedirs(os.path.dirname(new_full_path), exist_ok=True)

    # === 2. Санитизация и нормализация тегов ===
    normativnaya_osnova = sanitize_content(normativnaya_osnova)
    prakticheskie_riski = sanitize_content(prakticheskie_riski)

    tag_warnings = []
    if tags:
        from wiki_lint import load_allowed_tags
        allowed_tags = load_allowed_tags()
        tags, tag_warnings = normalize_tags(tags, allowed_tags)

    date_str = datetime.date.today().isoformat()

    # Сохраняем date_added если файл уже существует
    date_added = date_str
    existing_meta = None
    if os.path.exists(new_full_path):
        from wiki_tool import parse_yaml_front
        existing_meta = parse_yaml_front(new_full_path)
        if existing_meta and "date_added" in existing_meta:
            date_added = existing_meta["date_added"]

    final_tags = tags if tags else (existing_meta.get("tags", []) if existing_meta else [])
    final_related = related_topics if related_topics else (existing_meta.get("related_topics", []) if existing_meta else [])

    # === 3. Сборка нового контента через гибкий шаблон ===
    template_params = {
        "title": title,
        "normativnaya_osnova": normativnaya_osnova,
        "klyuchevye_pozitsii": klyuchevye_pozitsii,
        "prakticheskie_riski": prakticheskie_riski,
        "svodnaya_tablitsa": svodnaya_tablitsa,
        "extra_sections": extra_sections or [],
        "tags": final_tags,
        "related_topics": final_related,
        "sources": source_files or [],
        "date_added": date_added,
        "date_updated": date_str,
    }
    full_content = build_flexible_topic(template_params)

    # === 4. ПРЕ-ЧЕК: сравнение сущностей old vs new ===
    precheck_result = migration_precheck(old_full_path, full_content)

    if not precheck_result["passed"] and not force:
        return {
            "success": False,
            "error": "Пре-чек миграции не пройден: покрытие сущностей ниже 90%.",
            "precheck": {
                "passed": False,
                "coverage_pct": precheck_result["coverage_pct"],
                "old_entities_count": precheck_result["old_entities_count"],
                "new_entities_count": precheck_result["new_entities_count"],
                "missing_entities": {k: list(v) for k, v in precheck_result["missing_entities"].items() if v},
                "report": precheck_result["report"],
            },
            "hint": "Добавьте недостающие сущности в контент или используйте force=True для принудительной записи."
        }

    # === 5. Запись файла ===
    try:
        with open(new_full_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(full_content)
    except Exception as e:
        return {"success": False, "error": f"Не удалось записать тему: {e}"}

    link_reports = [f"Файл {normalized_new} успешно мигрирован из {old_path}"]

    # === 6. Обновление INDEX.md ===
    index_path = os.path.join(ROOT, "INDEX.md")
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_content = f.read()

            topic_rel_path = normalized_new.replace("\\", "/")
            if topic_rel_path not in index_content:
                topic_link = f"- [{title}]({topic_rel_path}) — обзор правового института."
                if "## Темы" in index_content:
                    idx_parts = index_content.split("## Темы", 1)
                    updated_index = idx_parts[0] + "## Темы\n\n" + topic_link + "\n" + idx_parts[1].lstrip()
                    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(updated_index)

            from wiki_tool import update_index_stats
            update_index_stats()
            link_reports.append("INDEX.md обновлен")
        except Exception as e:
            link_reports.append(f"Ошибка обновления INDEX.md: {e}")

    # === 7. Линтер ===
    from wiki_lint import run_linter
    errors, warnings = run_linter(quiet=True)

    # === 8. Git-коммит ===
    topic_rel_path = normalized_new.replace("\\", "/")
    git_result = auto_git_commit(
        ROOT,
        [topic_rel_path, "INDEX.md", "_sidebar.md"],
        f"[MCP] Миграция темы: {title} (из {old_path})"
    )
    link_reports.append(f"Git: {git_result.get('output', git_result.get('error', 'неизвестно'))}")

    if tag_warnings:
        link_reports.append(f"Теги нормализованы: {'; '.join(tag_warnings)}")

    return {
        "success": len(errors) == 0,
        "topic_file": topic_rel_path,
        "precheck": {
            "passed": precheck_result["passed"],
            "coverage_pct": precheck_result["coverage_pct"],
            "old_entities_count": precheck_result["old_entities_count"],
            "new_entities_count": precheck_result["new_entities_count"],
            "missing_entities": {k: list(v) for k, v in precheck_result["missing_entities"].items() if v},
            "report": precheck_result["report"],
            "force_used": force,
        },
        "logs": link_reports,
        "linter_results": {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    }


# ===========================================================================
# ИНТЕГРАЦИЯ С SSE ТРАНСПОРТОМ
# ===========================================================================

app = FastAPI(title="knowledge-wiki-mcp")
sse = SseServerTransport("/messages/")

app.router.routes.append(Mount("/messages", app=sse.handle_post_message))

@app.get("/sse")
async def handle_sse(request: Request):
    """
    SSE Endpoint, по которому облачные клиенты (например, Perplexity) подключаются к серверу.
    """
    async with sse.connect_sse(
        request.scope, 
        request.receive, 
        request._send
    ) as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream, 
            write_stream, 
            mcp._mcp_server.create_initialization_options(),
        )

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "Knowledge Wiki MCP Server",
        "transports": {
            "stdio": "Доступен через прямую командную строку (по умолчанию)",
            "sse": "http://<ip>:8000/sse (POST-запросы на http://<ip>:8000/messages/)"
        }
    }

# ===========================================================================
# ТОЧКА ВХОДА (Main Launcher)
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Knowledge Wiki MCP Server Launcher")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="Тип транспорта (stdio или sse)")
    parser.add_argument("--port", type=int, default=8000, help="Порт для SSE сервера (по умолчанию 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Хост для SSE сервера (по умолчанию 0.0.0.0)")
    
    args = parser.parse_args()
    
    if args.transport == "sse":
        print("=" * 60)
        print(f" [OK] Запуск MCP-сервера в режиме SSE")
        print(f" Адрес SSE:  http://{args.host}:{args.port}/sse")
        print(f" Адрес сообщений: http://{args.host}:{args.port}/messages")
        print(f" Локальный статус: http://{args.host}:{args.port}/")
        print(" Для остановки нажмите Ctrl+C")
        print("=" * 60)
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        print("[MCP Server] Запуск в режиме stdio (для Cursor/Claude Desktop)...", file=sys.stderr)
        # Очищаем sys.argv, чтобы FastMCP.run() запустился корректно со stdio без конфликта флагов
        sys.argv = [sys.argv[0]]
        mcp.run()
