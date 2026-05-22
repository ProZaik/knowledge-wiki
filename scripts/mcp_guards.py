"""
Модуль защитных функций (guards) для MCP-сервера wiki.

Содержит утилиты для:
- Санитизации входящего markdown-контента
- Нормализации тегов
- Валидации длины контента
- Автоматического коммита в git
"""

import os
import re
import subprocess
import glob
from typing import Optional

# Корневая директория проекта — на уровень выше scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_md_file(page_name: str) -> Optional[str]:
    """
    Ищет .md файл по имени страницы в директориях topics/ и sources/.

    Выполняет рекурсивный поиск по всем поддиректориям.
    Сравнение идёт без учёта регистра и расширения.

    Аргументы:
        page_name: имя страницы (например, 'ГПЗУ' или 'gpzu')

    Возвращает:
        Относительный путь от корня проекта (например, 'topics/gradostroitelstvo/gpzu.md')
        или None, если файл не найден.
    """
    # Нормализуем имя для поиска (в нижний регистр)
    target = page_name.lower().strip()

    # Ищем во всех поддиректориях topics/ и sources/
    for search_dir in ["topics", "sources"]:
        full_search = os.path.join(ROOT, search_dir)
        if not os.path.isdir(full_search):
            continue

        # Рекурсивно обходим все .md файлы
        for dirpath, _dirnames, filenames in os.walk(full_search):
            for fname in filenames:
                if not fname.endswith(".md"):
                    continue
                # Сравниваем имя файла без расширения
                basename = fname[:-3].lower()
                if basename == target:
                    # Формируем относительный путь от корня проекта
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, ROOT)
                    # Приводим к формату с прямыми слэшами
                    return rel_path.replace("\\", "/")

    return None


def _convert_obsidian_links(text: str) -> str:
    """
    Конвертирует Obsidian-ссылки [[...]] в стандартный markdown.

    Обрабатывает два формата:
    - [[PageName]] → [PageName](path) или просто PageName
    - [[PageName|Display Text]] → [Display Text](path) или просто Display Text
    """
    def _replace_link(match: re.Match) -> str:
        """Обработчик одной Obsidian-ссылки."""
        inner = match.group(1)

        # Разделяем по | если есть отображаемый текст
        if "|" in inner:
            page_name, display_text = inner.split("|", 1)
            page_name = page_name.strip()
            display_text = display_text.strip()
        else:
            page_name = inner.strip()
            display_text = page_name

        # Пытаемся найти файл
        found_path = _find_md_file(page_name)

        if found_path:
            return f"[{display_text}]({found_path})"
        else:
            # Файл не найден — просто убираем скобки
            return display_text

    # Паттерн для Obsidian-ссылок: [[...]] (не жадный, без переносов строк)
    pattern = r"\[\[([^\[\]]+?)\]\]"
    return re.sub(pattern, _replace_link, text)


def _strip_dangerous_html(text: str) -> str:
    """
    Удаляет опасные HTML-теги вместе с содержимым.
    Конвертирует безопасные HTML-теги в markdown-эквиваленты.

    Опасные теги (удаляются полностью с содержимым):
        script, style, iframe, object, embed, form, input

    Безопасные теги (конвертируются в markdown):
        b/strong → **text**
        i/em → *text*
        br → \\n
        Остальные — просто удаляем теги, оставляем содержимое
    """
    # 1. Удаляем опасные теги вместе с содержимым
    dangerous_tags = ["script", "style", "iframe", "object", "embed", "form"]
    for tag in dangerous_tags:
        # Удаляем парные теги с содержимым (DOTALL для многострочности)
        pattern = re.compile(
            rf"<\s*{tag}[^>]*>.*?<\s*/\s*{tag}\s*>",
            re.DOTALL | re.IGNORECASE
        )
        text = pattern.sub("", text)

    # Удаляем самозакрывающиеся опасные теги (input и подобные)
    selfclosing_dangerous = ["input", "embed", "object", "iframe"]
    for tag in selfclosing_dangerous:
        pattern = re.compile(
            rf"<\s*{tag}[^>]*/?\s*>",
            re.IGNORECASE
        )
        text = pattern.sub("", text)

    # 2. Конвертируем безопасные теги в markdown

    # <b>text</b> и <strong>text</strong> → **text**
    for tag in ["b", "strong"]:
        pattern = re.compile(
            rf"<\s*{tag}[^>]*>(.*?)<\s*/\s*{tag}\s*>",
            re.DOTALL | re.IGNORECASE
        )
        text = pattern.sub(r"**\1**", text)

    # <i>text</i> и <em>text</em> → *text*
    for tag in ["i", "em"]:
        pattern = re.compile(
            rf"<\s*{tag}[^>]*>(.*?)<\s*/\s*{tag}\s*>",
            re.DOTALL | re.IGNORECASE
        )
        text = pattern.sub(r"*\1*", text)

    # <br> и <br/> → перенос строки
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)

    # 3. Убираем оставшиеся безопасные HTML-теги, сохраняя содержимое
    safe_tags = [
        "p", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "a", "code", "pre", "span", "div",
        "table", "tr", "td", "th", "thead", "tbody",
    ]
    for tag in safe_tags:
        # Убираем открывающие теги
        text = re.sub(
            rf"<\s*{tag}[^>]*>",
            "",
            text,
            flags=re.IGNORECASE
        )
        # Убираем закрывающие теги
        text = re.sub(
            rf"<\s*/\s*{tag}\s*>",
            "",
            text,
            flags=re.IGNORECASE
        )

    return text


