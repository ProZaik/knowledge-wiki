#!/usr/bin/env python3
"""
Миграция файлов из archive_v1/sources/ в новую структуру MCP.

Читает каждый .md файл, определяет тип документа, извлекает метаданные,
и вызывает соответствующую функцию ingest_* из mcp_server.py.
"""
import sys
import os
import io
import re
import yaml

# Фикс кодировки Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mcp_server import ingest_letter, ingest_court_decision, ingest_article, ingest_law

ARCHIVE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "archive_v1", "sources"
)

# Уже загруженные тестовые файлы — пропускаем
SKIP_FILES = {
    "rosreestr-2026-05-10-14-5100.md",  # тестовый
}


def detect_type(filename: str, meta: dict, content: str) -> str:
    """Определяет тип документа по имени файла, метаданным и содержимому."""
    fn = filename.lower()
    title = (meta.get("title") or "").lower()

    # Судебные акты
    if fn.startswith("a47-") or fn.startswith("vs-") or fn.startswith("ks-rf"):
        return "court"
    if "определение" in title or "постановление кс" in title or "дело №" in title:
        return "court"

    # Нормативные акты
    if "федеральный закон" in title or "фз" in fn[:5]:
        return "law"

    # Письма органов (Росреестр, Минстрой, НОСТРОЙ и т.д.)
    if fn.startswith("rosreestr-") and any(c.isdigit() for c in fn[:20]):
        return "letter"
    if fn.startswith("minstroy-"):
        return "letter"
    if "письмо" in title:
        return "letter"

    # Обзорные/справочные материалы Росреестра без номера — как статьи
    if fn.startswith("rosreestr-") and not any(c.isdigit() for c in fn.split("-")[1][:4]):
        return "article"

    # Статьи
    if fn.startswith("pravo-ru") or fn.startswith("landlawfirm") or fn.startswith("urtmag"):
        return "article"
    if fn.startswith("ftl-") or fn.startswith("osint-") or fn.startswith("rg-"):
        return "article"

    # НОСТРОЙ, КИ — справочные
    if fn.startswith("nostroy-") or fn.startswith("ki-"):
        return "article"

    return "article"  # По умолчанию


def extract_date(meta: dict) -> str:
    """Извлекает дату из метаданных."""
    d = meta.get("date") or meta.get("date_adopted") or ""
    return str(d).strip() if d else "2026-01-01"


def extract_number(meta: dict, filename: str) -> str:
    """Извлекает номер документа."""
    n = meta.get("number") or meta.get("case_number") or meta.get("law_number") or ""
    if n:
        return str(n).strip()
    # Пытаемся извлечь из имени файла
    m = re.search(r'(\d{2,}-\d+.*?)\.md$', filename)
    return m.group(1) if m else ""


def extract_author(meta: dict, filename: str) -> str:
    """Определяет автора/орган."""
    fn = filename.lower()
    if fn.startswith("rosreestr"):
        return "Росреестр"
    if fn.startswith("minstroy"):
        return "Минстрой России"
    if fn.startswith("nostroy"):
        return "НОСТРОЙ"
    if fn.startswith("ks-rf"):
        return "Конституционный Суд РФ"
    if fn.startswith("a47") or fn.startswith("vs-"):
        return "Арбитражный суд"
    return meta.get("author", "")


def split_content(content: str) -> tuple[str, str]:
    """Разделяет файл на full_text (без YAML) и возвращает (body, summary)."""
    # Убираем YAML frontmatter
    body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, count=1, flags=re.DOTALL)
    # summary из meta
    return body.strip(), ""


