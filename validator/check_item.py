"""ЗАГЛУШКА (модуль ML-друга): LLM-проверка каждого требования по критериям 29148 п. 5.2.5."""

from __future__ import annotations

from validator.schema import Block, Finding, Requirement


def check_items(reqs: list[Requirement], blocks: list[Block]) -> list[Finding]:
    """Проверяет требования по одному. Заглушка: находок нет."""
    return []
