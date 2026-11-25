"""ЗАГЛУШКА (модуль ML-друга): нарезка документа на требования.

Детерминированная эвристика без LLM: каждый содержательный блок (абзац, пункт списка, строка таблицы
кроме заголовка таблицы) становится требованием. Тип берётся по названию раздела из общих слов шаблона ТЗ.
"""

from __future__ import annotations

import re

from validator.schema import Block, Requirement

_DOC_ID_RE = re.compile(r"^\s*([A-Za-zА-Яа-яЁё]{1,5}[-.]?\d+(?:\.\d+)*)[.)]\s")
_KIND_BY_SECTION: list[tuple[str, str]] = [
    ("нефункциональ", "NFR"),
    ("функциональ", "FR"),
    ("данн", "DATA"),
    ("интеграц", "INT"),
    ("прием", "AC"),
    ("приём", "AC"),
    ("параметр", "API"),
    ("ответ", "API"),
    ("статус", "API"),
    ("api", "API"),
    ("архитектур", "ARCH"),
    ("sequence", "ARCH"),
    ("bpmn", "ARCH"),
    ("дизайн", "UI"),
    ("ui", "UI"),
]


def _kind(section: str) -> str:
    for part in reversed(section.lower().split(" > ")):  # сначала самый глубокий раздел
        for marker, kind in _KIND_BY_SECTION:
            if re.search(rf"\b{marker}", part):
                return kind
    return "META"


def segment(blocks: list[Block]) -> list[Requirement]:
    """Нарезает блоки документа на требования R-01, R-02, ..."""
    reqs: list[Requirement] = []
    prev_kind = None
    for b in blocks:
        is_table_header = b.kind == "table_row" and prev_kind != "table_row"
        prev_kind = b.kind
        if b.kind in ("heading", "code") or is_table_header or not b.text.strip(" |"):
            continue
        m = _DOC_ID_RE.match(b.text)
        summary = b.text if len(b.text) <= 90 else b.text[:87].rstrip() + "..."
        reqs.append(
            Requirement(
                req_id=f"R-{len(reqs) + 1:02d}",
                doc_id=m.group(1) if m else None,
                kind=_kind(b.section),  # type: ignore[arg-type]
                section=b.section,
                quote=b.text,
                summary=summary,
                block_ids=[b.block_id],
            )
        )
    return reqs