def migrate_file(filepath: str, filename: str) -> dict:
    """Мигрирует один файл."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Парсим YAML
    meta = {}
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except Exception:
            meta = {}

    title = meta.get("title", filename[:-3].replace("-", " ").capitalize())
    tags = meta.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    related = meta.get("related_topics", [])
    if isinstance(related, list):
        # Нормализуем пути: добавляем topics/ если нет
        related = [f"topics/{r}" if not r.startswith("topics/") else r for r in related]
    else:
        related = []
    source_url = meta.get("source_url", "")

    body, _ = split_content(content)
    doc_type = detect_type(filename, meta, body)
    date = extract_date(meta)
    number = extract_number(meta, filename)
    author = extract_author(meta, filename)
    out_filename = filename[:-3]  # без .md

    # Генерируем выводы из summary или первых строк
    summary = meta.get("summary", "")

    if doc_type == "letter":
        return ingest_letter(
            filename=out_filename,
            title=str(title),
            number=number or "б/н",
            date=date,
            author_org=author,
            full_text=body,
            key_conclusions=[summary.strip()] if summary else ["См. полный текст"],
            practical_significance=summary.strip() if summary else "См. полный текст документа",
            tags=tags,
            source_url=source_url,
            related_topics=related,
        )

    elif doc_type == "court":
        court = author or "Суд не указан"
        return ingest_court_decision(
            filename=out_filename,
            title=str(title),
            case_number=number or meta.get("case_number", "не указан"),
            court=court,
            date=date,
            fabula=summary.strip() if summary else "См. полный текст",
            full_text=body,
            court_position=summary.strip() if summary else "См. полный текст",
            practical_conclusions=[summary.strip()] if summary else ["См. полный текст"],
            tags=tags,
            source_url=source_url,
            related_topics=related,
        )

    elif doc_type == "law":
        return ingest_law(
            filename=out_filename,
            title=str(title),
            law_number=number or meta.get("law_number", "не указан"),
            date_adopted=date,
            full_text=body,
            what_changes=summary.strip() if summary else "См. полный текст",
            commentary=summary.strip() if summary else "См. полный текст",
            tags=tags,
            source_url=source_url,
        )

    else:  # article
        return ingest_article(
            filename=out_filename,
            title=str(title),
            author=author or meta.get("author", "не указан"),
            source_name=meta.get("source_name", meta.get("source", "не указан")),
            full_text=body,
            key_theses=[summary.strip()] if summary else ["См. полный текст"],
            tags=tags,
            source_url=source_url,
            related_topics=related,
        )


def main():
    if not os.path.isdir(ARCHIVE_DIR):
        print(f"❌ Каталог архива не найден: {ARCHIVE_DIR}")
        return

    files = sorted(f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".md"))
    # Исключаем уже существующие в новой структуре
    new_sources_dir = os.path.join(os.path.dirname(ARCHIVE_DIR).replace("archive_v1", ""), "sources")
    existing = set()
    if os.path.isdir(new_sources_dir):
        existing = set(os.listdir(new_sources_dir))

    print(f"{'=' * 60}")
    print(f"  МИГРАЦИЯ archive_v1 → MCP")
    print(f"  Найдено файлов: {len(files)}")
    print(f"  Уже существует: {len(existing & set(files))}")
    print(f"{'=' * 60}\n")

    ok = 0
    fail = 0
    skipped = 0

    for fn in files:
        if fn in existing or fn in SKIP_FILES:
            print(f"  ⏭️  {fn} — уже существует, пропуск")
            skipped += 1
            continue

        filepath = os.path.join(ARCHIVE_DIR, fn)
        try:
            result = migrate_file(filepath, fn)
            success = result.get("success", False)
            if success:
                print(f"  ✅ {fn}")
                ok += 1
            else:
                err = result.get("error", "неизвестная ошибка")
                print(f"  ❌ {fn} — {err}")
                fail += 1
        except Exception as e:
            print(f"  ❌ {fn} — {e}")
            fail += 1

    print(f"\n{'=' * 60}")
    print(f"  ИТОГО: ✅ {ok} успешно | ❌ {fail} ошибок | ⏭️ {skipped} пропущено")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
