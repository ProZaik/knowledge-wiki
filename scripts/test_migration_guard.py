#!/usr/bin/env python3
"""
Тесты для модуля migration_guard.py — Entity Extractor и Pre-Check.
Запуск: python -m pytest test_migration_guard.py -v
"""

import os
import sys
import tempfile

# Добавляем каталог скриптов в PATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from migration_guard import extract_entities, compare_entities, migration_precheck


# ===========================================================================
# Тесты extract_entities
# ===========================================================================

class TestExtractLawArticles:
    """Извлечение статей законов."""

    def test_simple_article(self):
        entities = extract_entities("Согласно ст. 49 ГрК РФ экспертиза обязательна.")
        arts = entities["law_articles"]
        assert len(arts) > 0, f"Не найдена 'ст. 49' в {arts}"
        assert any("49" in e for e in arts), f"Число 49 не в {arts}"

    def test_part_and_article(self):
        entities = extract_entities("В соответствии с ч. 17 ст. 51 ГрК РФ")
        arts = entities["law_articles"]
        assert len(arts) > 0, f"Не найдена 'ч. 17 ст. 51' в {arts}"
        assert any("51" in e for e in arts), f"Число 51 не в {arts}"

    def test_punkt_chast_article(self):
        entities = extract_entities("п. 10.2 ст. 1 ГрК РФ определяет")
        arts = entities["law_articles"]
        assert any("ст. 1" in e or "п. 10.2" in e for e in arts), \
            f"Не найдена 'п. 10.2 ст. 1' в {arts}"

    def test_decimal_article(self):
        entities = extract_entities("ст. 48.1 ГрК")
        arts = entities["law_articles"]
        assert any("48.1" in e for e in arts), \
            f"Не найдена '48.1' в {arts}"

    def test_gpk_article(self):
        entities = extract_entities("ст. 446 ГПК РФ")
        arts = entities["law_articles"]
        assert any("ст. 446" in e for e in arts), \
            f"Не найдена 'ст. 446' в {arts}"

    def test_part_range(self):
        """ч.17.2-17.4 ст.51"""
        entities = extract_entities("ч.17.2-17.4 ст.51 ГрК")
        arts = entities["law_articles"]
        assert len(arts) > 0, f"Не найдена ч.17.2 или ст.51 в {arts}"


class TestExtractCourtCases:
    """Извлечение номеров судебных дел."""

    def test_standard_case(self):
        entities = extract_entities("дело А38-1153/2024 подтвердило")
        assert any("А38-1153/2024" in e for e in entities["court_cases"]), \
            f"Не найдено 'А38-1153/2024' в {entities['court_cases']}"

    def test_es_case(self):
        entities = extract_entities("определение 308-ЭС24-20719 ВС РФ")
        assert any("308-ЭС24-20719" in e for e in entities["court_cases"]), \
            f"Не найдено '308-ЭС24-20719' в {entities['court_cases']}"

    def test_kg_case(self):
        entities = extract_entities("78-КГ25-9-К3")
        assert any("78-КГ25-9-К3" in e for e in entities["court_cases"]), \
            f"Не найдено '78-КГ25-9-К3' в {entities['court_cases']}"


class TestExtractRegulations:
    """Извлечение подзаконных актов."""

    def test_pp(self):
        entities = extract_entities("ПП № 703 устанавливает критерии")
        regs = entities["regulations"]
        assert any("703" in e for e in regs), f"Не найдено 'ПП 703' в {regs}"

    def test_gost(self):
        entities = extract_entities("ГОСТ 25957-83 определяет категории")
        regs = entities["regulations"]
        assert any("25957" in e for e in regs), f"Не найден 'ГОСТ 25957' в {regs}"

    def test_gsn(self):
        entities = extract_entities("ГСН 81-05-01-2001 о временных зданиях")
        regs = entities["regulations"]
        assert any("81-05-01" in e for e in regs), f"Не найден 'ГСН 81-05-01' в {regs}"

    def test_fz(self):
        entities = extract_entities("Федеральный закон 218-ФЗ")
        regs = entities["regulations"]
        assert any("218-ФЗ" in e.upper() for e in regs), f"Не найден '218-ФЗ' в {regs}"

    def test_fz_295(self):
        entities = extract_entities("295-ФЗ вводит изменения")
        regs = entities["regulations"]
        assert any("295-ФЗ" in e.upper() for e in regs), f"Не найден '295-ФЗ' в {regs}"

    def test_snip(self):
        entities = extract_entities("СНиП 3.02.01-87 нормирует")
        regs = entities["regulations"]
        assert any("3.02.01" in e for e in regs), f"Не найден СНиП в {regs}"


