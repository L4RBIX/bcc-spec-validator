"""Правила на синтетических текстах (не на выданном документе): позитивные и негативные случаи."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from validator.doc import Doc
from validator.ingest import load
from validator.rules import (
    rule_duplicate_ids,
    rule_empty_sections,
    rule_http,
    rule_mixed_units,
    rule_placeholders,
    rule_unchecked_choices,
    rule_vague_words,
    rule_version_date,
    run_rules,
)
from validator.schema import Finding
from validator.verify import verify

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def doc(tmp_path):
    """Фабрика: Markdown-текст -> Doc через настоящий ingest."""

    def make(md: str) -> Doc:
        path = tmp_path / "doc.md"
        path.write_text(textwrap.dedent(md).strip() + "\n", encoding="utf-8")
        return Doc(load(path))

    return make


def assert_quotes_verbatim(d: Doc, findings: list[Finding]) -> None:
    kept, dropped = verify(findings, d.blocks)
    assert not [x for x in dropped if x.status != "duplicate"], dropped
    assert all(f.source == "rule" and f.confidence == 1.0 for f in kept)


# ---------------------------------------------------------------- 1. плейсхолдеры

PLACEHOLDERS = """
    # Док
    ## Общие параметры
    | Поле | Значение |
    | :--- | :--- |
    | Swagger | — |
    | Автор | TBD |
    | Host | Dev: a.test . Prod: — |
    | Владелец | Отдел продаж |

    ## Ответ
    | Parameter | Format | DB field |
    | :--- | :--- | :--- |
    | result | string | — |

    Срок внедрения TODO.
