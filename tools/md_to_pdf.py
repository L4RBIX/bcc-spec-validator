"""Конвертер Markdown -> PDF без системных зависимостей.

Свой мини-парсер MD -> HTML, рендер через PyMuPDF Story.

Поддерживает то, что встречается в типовых ТЗ: заголовки, абзацы, списки, таблицы, блоки кода,
жирный/курсив/inline-код, горизонтальные линии.

    python tools/md_to_pdf.py input.md output.pdf
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

import pymupdf

CSS = """
body { font-size: 10.5pt; line-height: 1.3; }
h1 { font-size: 20pt; font-weight: bold; margin: 0 0 8pt 0; }
h2 { font-size: 16pt; font-weight: bold; margin: 12pt 0 6pt 0; }
h3 { font-size: 14pt; font-weight: bold; margin: 10pt 0 5pt 0; }
h4 { font-size: 12.5pt; font-weight: bold; margin: 8pt 0 4pt 0; }
h5, h6 { font-size: 11.5pt; font-weight: bold; margin: 6pt 0 3pt 0; }
p { margin: 0 0 5pt 0; }
table { border-collapse: collapse; margin: 4pt 0 8pt 0; }
td, th { border: 0.6pt solid #000; padding: 2pt 4pt; font-size: 9pt; vertical-align: top; }
th { font-weight: bold; }
pre { font-family: monospace; font-size: 8.5pt; margin: 4pt 0 6pt 0; }
code { font-family: monospace; }
li { margin: 0 0 2pt 0; }
"""

_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def inline(text: str) -> str:
    """Экранирует текст и превращает inline-разметку MD в HTML."""
    codes: list[str] = []

    def keep_code(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]*)`", keep_code, text.rstrip())
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)]*)\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"<b>\2</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{html.escape(codes[int(m.group(1))])}</code>", text)


def _cells(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def md_to_html(md: str) -> str:
    """Преобразует Markdown в HTML-фрагмент для Story."""
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith(("```", "~~~")):
            fence = s[:3]
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(body)) + "</pre>")
            i += 1
            continue
        if _HR.match(s):
            i += 1
            continue
        if m := _HEADING.match(s):
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            out.append(_table_html(rows))
            continue
        if _BULLET.match(s) or _ORDERED.match(s):
            ordered = bool(_ORDERED.match(s))
            items = []
            while i < len(lines) and (m2 := (_ORDERED if ordered else _BULLET).match(lines[i].strip())):
                items.append(inline(m2.group(2) if ordered else m2.group(1)))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{it}</li>" for it in items) + f"</{tag}>")
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not _starts_block(lines[i].strip()):
            para.append(inline(lines[i].strip()))
            i += 1
        out.append("<p>" + "<br/>".join(para) + "</p>")
    return "\n".join(out)


def _starts_block(s: str) -> bool:
    return bool(
        s.startswith(("|", "```", "~~~", "#")) or _BULLET.match(s) or _ORDERED.match(s) or _HR.match(s)
    )


def _table_html(rows: list[str]) -> str:
    parts = ["<table>"]
    header_done = False
    for idx, row in enumerate(rows):
        if _TABLE_SEP.match(row):
            continue
        is_header = not header_done and idx + 1 < len(rows) and bool(_TABLE_SEP.match(rows[idx + 1]))
        tag = "th" if is_header else "td"
        header_done = header_done or is_header
        cells = "".join(f"<{tag}>{inline(c) or '&#160;'}</{tag}>" for c in _cells(row))
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</table>")
    return "".join(parts)


def convert(src: Path, dst: Path) -> int:
    """Рендерит Markdown-файл в PDF (A4). Возвращает число страниц."""
    story = pymupdf.Story(md_to_html(src.read_text(encoding="utf-8")), user_css=CSS)
    page_rect = pymupdf.paper_rect("a4")
    content = page_rect + (50, 50, -50, -50)
    dst.parent.mkdir(parents=True, exist_ok=True)
    writer = pymupdf.DocumentWriter(str(dst))
    pages = 0
    more = 1
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(content)
        story.draw(device)
        writer.end_page()
        pages += 1
    writer.close()
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown -> PDF")
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path)
    args = parser.parse_args(argv)
    if not args.src.is_file():
        print(f"Нет файла: {args.src}", file=sys.stderr)
        return 1
    pages = convert(args.src, args.dst)
    print(f"{args.dst}: {pages} стр.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