def _normalize_relative_paths(text: str) -> str:
    """
    Нормализует относительные пути, убирая префиксы ../ .

    Примеры:
        ../../sources/file.md → sources/file.md
        ../topics/file.md → topics/file.md
    """
    # Заменяем пути в markdown-ссылках ](../../path) и просто в тексте
    # Паттерн: одна или несколько последовательностей ../ перед sources/ или topics/
    pattern = r"(?:\.\./)+((sources|topics|templates|inbox)/)"
    text = re.sub(pattern, r"\1", text)
    return text


def _clean_blank_lines(text: str) -> str:
    """
    Убирает избыточные пустые строки.
    Более 2 последовательных пустых строк сокращаются до 2.
    """
    # Заменяем 3+ последовательных пустых строки на 2
    return re.sub(r"\n{4,}", "\n\n\n", text)


def _build_topic_index() -> dict[str, str]:
    """
    Строит индекс всех тем: {название_темы_lower → относительный_путь}.

    Считывает YAML-шапки всех .md файлов в topics/ и собирает:
    - title из frontmatter
    - Заголовок H1 (# ...) если нет title
    - Имя файла без расширения как fallback

    Возвращает:
        Словарь {название_в_нижнем_регистре: 'topics/domain/file.md'}
    """
    index: dict[str, str] = {}
    topics_dir = os.path.join(ROOT, "topics")

    if not os.path.isdir(topics_dir):
        return index

    for dirpath, _dirnames, filenames in os.walk(topics_dir):
        for fname in filenames:
            if not fname.endswith(".md") or fname.startswith("_"):
                continue

            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, ROOT).replace("\\", "/")

            title = None
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read(2000)  # Читаем только начало для скорости

                # Пытаемся извлечь title из YAML frontmatter
                fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
                if fm_match:
                    import yaml
                    try:
                        meta = yaml.safe_load(fm_match.group(1))
                        if isinstance(meta, dict):
                            title = meta.get("title")
                    except Exception:
                        pass

                # Fallback: заголовок H1
                if not title:
                    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
                    if h1_match:
                        title = h1_match.group(1).strip()

                # Fallback: имя файла
                if not title:
                    title = fname[:-3].replace("-", " ")

            except Exception:
                continue

            if title:
                index[title.lower()] = rel_path

    return index


