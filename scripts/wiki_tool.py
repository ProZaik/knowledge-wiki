#!/usr/bin/env python3
"""
Wiki Tool — утилита для автоматизации рутины в knowledge-wiki.
Позволяет обновлять статистику в INDEX.md, проверять новые материалы в inbox/
и сверять количество файлов.
"""

import os
import re
import sys

from wiki_common import (
    ROOT,
    get_all_markdown_files,
    parse_yaml_front as _parse_yaml_front_tuple,
    parse_yaml_front_meta_only as parse_yaml_front,
)


def calculate_stats():
    """Считает все необходимые метрики для базы знаний."""
    sources_dir = os.path.join(ROOT, "sources")
    topics_dir = os.path.join(ROOT, "topics")

    sources_files = get_all_markdown_files(sources_dir)
    topics_files = get_all_markdown_files(topics_dir)

    # Корневые служебные файлы (.md в корне, кроме скрытых)
    root_files = [
        fn for fn in os.listdir(ROOT)
        if fn.endswith(".md") and not fn.startswith(".") and not fn.startswith("_")
    ]

    verified_sources = 0
    draft_sources = 0
    unique_tags = set()
    domains = set()

    # Анализируем источники
    for sf in sources_files:
        meta = parse_yaml_front(sf)
        if meta:
            status = meta.get("status", "draft")
            if status == "verified":
                verified_sources += 1
            else:
                draft_sources += 1
            
            tags = meta.get("tags", [])
            if isinstance(tags, list):
                for t in tags:
                    unique_tags.add(str(t).strip())

    # Анализируем темы
    for tf in topics_files:
        meta = parse_yaml_front(tf)
        if meta:
            tags = meta.get("tags", [])
            if isinstance(tags, list):
                for t in tags:
                    unique_tags.add(str(t).strip())

        # Название домена — это папка первого уровня внутри topics/
        rel = os.path.relpath(tf, topics_dir)
        parts = rel.split(os.sep)
        if len(parts) > 1:
            domains.add(parts[0])

    sources_count = len(sources_files)
    topics_count = len(topics_files)
    root_files_count = len(root_files)
    total_files = sources_count + topics_count + root_files_count

    return {
        "total_files": total_files,
        "sources_count": sources_count,
        "topics_count": topics_count,
        "root_files_count": root_files_count,
        "domains_count": len(domains),
        "verified_sources": verified_sources,
        "draft_sources": draft_sources,
        "tags_count": len(unique_tags),
    }


def generate_stats_markdown(stats):
    """Форматирует статистику в markdown-строки для INDEX.md."""
    return f"""## Статистика

- Всего файлов в базе: **{stats['total_files']}** ({stats['sources_count']} sources + {stats['topics_count']} topics + {stats['root_files_count']} service files)
- Тем: **{stats['domains_count']} домена**, **{stats['topics_count']} тематических файлов**
- Источников verified: **{stats['verified_sources']}**
- Источников draft: **{stats['draft_sources']}**
- Тегов: **{stats['tags_count']}**"""


# Маппинг типов источников на эмодзи-заголовки для сайдбара и каталога
SOURCE_TYPE_EMOJI = {
    'письмо органа': '📜 Письма органов',
    'судебный акт': '⚖️ Судебные акты',
    'статья': '📝 Статьи',
    'нормативный акт': '📋 Нормативные акты',
}

# Порядок отображения групп источников в сайдбаре и каталоге
SOURCE_TYPE_ORDER = ['письмо органа', 'судебный акт', 'статья', 'нормативный акт']

# Русские названия месяцев для хронологии
RUSSIAN_MONTHS = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}


def _get_source_date(meta):
    """Извлекает дату источника из YAML-метаданных (поле date или date_adopted)."""
    date_str = meta.get('date') or meta.get('date_adopted') or ''
    return str(date_str).strip()


def _collect_sources_grouped():
    """Собирает все источники из sources/, группирует по типу, сортирует по дате (новые первыми).

    Возвращает dict: {тип -> [{filename, title, date, meta}, ...]}.
    """
    sources_dir = os.path.join(ROOT, 'sources')
    groups = {}  # type: dict[str, list[dict]]

    if not os.path.exists(sources_dir):
        return groups

    for fn in os.listdir(sources_dir):
        if not fn.endswith('.md') or fn.startswith('.') or fn.startswith('_'):
            continue
        fpath = os.path.join(sources_dir, fn)
        meta = parse_yaml_front(fpath)
        if not meta:
            continue

        src_type = meta.get('type', '').strip()
        title = meta.get('title', fn[:-3].replace('-', ' ').capitalize())
        date_str = _get_source_date(meta)

        if src_type not in groups:
            groups[src_type] = []
        groups[src_type].append({
            'filename': fn,
            'title': title,
            'date': date_str,
            'meta': meta,
        })

    # Сортировка внутри каждой группы — новые первыми
    for entries in groups.values():
        entries.sort(key=lambda e: e['date'], reverse=True)

    return groups


