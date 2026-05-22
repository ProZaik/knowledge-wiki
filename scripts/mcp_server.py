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


@mcp.tool()
def ingest_source(
    filename: str,
    title: str,
    full_text: str,
    tags: list[str],
    status: str = "draft",
    source_url: str = "",
    related_topics: list[str] = None
) -> dict:
    """Интеллектуальный импорт нового источника по правилам Andrej Karpathy Ingestion Workflow.
    Создает карточку в sources/, автоматически связывает её с указанными темами в topics/,
    обновляет CHANGELOG.md и INDEX.md, пересчитывает статистику и запускает линтер.
    
    ВАЖНО: В параметре full_text ОБЯЗАТЕЛЬНО передавать ПОЛНЫЙ оригинальный текст документа без сокращений!
    """
    if not filename.endswith(".md"):
        filename += ".md"
        
    sources_dir = os.path.join(ROOT, "sources")
    os.makedirs(sources_dir, exist_ok=True)
    
    filepath = os.path.join(sources_dir, filename)
    if os.path.exists(filepath):
        return {"success": False, "error": f"Файл источника '{filename}' уже существует."}
        
    # Валидация тегов
    from wiki_lint import load_allowed_tags
    allowed_tags = load_allowed_tags()
    invalid_tags = [t for t in tags if t not in allowed_tags]
    if invalid_tags:
        return {
            "success": False, 
            "error": f"Используются незарегистрированные теги: {', '.join(invalid_tags)}. Пожалуйста, сначала добавьте их в tags-registry.md."
        }
        
    date_str = datetime.date.today().isoformat()
    
    # Формируем YAML шапку
    frontmatter = {
        "title": title,
        "type": "судебный акт" if any(x in title.lower() for x in ["дело", "решение", "постановление"]) else "письмо органа",
        "status": status,
        "date_added": date_str,
        "tags": tags
    }
    if source_url:
        frontmatter["source_url"] = source_url
    if related_topics:
        frontmatter["related_topics"] = related_topics
        
    yaml_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
    content = f"---\n{yaml_str}---\n\n{full_text.strip()}\n"
    
    # 1. Запись источника
    try:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "error": f"Не удалось записать файл источника: {e}"}
        
    link_reports = []
    
    # 2. Связывание с темами
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
                
    # 3. Обновление CHANGELOG.md
    changelog_path = os.path.join(ROOT, "CHANGELOG.md")
    if os.path.exists(changelog_path):
        try:
            with open(changelog_path, "r", encoding="utf-8") as f:
                changelog_content = f.read()
            
            new_entry = f"\n\n## [{date_str}]\n\n### Добавлено:\n- **Источник:** [{title}](sources/{filename})\n"
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
            
    # 4. Обновление INDEX.md и статистики
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
            
    # 5. Запуск линтера
    from wiki_lint import run_linter
    errors, warnings = run_linter(quiet=True)
    
    return {
        "success": len(errors) == 0,
        "imported_file": f"sources/{filename}",
        "logs": link_reports,
        "linter_results": {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    }


@mcp.tool()
def update_topic(
    topic_path: str,
    title: str,
    content: str,
    tags: list[str] = None,
    related_topics: list[str] = None
) -> dict:
    """Создать или аккуратно обновить тему в папке `topics/`.
    Выполняет автоматическую проверку линтером и обновляет INDEX.md.
    
    Параметры:
    - topic_path: Относительный путь, например 'topics/zemelnoe-pravo/vri.md' (максимум 2 уровня вложенности).
    - title: Название темы.
    - content: Markdown контент.
    - tags: Список тегов.
    - related_topics: Список путей к связанным файлам.
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
    
    if tags:
        from wiki_lint import load_allowed_tags
        allowed_tags = load_allowed_tags()
        invalid_tags = [t for t in tags if t not in allowed_tags]
        if invalid_tags:
            return {
                "success": False, 
                "error": f"Используются незарегистрированные теги: {', '.join(invalid_tags)}. Пожалуйста, сначала добавьте их в tags-registry.md."
            }
            
    date_str = datetime.date.today().isoformat()
    
    # Сохраняем date_added
    date_added = date_str
    existing_meta = None
    if os.path.exists(full_path):
        from wiki_tool import parse_yaml_front
        existing_meta = parse_yaml_front(full_path)
        if existing_meta and "date_added" in existing_meta:
            date_added = existing_meta["date_added"]
            
    frontmatter = {
        "title": title,
        "type": "тема",
        "status": "verified",
        "date_added": date_added,
        "date_updated": date_str,
    }
    if tags:
        frontmatter["tags"] = tags
    elif existing_meta and "tags" in existing_meta:
        frontmatter["tags"] = existing_meta["tags"]
    else:
        frontmatter["tags"] = []
        
    if related_topics:
        frontmatter["related_topics"] = related_topics
    elif existing_meta and "related_topics" in existing_meta:
        frontmatter["related_topics"] = existing_meta["related_topics"]
        
    yaml_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # Очищаем контент от переданного frontmatter
    clean_content = content.strip()
    if clean_content.startswith("---"):
        split_parts = re.split(r'^---\s*$', clean_content, maxsplit=2, flags=re.MULTILINE)
        if len(split_parts) >= 3:
            clean_content = split_parts[2].strip()
            
    full_content = f"---\n{yaml_str}---\n\n{clean_content}\n"
    
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
                    parts = index_content.split("## Темы", 1)
                    updated_index = parts[0] + "## Темы\n\n" + topic_link + "\n" + parts[1].lstrip()
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
