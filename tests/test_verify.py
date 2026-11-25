"""Верификатор цитат: точные цитаты, перефразы, нечёткие совпадения, дедупликация, нумерация."""

from __future__ import annotations

from validator.schema import Block, Finding
from validator.verify import DocIndex, normalize, verify

BLOCKS = [
    Block(block_id="B-001", section="Док", page=1, line=1, kind="heading", text="Требования"),
    Block(
        block_id="B-002",
        section="Док > ФТ",
        page=1,
        line=3,
        kind="list",
        text="ТР-1. Лимит от 1 000 до 5 000 единиц включительно, «по умолчанию» выключен.",
    ),
    Block(
        block_id="B-003",
        section="Док > ФТ",
        page=1,
        line=4,
        kind="para",
        text="Отчёт формируется ежедневно в 09:00.",
    ),
    Block(
        block_id="B-004",
        section="Док > НФТ",
        page=2,
        line=1,
        kind="para",
        text="Система отвечает быстро и удобно для пользователя.",
    ),
]


def make(quotes, criterion="unambiguous", source="llm", confidence=0.5, req_ids=("R-01",)):
    return Finding(
        finding_id="",
        req_ids=list(req_ids),
        scope="item",
        criterion=criterion,
        severity="major",
        quotes=list(quotes),
        problem="p",
        impact="i",
        question="q",
        addressee="аналитик",
        options=["a"],
        fix="f",
        source=source,
        confidence=confidence,
    )


def test_normalize():
    assert normalize("  «Ёлка»\n  1 000 —  x ") == '"елка" 1000 - x'


def test_exact_quote_is_replaced_with_verbatim_text():
    kept, dropped = verify([make(['лимит от 1000 до 5000 единиц включительно, "по умолчанию"'])], BLOCKS)
    assert not dropped
    assert kept[0].quotes == ["Лимит от 1 000 до 5 000 единиц включительно, «по умолчанию»"]
    assert kept[0].finding_id == "F-001"


def test_paraphrase_is_dropped_with_reason():
    kept, dropped = verify([make(["система должна работать очень быстро и надёжно всегда"])], BLOCKS)
    assert kept == []
    assert len(dropped) == 1 and "цитата не найдена" in dropped[0].reason


def test_fuzzy_typo_is_accepted_and_fixed():
    kept, dropped = verify([make(["Отчет формируеться ежедневно в 09:00"])], BLOCKS)
    assert not dropped
    assert kept[0].quotes == ["Отчёт формируется ежедневно в 09:00"]


def test_short_quote_needs_exact_match():
    kept, _ = verify([make(["быстр"])], BLOCKS)
    assert len(kept) == 1
    kept, dropped = verify([make(["бвстро"])], BLOCKS)
    assert not kept and dropped


def test_quote_across_blocks():
    m = DocIndex(BLOCKS).find("выключен. Отчёт формируется")
    assert m is not None
    assert [b.block_id for b in m.blocks] == ["B-002", "B-003"]


def test_dedup_prefers_rule_and_merges_req_ids():
    llm = make(["Система отвечает быстро"], source="llm", confidence=0.99, req_ids=["R-02"])
    rule = make(["система отвечает быстро"], source="rule", confidence=0.4, req_ids=["R-03"])
    kept, dropped = verify([llm, rule], BLOCKS)
    assert len(kept) == 1
    assert kept[0].source == "rule"
    assert set(kept[0].req_ids) == {"R-02", "R-03"}
    assert len(dropped) == 1 and dropped[0].reason.startswith("дубликат")


def test_dedup_same_source_prefers_confidence():
    a = make(["Система отвечает быстро"], confidence=0.3)
    b = make(["Система отвечает быстро"], confidence=0.8)
    kept, _ = verify([a, b], BLOCKS)
    assert kept[0].confidence == 0.8


def test_different_criterion_is_not_duplicate():
    a = make(["Система отвечает быстро"], criterion="unambiguous")
    b = make(["Система отвечает быстро"], criterion="verifiable")
    kept, _ = verify([a, b], BLOCKS)
    assert len(kept) == 2


def test_numbering_follows_document_order():
    later = make(["Система отвечает быстро"])
    earlier = make(["Отчёт формируется ежедневно"])
    kept, _ = verify([later, earlier], BLOCKS)
    assert [(f.finding_id, f.quotes[0]) for f in kept] == [
        ("F-001", "Отчёт формируется ежедневно"),
        ("F-002", "Система отвечает быстро"),
    ]


def test_unknown_criterion_and_empty_quotes_dropped():
    kept, dropped = verify([make(["Отчёт"], criterion="beauty"), make([])], BLOCKS)
    assert not kept
    assert {d.reason.split(" ")[0] for d in dropped} == {"неизвестный", "нет"}
