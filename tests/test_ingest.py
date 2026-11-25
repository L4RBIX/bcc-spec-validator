"""Чтение MD, PDF и DOCX на синтетических фикстурах."""

from __future__ import annotations

import pytest

from validator.ingest import UnsupportedFormatError, load, normalize_spaces


def _by_kind(blocks, kind):
    return [b for b in blocks if b.kind == kind]


def test_md_structure_and_lines(sample_md):
    blocks = load(sample_md)
    lines = sample_md.read_text(encoding="utf-8").splitlines()
    assert [b.block_id for b in blocks[:3]] == ["B-001", "B-002", "B-003"]
    for b in blocks:
        assert b.page is None
        assert b.line is not None
    heading = next(b for b in blocks if b.text == "Функциональные требования")
    assert heading.kind == "heading"
    assert lines[heading.line - 1].startswith("### Функциональные требования")
    assert heading.section == "Бронирование переговорных > Раздел 1. Функционал > Функциональные требования"


def test_md_tables_lists_code(sample_md):
    blocks = load(sample_md)
    rows = _by_kind(blocks, "table_row")
    assert [r.text for r in rows] == [
        "Поле | Значение",
        "Система | Портал бронирования",
        "Версия | —",
        "Parameter | Format | DB field",
        "roomId | string | room_id",
    ]
    items = _by_kind(blocks, "list")
    assert items[0].text.startswith("ТР-1. Сотрудник бронирует")
    assert "**" not in items[0].text
    assert items[2].text == "1. Проверить сессию."
    code = _by_kind(blocks, "code")
    assert len(code) == 1 and "BookingController" in code[0].text
    assert code[0].section.endswith("Раздел 2. API > Логика")


def test_pdf_matches_md_structure(sample_pdf, sample_md):
    pdf = load(sample_pdf)
    md = load(sample_md)
    assert all(b.page == 1 and b.line and b.line >= 1 for b in pdf)
    assert [b.text for b in _by_kind(pdf, "table_row")] == [b.text for b in _by_kind(md, "table_row")]
    assert [b.text for b in _by_kind(pdf, "heading")] == [b.text for b in _by_kind(md, "heading")]
    assert [b.text for b in _by_kind(pdf, "list")] == [b.text for b in _by_kind(md, "list")]
    assert len(_by_kind(pdf, "code")) == 1
    row = next(b for b in pdf if b.text.startswith("roomId"))
    assert row.section.endswith("Раздел 2. API > Ответ")
    lines = [b.line for b in pdf]
    assert lines == sorted(lines), "номера строк на странице идут по порядку"


def test_docx(sample_docx):
    blocks = load(sample_docx)
    assert blocks[0].kind == "heading" and blocks[0].text == "Бронирование переговорных"
    para = blocks[1]
    assert para.kind == "para" and " " not in para.text
    items = _by_kind(blocks, "list")
    assert len(items) == 2 and items[0].section.endswith("Функциональные требования")
    rows = _by_kind(blocks, "table_row")
    assert [r.text for r in rows] == ["Parameter | Format | DB field", "roomId | string | room_id"]
    assert rows[0].section.endswith("Ответ")
    assert blocks[-1].text == "Текст после таблицы."


def test_unsupported_format(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        load(f)


def test_normalize_spaces_keeps_quotes():
    assert normalize_spaces("10 000 ₸ «да»​") == "10 000 ₸ «да»"
    assert normalize_spaces("ﬁeld") == "field"
