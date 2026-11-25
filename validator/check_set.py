"""ЗАГЛУШКА (модуль ML-друга): проверка набора требований по 29148 п. 5.2.6 и IEEE 830 п. 4.3."""

from __future__ import annotations

from validator.facts import Facts
from validator.schema import Block, Finding, Requirement


def check_set(
    reqs: list[Requirement], facts: Facts, blocks: list[Block], decisions: list[dict] | None = None
) -> list[Finding]:
    """Проверяет набор требований целиком. Заглушка: находок нет."""
    return []
