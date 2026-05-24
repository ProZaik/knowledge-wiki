#!/usr/bin/env python3
"""
migration_guard.py — модуль автоматической проверки полноты миграции wiki-заметок.

Извлекает из markdown-текста юридические сущности (статьи законов, номера дел,
подзаконные акты, числовые пороги) и сравнивает старый и новый файлы, формируя
отчёт о покрытии.

Зависимости: только стандартная библиотека (os, re).
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Вспомогательные утилиты
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    """Нормализует извлечённое значение: strip, сжатие пробелов."""
    return re.sub(r'\s+', ' ', value.strip())


def _normalize_regulation(value: str) -> str:
    """Нормализует подзаконный акт: uppercase, сжатие пробелов."""
    return re.sub(r'\s+', ' ', value.strip()).upper()


# ---------------------------------------------------------------------------
# Функция 1: extract_entities
# ---------------------------------------------------------------------------

def extract_entities(text: str) -> dict:
    """Извлекает из markdown-текста 4 класса юридических сущностей.

    Классы:
      - law_articles   — статьи законов (ст., ч., п.)
      - court_cases    — номера судебных дел
      - regulations    — подзаконные акты, ГОСТы, ФЗ
      - numeric_thresholds — числовые пороги/лимиты

    Args:
        text: markdown-текст для анализа.

    Returns:
        Словарь с ключами law_articles, court_cases, regulations,
        numeric_thresholds — каждое значение — set нормализованных строк.
    """
    law_articles = _extract_law_articles(text)
    court_cases = _extract_court_cases(text)
    regulations = _extract_regulations(text)
    numeric_thresholds = _extract_numeric_thresholds(text)

    return {
        "law_articles": law_articles,
        "court_cases": court_cases,
        "regulations": regulations,
        "numeric_thresholds": numeric_thresholds,
    }


def _extract_law_articles(text: str) -> set:
    """Извлекает ссылки на статьи законов (п., ч., ст. с необязательным кодексом).

    Примеры:
      - ст. 49 ГрК
      - ч. 17 ст. 51
      - п. 10.2 ст. 1 ГрК
      - ч.17.2-17.4 ст.51
      - п. 6 ч. 2
      - ч. 3.3
      - ст. 48.1
    """
    # Отдельные паттерны для надёжного извлечения
    patterns = [
        # Полная ссылка: п. X ч. Y ст. Z Кодекс
        re.compile(
            r'п\.?\s*\d+(?:\.\d+)?'
            r'\s+ч\.?\s*\d+(?:\.\d+)?'
            r'\s+ст\.?\s*\d+(?:\.\d+)?'
            r'(?:\s+[А-Яа-яA-Za-z]+(?:\s+[А-Яа-яA-Za-z]+)?)?',
            re.UNICODE
        ),
        # ч. Y ст. Z Кодекс (с опциональным диапазоном)
        re.compile(
            r'ч\.?\s*\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?'
            r'\s+ст\.?\s*\d+(?:\.\d+)?'
            r'(?:\s+[А-Яа-яA-Za-z]+(?:\s+[А-Яа-яA-Za-z]+)?)?',
            re.UNICODE
        ),
        # ст. Z Кодекс (самый частый)
        re.compile(
            r'ст\.?\s*\d+(?:\.\d+)?'
            r'(?:\s+[А-Яа-яA-Za-z]+(?:\s+[А-Яа-яA-Za-z]+)?)?',
            re.UNICODE
        ),
        # ч. Y без ст. (например, "ч. 3.3")
        re.compile(
            r'ч\.?\s*\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?',
            re.UNICODE
        ),
        # п. X ч. Y без ст.
        re.compile(
            r'п\.?\s*\d+(?:\.\d+)?'
            r'\s+ч\.?\s*\d+(?:\.\d+)?',
            re.UNICODE
        ),
    ]
    results = set()
    for pat in patterns:
        for m in pat.finditer(text):
            raw = m.group(0).strip()
            if raw:
                results.add(_normalize(raw))
    return results


def _extract_court_cases(text: str) -> set:
    """Извлекает номера судебных дел.

    Форматы:
      - А38-1153/2024       (стандартные арбитражные)
      - 308-ЭС24-20719     (ВС ЭС-номера)
      - 78-КГ25-9-К3        (КГ-номера)
    """
    patterns = [
        re.compile(r'[АA]\d{1,3}-\d+/\d{4}'),                 # А38-1153/2024
        re.compile(r'\d+-[ЭЕ][СC]\d{2}-\d+'),                 # 308-ЭС24-20719
        re.compile(r'\d+-КГ\d{2}-\d+-К\d'),                    # 78-КГ25-9-К3
    ]
    results = set()
    for pat in patterns:
        for m in pat.finditer(text):
            results.add(_normalize(m.group(0)))
    return results


def _extract_regulations(text: str) -> set:
    """Извлекает подзаконные акты, ГОСТы, ФЗ.

    Форматы:
      - ПП Правительства РФ № 703
      - Постановление Правительства РФ от 05.03.2007
      - ГОСТ 25957-83, СП 54.13330, СНиП 2.08.01-89
      - 190-ФЗ, 342-фз
    """
    patterns = [
        # ПП / Постановление (с опциональными «Правительства», «РФ», «№» / «от»)
        re.compile(
            r'(?:ПП|Постановление)\s*'
            r'(?:Правительства\s*)?'
            r'(?:РФ\s*)?'
            r'(?:№\s*|от\s*)?'
            r'\d[\d.\-/]*',
            re.UNICODE
        ),
        # ГОСТы / СНиПы / СП / ГСН
        re.compile(r'(?:ГОСТ|ГСН|СП|СНиП)\s*\d[\d.\-]*', re.UNICODE),
        # Федеральные законы (оба регистра)
        re.compile(r'\d+-[ФфFf][ЗзZz]'),
    ]
    results = set()
    for pat in patterns:
        for m in pat.finditer(text):
            results.add(_normalize_regulation(m.group(0)))
    return results


def _extract_numeric_thresholds(text: str) -> set:
    """Извлекает числовые пороги и лимиты с единицами измерения.

    Форматы:
      - ≤35 кВ, до 1500 м², не более 12 этажей, свыше 50 МПа
      - 1500 м², 100 мм, 10 м
      - 5 лет, 200 человек, 6 месяцев
    """
    patterns = [
        # Числа с оператором сравнения/предлогом + единица
        re.compile(
            r'(?:≤|≥|>|<|до|не более|не менее|свыше)\s*'
            r'[\d.,]+\s*'
            r'(?:м²|кВ|МПа|°[CС]|мм|руб|млн|млрд|'
            r'этаж[а-я]*|блок[а-я]*|метр[а-я]*)',
            re.UNICODE
        ),
        # Числа с единицами без оператора
        re.compile(
            r'[\d.,]+\s*(?:м²|кВ|МПа|°[CС]|мм\b|м\b)',
            re.UNICODE
        ),
        # Числа с временны́ми/людскими единицами
        re.compile(
            r'\d+\s*(?:человек|лет|года|год|месяц[а-я]*)',
            re.UNICODE
        ),
    ]
    results = set()
    for pat in patterns:
        for m in pat.finditer(text):
            results.add(_normalize(m.group(0)))
    return results


# ---------------------------------------------------------------------------
# Функция 2: compare_entities
# ---------------------------------------------------------------------------

def compare_entities(old_entities: dict, new_entities: dict) -> dict:
    """Сравнивает сущности старого и нового файлов.

    Для каждой категории вычисляет:
      - missing — есть в старом, нет в новом
      - added   — есть в новом, нет в старом

    Общий coverage = (total_old - total_missing) / total_old * 100.

    Args:
        old_entities: результат extract_entities для старого файла.
        new_entities: результат extract_entities для нового файла.

    Returns:
        Словарь:
          missing      — {category: set} пропущенных сущностей
          added        — {category: set} добавленных сущностей
          coverage_pct — float процент покрытия
          passed       — bool (coverage >= 90)
    """
    categories = ["law_articles", "court_cases", "regulations", "numeric_thresholds"]

    missing = {}
    added = {}
    total_old = 0
    total_missing = 0

    for cat in categories:
        old_set = old_entities.get(cat, set())
        new_set = new_entities.get(cat, set())
        cat_missing = old_set - new_set
        cat_added = new_set - old_set
        missing[cat] = cat_missing
        added[cat] = cat_added
        total_old += len(old_set)
        total_missing += len(cat_missing)

    if total_old == 0:
        coverage_pct = 100.0
    else:
        coverage_pct = (total_old - total_missing) / total_old * 100.0

    return {
        "missing": missing,
        "added": added,
        "coverage_pct": round(coverage_pct, 2),
        "passed": coverage_pct >= 90.0,
    }


# ---------------------------------------------------------------------------
# Функция 3: migration_precheck
# ---------------------------------------------------------------------------

def migration_precheck(old_path: str, new_content: str) -> dict:
    """Оркестратор пре-чека миграции.

    1. Читает файл old_path и извлекает сущности.
    2. Извлекает сущности из new_content.
    3. Сравнивает и формирует human-readable отчёт.

    Args:
        old_path: путь к исходному (старому) markdown-файлу.
        new_content: текст нового (мигрированного) файла.

    Returns:
        Словарь:
          passed            — bool
          coverage_pct      — float
          old_entities_count — int общее кол-во сущностей в оригинале
          new_entities_count — int общее кол-во сущностей в новом файле
          missing_entities  — {category: list} пропущенных сущностей
          report            — str человекочитаемый отчёт
    """
    # 1. Читаем старый файл
    with open(old_path, "r", encoding="utf-8") as f:
        old_text = f.read()

    # 2. Извлекаем сущности
    old_entities = extract_entities(old_text)
    new_entities = extract_entities(new_content)

    # 3. Сравниваем
    comparison = compare_entities(old_entities, new_entities)

    # Подсчёт общего числа сущностей
    old_count = sum(len(v) for v in old_entities.values())
    new_count = sum(len(v) for v in new_entities.values())

    # Преобразуем missing sets → sorted lists для отчёта
    missing_lists = {
        cat: sorted(items) for cat, items in comparison["missing"].items()
    }

    # 4. Формируем отчёт
    passed = comparison["passed"]
    coverage = comparison["coverage_pct"]
    status = "✅ ПРОЙДЕН" if passed else "❌ ОТКЛОНЁН"

    report_lines = [
        "=== Пре-чек миграции ===",
        f"Источник: {old_path}",
        f"Сущностей в оригинале: {old_count}",
        f"Сущностей в новом файле: {new_count}",
        f"Покрытие: {coverage}%",
        f"Статус: {status}",
    ]

    # Блок пропущенных сущностей (только непустые категории)
    cat_labels = {
        "law_articles": "Статьи",
        "court_cases": "Дела",
        "regulations": "НПА",
        "numeric_thresholds": "Пороги",
    }
    has_missing = any(len(v) > 0 for v in missing_lists.values())
    if has_missing:
        report_lines.append("")
        report_lines.append("Пропущенные сущности:")
        for cat, label in cat_labels.items():
            items = missing_lists.get(cat, [])
            if items:
                report_lines.append(f"  {label}: {', '.join(items)}")

    report = "\n".join(report_lines)

    return {
        "passed": passed,
        "coverage_pct": coverage,
        "old_entities_count": old_count,
        "new_entities_count": new_count,
        "missing_entities": missing_lists,
        "report": report,
    }


# ---------------------------------------------------------------------------
# CLI-интерфейс для отладки
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Использование: python migration_guard.py <old_file> <new_file>")
        sys.exit(1)

    old_file = sys.argv[1]
    new_file = sys.argv[2]

    with open(new_file, "r", encoding="utf-8") as f:
        new_text = f.read()

    result = migration_precheck(old_file, new_text)
    print(result["report"])
    sys.exit(0 if result["passed"] else 1)