class TestExtractThresholds:
    """Извлечение числовых порогов."""

    def test_square_meters(self):
        entities = extract_entities("площадь не более 1500 м²")
        thresholds = entities["numeric_thresholds"]
        assert any("1500" in e for e in thresholds), f"Не найден '1500 м²' в {thresholds}"

    def test_kv(self):
        entities = extract_entities("напряжение ≤35 кВ")
        thresholds = entities["numeric_thresholds"]
        assert any("35" in e for e in thresholds), f"Не найден '≤35 кВ' в {thresholds}"

    def test_mpa(self):
        entities = extract_entities("давление ≤1.2 МПа")
        thresholds = entities["numeric_thresholds"]
        assert any("1.2" in e for e in thresholds), f"Не найден '≤1.2 МПа' в {thresholds}"

    def test_people(self):
        entities = extract_entities("более 50 человек единовременного пребывания")
        thresholds = entities["numeric_thresholds"]
        assert any("50" in e for e in thresholds), f"Не найден '50 человек' в {thresholds}"

    def test_years(self):
        entities = extract_entities("срок действия 3 года")
        thresholds = entities["numeric_thresholds"]
        assert any("3" in e for e in thresholds), f"Не найден '3 года' в {thresholds}"


# ===========================================================================
# Тесты compare_entities
# ===========================================================================

class TestCompareEntities:
    """Сравнение наборов сущностей."""

    def test_100_percent_coverage(self):
        old = {
            "law_articles": {"ст. 49 ГрК", "ч. 17 ст. 51"},
            "court_cases": {"А38-1153/2024"},
            "regulations": {"ПП 703"},
            "numeric_thresholds": {"1500 м²"},
        }
        new = dict(old)  # копия
        result = compare_entities(old, new)
        assert result["passed"] is True
        assert result["coverage_pct"] == 100.0

    def test_missing_entities(self):
        old = {
            "law_articles": {"ст. 49 ГрК", "ч. 17 ст. 51"},
            "court_cases": {"А38-1153/2024"},
            "regulations": {"ПП 703"},
            "numeric_thresholds": {"1500 м²"},
        }
        new = {
            "law_articles": {"ст. 49 ГрК"},
            "court_cases": set(),
            "regulations": {"ПП 703"},
            "numeric_thresholds": {"1500 м²"},
        }
        result = compare_entities(old, new)
        assert result["passed"] is False
        assert "ч. 17 ст. 51" in result["missing"]["law_articles"]
        assert "А38-1153/2024" in result["missing"]["court_cases"]

    def test_empty_old(self):
        """Если в старом файле нет сущностей → coverage 100%"""
        old = {
            "law_articles": set(),
            "court_cases": set(),
            "regulations": set(),
            "numeric_thresholds": set(),
        }
        new = {
            "law_articles": {"ст. 49 ГрК"},
            "court_cases": set(),
            "regulations": set(),
            "numeric_thresholds": set(),
        }
        result = compare_entities(old, new)
        assert result["passed"] is True
        assert result["coverage_pct"] == 100.0

    def test_precheck_reject(self):
        """coverage < 90% → passed = False"""
        old = {
            "law_articles": {"ст. 49", "ст. 51", "ст. 38", "ст. 48.1"},
            "court_cases": {"А38-1153/2024", "А45-18953/2016"},
            "regulations": {"ПП 703", "ПП 881", "ПП 1816", "ГОСТ 25957-83"},
            "numeric_thresholds": {"1500 м²"},
        }
        # Оставляем только 2 из 11 → ~18% coverage
        new = {
            "law_articles": {"ст. 49"},
            "court_cases": set(),
            "regulations": {"ПП 703"},
            "numeric_thresholds": set(),
        }
        result = compare_entities(old, new)
        assert result["passed"] is False
        assert result["coverage_pct"] < 90.0


# ===========================================================================
# Тесты migration_precheck
# ===========================================================================

class TestMigrationPrecheck:
    """Интеграционные тесты migration_precheck."""

    def test_identical_content(self):
        """Одинаковый контент → 100% coverage"""
        content = """
# Экспертиза ПД

Согласно ст. 49 ГрК РФ экспертиза обязательна.
Дело А38-1153/2024 подтвердило это.
ПП № 703 устанавливает критерии.
Площадь не более 1500 м².
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_path = f.name

        try:
            result = migration_precheck(tmp_path, content)
            assert result["passed"] is True
            assert result["coverage_pct"] == 100.0
        finally:
            os.unlink(tmp_path)

    def test_missing_content_rejected(self):
        """Неполный контент → rejected"""
        old_content = """
# Тема

ст. 49 ГрК, ч. 17 ст. 51, ст. 38 ГрК, ст. 48.1 ГрК
Дело А38-1153/2024, 308-ЭС24-20719
ПП № 703, ПП № 881, ГОСТ 25957-83
Площадь не более 1500 м², ≤35 кВ
"""
        new_content = """
# Тема
ст. 49 ГрК
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(old_content)
            tmp_path = f.name

        try:
            result = migration_precheck(tmp_path, new_content)
            assert result["passed"] is False
            assert result["coverage_pct"] < 90.0
            assert len(result["report"]) > 0
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