def autolink(text: str) -> str:
    """
    Автоматически расставляет ссылки на существующие темы wiki.

    Сканирует текст на упоминания известных тем (по их title из YAML-шапок)
    и оборачивает первое вхождение каждого термина в markdown-ссылку.

    Не линкует:
    - Текст внутри уже существующих markdown-ссылок [...](...) 
    - Текст внутри заголовков (# ...)
    - Текст внутри блоков кода (``` ... ```)
    - Текст внутри YAML frontmatter (--- ... ---)
    - Повторные вхождения одного и того же термина (линкуется только первое)

    Аргументы:
        text: markdown-текст для обработки

    Возвращает:
        Текст с расставленными ссылками.
    """
    topic_index = _build_topic_index()
    if not topic_index:
        return text

    # Сортируем по длине (длинные термины первыми, чтобы "разрешение на строительство"
    # матчилось раньше чем "строительство")
    sorted_terms = sorted(topic_index.keys(), key=len, reverse=True)

    # Отделяем YAML frontmatter — не линкуем в нём
    frontmatter = ""
    body = text
    fm_match = re.match(r"^(---\s*\n.*?\n---\s*\n?)", text, re.DOTALL)
    if fm_match:
        frontmatter = fm_match.group(1)
        body = text[len(frontmatter):]

    # Отделяем блоки кода — не линкуем в них
    code_blocks: list[str] = []
    code_pattern = re.compile(r"(```.*?```)", re.DOTALL)

    def _save_code(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f"__CODE_BLOCK_{len(code_blocks) - 1}__"

    body = code_pattern.sub(_save_code, body)

    # Множество уже залинкованных терминов (линкуем только первое вхождение)
    linked: set[str] = set()

    for term_lower in sorted_terms:
        if term_lower in linked:
            continue

        rel_path = topic_index[term_lower]

        # Паттерн: ищем термин целым словом, НЕ внутри [...] и НЕ в строке-заголовке
        # Используем case-insensitive поиск
        pattern = re.compile(
            r"(?<!\[)"           # Не внутри квадратных скобок (начало)
            r"(?<!\()"           # Не внутри круглых скобок (путь ссылки)
            r"\b("
            + re.escape(term_lower)
            + r")\b"
            r"(?!\])"            # Не внутри квадратных скобок (конец)
            r"(?!\()",           # Не перед круглой скобкой
            re.IGNORECASE
        )

        def _replace_first(match: re.Match) -> str:
            """Заменяет только первое вхождение."""
            original = match.group(0)
            line_start = body.rfind("\n", 0, match.start()) + 1
            line = body[line_start:match.start()]

            # Не линкуем в заголовках
            if line.lstrip().startswith("#"):
                return original

            # Не линкуем если уже внутри markdown-ссылки
            before = body[max(0, match.start() - 1):match.start()]
            if before == "[":
                return original

            return f"[{original}]({rel_path})"

        new_body, count = pattern.subn(_replace_first, body, count=1)
        if count > 0:
            body = new_body
            linked.add(term_lower)

    # Восстанавливаем блоки кода
    for i, block in enumerate(code_blocks):
        body = body.replace(f"__CODE_BLOCK_{i}__", block)

    return frontmatter + body


def sanitize_content(text: str) -> str:
    """
    Санитизирует входящий markdown-контент перед записью в wiki.

    Выполняет последовательно:
    1. Конвертация Obsidian-ссылок [[...]] в стандартный markdown
    2. Удаление опасных HTML-тегов, конвертация безопасных в markdown
    3. Нормализация относительных путей (убираем ../)
    4. Очистка избыточных пустых строк
    5. Автолинкер: расстановка ссылок на существующие темы wiki

    Аргументы:
        text: исходный markdown-текст

    Возвращает:
        Очищенный и нормализованный markdown-текст.
    """
    # Шаг 1: Конвертация Obsidian-ссылок
    text = _convert_obsidian_links(text)

    # Шаг 2: Обработка HTML-тегов
    text = _strip_dangerous_html(text)

    # Шаг 3: Нормализация относительных путей
    text = _normalize_relative_paths(text)

    # Шаг 4: Очистка пустых строк
    text = _clean_blank_lines(text)

    # Шаг 5: Автоматическая расстановка ссылок на темы
    text = autolink(text)

    return text


def normalize_tags(
    tags: list[str],
    allowed_tags: set
) -> tuple[list[str], list[str]]:
    """
    Нормализует теги, пытаясь сопоставить невалидные с ближайшими допустимыми.

    Логика поиска для каждого тега:
    1. Если тег уже в allowed_tags → оставляем как есть
    2. Пробуем сопоставление по префиксу: последовательно отбрасываем
       суффиксы после '-' или '.'. Например: 'ГрК-55.8' → 'ГрК-55' → 'ГрК'
    3. Если не найден — пробуем поиск без учёта регистра
    4. Если всё ещё не найден — добавляем предупреждение, пропускаем тег

    Результат дедуплицируется с сохранением порядка.

    Аргументы:
        tags: список тегов для нормализации
        allowed_tags: множество допустимых тегов

    Возвращает:
        Кортеж (normalized_tags, warnings):
        - normalized_tags: список валидных/нормализованных тегов
        - warnings: список предупреждений о непризнанных тегах
    """
    normalized: list[str] = []
    warnings: list[str] = []

    # Словарь для поиска без учёта регистра: ключ — нижний регистр, значение — оригинал
    lower_map: dict[str, str] = {}
    for allowed in allowed_tags:
        lower_map[allowed.lower()] = allowed

    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue

        # 1. Точное совпадение
        if tag in allowed_tags:
            normalized.append(tag)
            continue

        # 2. Сопоставление по префиксу — последовательно отбрасываем суффиксы
        found = False
        candidate = tag
        while True:
            # Ищем последний разделитель (- или .)
            last_dash = candidate.rfind("-")
            last_dot = candidate.rfind(".")
            last_sep = max(last_dash, last_dot)

            if last_sep <= 0:
                # Разделителей больше нет
                break

            candidate = candidate[:last_sep]
            if candidate in allowed_tags:
                normalized.append(candidate)
                found = True
                break

        if found:
            continue

        # 3. Поиск без учёта регистра (по исходному тегу)
        tag_lower = tag.lower()
        if tag_lower in lower_map:
            normalized.append(lower_map[tag_lower])
            continue

        # 4. Не найден — предупреждение
        warnings.append(f"Тег '{tag}' не найден в реестре допустимых тегов и пропущен")

    # Дедупликация с сохранением порядка
    seen: set[str] = set()
    deduped: list[str] = []
    for t in normalized:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    return deduped, warnings


def validate_content_length(
    content: str,
    min_chars: int = 200
) -> tuple[bool, str]:
    """
    Проверяет, что основной текст (без YAML-фронтматтера) содержит
    не менее min_chars символов.

    Перед подсчётом удаляются:
    - YAML-фронтматтер (блок между --- ... ---)
    - Markdown-заголовки (строки, начинающиеся с #)
    - Ведущие/завершающие пробельные символы

    Аргументы:
        content: полный текст заметки (включая фронтматтер)
        min_chars: минимальное количество символов (по умолчанию 200)

    Возвращает:
        Кортеж (is_valid, error_message):
        - is_valid: True, если контент достаточной длины
        - error_message: пустая строка при успехе, описание ошибки при провале
    """
    text = content

    # Удаляем YAML-фронтматтер (блок между --- в начале файла)
    frontmatter_pattern = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)
    text = frontmatter_pattern.sub("", text)

    # Удаляем строки с markdown-заголовками
    text = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.MULTILINE)

    # Удаляем пробельные символы для подсчёта
    text = text.strip()

    char_count = len(text)

    if char_count >= min_chars:
        return True, ""
    else:
        return (
            False,
            f"Контент слишком короткий: {char_count} символов "
            f"(минимум {min_chars}). Добавьте больше содержательного текста."
        )


