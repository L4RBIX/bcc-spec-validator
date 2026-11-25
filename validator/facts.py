"""ЗАГЛУШКА (модуль ML-друга): извлечение фактов (сущности, величины, правила) из требований."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from validator.schema import Requirement


class Facts(BaseModel):
    """Факты, извлечённые из требований. Заглушка-модель: структуру определит ML-модуль."""

    model_config = ConfigDict(extra="allow")


def extract_facts(reqs: list[Requirement], decisions: list[dict] | None = None) -> Facts:
    """Извлекает факты из требований с учётом решений из уточнений. Заглушка: пусто."""
    return Facts()
