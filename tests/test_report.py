"""Markdown-отчёт: все разделы п. 6 README, ссылки на место, экранирование."""

from __future__ import annotations

from pathlib import Path

from validator.report_md import display_section, render_markdown, root_heading, verdict
from validator.runinfo import RunInfo, almaty_now
from validator.schema import Block, Finding, Requirement

SECTIONS = [
    "## 1. Паспорт прогона",
    "## 2. Как агент нарезал требования",
    "## 3. Проверка каждого требования",
    "## 4. Проверка всего набора требований",
    "## 5. Сводка",
    "## 6. Итог",
]

BLOCKS = [
    Block(
        block_id="B-001",
        section="Док > ФТ",
        page=2,
        line=7,
        kind="list",
        text="ТР-1. Ответ приходит быстро | без ошибок.",
    ),
]
REQS = [
    Requirement(
        req_id="R-01",
        doc_id="ТР-1",
        kind="FR",
        section="Док > ФТ",
        quote=BLOCKS[0].text,
        summary="Ответ приходит быстро",
        block_ids=["B-001"],
    ),
]


def run_info(provider: str = "gemini") -> RunInfo:
    return RunInfo(
        doc_path=Path("doc.pdf"),
        sha256="abc",
        started_at=almaty_now(),
        provider=provider,
        model="m",
        agent_version="v0.1.0",
    )


def finding(scope="item", severity="critical", fid="F-001") -> Finding:
    return Finding(
        finding_id=fid,
        req_ids=["R-01"],
        scope=scope,
        criterion="verifiable",
        severity=severity,
        quotes=["Ответ приходит быстро"],
        problem="Нет числового порога.",
        impact="Нельзя проверить.",
        question="Какое время ответа?",
        addressee="BO",
        options=["1 c", "3 c"],
        fix="Указать порог.",
        source="rule",
        confidence=1.0,
    )


def test_all_sections_present_without_findings():
    md = render_markdown(run_info(), BLOCKS, REQS, [])
    for s in SECTIONS:
        assert s in md
    assert md.count("находок нет") >= 3
    assert "ТР-1. Ответ приходит быстро \\| без ошибок." in md  # пайп экранирован в таблице


def test_finding_has_location_and_quote():
    md = render_markdown(run_info(), BLOCKS, REQS, [finding(), finding("set", "minor", "F-002")])
    assert "#### F-001 · критично · Проверяемость" in md
    assert "раздел «Док > ФТ», стр. 2, строка 7" in md
    assert "«Ответ приходит быстро»" in md
    assert "### F-002" in md
    assert "Можно ли начинать разработку и тестирование: Нет." in md
    assert "1. F-001 (критично): Указать порог." in md


def test_verdict_levels():
    assert verdict([], "gemini").code == "go"
    assert verdict([finding(severity="major")], "gemini").code == "conditional"
    assert verdict([finding()], "gemini").code == "no-go"
    assert "fake" in verdict([], "fake").text


def _heading(bid: str, section: str) -> Block:
    return Block(
        block_id=bid, section=section, page=None, line=1, kind="heading", text=section.split(" > ")[-1]
    )


def test_single_root_h1_hidden_in_output_only():
    blocks = [
        _heading("B-001", "Док"),
        _heading("B-002", "Док > ФТ"),
        Block(
            block_id="B-003",
            section="Док > ФТ",
            page=None,
            line=3,
            kind="para",
            text="Ответ приходит быстро.",
        ),
    ]
    assert root_heading(blocks) == "Док"
    assert display_section("Док > ФТ", "Док") == "ФТ"
    assert display_section("Док", "Док") == "Док"
    req = REQS[0].model_copy(update={"block_ids": ["B-003"]})
    md = render_markdown(run_info(), blocks, [req], [finding()])
    assert "раздел «ФТ», строка 3" in md
    assert "раздел «Док > ФТ»" not in md
    assert blocks[2].section == "Док > ФТ"  # сами данные не меняются


def test_two_root_headings_keep_full_path():
    blocks = [_heading("B-001", "Часть 1"), _heading("B-002", "Часть 2"), _heading("B-003", "Часть 2 > ФТ")]
    assert root_heading(blocks) is None
    assert display_section("Часть 2 > ФТ", None) == "Часть 2 > ФТ"
