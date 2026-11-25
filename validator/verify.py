"""Верификация находок кодом: каждая цитата обязана дословно существовать в документе.

Цитата ищется по всему тексту документа (точное вхождение после нормализации, иначе нечёткое
partial_ratio >= FUZZY_THRESHOLD), заменяется дословным фрагментом из документа и получает
привязку к блокам (раздел, страница, строка). Находки без подтверждённых цитат отбрасываются.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel
from rapidfuzz import fuzz

from validator.schema import CRITERIA, Block, Finding

FUZZY_THRESHOLD = 90.0
MIN_FUZZY_LEN = 12  # короче этого нечёткий поиск не применяется: слишком много ложных совпадений
DUPLICATE_REASON = "дубликат другой находки (та же цитата и критерий)"
SOURCE_PRIORITY = {"rule": 0, "simulation": 1, "llm": 2}

_QUOTE_CHARS = {"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‟": '"'}
_DASH_CHARS = {"–": "-", "—": "-", "−": "-", "‑": "-"}
_DROP_CHARS = {"*", "`"}  # разметка, которую модель может притащить в цитату


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Нормализует текст для сравнения и соответствие индексов: нормализованный -> исходный.

    lower, ё->е, «»“” -> ", тире -> -, схлопнуть пробелы, убрать пробелы между цифрами,
    убрать символы разметки * и `.
    """
    out: list[str] = []
    idx: list[int] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            prev_digit = bool(out) and out[-1].isdigit()
            next_digit = j < n and text[j].isdigit()
            if out and out[-1] != " " and not (prev_digit and next_digit) and j < n:
                out.append(" ")
                idx.append(i)
            i = j
            continue
        if ch in _DROP_CHARS:
            i += 1
            continue
        c = ch.lower()
        c = "е" if c == "ё" else _QUOTE_CHARS.get(c, _DASH_CHARS.get(c, c))
        out.append(c)
        idx.append(i)
        i += 1
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normalize(text: str) -> str:
    """Нормализованная форма текста для сравнения цитат."""
    return normalize_with_map(text)[0]


@dataclass(frozen=True)
class QuoteMatch:
    """Найденная в документе цитата."""

    fragment: str  # дословный фрагмент документа
    start: int  # смещение в склеенном тексте документа (для сортировки по порядку документа)
    blocks: tuple[Block, ...]  # блоки, которые покрывает цитата
    score: float  # 100 для точного вхождения

    @property
    def first(self) -> Block:
        return self.blocks[0]


class DocIndex:
    """Индекс текста документа для поиска цитат с привязкой к блокам."""

    SEP = "\n"

    def __init__(self, blocks: list[Block]) -> None:
        self.blocks = blocks
        parts: list[str] = []
        self._starts: list[int] = []
        pos = 0
        for b in blocks:
            self._starts.append(pos)
            parts.append(b.text)
            pos += len(b.text) + len(self.SEP)
        self.text = self.SEP.join(parts)
        self.norm, self._map = normalize_with_map(self.text)

    def _blocks_for(self, start: int, end: int) -> tuple[Block, ...]:
        res = []
        for b, s in zip(self.blocks, self._starts, strict=True):
            if s < end and start < s + len(b.text):
                res.append(b)
        return tuple(res)

    def _expand_to_words(self, start: int, end: int) -> tuple[int, int]:
        t = self.text
        while start > 0 and t[start - 1].isalnum() and t[start].isalnum():
            start -= 1
        while end < len(t) and t[end - 1].isalnum() and t[end].isalnum():
            end += 1
        return start, end

    def find(self, quote: str) -> QuoteMatch | None:
        """Ищет цитату: точно после нормализации, иначе нечётко. None, если не найдена."""
        nq = normalize(quote)
        if not nq:
            return None
        pos = self.norm.find(nq)
        score = 100.0
        if pos >= 0:
            nstart, nend = pos, pos + len(nq)
        else:
            if len(nq) < MIN_FUZZY_LEN:
                return None
            al = fuzz.partial_ratio_alignment(nq, self.norm, score_cutoff=FUZZY_THRESHOLD)
            if al is None or al.score < FUZZY_THRESHOLD:
                return None
            nstart, nend, score = al.dest_start, al.dest_end, al.score
        if nend <= nstart:
            return None
        start = self._map[nstart]
        end = self._map[nend - 1] + 1
        if score < 100.0:
            start, end = self._expand_to_words(start, end)
        fragment = self.text[start:end].strip()
        return QuoteMatch(fragment=fragment, start=start, blocks=self._blocks_for(start, end), score=score)


