#!/usr/bin/env python3
import os
import shutil
import re
import yaml

# Определяем пути
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_DIR = os.path.join(ROOT, "sources")
TOPICS_DIR = os.path.join(ROOT, "topics")
INBOX_DIR = os.path.join(ROOT, "inbox")
ARCHIVE_DIR = os.path.join(ROOT, "archive_v1")

def parse_yaml_front(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.startswith("---"):
            return None, content
        parts = re.split(r'^---\s*$', content, maxsplit=2, flags=re.MULTILINE)
        if len(parts) >= 3:
            return yaml.safe_load(parts[1]), parts[2]
    except Exception:
        pass
    return None, ""

def main():
    print("=== Начало процесса архивации и очистки ===")

    # 1. Создаем директории архива
    archive_sources = os.path.join(ARCHIVE_DIR, "sources")
    archive_topics = os.path.join(ARCHIVE_DIR, "topics")
    os.makedirs(archive_sources, exist_ok=True)
    os.makedirs(archive_topics, exist_ok=True)
    print(f"Директории архива созданы: {ARCHIVE_DIR}")

    # 2. Копируем файлы в архив
    # Копируем sources
    for fn in os.listdir(SOURCES_DIR):
        if fn == ".gitkeep":
            continue
        src_path = os.path.join(SOURCES_DIR, fn)
        dest_path = os.path.join(archive_sources, fn)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, dest_path)

    # Копируем topics
    for item in os.listdir(TOPICS_DIR):
        item_path = os.path.join(TOPICS_DIR, item)
        if os.path.isdir(item_path):
            dest_subdir = os.path.join(archive_topics, item)
            os.makedirs(dest_subdir, exist_ok=True)
            for fn in os.listdir(item_path):
                file_path = os.path.join(item_path, fn)
                if os.path.isfile(file_path):
                    shutil.copy2(file_path, os.path.join(dest_subdir, fn))
    
    print("Все файлы успешно скопированы в архив archive_v1/")

    # 3. Собираем данные об источниках для backlog-файла
    backlog_entries = []
    sources_to_process = []
    
    for fn in sorted(os.listdir(SOURCES_DIR)):
        if not fn.endswith(".md") or fn.startswith(".") or fn == ".gitkeep":
            continue
        
        filepath = os.path.join(SOURCES_DIR, fn)
        meta, content = parse_yaml_front(filepath)
        
        title = meta.get("title", fn) if meta else fn
        url = meta.get("url", "") if meta else ""
        tags = meta.get("tags", []) if meta else []
        status = meta.get("status", "draft") if meta else "draft"
        
        # Если ссылки нет в YAML, попробуем поискать в контенте
        if not url and content:
            url_match = re.search(r'https?://[^\s)"]+', content)
            if url_match:
                url = url_match.group(0)

        sources_to_process.append({
            "filename": fn,
            "title": title,
            "url": url,
            "tags": tags,
            "status": status
        })

    # 4. Формируем inbox/sources_to_ingest.md
    backlog_path = os.path.join(INBOX_DIR, "sources_to_ingest.md")
    
    backlog_content = """# Бэклог источников для импорта (Karpathy Ingestion Workflow)

Этот файл содержит список всех источников, перенесённых в архив при очистке базы знаний. Вы можете использовать его для поэтапного, чистого и качественного импорта материалов в новую базу знаний.

> [!IMPORTANT]
> **ПРАВИЛО ИМПОРТА:** При импорте источника из этого бэклога обязательно сохраняйте его **полный текст** (full text) в создаваемом файле `sources/...`, а не просто делайте из него краткие обрезки или конспекты!

## Список источников для импорта

| Название источника | Теги | Ссылка на оригинал | Архивная копия |
| :--- | :--- | :--- | :--- |
"""

    for s in sources_to_process:
        url_link = f"[Ссылка]({s['url']})" if s['url'] else "—"
        tags_str = ", ".join([f"`{t}`" for t in s['tags']])
        archive_link = f"[Открыть](archive_v1/sources/{s['filename']})"
        backlog_content += f"| **{s['title']}** | {tags_str} | {url_link} | {archive_link} |\n"

    backlog_content += """
## Пошаговый процесс импорта:
1. Выберите источник из таблицы выше.
2. Откройте его локальную архивную копию по ссылке в столбце «Архивная копия».
3. Перейдите по ссылке на оригинал (если есть) для проверки актуальности.
4. Создайте новый файл в `sources/` (например, `sources/имя-источника.md`).
5. Скопируйте туда **полный текст** материала, оформив YAML-шапку по новым стандартам:
   ```yaml
   title: "Официальное название источника"
   type: "судебный акт" или "письмо органа" или "статья"
   status: "verified"
   date_added: YYYY-MM-DD
   tags: [теги-из-tags-registry]
   ```
6. В разделе `topics/` найдите или создайте связанные концептуальные темы. Интегрируйте туда ключевые выводы из источника, ссылаясь на него через стандартную markdown-ссылку `[Текст](sources/имя-источника.md)`.
7. Запустите `python scripts/wiki_tool.py --update-stats` для пересчёта статистики.
8. Запустите `python scripts/wiki_lint.py` для валидации.
9. Создайте коммит!
"""

    with open(backlog_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(backlog_content)
    print(f"Файл бэклога успешно создан: {backlog_path}")

    # 5. Очищаем папку sources/ (удаляем все md-файлы, оставляем .gitkeep)
    for fn in os.listdir(SOURCES_DIR):
        if fn == ".gitkeep":
            continue
        path = os.path.join(SOURCES_DIR, fn)
        if os.path.isfile(path):
            os.remove(path)
    print("Папка sources/ успешно очищена.")

    # 6. Очищаем папку topics/
    # Для каждого домена удаляем файлы, кроме _index.md и .gitkeep, а _index.md сбрасываем в чистый вид
    for item in os.listdir(TOPICS_DIR):
        item_path = os.path.join(TOPICS_DIR, item)
        if os.path.isdir(item_path):
            for fn in os.listdir(item_path):
                filepath = os.path.join(item_path, fn)
                if fn == "_index.md":
                    # Сбрасываем _index.md в чистый вид
                    meta, _ = parse_yaml_front(filepath)
                    title = meta.get("title", item.capitalize()) if meta else item.capitalize()
                    tags = meta.get("tags", []) if meta else []
                    tags_str = ", ".join(tags)
                    
                    clean_index_content = f"""---
title: "{title}"
type: тема
status: verified
date_added: 2026-05-22
tags: [{tags_str}]
---

# {title.split(" — ")[0]}

## Заметки в этой теме

*(Раздел пока не содержит заметок. Вы можете начать наполнение!)*
"""
                    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
                        f.write(clean_index_content)
                elif fn == ".gitkeep":
                    continue
                else:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
    print("Папка topics/ успешно очищена, файлы _index.md сброшены в чистый вид.")

    # 7. Очищаем корневой INDEX.md, оставляя только структуру доменов и пустую статистику
    index_path = os.path.join(ROOT, "INDEX.md")
    clean_index_content = """# Индекс базы знаний

> Обновляется при КАЖДОМ добавлении или обновлении файла.  
> Последнее обновление: 2026-05-22

---

## Темы (`topics/`)

### Градостроительство
*(Раздел пуст. Ожидает наполнения)*

### Земельное право
*(Раздел пуст. Ожидает наполнения)*

### Жилищное право
*(Раздел пуст. Ожидает наполнения)*

### СРО
*(Раздел пуст. Ожидает наполнения)*

---

## Источники (`sources/`)

### Статус verified
*(Раздел пуст. Ожидает наполнения)*

### Статус draft (требует ручной проверки)
*(Раздел пуст. Ожидает наполнения)*

---

## Все теги

*(Теги отсутствуют)*

> Полный реестр тегов с описаниями: [tags-registry.md](tags-registry.md)

---

## Статистика

- Всего файлов в базе: **0**
- Тем: **0 доменов, 0 тематических файлов**
- Источников verified: **0**
- Источников draft: **0**
- Тегов: **0**
"""
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(clean_index_content)
    print("Корневой INDEX.md успешно очищен.")
    print("=== Архивация и очистка завершены успешно! ===")

if __name__ == "__main__":
    main()