def auto_git_commit(
    root: str,
    files: list[str],
    message: str
) -> dict:
    """
    Выполняет git add и git commit для указанных файлов.

    Использует 'git add -A' для добавления всех изменений
    (включая обновления sidebar/index), затем коммитит с указанным сообщением.

    Аргументы:
        root: путь к корневой директории репозитория
        files: список относительных путей файлов (для информации;
               фактически добавляются все изменения через -A)
        message: сообщение коммита

    Возвращает:
        Словарь с результатом:
        - success (bool): True при успехе, False при ошибке
        - output (str): стандартный вывод команд git
        - error (str): текст ошибки (пустой при успехе)
    """
    result = {
        "success": False,
        "output": "",
        "error": "",
    }

    # Проверяем, доступен ли git
    try:
        version_proc = subprocess.run(
            ["git", "--version"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        if version_proc.returncode != 0:
            result["error"] = "Git не установлен или недоступен в PATH"
            return result
    except FileNotFoundError:
        result["error"] = "Git не найден. Убедитесь, что git установлен и доступен в PATH."
        return result
    except Exception as e:
        result["error"] = f"Ошибка при проверке git: {e}"
        return result

    # Проверяем, что это git-репозиторий
    try:
        status_proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        if status_proc.returncode != 0:
            result["error"] = f"Директория '{root}' не является git-репозиторием"
            return result
    except Exception as e:
        result["error"] = f"Ошибка при проверке репозитория: {e}"
        return result

    output_parts = []

    # Шаг 1: git add -A (добавляем все изменения)
    try:
        add_proc = subprocess.run(
            ["git", "add", "-A"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if add_proc.returncode != 0:
            result["error"] = f"Ошибка при git add: {add_proc.stderr.strip()}"
            result["output"] = add_proc.stdout.strip()
            return result
        if add_proc.stdout.strip():
            output_parts.append(add_proc.stdout.strip())
    except Exception as e:
        result["error"] = f"Ошибка при выполнении git add: {e}"
        return result

    # Шаг 2: git commit -m "message"
    try:
        commit_proc = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if commit_proc.returncode != 0:
            stderr = commit_proc.stderr.strip()
            stdout = commit_proc.stdout.strip()
            # Если нечего коммитить — это не критическая ошибка
            if "nothing to commit" in stdout or "nothing to commit" in stderr:
                result["success"] = True
                result["output"] = "Нет изменений для коммита"
                return result
            result["error"] = f"Ошибка при git commit: {stderr or stdout}"
            result["output"] = stdout
            return result

        output_parts.append(commit_proc.stdout.strip())
    except Exception as e:
        result["error"] = f"Ошибка при выполнении git commit: {e}"
        return result

    # Успех
    result["success"] = True
    result["output"] = "\n".join(output_parts)
    return result