"""


def test_placeholders(doc):
    d = doc(PLACEHOLDERS)
    found = rule_placeholders(d)
    by_field = {f.problem.split("поле «")[1].split("»")[0]: f for f in found if "поле «" in f.problem}
    assert set(by_field) == {"Swagger", "Автор", "Host › Prod"}
    assert by_field["Swagger"].severity == "major"  # техническое поле
    assert by_field["Host › Prod"].severity == "major"
    assert by_field["Автор"].severity == "minor"
    sw = by_field["Swagger"]
    assert sw.problem == "В разделе «Общие параметры» поле «Swagger» не заполнено (стоит «—»)."
    assert sw.question == "Какое значение поля «Swagger» должно быть в разделе «Общие параметры»?"
    assert sw.options == ["Указать значение", "Пометить как «не применимо» с причиной"]
    assert sw.fix == "Заполнить поле «Swagger» или явно указать, почему оно не применимо."
    assert "разработчик" in sw.impact and "тестировщик" in sw.impact
    assert any("«TODO»" in f.problem for f in found)
    assert not any("result" in q for f in found for q in f.quotes)  # «—» в многоколоночной таблице не трогаем
    assert_quotes_verbatim(d, found)


# ---------------------------------------------------------------- 2. неотмеченные варианты и подписи


def test_unchecked_choices_and_empty_signatures(doc):
    d = doc(
        """
        # Док
        ## Ревью
        | Проверка | Выполнено |
        | :--- | :--- |
        | Требования проверены | Да / Нет |
        | Есть тесты | Да / Нет / Не требуется |
        ## Согласующие
        | Подразделение | ФИО | Подпись |
        | :--- | :--- | :--- |
        | | | |
        """
    )
    found = rule_unchecked_choices(d)
    assert [(f.severity, f.addressee) for f in found] == [("minor", "аналитик"), ("major", "BO")]
    assert "в 2 из 2 пунктов" in found[0].problem
    assert_quotes_verbatim(d, found)


def test_chosen_options_and_signed_table_are_clean(doc):
    d = doc(
        """
        # Док
        ## Ревью
        | Проверка | Выполнено |
        | :--- | :--- |
        | Требования проверены | Да |
        ## Согласующие
        | Подразделение | ФИО | Подпись |
        | :--- | :--- | :--- |
        | Продажи | Иванов И. И. | подписано |
        """
    )
    assert rule_unchecked_choices(d) == []


# ---------------------------------------------------------------- 3. пустые разделы


def test_empty_sections(doc):
    d = doc(
        """
        # Док
        ## Тестирование
        заполняются позже
        ## Безопасность
        ## Родитель
        ### Ребёнок
        Не используются.
        """
    )
    found = rule_empty_sections(d)
    assert [f.problem for f in found] == [
        "Раздел «Тестирование» не заполнен: вместо содержания стоит «заполняются позже».",
        "Раздел «Безопасность» не заполнен: после заголовка нет текста.",
    ]
    assert all(f.criterion == "set_complete" and f.scope == "set" for f in found)
    assert_quotes_verbatim(d, found)


# ---------------------------------------------------------------- 4. версия и дата


def test_version_and_date_missing(doc):
    found = rule_version_date(doc("# Док\n\nТекст требований без шапки."))
    assert len(found) == 1 and found[0].severity == "minor"
    assert found[0].problem == "В начале документа не указаны: версия и дата."


def test_version_explicitly_not_filled(doc):
    d = doc("# Док\n\nВерсия документа не заполнена.\n")
    found = rule_version_date(d)
    assert found[0].severity == "major" and found[0].quotes == ["Версия документа не заполнена."]
    assert_quotes_verbatim(d, found)


def test_version_and_date_present(doc):
    d = doc("# Док\n\n| Поле | Значение |\n| :--- | :--- |\n| Версия | 2.1 |\n| Дата | 2026-11-01 |\n")
    assert rule_version_date(d) == []


# ---------------------------------------------------------------- 5. размытые слова


def test_vague_words(doc):
    d = doc("# Док\n\nСистема отвечает быстро и т.д. Отчёт строится за 2 секунды.\n")
    found = rule_vague_words(d)
    assert len(found) == 1
    assert found[0].quotes == ["Система отвечает быстро и т.д. Отчёт строится за 2 секунды."]  # короткий блок целиком
    assert "«быстро», «и т.д.»" in found[0].problem
    assert_quotes_verbatim(d, found)


def test_precise_text_has_no_vague_words(doc):
    assert rule_vague_words(doc("# Док\n\nОтчёт строится за 2 секунды для 95% запросов.\n")) == []


# ---------------------------------------------------------------- 6. единицы


def test_mixed_currency_units(doc):
    d = doc("# Док\n## Данные\nСумма хранится в копейках.\n## Экран\nЛимит показывается в рублях.\n")
    found = rule_mixed_units(d)
    assert len(found) == 1 and found[0].criterion == "unambiguous" and len(found[0].quotes) == 2
    assert "«рубль» и «копейка»" in found[0].problem
    assert_quotes_verbatim(d, found)


def test_mixed_time_units_only_in_same_section(doc):
    same = doc("# Док\n## НФТ\nТаймаут 500 мс.\nОтвет за 2 сек.\n")
    assert len(rule_mixed_units(same)) == 1
    apart = doc("# Док\n## НФТ\nТаймаут 500 мс.\n## Сессия\nСессия живёт 30 мин.\n")
    assert rule_mixed_units(apart) == []


def test_single_currency_is_clean(doc):
    assert rule_mixed_units(doc("# Док\n\nЛимит 1 000 ₸, комиссия 50 тенге.\n")) == []


# ---------------------------------------------------------------- 7. HTTP


def test_get_with_mutation(doc):
    d = doc(
        """
        # Док
        ## API
        | Поле | Значение |
        | :--- | :--- |
        | Description | Сохранение настройки уведомлений |
        | Method | GET |
        """
    )
    found = rule_http(d)
    assert len(found) == 1
    f = found[0]
    assert (f.criterion, f.severity, f.addressee) == ("correct", "major", "архитектор")
    assert "метод GET описан для операции, которая меняет данные («Сохранение»)" in f.problem
    assert_quotes_verbatim(d, found)


@pytest.mark.parametrize(
    ("method", "description", "expected"),
    [("POST", "Сохранение настройки", 0), ("DELETE", "Удаление настройки", 0), ("DELETE", "Создание копии", 1)],
)
def test_method_semantics(doc, method, description, expected):
    d = doc(
        f"# Док\n## API\n| Поле | Значение |\n| :--- | :--- |\n| Description | {description} |\n| Method | {method} |\n"
    )
    assert len(rule_http(d)) == expected


def test_status_codes_in_plain_paragraphs(doc):
    """Замечание 2: коды статусов обычными абзацами, без заголовков-примеров."""
    d = doc(
        """
        # Док
        ## Методы
        Метод: POST /v1/orders

        200 — запрос выполнен успешно.

        400 — параметры заданы неверно.

        При отсутствии заказа сервис возвращает код 404.

        Пример ответа 409:

        ```json
        {"error": "conflict"}
        ```
        """
    )
    assert all(b.kind != "heading" or b.text in ("Док", "Методы") for b in d.blocks)
    found = rule_http(d)
    codes = sorted(f.problem.split("Код ответа ")[1][:3] for f in found)
    assert codes == ["404", "409"]
    assert all(f.criterion == "set_consistent" and len(f.quotes) >= 2 for f in found)
    assert_quotes_verbatim(d, found)


def test_declared_statuses_match_examples(doc):
    d = doc(
        """
        # Док
        ## API
        Метод: POST /v1/orders

        201 — заказ создан и возвращён в ответе.

        **201 Created**

        ```json
        {"id": 1}
        ```
        Сумма заказа до 500 000 тенге.
        """
    )
    assert rule_http(d) == []


def test_created_with_wrong_code(doc):
    d = doc("# Док\n## API\nМетод: POST /v1/x\n\n200. Successful — Created\n\n```json\n{}\n```\n")
    found = [f for f in rule_http(d) if "Created" in f.problem]
    assert len(found) == 1 and found[0].quotes == ["200. Successful — Created"]


def test_content_type_without_body(doc):
    d = doc("# Док\n## API\n### Request body\n* Content-Type: application/json.\n* Тело не используется.\n")
    found = rule_http(d)
    assert len(found) == 1 and found[0].criterion == "set_consistent" and len(found[0].quotes) == 2


def test_identifier_in_query(doc):
    d = doc(
        """
        # Док
        ## API
        ### Query-параметры
        | Parameter | Format | Description |
        | :--- | :--- | :--- |
        | accountId | string | Счёт клиента |
        | limit | integer | Размер страницы |
        ### Пример
        GET /api/statements?clientId=5&limit=10
        """
    )
    found = {
        f.problem.split("идентификатор «")[1].split("»")[0]: f for f in rule_http(d) if "идентификатор «" in f.problem
    }
    assert set(found) == {"accountId", "clientId"}
    assert all(f.addressee == "ИБ" and f.severity == "major" for f in found.values())


def test_no_api_section_no_http_findings(doc):
    assert rule_http(doc("# Док\n## Цели\nПоказать 404 на экране ошибки.\n")) == []


# ---------------------------------------------------------------- 8. дубли идентификаторов


def test_duplicate_ids(doc):
    d = doc("# Док\n## ФТ\n* ТР-1. Первое требование.\n* ТР-2. Второе.\n## НФТ\n* ТР-1. Третье требование.\n")
    found = rule_duplicate_ids(d)
    assert len(found) == 1 and found[0].criterion == "traceable" and len(found[0].quotes) == 2
    assert_quotes_verbatim(d, found)
    assert rule_duplicate_ids(doc("# Док\n* ТР-1. Первое.\n* ТР-2. Второе.\n")) == []


# ---------------------------------------------------------------- чистое ТЗ (замечание 3)


def test_clean_document_has_zero_findings_md():
    assert run_rules(load(FIXTURES / "clean.md")) == []


def test_clean_document_has_zero_findings_pdf(tmp_path):
    from md_to_pdf import convert

    pdf = tmp_path / "clean.pdf"
    convert(FIXTURES / "clean.md", pdf)
    assert run_rules(load(pdf)) == []


def test_every_finding_has_meaningful_texts(doc):
    """Замечание 4: у каждой находки заполнены все тексты, вопрос -- вопрос, есть варианты."""
    found = run_rules(doc(PLACEHOLDERS).blocks)
    assert found
    for f in found:
        assert f.problem and f.impact and f.fix and f.question.endswith("?")
        assert len(f.options) >= 2
        assert "обнаружен" not in f.problem.lower()
