"""Чтение документа требований (MD, PDF, DOCX) в плоский список блоков с привязкой к месту."""

from __future__ import annotations

import bisect
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from validator.schema import Block

SUPPORTED_SUFFIXES = (".md", ".markdown", ".pdf", ".docx")

# Неразрывные, узкие и прочие «особые» пробелы -> обычный пробел.
_SPACE_RE = re.compile("[\u00a0\u2000-\u200a\u202f\u205f\u3000]")
_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\ufeff\u00ad]")
_LIGATURES = str.maketrans({"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"})
_BULLET_RE = re.compile(r"^\s*(?:[-*+•▪◦‣●–]\s+)")
_ORDERED_RE = re.compile(r"^\s*\d{1,2}[.)]\s+")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_MD_HR_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_MD_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_MD_BOLD_LINE_RE = re.compile(r"^(\*\*|__)(?!\s)(.+?)(?<!\s)\1$")
_PSEUDO_HEADING_LEVEL = 7  # строка целиком жирным: заголовок ниже h6
_PSEUDO_HEADING_MAX = 40
# Жирные слова-выноски -- это не заголовки разделов.
_CALLOUT_WORDS = frozenset(
    "важно примечание примечания внимание замечание пример примеры note warning important example tip".split()
)
_SENTENCE_END = (".", ":", ";", ",")


class UnsupportedFormatError(ValueError):
    """Формат входного файла не поддерживается."""


def normalize_spaces(text: str) -> str:
    """Неразрывные и узкие пробелы -> обычные; убирает символы нулевой ширины; раскрывает лигатуры PDF."""
    return _ZERO_WIDTH_RE.sub("", _SPACE_RE.sub(" ", text)).translate(_LIGATURES)


def load(path: str | Path) -> list[Block]:
    """Читает файл требований и возвращает блоки в порядке документа с ID B-001, B-002, ..."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".md", ".markdown"):
        raw = list(_load_md(p))
    elif suffix == ".pdf":
        raw = list(_load_pdf(p))
    elif suffix == ".docx":
        raw = list(_load_docx(p))
    else:
        raise UnsupportedFormatError(
            f"Формат «{p.suffix or 'без расширения'}» не поддерживается. Поддерживаются: PDF, MD, DOCX."
        )
    return [
        Block(block_id=f"B-{i:03d}", section=sec, page=page, line=line, kind=kind, text=text)
        for i, (sec, page, line, kind, text) in enumerate(raw, start=1)
    ]


RawBlock = tuple[str, int | None, int | None, str, str]


class _Sections:
    """Стек заголовков -> путь раздела «H1 > H2 > H3»."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def enter(self, level: int, title: str) -> None:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, title))

    @property
    def path(self) -> str:
        return " > ".join(t for _, t in self._stack)


# ---------------------------------------------------------------- Markdown


def _is_pseudo_heading(text: str) -> bool:
    """Строка целиком жирным -- заголовок, только если она короткая (<= 40 символов), не кончается
    двоеточием или другой пунктуацией, не пункт списка и не слово-выноска («Важно», «Примечание»).
    """
    return (
        0 < len(text) <= _PSEUDO_HEADING_MAX
        and not text.endswith(_SENTENCE_END)
        and not _BULLET_RE.match(text)
        and text.lower().strip("!") not in _CALLOUT_WORDS
    )


