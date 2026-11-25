"""ЗАГЛУШКА (модуль ML-друга): клиент LLM и выбор провайдера.

Интерфейс, на который опирается CLI:
    configure(provider, use_cache) -- вызывается один раз до пайплайна;
    model_name() -> str            -- строка модели для паспорта прогона.
Журнал вызовов LLM ожидается в out/llm_log.jsonl (по строке на вызов).
"""

from __future__ import annotations

import os

PROVIDERS = ("gemini", "fake")
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

_state: dict[str, object] = {"provider": "fake", "use_cache": True}


def configure(provider: str, use_cache: bool = True) -> None:
    """Выбирает провайдера LLM для всего прогона."""
    if provider not in PROVIDERS:
        raise ValueError(f"Неизвестный провайдер: {provider}")
    _state["provider"] = provider
    _state["use_cache"] = use_cache


def provider() -> str:
    """Текущий провайдер."""
    return str(_state["provider"])


def model_name() -> str:
    """Имя модели для паспорта прогона."""
    if _state["provider"] == "fake":
        return "fake (детерминированные данные, без LLM)"
    return os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
