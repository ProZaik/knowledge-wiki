#!/usr/bin/env python3
"""
Модуль шаблонов для MCP-сервера knowledge-wiki.

Содержит функции-строители, которые собирают структурированный markdown
(с YAML-шапкой) из отдельных полей, переданных AI-моделью.
MCP-сервер вызывает эти функции вместо того, чтобы позволять модели
генерировать произвольный markdown.

Каждая функция возвращает готовую markdown-строку для записи на диск.
"""

import datetime
import os
import yaml

# Корень репозитория (на один уровень выше каталога scripts/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _today() -> str:
    """Возвращает текущую дату в формате ISO (YYYY-MM-DD)."""
    return datetime.date.today().isoformat()


def _render_frontmatter(data: dict) -> str:
    """Рендерит словарь в YAML-блок frontmatter (с разделителями ---)."""
    yaml_str = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{yaml_str}---"


def _numbered_list(items: list[str]) -> str:
    """Формирует нумерованный список из элементов."""
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {item}")
    return "\n".join(lines)


def _render_tags(tags: list[str]) -> str:
    """Рендерит теги как кликабельные ссылки на индекс тегов.

    Каждый тег становится ссылкой вида [тег](tags/index.md#тег),
    где якорь — lowercase slug тега.
    """
    if not tags:
        return ""
    tag_links = []
    for tag in tags:
        # Docsify якори: lowercase, пробелы → дефисы
        anchor = tag.lower().replace(" ", "-")
        tag_links.append(f"[`{tag}`](tags/index.md#{ anchor })")
    return "**Теги:** " + " · ".join(tag_links)