def _strip_inline_md(text: str) -> str:
    """Убирает inline-разметку Markdown (жирный, курсив, код, ссылки), оставляя текст."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    return text.strip()


def _md_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [_strip_inline_md(c) for c in re.split(r"(?<!\\)\|", body)]


def _load_md(path: Path) -> Iterator[RawBlock]:
    lines = normalize_spaces(path.read_text(encoding="utf-8")).splitlines()
    sections = _Sections()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        lineno = i + 1
        stripped = line.strip()
        if not stripped or _MD_HR_RE.match(stripped):
            i += 1
            continue
        if _MD_FENCE_RE.match(stripped):
            fence = _MD_FENCE_RE.match(stripped).group(1)  # type: ignore[union-attr]
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                body.append(lines[i].rstrip())
                i += 1
            i += 1  # закрывающий забор
            if any(b.strip() for b in body):
                yield sections.path, None, lineno, "code", "\n".join(body).strip("\n")
            continue
        heading = _MD_HEADING_RE.match(stripped)
        bold_line = _MD_BOLD_LINE_RE.match(stripped)
        if heading:
            title = _strip_inline_md(heading.group(2))
            sections.enter(len(heading.group(1)), title)
            yield sections.path, None, lineno, "heading", title
        elif bold_line and _is_pseudo_heading(_strip_inline_md(stripped)):
            title = _strip_inline_md(stripped)
            sections.enter(_PSEUDO_HEADING_LEVEL, title)
            yield sections.path, None, lineno, "heading", title
        elif stripped.startswith("|"):
            if not _MD_TABLE_SEP_RE.match(stripped):
                yield sections.path, None, lineno, "table_row", " | ".join(_md_cells(stripped))
        elif _BULLET_RE.match(stripped):
            yield sections.path, None, lineno, "list", _strip_inline_md(_BULLET_RE.sub("", stripped, count=1))
        elif _ORDERED_RE.match(stripped):
            yield sections.path, None, lineno, "list", _strip_inline_md(stripped)
        else:
            text = stripped[1:].strip() if stripped.startswith(">") else stripped
            yield sections.path, None, lineno, "para", _strip_inline_md(text)
        i += 1


# ---------------------------------------------------------------- PDF

_BOLD_FLAG = 16
_MONO_FLAG = 8
_BULLET_ONLY = ("•", "-", "–", "▪", "◦", "●")


@dataclass
class _PdfItem:
    """Элемент страницы PDF до присвоения раздела: y-координата для сортировки и содержимое."""

    y: float
    kind: str
    text: str
    level: int = 0  # для заголовков


def _span_is_bold(span: dict) -> bool:
    return bool(span["flags"] & _BOLD_FLAG) or "bold" in span.get("font", "").lower()


def _span_is_mono(span: dict) -> bool:
    font = span.get("font", "").lower()
    return bool(span["flags"] & _MONO_FLAG) or any(m in font for m in ("mono", "courier", "consol"))


def _line_text(line: dict) -> str:
    return normalize_spaces("".join(s["text"] for s in line["spans"])).strip()


def _visible_spans(line: dict) -> list[dict]:
    return [s for s in line["spans"] if s["text"].strip()]


def _inside(bbox: tuple[float, ...], rects: list[tuple[float, ...]]) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return any(r[0] - 1 <= cx <= r[2] + 1 and r[1] - 1 <= cy <= r[3] + 1 for r in rects)


def _font_stats(pages: list[tuple[list[dict], list[tuple[float, ...]]]]) -> tuple[float, dict[float, int]]:
    """Основной размер шрифта (по объёму текста вне таблиц) и уровни заголовков по размерам крупнее него."""
    sizes: Counter[float] = Counter()
    line_sizes: list[float] = []
    for blocks, rects in pages:
        for b in blocks:
            for ln in b["lines"]:
                spans = _visible_spans(ln)
                if not spans or _inside(ln["bbox"], rects):
                    continue
                for sp in spans:
                    sizes[round(sp["size"], 1)] += len(sp["text"].strip())
                line_sizes.append(round(max(sp["size"] for sp in spans), 1))
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    big = sorted({s for s in line_sizes if s > body * 1.08}, reverse=True)
    return body, {size: i + 1 for i, size in enumerate(big)}


def _load_pdf(path: Path) -> Iterator[RawBlock]:
    import pymupdf

    if hasattr(pymupdf, "no_recommend_layout"):
        pymupdf.no_recommend_layout()  # иначе find_tables печатает рекламу в stdout
    doc = pymupdf.open(path)
    pages = []
    for page in doc:
        tables = list(page.find_tables().tables)
        blocks = [b for b in page.get_text("dict", sort=True)["blocks"] if b.get("type") == 0]
        pages.append((page, tables, blocks))
    body, levels = _font_stats([(blocks, [tuple(t.bbox) for t in tables]) for _, tables, blocks in pages])
    bold_level = len(levels) + 1  # жирная строка основного размера = самый нижний уровень заголовка
    sections = _Sections()
    for page_no, (page, tables, blocks) in enumerate(pages, start=1):
        rects = [tuple(t.bbox) for t in tables]
        text_lines = [ln for b in blocks for ln in b["lines"] if _line_text(ln)]
        tops = _dedupe_tops(sorted(ln["bbox"][1] for ln in text_lines))
        free = [ln["bbox"][2] for ln in text_lines if not _inside(ln["bbox"], rects)]
        right_edge = max(free, default=page.rect.x1)
        items = [it for t in tables for it in _pdf_table_rows(page, t)]
        for b in blocks:
            items.extend(_pdf_text_block(b, rects, levels, bold_level, right_edge))
        items.sort(key=lambda it: it.y)
        for it in _merge_code(items):
            line = max(1, bisect.bisect_right(tops, it.y + 1.0))
            if it.kind == "heading":
                sections.enter(it.level, it.text)
            yield sections.path, page_no, line, it.kind, it.text


def _pdf_table_rows(page, table) -> Iterator[_PdfItem]:
    """Строки таблицы: текст ячеек берётся по их координатам и склеивается через « | »."""
    for row in table.rows:
        cells = []
        for rect in row.cells:
            text = page.get_text("text", clip=rect, sort=True) if rect else ""
            cells.append(normalize_spaces(" ".join(text.split())))
        yield _PdfItem(y=row.bbox[1], kind="table_row", text=" | ".join(cells))


def _merge_code(items: list[_PdfItem]) -> Iterator[_PdfItem]:
    """Склеивает подряд идущие строки кода в один блок."""
    code: list[_PdfItem] = []
    for it in items:
        if it.kind == "code":
            code.append(it)
            continue
        if code:
            yield _PdfItem(y=code[0].y, kind="code", text="\n".join(c.text for c in code))
            code = []
        yield it
    if code:
        yield _PdfItem(y=code[0].y, kind="code", text="\n".join(c.text for c in code))


def _dedupe_tops(tops: list[float]) -> list[float]:
    """Сливает строки, чьи верхние границы почти совпадают (одна визуальная строка)."""
    out: list[float] = []
    for t in tops:
        if not out or t - out[-1] > 2.0:
            out.append(t)
    return out


def _is_heading_line(text: str, spans: list[dict], size: float, levels: dict[float, int]) -> bool:
    if size in levels:
        return True
    return all(_span_is_bold(s) for s in spans) and _is_pseudo_heading(text)


def _hard_break(prev_x1: float, line: dict, text: str, right_edge: float) -> bool:
    """Жёсткий перенос: первое слово строки поместилось бы в остаток предыдущей строки."""
    width = line["bbox"][2] - line["bbox"][0]
    char_w = width / max(len(text), 1)
    first_word = text.split(maxsplit=1)[0]
    return right_edge - prev_x1 > char_w * (len(first_word) + 1)


def _pdf_text_block(
    block: dict, table_rects: list, levels: dict[float, int], bold_level: int, right_edge: float
) -> Iterator[_PdfItem]:
    """Разбирает текстовый блок PyMuPDF на заголовки, код, пункты списков и абзацы.

    Строки, перенесённые по ширине страницы, склеиваются через пробел; жёсткий перенос
    (строка закончилась заметно раньше правого края) начинает новый абзац.
    """
    para: list[str] = []
    para_y: float | None = None
    para_kind = "para"
    prev_x1 = right_edge

    def flush() -> Iterator[_PdfItem]:
        nonlocal para, para_y, para_kind
        if para and para_y is not None:
            yield _PdfItem(y=para_y, kind=para_kind, text=" ".join(para))
        para, para_y, para_kind = [], None, "para"

    for ln in block["lines"]:
        text = _line_text(ln)
        if not text or _inside(ln["bbox"], table_rects):
            continue
        spans = _visible_spans(ln)
        size = round(max(s["size"] for s in spans), 1)
        y = ln["bbox"][1]
        if _is_heading_line(text, spans, size, levels):
            yield from flush()
            yield _PdfItem(y=y, kind="heading", text=text, level=levels.get(size, bold_level))
            continue
        if all(_span_is_mono(s) for s in spans):
            yield from flush()
            yield _PdfItem(y=y, kind="code", text=text)
            continue
        if _BULLET_RE.match(text) or _ORDERED_RE.match(text) or text in _BULLET_ONLY:
            yield from flush()
            para_y, para_kind = y, "list"
            text = _BULLET_RE.sub("", text, count=1)
            if text in _BULLET_ONLY:
                continue
        elif para and _hard_break(prev_x1, ln, text, right_edge):
            yield from flush()
        if para_y is None:
            para_y = y
        para.append(text)
        prev_x1 = ln["bbox"][2]
    yield from flush()


# ---------------------------------------------------------------- DOCX


def _docx_heading_level(style_name: str) -> int | None:
    name = (style_name or "").lower()
    if name == "title":
        return 1
    m = re.match(r"(?:heading|заголовок)\s*(\d)", name)
    return int(m.group(1)) + 1 if m else None


def _load_docx(path: Path) -> Iterator[RawBlock]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    sections = _Sections()
    counter = 0
    for el in doc.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(el, doc)
            text = normalize_spaces(para.text).strip()
            counter += 1
            if not text:
                continue
            style = para.style.name if para.style is not None else ""
            level = _docx_heading_level(style)
            if level is not None:
                sections.enter(level, text)
                yield sections.path, None, counter, "heading", text
            elif "list" in style.lower() or el.find(".//{*}numPr") is not None:
                yield sections.path, None, counter, "list", _BULLET_RE.sub("", text, count=1)
            else:
                yield sections.path, None, counter, "para", text
        elif tag == "tbl":
            for row in Table(el, doc).rows:
                counter += 1
                cells: list[str] = []
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:  # объединённые ячейки python-docx повторяет
                        continue
                    seen.add(id(cell._tc))
                    cells.append(normalize_spaces(" ".join(cell.text.split())))
                yield sections.path, None, counter, "table_row", " | ".join(cells)
