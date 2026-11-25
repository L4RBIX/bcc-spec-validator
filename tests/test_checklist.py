"""Заполнение чек-листа ревью по находкам."""

from __future__ import annotations

import textwrap

from tests.test_report import run_info
from validator.checklist import fill_checklist
from validator.ingest import load
from validator.report_md import CHECKLIST_TITLE, render_markdown
from validator.schema import Finding

DOC = """
    # Док
    ## Требования
    Откат выполняется выключением фича-флага.
    ## Ревью
    | Проверка | Создано | Примечания |
    | :--- | :--- | :--- |
    | Требование может быть протестировано | Да / Нет | |
    | Предусмотрена схема отката решения | Да / Нет / Не требуется | |
    | Поддерживается версионность документа | Да / Нет | |
    | Требование носит интеграционный характер | Да / Нет / Не требуется | |
    | Погода в офисе комфортная | Да / Нет | |
"""


def _blocks(tmp_path, md: str = DOC):
    p = tmp_path / "doc.md"
    p.write_text(textwrap.dedent(md).strip() + "\n", encoding="utf-8")
    return load(p)


def _finding(fid: str, criterion: str) -> Finding:
    return Finding(
        finding_id=fid,
        req_ids=[],
        scope="set",
        criterion=criterion,
        severity="minor",
        quotes=["Док"],
        problem="p",
        impact="i",
        question="q?",
        addressee="аналитик",
        options=["a", "b"],
        fix="f",
        source="rule",
        confidence=1.0,
    )


def test_fill_checklist(tmp_path):
    items = fill_checklist(_blocks(tmp_path), [_finding("F-001", "modifiable")], [])
    answers = {i.text: (i.answer, i.finding_ids) for i in items}
    assert answers["Требование может быть протестировано"] == ("Да", [])
    assert answers["Предусмотрена схема отката решения"] == ("Да", [])
    assert answers["Поддерживается версионность документа"] == ("Нет", ["F-001"])
    assert answers["Требование носит интеграционный характер"][0] == "Не требуется"
    assert answers["Погода в офисе комфортная"][0] == "—"
    assert all(i.reason for i in items)


def test_rollback_not_mentioned_outside_checklist(tmp_path):
    md = DOC.replace("    Откат выполняется выключением фича-флага.\n", "    Текст требования.\n")
    items = fill_checklist(_blocks(tmp_path, md), [], [])
    rollback = next(i for i in items if "отката" in i.text)
    assert rollback.answer == "Нет"


def test_no_checklist_no_section(tmp_path):
    blocks = _blocks(tmp_path, "# Док\n\nТолько текст.\n")
    assert fill_checklist(blocks, [], []) is None
    assert CHECKLIST_TITLE not in render_markdown(run_info(), blocks, [], [], None)


def test_checklist_section_rendered(tmp_path):
    blocks = _blocks(tmp_path)
    items = fill_checklist(blocks, [], [])
    md = render_markdown(run_info(), blocks, [], [], items)
    assert CHECKLIST_TITLE in md and "| 3 | Поддерживается версионность документа | **Да** |" in md