def generate_sidebar():
    """Автоматически генерирует _sidebar.md: темы, источники по типам, ссылки на теги и граф."""
    sidebar_path = os.path.join(ROOT, "_sidebar.md")
    topics_dir = os.path.join(ROOT, "topics")

    # Стандартный заголовок
    lines = [
        "<!-- _sidebar.md -->",
        "",
        "* **📚 База знаний**",
        ""
    ]

    # Стандартный маппинг эмодзи для доменов на случай, если они не указаны в _index.md
    emoji_map = {
        "gradostroitelstvo": "⚖️",
        "zemelnoe-pravo": "🌍",
        "zhilishnoe-pravo": "🏠",
        "sro": "🏗️"
    }

    # ——— Секция тем ———
    if os.path.exists(topics_dir):
        domains = sorted([d for d in os.listdir(topics_dir) if os.path.isdir(os.path.join(topics_dir, d)) and not d.startswith(".")])

        for domain in domains:
            domain_path = os.path.join(topics_dir, domain)
            index_path = os.path.join(domain_path, "_index.md")

            # Читаем название домена из _index.md
            domain_title = domain.capitalize().replace("-", " ")
            emoji = emoji_map.get(domain, "📁")

            if os.path.exists(index_path):
                meta = parse_yaml_front(index_path)
                if meta:
                    if "title" in meta:
                        # Убираем суффиксы типа " — обзор темы" для краткости меню
                        title_clean = meta["title"].split("—")[0].strip()
                        title_clean = title_clean.split("-")[0].strip()
                        domain_title = title_clean
                    if "emoji" in meta:
                        emoji = meta["emoji"]
                else:
                    # Если нет метаданных, попробуем H1
                    try:
                        with open(index_path, "r", encoding="utf-8") as f:
                            for l in f:
                                if l.startswith("# "):
                                    domain_title = l[2:].strip()
                                    break
                    except Exception:
                        pass

            # Находим все файлы тем
            topic_files = []
            for fn in sorted(os.listdir(domain_path)):
                if fn.endswith(".md") and not fn.startswith(".") and not fn.startswith("_"):
                    tf_path = os.path.join(domain_path, fn)
                    title = fn[:-3].capitalize().replace("-", " ")
                    meta = parse_yaml_front(tf_path)
                    if meta and "title" in meta:
                        title = meta["title"]
                    else:
                        # Пробуем H1
                        try:
                            with open(tf_path, "r", encoding="utf-8") as f:
                                for l in f:
                                    if l.startswith("# "):
                                        title = l[2:].strip()
                                        break
                        except Exception:
                            pass
                    topic_files.append((fn, title))

            # Ссылка на обзорный файл темы всегда полезна
            rel_index_path = f"topics/{domain}/_index.md"

            if topic_files:
                lines.append(f"* **{emoji} {domain_title}**")
                lines.append(f"  * [🧭 Обзор](topics/{domain}/_index.md)")
                for fn, title in topic_files:
                    lines.append(f"  * [{title}](topics/{domain}/{fn})")
            else:
                # Если подтем нет, показываем только сам домен со ссылкой на обзор
                lines.append(f"* [{emoji} **{domain_title}**]({rel_index_path})")
            lines.append("")

    # ——— Секция источников ———
    source_groups = _collect_sources_grouped()
    if source_groups:
        lines.append("* **📂 Источники**")
        lines.append("  * [📋 Каталог источников](sources/_index.md)")
        lines.append("")

        for src_type in SOURCE_TYPE_ORDER:
            entries = source_groups.get(src_type)
            if not entries:
                continue
            header = SOURCE_TYPE_EMOJI.get(src_type, f"📄 {src_type.capitalize()}")
            lines.append(f"* **{header}**")
            for entry in entries:
                lines.append(f"  * [{entry['title']}](sources/{entry['filename']})")
            lines.append("")

        # Типы, которых нет в стандартном маппинге
        for src_type, entries in source_groups.items():
            if src_type in SOURCE_TYPE_ORDER:
                continue
            header = f"📄 {src_type.capitalize()}" if src_type else "📄 Прочее"
            lines.append(f"* **{header}**")
            for entry in entries:
                lines.append(f"  * [{entry['title']}](sources/{entry['filename']})")
            lines.append("")

    # ——— Нижние ссылки ———
    lines.append("* **🏷️ [Индекс тегов](tags/index.md)**")
    lines.append("* **🕸️ [Граф знаний](_graph.md)**")
    lines.append("")

    with open(sidebar_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("[OK] _sidebar.md успешно сгенерирован на основе файловой структуры!")
    return True


def _read_title_from_file(filepath):
    """Извлекает заголовок из YAML frontmatter (поле title) или из первого H1."""
    meta = parse_yaml_front(filepath)
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


def generate_backlinks():
    """Сканирует все .md-файлы в topics/ и sources/, строит карту обратных ссылок
    и дописывает/обновляет секцию BACKLINKS в каждом файле topics/."""
    sources_dir = os.path.join(ROOT, "sources")
    topics_dir = os.path.join(ROOT, "topics")

    all_files = get_all_markdown_files(topics_dir) + get_all_markdown_files(sources_dir)
    # Включаем также _index.md-файлы для полноты сканирования ссылок
    for dirpath, _, filenames in os.walk(topics_dir):
        for fn in filenames:
            if fn.startswith("_") and fn.endswith(".md"):
                fp = os.path.join(dirpath, fn)
                if fp not in all_files:
                    all_files.append(fp)

    # Карта: относительный путь (от ROOT) -> список файлов, которые ссылаются на него
    backlinks_map = {}  # type: dict[str, list[str]]

    # Регулярка для поиска markdown-ссылок вида [текст](путь.md)
    link_pattern = re.compile(r'\]\(([^)]+\.md)\)')

    for fpath in all_files:
        rel_self = os.path.relpath(fpath, ROOT).replace("\\", "/")
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        # Убираем секцию backlinks из содержимого, чтобы не считать их как ссылки
        content_clean = re.sub(
            r'<!-- BACKLINKS_START -->.*?<!-- BACKLINKS_END -->',
            '', content, flags=re.DOTALL
        )

        for match in link_pattern.finditer(content_clean):
            raw_link = match.group(1)
            # Разрешаем относительные пути от файла-источника
            link_dir = os.path.dirname(fpath)
            abs_target = os.path.normpath(os.path.join(link_dir, raw_link))
            rel_target = os.path.relpath(abs_target, ROOT).replace("\\", "/")

            if rel_target == rel_self:
                continue  # не считаем самоссылку

            if rel_target not in backlinks_map:
                backlinks_map[rel_target] = []
            if rel_self not in backlinks_map[rel_target]:
                backlinks_map[rel_target].append(rel_self)

    # Обрабатываем только файлы тем (topics/) — дописываем/обновляем секцию
    topic_files_all = get_all_markdown_files(topics_dir)
    # Также включаем _index.md
    for dirpath, _, filenames in os.walk(topics_dir):
        for fn in filenames:
            if fn.startswith("_") and fn.endswith(".md"):
                fp = os.path.join(dirpath, fn)
                if fp not in topic_files_all:
                    topic_files_all.append(fp)

    updated_count = 0
    for fpath in topic_files_all:
        rel_path = os.path.relpath(fpath, ROOT).replace("\\", "/")
        linkers = backlinks_map.get(rel_path, [])

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        # Удаляем существующую секцию backlinks
        content_stripped = re.sub(
            r'\n*<!-- BACKLINKS_START -->.*?<!-- BACKLINKS_END -->\s*',
            '', content, flags=re.DOTALL
        ).rstrip()

        if linkers:
            # Формируем секцию
            bl_lines = []
            bl_lines.append("<!-- BACKLINKS_START -->")
            bl_lines.append("---")
            bl_lines.append("> **📎 На эту статью ссылаются:**")
            for lf in sorted(linkers):
                abs_lf = os.path.join(ROOT, lf.replace("/", os.sep))
                title = _read_title_from_file(abs_lf)
                # Вычисляем относительный путь от текущего файла к ссылающемуся
                rel_link = os.path.relpath(abs_lf, os.path.dirname(fpath)).replace("\\", "/")
                bl_lines.append(f"> - [{title}]({rel_link})")
            bl_lines.append("<!-- BACKLINKS_END -->")
            new_content = content_stripped + "\n\n" + "\n".join(bl_lines) + "\n"
        else:
            new_content = content_stripped + "\n"

        if new_content != content:
            with open(fpath, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_content)
            updated_count += 1

    print(f"[OK] Обратные ссылки обновлены для {updated_count} файлов тем.")
    return True


def generate_tag_index():
    """Генерирует tags/index.md — индекс всех тегов с ссылками на статьи."""
    sources_dir = os.path.join(ROOT, "sources")
    topics_dir = os.path.join(ROOT, "topics")
    tags_dir = os.path.join(ROOT, "tags")

    all_files = get_all_markdown_files(topics_dir) + get_all_markdown_files(sources_dir)
    # Включаем _index.md-файлы, которые тоже содержат теги
    for dirpath, _, filenames in os.walk(topics_dir):
        for fn in filenames:
            if fn.startswith("_") and fn.endswith(".md"):
                fp = os.path.join(dirpath, fn)
                if fp not in all_files:
                    all_files.append(fp)

    # Карта: тег -> [{title, path, type}]
    tag_map = {}  # type: dict[str, list[dict]]

    for fpath in all_files:
        meta = parse_yaml_front(fpath)
        if not meta:
            continue

        tags = meta.get("tags", [])
        if not isinstance(tags, list) or not tags:
            continue

        rel_path = os.path.relpath(fpath, ROOT).replace("\\", "/")
        title = _read_title_from_file(fpath)

        # Определяем тип: тема или источник
        if rel_path.startswith("topics/"):
            file_type = "тема"
            sort_order = 0
        else:
            file_type = "источник"
            sort_order = 1

        for tag in tags:
            tag_str = str(tag).strip()
            if not tag_str:
                continue
            if tag_str not in tag_map:
                tag_map[tag_str] = []
            tag_map[tag_str].append({
                "title": title,
                "path": rel_path,
                "type": file_type,
                "sort_order": sort_order,
            })

    # Сортируем теги по алфавиту (без учёта регистра)
    sorted_tags = sorted(tag_map.keys(), key=lambda t: t.lower())

    # Формируем содержимое
    lines = [
        '---',
        'title: "Индекс по тегам"',
        'type: служебный',
        '---',
        '# 🏷️ Индекс по тегам',
        '',
    ]

    for tag in sorted_tags:
        lines.append(f"## {tag}")
        # Сортируем: сначала темы (sort_order=0), потом источники (sort_order=1)
        articles = sorted(tag_map[tag], key=lambda a: (a["sort_order"], a["title"]))
        for art in articles:
            lines.append(f"- [{art['title']}]({art['path']}) ({art['type']})")
        lines.append("")

    # Создаём директорию tags/ при необходимости
    os.makedirs(tags_dir, exist_ok=True)

    tag_index_path = os.path.join(tags_dir, "index.md")
    with open(tag_index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    print(f"[OK] Индекс тегов сгенерирован: tags/index.md ({len(sorted_tags)} тегов).")
    return True


def generate_sources_catalog():
    """Генерирует sources/_index.md — каталог всех источников, сгруппированных по типу."""
    sources_dir = os.path.join(ROOT, 'sources')
    os.makedirs(sources_dir, exist_ok=True)
    catalog_path = os.path.join(sources_dir, '_index.md')

    source_groups = _collect_sources_grouped()

    lines = [
        '---',
        'title: Каталог источников',
        '---',
        '# 📋 Каталог источников',
        '',
    ]

    # Определяем колонки таблицы в зависимости от типа источника
    type_columns = {
        'письмо органа':   ('Дата', 'Документ', 'Автор', 'Теги'),
        'судебный акт':    ('Дата', 'Документ', 'Суд', 'Теги'),
        'статья':          ('Дата', 'Документ', 'Автор', 'Теги'),
        'нормативный акт': ('Дата', 'Документ', 'Номер', 'Теги'),
    }

    def _format_tags(meta):
        """Форматирует список тегов как кликабельные ссылки на tags/index.md."""
        tags = meta.get('tags', [])
        if not isinstance(tags, list) or not tags:
            return ''
        parts = []
        for t in tags:
            tag_str = str(t).strip()
            anchor = tag_str.lower()
            parts.append(f'[`{tag_str}`](../tags/index.md#{anchor})')
        return ' · '.join(parts)

    def _get_extra_column(meta, src_type):
        """Извлекает значение дополнительной колонки (Автор/Суд/Номер) в зависимости от типа."""
        if src_type == 'письмо органа':
            return meta.get('author_org', meta.get('author', ''))
        elif src_type == 'судебный акт':
            return meta.get('court', '')
        elif src_type == 'статья':
            return meta.get('author', meta.get('author_org', ''))
        elif src_type == 'нормативный акт':
            return meta.get('law_number', meta.get('number', ''))
        return ''

    for src_type in SOURCE_TYPE_ORDER:
        entries = source_groups.get(src_type)
        if not entries:
            continue
        header = SOURCE_TYPE_EMOJI.get(src_type, f'📄 {src_type.capitalize()}')
        cols = type_columns.get(src_type, ('Дата', 'Документ', 'Автор', 'Теги'))

        lines.append(f'## {header} ({len(entries)})')
        lines.append('')
        lines.append(f'| {cols[0]} | {cols[1]} | {cols[2]} | {cols[3]} |')
        lines.append('|------|----------|-------|------|')

        for entry in entries:
            m = entry['meta']
            date_val = entry['date']
            link = f"[{entry['title']}]({entry['filename']})"
            extra = _get_extra_column(m, src_type)
            tags_str = _format_tags(m)
            lines.append(f'| {date_val} | {link} | {extra} | {tags_str} |')

        lines.append('')

    # Нестандартные типы
    for src_type, entries in source_groups.items():
        if src_type in SOURCE_TYPE_ORDER:
            continue
        header = f'📄 {src_type.capitalize()}' if src_type else '📄 Прочее'
        lines.append(f'## {header} ({len(entries)})')
        lines.append('')
        lines.append('| Дата | Документ | Теги |')
        lines.append('|------|----------|------|')
        for entry in entries:
            m = entry['meta']
            date_val = entry['date']
            link = f"[{entry['title']}]({entry['filename']})"
            tags_str = _format_tags(m)
            lines.append(f'| {date_val} | {link} | {tags_str} |')
        lines.append('')

    with open(catalog_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))

    total = sum(len(v) for v in source_groups.values())
    print(f'[OK] Каталог источников сгенерирован: sources/_index.md ({total} источников).')
    return True


def generate_timeline():
    """Генерирует _timeline.md — хронологию всех источников по месяцам."""
    timeline_path = os.path.join(ROOT, '_timeline.md')
    source_groups = _collect_sources_grouped()

    # Собираем все источники в единый плоский список
    all_sources = []
    for entries in source_groups.values():
        for entry in entries:
            all_sources.append(entry)

    # Сортируем по дате — новые первыми
    all_sources.sort(key=lambda e: e['date'], reverse=True)

    # Группируем по месяцу (YYYY-MM)
    months = {}  # type: dict[str, list[dict]]
    for entry in all_sources:
        d = entry['date']
        month_key = d[:7] if len(d) >= 7 else 'без даты'
        if month_key not in months:
            months[month_key] = []
        months[month_key].append(entry)

    # Маппинг типа в компактный эмодзи
    type_emoji_short = {
        'письмо органа': '📜',
        'судебный акт': '⚖️',
        'статья': '📝',
        'нормативный акт': '📋',
    }

    lines = [
        '---',
        'title: Хронология',
        '---',
        '# 📅 Хронология источников',
        '',
    ]

    for month_key in sorted(months.keys(), reverse=True):
        entries = months[month_key]

        # Формируем красивый заголовок месяца: "Май 2026"
        if month_key != 'без даты' and len(month_key) == 7:
            try:
                year = int(month_key[:4])
                month_num = int(month_key[5:7])
                month_name = RUSSIAN_MONTHS.get(month_num, month_key)
                month_header = f'{month_name} {year}'
            except (ValueError, IndexError):
                month_header = month_key
        else:
            month_header = month_key

        lines.append(f'## {month_header}')
        lines.append('')
        lines.append('| Дата | Тип | Документ |')
        lines.append('|------|-----|----------|')

        for entry in entries:
            # Форматируем дату как ДД.ММ.ГГГГ
            d = entry['date']
            if len(d) == 10 and d[4] == '-':
                formatted_date = f"{d[8:10]}.{d[5:7]}.{d[:4]}"
            else:
                formatted_date = d

            src_type = entry['meta'].get('type', '')
            emoji = type_emoji_short.get(src_type, '📄')
            link = f"[{entry['title']}](sources/{entry['filename']})"
            lines.append(f'| {formatted_date} | {emoji} | {link} |')

        lines.append('')

    with open(timeline_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))

    print(f'[OK] Хронология сгенерирована: _timeline.md ({len(all_sources)} источников).')
    return True


