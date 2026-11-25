"""ЗАГЛУШКА (модуль ML-друга): вопросы авторам документа по находкам.

Детерминированно: по вопросу на каждую критичную или существенную находку.
"""

from __future__ import annotations

from validator.schema import Finding, Question

_PRIORITY = {"critical": 1, "major": 2, "minor": 3}


def make_questions(findings: list[Finding]) -> list[Question]:
    """Строит вопросы к авторам по находкам."""
    out: list[Question] = []
    for f in findings:
        if f.severity == "minor" or not f.question.strip():
            continue
        out.append(
            Question(
                q_id=f"Q-{len(out) + 1:02d}",
                finding_ids=[f.finding_id],
                addressee=f.addressee,
                priority=_PRIORITY[f.severity],
                text=f.question,
                why=f.impact,
                options=f.options,
                default_if_no_answer=f.options[0] if f.options else "",
            )
        )
    return out
