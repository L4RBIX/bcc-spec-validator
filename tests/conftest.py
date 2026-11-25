"""Общие фикстуры: синтетический документ в MD, PDF и DOCX."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(scope="session")
def sample_md() -> Path:
    return FIXTURES / "sample.md"


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory, sample_md) -> Path:
    from md_to_pdf import convert

    out = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    convert(sample_md, out)
    return out


@pytest.fixture(scope="session")
def sample_docx(tmp_path_factory) -> Path:
    from docx import Document

    doc = Document()
    doc.add_heading("Бронирование переговорных", level=1)
    doc.add_paragraph("Учебный синтетический документ для тестов агента.")
    doc.add_heading("Функциональные требования", level=2)
    doc.add_paragraph("ТР-1. Сотрудник бронирует комнату на интервал от 15 до 240 минут.", style="List Bullet")
    doc.add_paragraph("ТР-2. Бронь отменяется автоматически.", style="List Bullet")
    doc.add_heading("Ответ", level=2)
    table = doc.add_table(rows=2, cols=3)
    for i, text in enumerate(["Parameter", "Format", "DB field"]):
        table.rows[0].cells[i].text = text
    for i, text in enumerate(["roomId", "string", "room_id"]):
        table.rows[1].cells[i].text = text
    doc.add_paragraph("Текст после таблицы.")
    out = tmp_path_factory.mktemp("docx") / "sample.docx"
    doc.save(str(out))
    return out