def generate_knowledge_graph():
    """Генерирует интерактивный граф знаний (vis.js) — темы и источники с цветами и связями."""
    import json as _json

    topics_dir = os.path.join(ROOT, "topics")
    sources_dir = os.path.join(ROOT, "sources")
    graph_html_path = os.path.join(ROOT, "graph.html")
    graph_md_path = os.path.join(ROOT, "_graph.md")

    # === Цвета ===
    TOPIC_COLOR = "#4A90D9"       # синий
    SOURCE_COLORS = {
        "письмо органа":   "#E8A838",  # оранжевый
        "судебный акт":    "#D94A68",  # красный
        "статья":          "#50B878",  # зелёный
        "нормативный акт": "#9B59B6",  # фиолетовый
    }
    DEFAULT_SRC_COLOR = "#95A5A6"

    nodes_data = []  # [{id, label, color, shape, url, group}]
    edges_data = []  # [{from, to}]
    seen_edges = set()

    # --- Собираем темы ---
    topic_files = get_all_markdown_files(topics_dir)
    for dirpath, _, filenames in os.walk(topics_dir):
        for fn in filenames:
            if fn.startswith("_") and fn.endswith(".md"):
                fp = os.path.join(dirpath, fn)
                if fp not in topic_files:
                    topic_files.append(fp)

    # rel_path -> node_id для связей
    path_to_id = {}

    for fpath in topic_files:
        rel_path = os.path.relpath(fpath, ROOT).replace("\\", "/")
        title = _read_title_from_file(fpath)
        title_short = title.split("—")[0].strip()
        node_id = "t_" + rel_path.replace("/", "_").replace(".", "_")

        nodes_data.append({
            "id": node_id,
            "label": title_short,
            "color": TOPIC_COLOR,
            "shape": "dot",
            "size": 25,
            "font": {"size": 14, "color": "#ffffff"},
            "url": "#/" + rel_path,
            "group": "topic",
        })
        path_to_id[rel_path] = node_id

    # --- Собираем источники ---
    source_groups = _collect_sources_grouped()
    for src_type, entries in source_groups.items():
        color = SOURCE_COLORS.get(src_type, DEFAULT_SRC_COLOR)
        for entry in entries:
            rel_path = f"sources/{entry['filename']}"
            node_id = "s_" + entry["filename"].replace(".", "_").replace("-", "_")
            # Укорачиваем название для графа
            label = entry["title"]
            if len(label) > 40:
                label = label[:37] + "..."

            nodes_data.append({
                "id": node_id,
                "label": label,
                "color": color,
                "shape": "box",
                "size": 15,
                "font": {"size": 11, "color": "#333333"},
                "url": "#/" + rel_path,
                "group": src_type,
            })
            path_to_id[rel_path] = node_id

            # Связи source -> related_topics
            meta = entry.get("meta", {})
            related = meta.get("related_topics", [])
            if isinstance(related, list):
                for rt in related:
                    rt_str = str(rt).strip()
                    if rt_str in path_to_id:
                        edge_key = tuple(sorted([node_id, path_to_id[rt_str]]))
                        if edge_key not in seen_edges:
                            edges_data.append({"from": node_id, "to": path_to_id[rt_str]})
                            seen_edges.add(edge_key)

            # Связи source -> topics по общим тегам
            src_tags = set(meta.get("tags", []))
            if src_tags:
                for tfpath in topic_files:
                    tmeta = parse_yaml_front(tfpath)
                    if not tmeta:
                        continue
                    ttags = set(tmeta.get("tags", []))
                    if src_tags & ttags:
                        trel = os.path.relpath(tfpath, ROOT).replace("\\", "/")
                        if trel in path_to_id:
                            edge_key = tuple(sorted([node_id, path_to_id[trel]]))
                            if edge_key not in seen_edges:
                                edges_data.append({"from": node_id, "to": path_to_id[trel]})
                                seen_edges.add(edge_key)

    # --- Связи topic <-> topic ---
    link_pattern = re.compile(r'\]\(([^)]+\.md)\)')
    for fpath in topic_files:
        rel_self = os.path.relpath(fpath, ROOT).replace("\\", "/")
        self_id = path_to_id.get(rel_self)
        if not self_id:
            continue
        meta = parse_yaml_front(fpath)
        if meta:
            related = meta.get("related_topics", [])
            if isinstance(related, list):
                for rt in related:
                    rt_str = str(rt).strip()
                    if rt_str in path_to_id:
                        edge_key = tuple(sorted([self_id, path_to_id[rt_str]]))
                        if edge_key not in seen_edges:
                            edges_data.append({"from": self_id, "to": path_to_id[rt_str]})
                            seen_edges.add(edge_key)

    # === Генерируем graph.html ===
    nodes_json = _json.dumps(nodes_data, ensure_ascii=False, indent=2)
    edges_json = _json.dumps(edges_data, ensure_ascii=False, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Граф знаний</title>
<script src="https://cdn.jsdelivr.net/npm/vis-network@9/dist/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #1a1a2e; font-family: 'Segoe UI', sans-serif; }}
  #graph {{ width: 100vw; height: 100vh; }}
  #legend {{
    position: fixed; top: 16px; right: 16px;
    background: rgba(26,26,46,0.92); border: 1px solid #333;
    border-radius: 12px; padding: 16px 20px;
    color: #ccc; font-size: 13px; z-index: 10;
    backdrop-filter: blur(8px);
  }}
  #legend h3 {{ color: #fff; margin-bottom: 10px; font-size: 15px; }}
  .legend-item {{ display: flex; align-items: center; margin: 6px 0; }}
  .legend-dot {{ width: 14px; height: 14px; border-radius: 50%; margin-right: 10px; flex-shrink: 0; }}
  .legend-box {{ width: 14px; height: 14px; border-radius: 3px; margin-right: 10px; flex-shrink: 0; }}
  #title {{
    position: fixed; top: 16px; left: 16px;
    color: #fff; font-size: 22px; font-weight: 700;
    text-shadow: 0 2px 8px rgba(0,0,0,0.5); z-index: 10;
  }}
  #stats {{
    position: fixed; bottom: 16px; left: 16px;
    color: #666; font-size: 12px; z-index: 10;
  }}
