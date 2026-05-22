#!/usr/bin/env python3
"""Проверяет все источники в sources/ на корректность структуры и метаданных."""
import os, re, yaml, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCES = os.path.join(ROOT, 'sources')
VALID_TYPES = ['письмо органа', 'судебный акт', 'статья', 'нормативный акт']

total = 0
ok_count = 0
problems = []
type_counts = {}
tag_set = set()
sizes = []

for fn in sorted(os.listdir(SOURCES)):
    if not fn.endswith('.md') or fn.startswith('_'):
        continue
    total += 1
    fp = os.path.join(SOURCES, fn)
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()

    issues = []
    meta = {}

    # 1. YAML frontmatter
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        issues.append('НЕТ YAML шапки')
    else:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except Exception as e:
            issues.append(f'YAML ошибка: {e}')
            meta = {}

    if meta:
        # title
        if not meta.get('title'):
            issues.append('нет title')
        # type
        doc_type = meta.get('type', '')
        if not doc_type:
            issues.append('нет type')
        elif doc_type not in VALID_TYPES:
            issues.append(f'неизвестный type: {doc_type!r}')
        else:
            type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
        # status
        if not meta.get('status'):
            issues.append('нет status')
        # tags
        tags = meta.get('tags', [])
        if not tags:
            issues.append('нет tags')
        elif isinstance(tags, list):
            tag_set.update(str(t) for t in tags)
        # date
        if not meta.get('date') and not meta.get('date_adopted'):
            issues.append('нет date/date_adopted')

    # 2. Content body
    body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, count=1, flags=re.DOTALL)
    if len(body.strip()) < 100:
        issues.append(f'слишком мало текста ({len(body.strip())} симв.)')
    sizes.append(len(content))

    # 3. Has sections
    if '## ' not in content:
        issues.append('нет секций (## заголовков)')

    if issues:
        problems.append((fn, issues))
    else:
        ok_count += 1

# Отчёт
print("=" * 65)
print("  ПОЛНАЯ ПРОВЕРКА ИСТОЧНИКОВ")
print("=" * 65)
print(f"  Всего файлов:    {total}")
print(f"  Без проблем:     {ok_count}")
print(f"  С проблемами:    {len(problems)}")
print(f"  Уникальных тегов: {len(tag_set)}")
print(f"  Общий размер:    {sum(sizes)//1024} KB")
print()
print("  ПО ТИПАМ:")
for t in VALID_TYPES:
    c = type_counts.get(t, 0)
    emoji = {'письмо органа': '📜', 'судебный акт': '⚖️', 'статья': '📝', 'нормативный акт': '📋'}.get(t, '📄')
    print(f"    {emoji} {t}: {c}")
unknown = total - sum(type_counts.values())
if unknown > 0:
    print(f"    ❓ без типа / неизвестный: {unknown}")
print()

if problems:
    print("  ПРОБЛЕМНЫЕ ФАЙЛЫ:")
    for fn, issues in problems:
        print(f"    ❌ {fn}")
        for i in issues:
            print(f"       └ {i}")
    print()
else:
    print("  ✅ ВСЕ ФАЙЛЫ В ПОРЯДКЕ!")
    print()

# Список всех файлов
print("  ПОЛНЫЙ СПИСОК:")
for fn in sorted(os.listdir(SOURCES)):
    if not fn.endswith('.md') or fn.startswith('_'):
        continue
    fp = os.path.join(SOURCES, fn)
    size = os.path.getsize(fp)
    status = "✅" if fn not in [p[0] for p in problems] else "❌"
    print(f"    {status} {fn:55s} {size:>6,d} байт")
print()
print("=" * 65)
