"""Заполнение шаблонного чек-листа ревью из документа по находкам агента.

Если в документе есть таблица-чек-лист (строки с вариантами «Да / Нет»), агент выставляет по каждому
пункту Да / Нет / Не требуется с обоснованием и ссылками на находки. Сопоставление пункта с проверками --
по словарю rules_data/checklist_map.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from validator.doc import Doc, Table, cells
from validator.rules import DATA_DIR, lexicon
from validator.schema import CRITERIA, Block, Finding, Requirement

NOT_MAPPED = "—"


@dataclass
class ChecklistItem:
    """Пункт чек-листа и ответ агента."""

    text: str
    row: Block
    answer: str  # Да | Нет | Не требуется | —
    reason: str
    finding_ids: list[str] = field(default_factory=list)


@lru_cache
def checklist_map() -> list[dict]:
    """Словарь сопоставления пунктов чек-листа (rules_data/checklist_map.yaml)."""
    return yaml.safe_load((DATA_DIR / "checklist_map.yaml").read_text(encoding="utf-8"))


def _choice_cell(text: str) -> bool:
    rx = re.compile(r"^\s*(?:" + "|".join(lexicon()["choice_patterns"]) + r")\s*$", re.IGNORECASE)
    return bool(rx.match(text))


def find_checklist(doc: Doc) -> Table | None:
    """Таблица, у которой не меньше двух строк содержат варианты выбора «Да / Нет»."""
    for table in doc.tables:
        if sum(1 for r in table.data if any(_choice_cell(c) for c in cells(r))) >= 2:
            return table
    return None


def _has_stem(text: str, stems: list[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![a-zа-яё]){re.escape(s)}", low) for s in stems)


def _entry_for(text: str) -> dict | None:
    return next((e for e in checklist_map() if _has_stem(text, e["keywords"])), None)


def _criteria_names(criteria: list[str]) -> str:
    return ", ".join(f"«{CRITERIA[c][1]}»" for c in criteria if c in CRITERIA)


def _related(entry: dict, findings: list[Finding], kind_reqs: set[str] | None) -> list[Finding]:
    criteria = set(entry.get("criteria", []))
    addressee = entry.get("addressee")
    out = []
    for f in findings:
        by_crit, by_addr = f.criterion in criteria, bool(addressee) and f.addressee == addressee
        hit = (by_crit and by_addr) if entry.get("require_both") else (by_crit or by_addr)
        if hit and (kind_reqs is None or set(f.req_ids) & kind_reqs):
            out.append(f)
    return out


def _evaluate(entry: dict, allow_na: bool, ctx: _Ctx) -> tuple[str, str, list[str]]:
    """Ответ, обоснование и F-id для одного пункта."""
    kind_reqs: set[str] | None = None
    checked: list[str] = []
    if "kinds" in entry:
        kind_reqs = {r.req_id for r in ctx.reqs if r.kind in entry["kinds"]}
        if not kind_reqs:
            answer = "Не требуется" if allow_na else "Нет"
            return answer, f"В документе нет требований типа {', '.join(entry['kinds'])}.", []
        checked.append(f"требований типа {', '.join(entry['kinds'])}: {len(kind_reqs)}")
    if "present" in entry:
        found = [h for stem in entry["present"] for h in ctx.doc.headings if _has_stem(h.text, [stem])]
        if not found:
            return "Нет", f"В документе нет раздела на эту тему (искали заголовки: {', '.join(entry['present'])}).", []
        checked.append(f"есть раздел «{ctx.doc.where(found[0])}»")
    if "search" in entry:
        hits = [b for b in ctx.body if _has_stem(b.text, entry["search"])]
        if not hits:
            return "Нет", f"В тексте документа нет упоминаний ({', '.join(entry['search'])}).", []
        checked.append(f"упоминание в разделе «{ctx.doc.where(hits[0])}»")
    related = _related(entry, ctx.findings, kind_reqs)
    if related:
        ids = [f.finding_id for f in related]
        names = _criteria_names(list(dict.fromkeys(f.criterion for f in related)))
        return "Нет", f"Есть нарушения ({names}): {', '.join(ids)}.", ids
    what = _criteria_names(entry.get("criteria", []))
    tail = f"нарушений по критериям {what} агент не нашёл" if what else "нарушений агент не нашёл"
    if entry.get("addressee") and not entry.get("require_both"):
        tail += f", замечаний для адресата «{entry['addressee']}» нет"
    reason = "; ".join([*checked, tail])
    return "Да", reason[0].upper() + reason[1:] + ".", []


@dataclass
class _Ctx:
    doc: Doc
    findings: list[Finding]
    reqs: list[Requirement]
    body: list[Block]


def fill_checklist(blocks: list[Block], findings: list[Finding], reqs: list[Requirement]) -> list[ChecklistItem] | None:
    """Заполняет чек-лист документа. None, если таблицы-чек-листа в документе нет."""
    doc = Doc(blocks)
    table = find_checklist(doc)
    if table is None:
        return None
    own = {r.block_id for r in table.rows}
    ctx = _Ctx(doc, findings, reqs, [b for b in blocks if b.block_id not in own])
    items: list[ChecklistItem] = []
    for row in table.data:
        row_cells = cells(row)
        if not any(_choice_cell(c) for c in row_cells):
            continue
        allow_na = any("не требуется" in c.lower() for c in row_cells)
        entry = _entry_for(row_cells[0])
        if entry is None:
            items.append(
                ChecklistItem(
                    row_cells[0], row, NOT_MAPPED, "Пункт не сопоставлен с проверками агента, нужна ручная проверка."
                )
            )
            continue
        answer, reason, ids = _evaluate(entry, allow_na, ctx)
        items.append(ChecklistItem(row_cells[0], row, answer, reason, ids))
    return items