class DroppedFinding(BaseModel):
    """Находка, отброшенная верификатором, и причина."""

    finding: Finding
    reason: str


def _dedup_key(f: Finding) -> tuple[str, str]:
    return normalize(f.quotes[0]), f.criterion


def _better(a: Finding, b: Finding) -> bool:
    """True, если находка a приоритетнее b при дедупликации."""
    pa, pb = SOURCE_PRIORITY.get(a.source, 9), SOURCE_PRIORITY.get(b.source, 9)
    return pa < pb or (pa == pb and a.confidence > b.confidence)


def verify(findings: list[Finding], blocks: list[Block]) -> tuple[list[Finding], list[DroppedFinding]]:
    """Проверяет цитаты находок по документу, дедуплицирует и нумерует F-001... в порядке документа.

    Возвращает (принятые находки, отброшенные с причинами).
    """
    index = DocIndex(blocks)
    dropped: list[DroppedFinding] = []
    checked: list[tuple[int, Finding]] = []
    for f in findings:
        reason = _structural_problem(f)
        if reason:
            dropped.append(DroppedFinding(finding=f, reason=reason))
            continue
        matches = [index.find(q) for q in f.quotes]
        missing = [q for q, m in zip(f.quotes, matches, strict=True) if m is None]
        if missing:
            dropped.append(
                DroppedFinding(finding=f, reason="цитата не найдена в документе: " + " | ".join(missing))
            )
            continue
        found = [m for m in matches if m is not None]
        fixed = f.model_copy(update={"quotes": _unique([m.fragment for m in found])})
        checked.append((min(m.start for m in found), fixed))

    best: dict[tuple[str, str], tuple[int, Finding]] = {}
    for pos, f in checked:
        key = _dedup_key(f)
        if key not in best:
            best[key] = (pos, f)
            continue
        old_pos, old = best[key]
        winner, loser = (f, old) if _better(f, old) else (old, f)
        merged = winner.model_copy(update={"req_ids": _unique(winner.req_ids + loser.req_ids)})
        best[key] = (min(pos, old_pos), merged)
        dropped.append(DroppedFinding(finding=loser, reason=DUPLICATE_REASON))

    ordered = sorted(best.values(), key=lambda pf: (pf[0], list(CRITERIA).index(pf[1].criterion)))
    kept = [f.model_copy(update={"finding_id": f"F-{i:03d}"}) for i, (_, f) in enumerate(ordered, start=1)]
    return kept, dropped


def _structural_problem(f: Finding) -> str | None:
    if not f.quotes or not any(q.strip() for q in f.quotes):
        return "нет ни одной цитаты"
    if f.criterion not in CRITERIA:
        return f"неизвестный критерий «{f.criterion}»"
    return None


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def write_dropped(dropped: list[DroppedFinding], path: Path) -> None:
    """Пишет отброшенные находки в JSONL (по строке на находку)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for d in dropped:
            fh.write(json.dumps(d.model_dump(), ensure_ascii=False) + "\n")


def is_duplicate_reason(reason: str) -> bool:
    """True, если находка отброшена как дубликат, а не из-за цитаты."""
    return bool(re.match(r"^дубликат", reason))
