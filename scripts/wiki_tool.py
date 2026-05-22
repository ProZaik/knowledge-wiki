#!/usr/bin/env python3
"""
Wiki Tool — утилита для автоматизации рутины в knowledge-wiki.
Позволяет обновлять статистику в INDEX.md, проверять новые материалы в inbox/
и сверять количество файлов.
"""

import os
import re
import sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_all_markdown_files(directory):
    """Рекурсивно находит все md-файлы, исключая скрытые."""
    md_files = []
    if not os.path.exists(directory):
        return md_files
    for dirpath, _, filenames in os.walk(directory):
        for fn in filenames:
            if fn.endswith(".md") and not fn.startswith(".") and not fn.startswith("_"):
                md_files.append(os.path.join(dirpath, fn))
    return md_files


def parse_yaml_front(filepath):
    """Считывает YAML frontmatter из markdown-файла."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.startswith("---"):
            return None
        parts = re.split(r'^---\s*$', content, maxsplit=2, flags=re.MULTILINE)
        if len(parts) >= 3:
            return yaml.safe_load(parts[1])
    except Exception:
        pass
    return None


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


def generate_sidebar():
    """Автоматически генерирует файл _sidebar.md на основе существующей файловой структуры в topics/"""
    sidebar_path = os.path.join(ROOT, "_sidebar.md")
    topics_dir = os.path.join(ROOT, "topics")
    
    # Стандартный заголовок
    lines = [
        "<!-- _sidebar.md -->",
        "",
        "* [🏠 Главная](INDEX.md)",
        "* [🏷️ Теги](tags-registry.md)",
        ""
    ]
    
    # Стандартный маппинг эмодзи для доменов на случай, если они не указаны в _index.md
    emoji_map = {
        "gradostroitelstvo": "⚖️",
        "zemelnoe-pravo": "🌍",
        "zhilishnoe-pravo": "🏠",
        "sro": "🏗️"
    }
    
    # Сканируем директории первого уровня в topics/
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
            
            lines.append("---")
            lines.append("")
            
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

    with open(sidebar_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("[OK] _sidebar.md успешно сгенерирован на основе файловой структуры!")
    return True


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
