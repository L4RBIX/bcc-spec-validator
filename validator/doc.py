"""Навигация по блокам документа: разделы, главы, таблицы, ячейки, предложения."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

from validator.schema import Block

SEP = " > "
CELL_SEP = " | "
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=\S)|\s\|\s|\n")


def root_heading(blocks: list[Block]) -> str | None:
    """Заголовок верхнего уровня, если он в документе единственный (обычно название документа)."""
    tops = {b.text for b in blocks if b.kind == "heading" and SEP not in b.section}
    return tops.pop() if len(tops) == 1 else None


def display_section(section: str, root: str | None) -> str:
    """Путь раздела для вывода: без единственного корневого H1. Данные блока не меняются."""
    if root and section.startswith(root + SEP):
        return section[len(root) + len(SEP) :]
    return section


def cells(block: Block) -> list[str]:
    """Ячейки строки таблицы."""
    return [c.strip() for c in block.text.split(CELL_SEP)] if block.kind == "table_row" else [block.text]


def sentence_at(text: str, start: int, end: int) -> str:
    """Предложение (или ячейка таблицы), содержащее фрагмент text[start:end], дословно."""
    left, right = 0, len(text)
    for m in _SENTENCE_BOUNDARY.finditer(text):
        if m.end() <= start:
            left = m.end()
        elif m.start() >= end:
            right = m.start()
            break
    return text[left:right].strip()


@dataclass(frozen=True)
class Table:
    """Подряд идущие строки таблицы одного раздела; первая строка -- заголовок."""

    rows: tuple[Block, ...]

    @property
    def header(self) -> Block:
        return self.rows[0]

    @property
    def data(self) -> tuple[Block, ...]:
        return self.rows[1:]

    @property
    def section(self) -> str:
        return self.header.section


class Doc:
    """Документ как список блоков плюс производные структуры."""

    def __init__(self, blocks: list[Block]) -> None:
        self.blocks = blocks
        self.root = root_heading(blocks)
        self.pos = {b.block_id: i for i, b in enumerate(blocks)}

    def where(self, block: Block) -> str:
        """Раздел блока для текста находки."""
        return display_section(block.section, self.root) or "начало документа"

    def title(self, block: Block) -> str:
        """Последний уровень раздела блока."""
        return block.section.rsplit(SEP, 1)[-1] if block.section else "начало документа"

    def chapter(self, block: Block) -> str:
        """Глава: первый уровень раздела под корневым заголовком."""
        parts = block.section.split(SEP) if block.section else []
        if self.root and parts and parts[0] == self.root:
            parts = parts[1:]
        return parts[0] if parts else ""

    def depth(self, block: Block) -> int:
        """Глубина раздела (число уровней пути)."""
        return block.section.count(SEP) + 1 if block.section else 0

    def next(self, block: Block, offset: int = 1) -> Block | None:
        """Блок через offset позиций после данного."""
        i = self.pos[block.block_id] + offset
        return self.blocks[i] if 0 <= i < len(self.blocks) else None

    @cached_property
    def tables(self) -> list[Table]:
        """Таблицы документа: подряд идущие строки одного раздела."""
        out: list[Table] = []
        run: list[Block] = []
        for b in self.blocks:
            if b.kind == "table_row" and (not run or run[-1].section == b.section):
                run.append(b)
                continue
            if run:
                out.append(Table(tuple(run)))
            run = [b] if b.kind == "table_row" else []
        if run:
            out.append(Table(tuple(run)))
        return out

    @cached_property
    def headings(self) -> list[Block]:
        return [b for b in self.blocks if b.kind == "heading"]