</style>
</head>
<body>
<div id="title">🕸️ Граф знаний</div>
<div id="legend">
  <h3>Легенда</h3>
  <div class="legend-item"><div class="legend-dot" style="background:{TOPIC_COLOR}"></div>Темы</div>
  <div class="legend-item"><div class="legend-box" style="background:{SOURCE_COLORS['письмо органа']}"></div>Письма органов</div>
  <div class="legend-item"><div class="legend-box" style="background:{SOURCE_COLORS['судебный акт']}"></div>Судебные акты</div>
  <div class="legend-item"><div class="legend-box" style="background:{SOURCE_COLORS['статья']}"></div>Статьи</div>
  <div class="legend-item"><div class="legend-box" style="background:{SOURCE_COLORS['нормативный акт']}"></div>Нормативные акты</div>
</div>
<div id="stats">{len(nodes_data)} узлов · {len(edges_data)} связей</div>
<div id="graph"></div>
<script>
var nodes = new vis.DataSet({nodes_json});
var edges = new vis.DataSet({edges_json});
var container = document.getElementById('graph');
var data = {{ nodes: nodes, edges: edges }};
var options = {{
  physics: {{
    barnesHut: {{
      gravitationalConstant: -3000,
      centralGravity: 0.3,
      springLength: 120,
      springConstant: 0.04,
      damping: 0.09
    }},
    stabilization: {{ iterations: 150 }}
  }},
  edges: {{
    color: {{ color: '#555', highlight: '#aaa', hover: '#888' }},
    width: 1.5,
    smooth: {{ type: 'continuous' }}
  }},
  interaction: {{
    hover: true,
    tooltipDelay: 100,
    zoomView: true,
    dragView: true
  }}
}};
var network = new vis.Network(container, data, options);
network.on('click', function(params) {{
  if (params.nodes.length > 0) {{
    var nodeId = params.nodes[0];
    var node = nodes.get(nodeId);
    if (node && node.url) {{
      window.open(node.url, '_blank');
    }}
  }}
}});
</script>
</body>
</html>"""

    with open(graph_html_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    # === Генерируем _graph.md со ссылкой ===
    md_lines = [
        "---",
        'title: "Граф знаний"',
        "---",
        "# 🕸️ Граф знаний",
        "",
        f"> **{len(nodes_data)}** узлов · **{len(edges_data)}** связей",
        "",
        "[🔗 Открыть интерактивный граф](graph.html ':target=_blank')",
        "",
        '<iframe src="graph.html" width="100%" height="700" style="border:1px solid #333; border-radius:8px;"></iframe>',
        "",
    ]

    with open(graph_md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md_lines))

    print(f"[OK] Граф знаний сгенерирован: graph.html ({len(nodes_data)} узлов, {len(edges_data)} связей).")


def update_index_stats():
    """Считывает INDEX.md, обновляет блок статистики, генерирует _sidebar.md и записывает обратно."""
    index_path = os.path.join(ROOT, "INDEX.md")
    if not os.path.exists(index_path):
        print("[X] Ошибка: INDEX.md не найден!")
        return False

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    stats = calculate_stats()
    new_stats_md = generate_stats_markdown(stats)

    # Ищем блок ## Статистика и заменяем всё после него до конца файла или следующего заголовка
    pattern = r"## Статистика\s*\n\s*(?:- .*\n?)*"
    if not re.search(pattern, content):
        # Если регулярка не нашла точный паттерн, пробуем простую замену до конца файла
        parts = content.split("## Статистика")
        if len(parts) < 2:
            print("[X] Ошибка: Не удалось найти раздел '## Статистика' в INDEX.md")
            return False
        content = parts[0] + new_stats_md + "\n"
    else:
        content = re.sub(pattern, new_stats_md + "\n", content)

    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    print(f"[OK] Статистика в INDEX.md успешно обновлена! Всего файлов: {stats['total_files']}.")
    
    # Также автоматически генерируем сайдбар
    generate_sidebar()

    # Генерация обратных ссылок
    try:
        generate_backlinks()
    except Exception as e:
        print(f"[!] Ошибка при генерации обратных ссылок: {e}")

    # Генерация индекса тегов
    try:
        generate_tag_index()
    except Exception as e:
        print(f"[!] Ошибка при генерации индекса тегов: {e}")

    # Генерация графа знаний
    try:
        generate_knowledge_graph()
    except Exception as e:
        print(f"[!] Ошибка при генерации графа знаний: {e}")

    # Генерация каталога источников
    try:
        generate_sources_catalog()
    except Exception as e:
        print(f"[!] Ошибка при генерации каталога источников: {e}")

    # Генерация хронологии
    try:
        generate_timeline()
    except Exception as e:
        print(f"[!] Ошибка при генерации хронологии: {e}")

    return True


def check_index_stats():
    """Проверяет, совпадает ли статистика в INDEX.md с реальным положением дел."""
    index_path = os.path.join(ROOT, "INDEX.md")
    if not os.path.exists(index_path):
        print("[X] Ошибка: INDEX.md не найден!")
        return False

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    stats = calculate_stats()
    expected_md = generate_stats_markdown(stats)

    if expected_md not in content:
        print("[!] ВНИМАНИЕ: Статистика в INDEX.md устарела!")
        print("Ожидается:")
        print(expected_md)
        return False

    print("[OK] Статистика в INDEX.md совпадает с фактической.")
    return True


def check_inbox():
    """Проверяет папку inbox/ на наличие необработанных файлов."""
    inbox_dir = os.path.join(ROOT, "inbox")
    if not os.path.exists(inbox_dir):
        print("[OK] Папка inbox/ отсутствует.")
        return

    inbox_files = get_all_markdown_files(inbox_dir)
    # Исключаем .gitkeep
    inbox_files = [f for f in inbox_files if os.path.basename(f) != ".gitkeep"]

    if not inbox_files:
        print("[OK] inbox/ пуст. Нет новых материалов для обработки.")
        return

    print("=" * 60)
    print(f" [!] ОБНАРУЖЕНЫ НОВЫЕ МАТЕРИАЛЫ В INBOX ({len(inbox_files)}):")
    print("=" * 60)
    for f in inbox_files:
        rel = os.path.relpath(f, ROOT)
        print(f"  - {rel}")
    print("\nИнструкция для импорта: прочитайте файл, создайте источник в sources/,")
    print("обновите связанные темы в topics/ и запишите изменения в CHANGELOG.md.")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Wiki Tool — Автоматизация утилит базы знаний")
    parser.add_argument("--update-stats", action="store_true", help="Обновить статистику в INDEX.md")
    parser.add_argument("--update-sidebar", action="store_true", help="Обновить меню _sidebar.md на основе структуры topics/")
    parser.add_argument("--check-stats", action="store_true", help="Проверить актуальность статистики в INDEX.md")
    parser.add_argument("--check-inbox", action="store_true", help="Проверить папку inbox/ на новые файлы")

    args = parser.parse_args()

    if args.update_stats:
        success = update_index_stats()
        sys.exit(0 if success else 1)
    elif args.update_sidebar:
        success = generate_sidebar()
        sys.exit(0 if success else 1)
    elif args.check_stats:
        success = check_index_stats()
        sys.exit(0 if success else 1)
    elif args.check_inbox:
        check_inbox()
        sys.exit(0)
    else:
        # По умолчанию просто выводим сводку и обновляем статистику/сайдбар
        success = update_index_stats()
        if success:
            stats = calculate_stats()
            print("=" * 60)
            print("  СВОДКА СТАТИСТИКИ БАЗЫ ЗНАНИЙ")
            print("=" * 60)
            for k, v in stats.items():
                print(f"  {k:20}: {v}")
            print("=" * 60)
            check_inbox()
            sys.exit(0)
        sys.exit(1)
