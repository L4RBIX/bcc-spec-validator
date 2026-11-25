"""Контракты данных между модулями агента. Поля менять только по согласованию команды."""

from typing import Literal

from pydantic import BaseModel


class Block(BaseModel):
    block_id: str  # B-001
    section: str  # "Часть A > Функциональные требования"
    page: int | None
    line: int | None
    kind: Literal["heading", "para", "list", "table_row", "code"]
    text: str


class Requirement(BaseModel):
    req_id: str  # R-01, сквозная нумерация (подтребования R-03a, R-03b)
    doc_id: str | None  # идентификатор из документа или None
    kind: Literal["FR", "NFR", "DATA", "INT", "API", "AC", "UI", "ARCH", "META"]
    section: str
    quote: str  # дословно из документа
    summary: str  # краткая формулировка для таблицы нарезки
    block_ids: list[str]


class Finding(BaseModel):
    finding_id: str  # F-001, присваивает verify.py
    req_ids: list[str]
    scope: Literal["item", "set"]
    criterion: str  # значение из CRITERIA
    severity: Literal["critical", "major", "minor"]
    quotes: list[str]  # дословно, минимум одна
    problem: str
    impact: str
    question: str
    addressee: Literal["BO", "аналитик", "архитектор", "ИБ", "QA"]
    options: list[str]
    fix: str
    source: Literal["rule", "llm", "simulation"]
    confidence: float


class Question(BaseModel):
    q_id: str
    finding_ids: list[str]
    addressee: str
    priority: int  # 1 = блокирует разработку
    text: str
    why: str
    options: list[str]
    default_if_no_answer: str


# Справочник критериев: значение -> (источник, русское название).
CRITERIA: dict[str, tuple[str, str]] = {
    "necessary": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Необходимость"),
    "appropriate": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Уместность уровня детализации"),
    "unambiguous": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Однозначность"),
    "complete": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Полнота"),
    "singular": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Единичность"),
    "feasible": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Выполнимость"),
    "verifiable": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Проверяемость"),
    "correct": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Корректность"),
    "conforming": ("ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Соответствие шаблону"),
    "set_complete": ("ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Полнота набора"),
    "set_consistent": ("ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Непротиворечивость набора"),
    "set_feasible": ("ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Выполнимость набора"),
    "set_comprehensible": ("ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Понятность набора"),
    "set_validatable": ("ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Валидируемость набора"),
    "ranked": ("IEEE 830-1998 п. 4.3", "Ранжированность"),
    "modifiable": ("IEEE 830-1998 п. 4.3", "Модифицируемость"),
    "traceable": ("IEEE 830-1998 п. 4.3", "Трассируемость"),
}

SEVERITY_ORDER: dict[str, int] = {"critical": 0, "major": 1, "minor": 2}
