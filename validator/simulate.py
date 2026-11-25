"""ЗАГЛУШКА (модуль ML-друга): симуляция сценариев по извлечённым фактам."""

from __future__ import annotations

from validator.facts import Facts
from validator.schema import Finding, Requirement


def simulate(facts: Facts, reqs: list[Requirement], decisions: list[dict] | None = None) -> list[Finding]:
    """Прогоняет сценарии по фактам и ищет противоречия. Заглушка: находок нет."""
    return []
