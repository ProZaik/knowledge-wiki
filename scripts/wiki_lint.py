#!/usr/bin/env python3
"""
Wiki Lint — автоматическая проверка целостности knowledge-wiki.
Запускается через GitHub Action при каждом пуше.

Проверки:
1. YAML-шапка: обязательные поля (title, type, status, date_added, tags)
2. Теги: все теги из файлов должны быть в tags-registry.md
3. Ссылки: все внутренние ссылки (markdown + YAML related_topics) ведут на существующие файлы
4. Структура: topics/ — максимум 2 уровня вложенности
5. INDEX.md: все файлы из topics/ и sources/ упомянуты в индексе
"""

import os
import re
import sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


# ---------------------------------------------------------------------------
# 1. Загрузить допустимые теги из tags-registry.md
# ---------------------------------------------------------------------------
def load_allowed_tags():
    path = os.path.join(ROOT, "tags-registry.md")
    if not os.path.exists(path):
        err("tags-registry.md не найден в корне репозитория")
        return set()

    tags = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            # Ищем теги в первом столбце таблиц: | `тег` | описание |
            m = re.match(r'\|\s*`([^`]+)`\s*\|', line)
            if m:
                tags.add(m.group(1))
    return tags


# ---------------------------------------------------------------------------
# 2. Загрузить содержимое INDEX.md для проверки упоминаний
# ---------------------------------------------------------------------------
def load_index_content():
    path = os.path.join(ROOT, "INDEX.md")
    if not os.path.exists(path):
        err("INDEX.md не найден в корне репозитория")
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 3. Парсинг YAML-шапки из markdown-файла
# ---------------------------------------------------------------------------
def parse_yaml_front(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # YAML frontmatter: между первой и второй строкой ---
    if not content.startswith("---"):
        return None, content

    parts = re.split(r'^---\s*$', content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return None, content

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        err(f"{filepath}: невалидный YAML — {e}")
        return None, content

    return meta, content


# ---------------------------------------------------------------------------
# 4. Проверка YAML-шапки
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {"title", "type", "status", "date_added", "tags"}


def check_yaml(filepath, meta):
    rel = os.path.relpath(filepath, ROOT)
    if meta is None:
        err(f"{rel}: отсутствует YAML-шапка")
        return

    missing = REQUIRED_FIELDS - set(meta.keys())
    if missing:
        err(f"{rel}: YAML — не хватает полей: {', '.join(sorted(missing))}")

    if "status" in meta and meta["status"] not in ("draft", "verified", "needs-review", "archived"):
        err(f"{rel}: YAML — недопустимый статус '{meta['status']}'")


# ---------------------------------------------------------------------------
# 5. Проверка тегов
# ---------------------------------------------------------------------------
def check_tags(filepath, meta, allowed_tags):
    rel = os.path.relpath(filepath, ROOT)
    if meta is None or "tags" not in meta:
        return

    tags = meta["tags"]
    if not isinstance(tags, list):
        err(f"{rel}: YAML — tags должен быть списком")
        return

    for tag in tags:
        tag_str = str(tag).strip()
        if tag_str not in allowed_tags:
            err(f"{rel}: тег '{tag_str}' отсутствует в tags-registry.md")


# ---------------------------------------------------------------------------
# 6. Проверка внутренних ссылок (markdown + YAML related_topics)
# ---------------------------------------------------------------------------
LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')


def check_links(filepath, content, meta):
    rel = os.path.relpath(filepath, ROOT)

    # Markdown-ссылки внутри текста (не http)
    for match in LINK_RE.finditer(content):
        target = match.group(2).strip()
        if target.startswith("http") or target.startswith("#") or target.startswith("mailto:"):
            continue

        # Убираем якоря
        target_clean = target.split("#")[0]
        if not target_clean:
            continue

        # Docsify разрешает пути от корня репозитория
        full_path = os.path.join(ROOT, target_clean)
        if not os.path.exists(full_path):
            err(f"{rel}: битая ссылка -> {target_clean}")

    # YAML related_topics
    if meta and "related_topics" in meta and isinstance(meta["related_topics"], list):
        for rt in meta["related_topics"]:
            rt_str = str(rt).strip()
            full_path = os.path.join(ROOT, rt_str)
            if not os.path.exists(full_path):
                err(f"{rel}: YAML related_topics — битая ссылка -> {rt_str}")

    # YAML conflict_with
    if meta and "conflict_with" in meta:
        conflicts = meta["conflict_with"]
        if isinstance(conflicts, str):
            conflicts = [conflicts]
        if isinstance(conflicts, list):
            for c in conflicts:
                c_str = str(c).strip()
                if c_str:
                    full_path = os.path.join(ROOT, c_str)
                    if not os.path.exists(full_path):
                        warn(f"{rel}: YAML conflict_with — путь не найден: {c_str}")


# ---------------------------------------------------------------------------
# 7. Проверка глубины topics/
# ---------------------------------------------------------------------------
def check_depth():
    topics_dir = os.path.join(ROOT, "topics")
    if not os.path.exists(topics_dir):
        return

    for dirpath, dirnames, filenames in os.walk(topics_dir):
        # Глубина от topics/
        depth = os.path.relpath(dirpath, topics_dir).count(os.sep)
        # topics/<домен>/<тема>.md => depth домена = 0, файлы лежат на глубине 0
        # topics/<домен>/<подпапка>/ => depth = 1 — запрещено
        if depth >= 2:
            rel = os.path.relpath(dirpath, ROOT)
            err(f"{rel}: превышена глубина вложенности (максимум topics/<домен>/<тема>.md)")


# ---------------------------------------------------------------------------
# 8. Проверка INDEX.md — все файлы из topics/ и sources/ упомянуты
# ---------------------------------------------------------------------------
def check_index_coverage(index_content):
    if not index_content:
        return

    dirs_to_check = ["topics", "sources"]
    for d in dirs_to_check:
        full_dir = os.path.join(ROOT, d)
        if not os.path.exists(full_dir):
            continue
        for dirpath, _, filenames in os.walk(full_dir):
            for fn in filenames:
                if fn.startswith(".") or fn.startswith("_"):
                    continue
                if not fn.endswith(".md"):
                    continue

                rel_path = os.path.relpath(os.path.join(dirpath, fn), ROOT).replace("\\", "/")
                if rel_path not in index_content:
                    warn(f"{rel_path}: файл не упомянут в INDEX.md")


def run_linter(quiet=False):
    """
    Запускает полную проверку базы знаний.
    Возвращает кортеж (errors, warnings).
    """
    global errors, warnings
    errors.clear()
    warnings.clear()

    allowed_tags = load_allowed_tags()
    index_content = load_index_content()

    # 1. Проверяем наличие CHANGELOG.md в корне
    changelog_path = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.exists(changelog_path):
        err("CHANGELOG.md не найден в корне репозитория")

    # 2. Проверяем актуальность статистики в INDEX.md
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        from wiki_tool import check_index_stats
        if not quiet:
            print("Сверка статистики INDEX.md...")
        if not check_index_stats():
            err("INDEX.md: статистика в файле не соответствует реальным данным. Запустите 'python scripts/wiki_tool.py --update-stats'")
    except ImportError as e:
        err(f"Не удалось импортировать wiki_tool для сверки статистики: {e}")

    # Сканируем topics/ и sources/
    scan_dirs = ["topics", "sources", "inbox"]
    for d in scan_dirs:
        full_dir = os.path.join(ROOT, d)
        if not os.path.exists(full_dir):
            continue
        for dirpath, _, filenames in os.walk(full_dir):
            for fn in filenames:
                if not fn.endswith(".md") or fn.startswith(".") or fn.startswith("_") or fn == "sources_to_ingest.md":
                    continue
                filepath = os.path.join(dirpath, fn)
                meta, content = parse_yaml_front(filepath)
                check_yaml(filepath, meta)
                check_tags(filepath, meta, allowed_tags)
                check_links(filepath, content, meta)

    check_depth()
    check_index_coverage(index_content)

    return list(errors), list(warnings)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    errs, warns = run_linter()

    # Вывод
    print("=" * 60)
    print("  WIKI LINT — knowledge-wiki")
    print("=" * 60)

    if warns:
        print(f"\n[!] ПРЕДУПРЕЖДЕНИЯ ({len(warns)}):")
        for w in warns:
            print(f"  - {w}")

    if errs:
        print(f"\n[X] ОШИБКИ ({len(errs)}):")
        for e in errs:
            print(f"  - {e}")
        print(f"\n{'=' * 60}")
        print(f"ИТОГО: {len(errs)} ошибок, {len(warns)} предупреждений")
        print("=" * 60)
        sys.exit(1)
    else:
        print(f"\n[OK] Все проверки пройдены.")
        if warns:
            print(f"     ({len(warns)} предупреждений — не блокируют)")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()
