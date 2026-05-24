#!/usr/bin/env python3
"""
Wiki Common — общий модуль утилит для knowledge-wiki.

Единая точка для функций, которые ранее дублировались в wiki_lint.py,
wiki_tool.py и mcp_guards.py:
- Парсинг YAML frontmatter
- Рекурсивный поиск markdown-файлов
- Извлечение заголовков
- Разрешение относительных ссылок
- Загрузка реестра тегов
"""

import os
import re
import yaml

# Корневая директория проекта — на уровень выше scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_yaml_front(filepath):
    """Парсит YAML frontmatter из markdown-файла.

    Возвращает кортеж (meta, content):
    - meta: dict с метаданными из YAML-блока, или None если нет frontmatter
    - content: полный текст файла

    Обработка edge-cases:
    - Файл без frontmatter (не начинается с ---)
    - Невалидный YAML (возвращает None, content)
    - Горизонтальные линии --- в теле документа (корректно обрабатываются
      благодаря maxsplit=2)
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None, ""

    if not content.startswith("---"):
        return None, content

    # Разделяем по --- только первые два вхождения (open + close frontmatter)
    parts = re.split(r'^---\s*$', content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return None, content

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None, content

    if not isinstance(meta, dict):
        return None, content

    return meta, content


def parse_yaml_front_meta_only(filepath):
    """Считывает только метаданные из YAML frontmatter (без полного контента).

    Более легковесная версия для случаев, когда нужен только meta dict.
    Возвращает dict или None.
    """
    meta, _ = parse_yaml_front(filepath)
    return meta


def get_all_markdown_files(directory):
    """Рекурсивно находит все .md-файлы, исключая скрытые и служебные (начинающиеся с _ или .)."""
    md_files = []
    if not os.path.exists(directory):
        return md_files
    for dirpath, _, filenames in os.walk(directory):
        for fn in filenames:
            if fn.endswith(".md") and not fn.startswith(".") and not fn.startswith("_"):
                md_files.append(os.path.join(dirpath, fn))
    return md_files


def read_title_from_file(filepath):
    """Извлекает заголовок из файла: YAML title → первый H1 → имя файла."""
    meta = parse_yaml_front_meta_only(filepath)
    if meta and "title" in meta:
        return meta["title"]
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    return line[2:].strip()
    except Exception:
        pass
    # Крайний случай — имя файла без расширения
    return os.path.splitext(os.path.basename(filepath))[0].replace("-", " ").capitalize()


def resolve_relative_link(source_filepath, target_path):
    """Разрешает относительную ссылку из markdown-файла.

    Ключевое отличие от предыдущей реализации: ссылки разрешаются
    от директории исходного файла, а НЕ от корня репозитория.

    Args:
        source_filepath: абсолютный путь к файлу, содержащему ссылку
        target_path: относительный путь из ссылки (например, '../../sources/doc.md')

    Returns:
        Абсолютный путь к целевому файлу (нормализованный)
    """
    source_dir = os.path.dirname(source_filepath)
    return os.path.normpath(os.path.join(source_dir, target_path))


def resolve_root_link(target_path):
    """Разрешает ссылку от корня репозитория (для YAML related_topics).

    Args:
        target_path: путь от корня (например, 'topics/zemelnoe-pravo/vri.md')

    Returns:
        Абсолютный путь к целевому файлу
    """
    return os.path.join(ROOT, target_path)


def load_allowed_tags():
    """Загружает допустимые теги из tags-registry.md.

    Парсит таблицы формата: | `тег` | описание |
    Возвращает множество (set) строк тегов.
    """
    path = os.path.join(ROOT, "tags-registry.md")
    if not os.path.exists(path):
        return set()

    tags = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\|\s*`([^`]+)`\s*\|', line)
            if m:
                tags.add(m.group(1))
    return tags


def load_index_content():
    """Загружает содержимое INDEX.md для проверки упоминаний."""
    path = os.path.join(ROOT, "INDEX.md")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