def _build_source_index() -> dict[str, str]:
    """Строит индекс источников: {title_lower: relative_path}.

    Сканирует sources/ и читает title из YAML-шапок.
    """
    import re
    index: dict[str, str] = {}
    sources_dir = os.path.join(ROOT, "sources")
    if not os.path.isdir(sources_dir):
        return index
    for fname in os.listdir(sources_dir):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(sources_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                head = f.read(1500)
            m = re.match(r"^---\s*\n(.*?)\n---", head, re.DOTALL)
            if m:
                meta = yaml.safe_load(m.group(1))
                if isinstance(meta, dict) and "title" in meta:
                    index[meta["title"].lower()] = f"sources/{fname}"
        except Exception:
            continue
    return index


def _linkify_source(name: str, source_index: dict[str, str] | None = None) -> str:
    """Если источник найден в индексе — оборачивает его в markdown-ссылку."""
    if source_index is None:
        source_index = _build_source_index()
    key = name.lower()
    # Точное совпадение
    if key in source_index:
        return f"[{name}]({source_index[key]})"
    # Частичное совпадение (title содержит имя или наоборот)
    for title_lower, path in source_index.items():
        if key in title_lower or title_lower in key:
            return f"[{name}]({path})"
    return name


# =========================================================================
# Функция 1: Письмо органа власти
# =========================================================================


def build_letter(params: dict) -> str:
    """Собирает markdown для письма государственного органа (type: «письмо органа»).

    Обязательные ключи params:
        title (str): Полное название, напр. «Письмо Росреестра от 12.03.2026 № 13-2496-АБ/26»
        number (str): Номер письма
        date (str): Дата в ISO-формате «2026-03-12»
        author_org (str): Орган-автор
        full_text (str): ПОЛНЫЙ оригинальный текст письма
        key_conclusions (list[str]): 3-5 ключевых выводов
        practical_significance (str): Практическое значение

    Необязательные ключи:
        tags (list[str]): Теги
        source_url (str): URL источника
        related_topics (list[str]): Пути к связанным темам

    Возвращает:
        str: Готовый markdown с YAML-шапкой.
    """
    # --- Извлечение обязательных полей ---
    title = params["title"]
    number = params["number"]
    date = params["date"]
    author_org = params["author_org"]
    full_text = params["full_text"]
    key_conclusions = params["key_conclusions"]
    practical_significance = params["practical_significance"]

    # --- Извлечение необязательных полей ---
    tags = params.get("tags", [])
    source_url = params.get("source_url", "")
    related_topics = params.get("related_topics", [])

    # --- Формирование frontmatter ---
    fm: dict = {
        "title": title,
        "type": "письмо органа",
        "status": "verified",
        "number": number,
        "date": date,
        "author_org": author_org,
        "date_added": _today(),
    }
    if tags:
        fm["tags"] = tags
    if source_url:
        fm["source_url"] = source_url
    if related_topics:
        fm["related_topics"] = related_topics

    # --- Сборка markdown ---
    tag_line = _render_tags(tags)
    sections = [
        _render_frontmatter(fm),
        "",
        f"# {title}",
        "",
        f"**Автор:** {author_org}  ",
        f"**Номер:** {number}  ",
        f"**Дата:** {date}",
    ]
    if tag_line:
        sections.extend(["", tag_line])
    sections.extend([
        "",
        "## Ключевые выводы",
        "",
        _numbered_list(key_conclusions),
        "",
        "## Практическое значение",
        "",
        practical_significance.strip(),
        "",
        "## Полный текст",
        "",
        full_text.strip(),
        "",
    ])
    return "\n".join(sections)


# =========================================================================
# Функция 2: Судебный акт
# =========================================================================


def build_court_decision(params: dict) -> str:
    """Собирает markdown для судебного акта (type: «судебный акт»).

    Обязательные ключи params:
        title (str): Напр. «Определение ВС РФ по делу А19-17707/2024»
        case_number (str): Номер дела
        court (str): Наименование суда
        date (str): Дата в ISO-формате
        fabula (str): Краткое описание дела (3-5 предложений)
        full_text (str): ПОЛНЫЙ оригинальный текст
        court_position (str): Правовая позиция суда
        practical_conclusions (list[str]): Практические выводы

    Необязательные ключи:
        tags (list[str]): Теги
        source_url (str): URL
        related_topics (list[str]): Связанные темы

    Возвращает:
        str: Готовый markdown с YAML-шапкой.
    """
    # --- Обязательные поля ---
    title = params["title"]
    case_number = params["case_number"]
    court = params["court"]
    date = params["date"]
    fabula = params["fabula"]
    full_text = params["full_text"]
    court_position = params["court_position"]
    practical_conclusions = params["practical_conclusions"]

    # --- Необязательные поля ---
    tags = params.get("tags", [])
    source_url = params.get("source_url", "")
    related_topics = params.get("related_topics", [])

    # --- Frontmatter ---
    fm: dict = {
        "title": title,
        "type": "судебный акт",
        "status": "verified",
        "case_number": case_number,
        "court": court,
        "date": date,
        "date_added": _today(),
    }
    if tags:
        fm["tags"] = tags
    if source_url:
        fm["source_url"] = source_url
    if related_topics:
        fm["related_topics"] = related_topics

    # --- Markdown ---
    tag_line = _render_tags(tags)
    sections = [
        _render_frontmatter(fm),
        "",
        f"# {title}",
        "",
        f"**Суд:** {court}  ",
        f"**Номер дела:** {case_number}  ",
        f"**Дата:** {date}",
    ]
    if tag_line:
        sections.extend(["", tag_line])
    sections.extend([
        "",
        "## Фабула",
        "",
        fabula.strip(),
        "",
        "## Позиция суда",
        "",
        court_position.strip(),
        "",
        "## Выводы для практики",
        "",
        _numbered_list(practical_conclusions),
        "",
        "## Полный текст",
        "",
        full_text.strip(),
        "",
    ])
    return "\n".join(sections)


# =========================================================================
# Функция 3: Статья / комментарий
# =========================================================================


def build_article(params: dict) -> str:
    """Собирает markdown для статьи или комментария (type: «статья»).

    Обязательные ключи params:
        title (str): Название статьи
        author (str): Имя автора
        source_name (str): Название издания
        full_text (str): ПОЛНЫЙ текст
        key_theses (list[str]): Ключевые тезисы / аргументы

    Необязательные ключи:
        source_url (str): URL
        tags (list[str]): Теги
        related_topics (list[str]): Связанные темы

    Возвращает:
        str: Готовый markdown с YAML-шапкой.
    """
    # --- Обязательные поля ---
    title = params["title"]
    author = params["author"]
    source_name = params["source_name"]
    full_text = params["full_text"]
    key_theses = params["key_theses"]

    # --- Необязательные поля ---
    source_url = params.get("source_url", "")
    tags = params.get("tags", [])
    related_topics = params.get("related_topics", [])

    # --- Frontmatter ---
    fm: dict = {
        "title": title,
        "type": "статья",
        "status": "verified",
        "author": author,
        "source_name": source_name,
        "date_added": _today(),
    }
    if tags:
        fm["tags"] = tags
    if source_url:
        fm["source_url"] = source_url
    if related_topics:
        fm["related_topics"] = related_topics

    # --- Markdown ---
    tag_line = _render_tags(tags)
    sections = [
        _render_frontmatter(fm),
        "",
        f"# {title}",
        "",
        f"**Автор:** {author}  ",
        f"**Источник:** {source_name}",
    ]
    if tag_line:
        sections.extend(["", tag_line])
    sections.extend([
        "",
        "## Ключевые тезисы",
        "",
        _numbered_list(key_theses),
        "",
        "## Полный текст",
        "",
        full_text.strip(),
        "",
    ])
    return "\n".join(sections)


# =========================================================================
# Функция 4: Нормативный акт (закон)
# =========================================================================


def build_law(params: dict) -> str:
    """Собирает markdown для нормативного акта (type: «нормативный акт»).

    Обязательные ключи params:
        title (str): Напр. «Федеральный закон от 26.03.2003 № 35-ФЗ»
        law_number (str): Номер закона, напр. «35-ФЗ»
        date_adopted (str): Дата принятия в ISO-формате
        full_text (str): Полный текст или извлечение
        what_changes (str): Что меняет / вводит данный акт
        commentary (str): Экспертный комментарий о значении

    Необязательные ключи:
        tags (list[str]): Теги
        source_url (str): URL
        related_topics (list[str]): Связанные темы

    Возвращает:
        str: Готовый markdown с YAML-шапкой.
    """
    # --- Обязательные поля ---
    title = params["title"]
    law_number = params["law_number"]
    date_adopted = params["date_adopted"]
    full_text = params["full_text"]
    what_changes = params["what_changes"]
    commentary = params["commentary"]

    # --- Необязательные поля ---
    tags = params.get("tags", [])
    source_url = params.get("source_url", "")
    related_topics = params.get("related_topics", [])

    # --- Frontmatter ---
    fm: dict = {
        "title": title,
        "type": "нормативный акт",
        "status": "verified",
        "law_number": law_number,
        "date_adopted": date_adopted,
        "date_added": _today(),
    }
    if tags:
        fm["tags"] = tags
    if source_url:
        fm["source_url"] = source_url
    if related_topics:
        fm["related_topics"] = related_topics

    # --- Markdown ---
    tag_line = _render_tags(tags)
    sections = [
        _render_frontmatter(fm),
        "",
        f"# {title}",
        "",
        f"**Номер:** {law_number}  ",
        f"**Дата принятия:** {date_adopted}",
    ]
    if tag_line:
        sections.extend(["", tag_line])
    sections.extend([
        "",
        "## Что меняет",
        "",
        what_changes.strip(),
        "",
        "## Комментарий",
        "",
        commentary.strip(),
        "",
        "## Текст (извлечение)",
        "",
        full_text.strip(),
        "",
    ])
    return "\n".join(sections)


# =========================================================================
# Функция 5: Тема (синтез-статья вики)
# =========================================================================


def build_topic(params: dict) -> str:
    """Собирает markdown для вики-темы / синтез-статьи (type: «тема»).

    Обязательные ключи params:
        title (str): Название темы
        normativnaya_osnova (str): Какие нормы регулируют данную область
        klyuchevye_pozitsii (list[dict]): Список позиций; каждый dict содержит:
            tezis (str): Тезис / позиция
            istochnik (str): Ссылка на источник
            vyvod (str): Вывод
        prakticheskie_riski (str): Что может пойти не так
        svodnaya_tablitsa (list[dict]): Сводная таблица; каждый dict содержит:
            istochnik (str): Название источника
            tip (str): Тип (письмо / суд / статья / закон)
            klyuchevoy_vyvod (str): Ключевой вывод из этого источника

    Необязательные ключи:
        tags (list[str]): Теги
        related_topics (list[str]): Связанные темы
        date_added (str): Сохранить существующую дату добавления (при обновлении)
        date_updated (str): Переопределить дату обновления

    Возвращает:
        str: Готовый markdown с YAML-шапкой.
    """
    # --- Обязательные поля ---
    title = params["title"]
    normativnaya_osnova = params["normativnaya_osnova"]
    klyuchevye_pozitsii = params["klyuchevye_pozitsii"]
    prakticheskie_riski = params["prakticheskie_riski"]
    svodnaya_tablitsa = params["svodnaya_tablitsa"]

    # --- Необязательные поля ---
    tags = params.get("tags", [])
    related_topics = params.get("related_topics", [])
    date_added = params.get("date_added", _today())
    date_updated = params.get("date_updated", _today())

    # --- Frontmatter ---
    fm: dict = {
        "title": title,
        "type": "тема",
        "status": "verified",
        "date_added": date_added,
        "date_updated": date_updated,
    }
    if tags:
        fm["tags"] = tags
    if related_topics:
        fm["related_topics"] = related_topics

    # --- Секция «Ключевые позиции» ---
    pozitsii_parts: list[str] = []
    for pos in klyuchevye_pozitsii:
        pozitsii_parts.append(f"### {pos['tezis']}")
        pozitsii_parts.append("")
        pozitsii_parts.append(f"> {pos['istochnik']}")
        pozitsii_parts.append("")
        pozitsii_parts.append(f"**Вывод:** {pos['vyvod']}")
        pozitsii_parts.append("")

    # --- Секция «Сводная таблица источников» (с линковкой на sources/) ---
    source_index = _build_source_index()
    table_lines: list[str] = [
        "| Источник | Тип | Ключевой вывод |",
        "|----------|-----|----------------|",
    ]
    for row in svodnaya_tablitsa:
        src = _linkify_source(row["istochnik"], source_index)
        tip = row["tip"]
        conclusion = row["klyuchevoy_vyvod"]
        table_lines.append(f"| {src} | {tip} | {conclusion} |")

    # --- Markdown ---
    tag_line = _render_tags(tags)
    sections = [
        _render_frontmatter(fm),
        "",
        f"# {title}",
        "",
    ]
    if tag_line:
        sections.extend([tag_line, ""])
    sections.extend([
        "## Нормативная основа",
        "",
        normativnaya_osnova.strip(),
        "",
        "## Ключевые позиции",
        "",
        "\n".join(pozitsii_parts).rstrip(),
        "",
        "## Практические риски",
        "",
        prakticheskie_riski.strip(),
        "",
        "## Сводная таблица источников",
        "",
        "\n".join(table_lines),
        "",
    ])
    return "\n".join(sections)
