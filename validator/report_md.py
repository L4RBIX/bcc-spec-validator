"""Markdown-отчёт о проверке требований (состав строго по п. 6 README кейса)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from validator.runinfo import RunInfo
from validator.schema import CRITERIA, SEVERITY_ORDER, Block, Finding, Requirement
from validator.verify import DocIndex

SEVERITY_RU = {"critical": "критично", "major": "существенно", "minor": "незначительно"}
SOURCE_RU = {"rule": "правило", "llm": "LLM", "simulation": "симуляция"}
KIND_RU = {
    "FR": "функц.",
    "NFR": "нефункц.",
    "DATA": "данные",
    "INT": "интеграция",
    "API": "API",
    "AC": "приёмка",
    "UI": "UI",
    "ARCH": "архитектура",
    "META": "общее",
}
TOP_FIX = 5
NO_FINDINGS = "находок нет"


@dataclass(frozen=True)
class Verdict:
    """Итоговое решение по документу."""

    code: str  # go | conditional | no-go
    title: str
    text: str


def verdict(findings: list[Finding], provider: str) -> Verdict:
    """Можно ли начинать разработку и тестирование по документу."""
    sev = Counter(f.severity for f in findings)
    if sev["critical"]:
        v = Verdict(
            "no-go",
            "Нет",
            f"Начинать разработку и тестирование по документу нельзя: {sev['critical']} критичных дефектов "
            "делают требования непроверяемыми, противоречивыми или неполными.",
        )
    elif sev["major"]:
        v = Verdict(
            "conditional",
            "Условно",
            f"Критичных дефектов нет, но {sev['major']} существенных нужно закрыть до старта работ "
            "по затронутым требованиям.",
        )
    else:
        v = Verdict("go", "Да", "Критичных и существенных дефектов не найдено.")
    if provider == "fake":
        v = Verdict(
            v.code,
            v.title,
            v.text + " Прогон на провайдере fake: LLM-проверка не выполнялась, "
            "вердикт отражает только детерминированную часть агента.",
        )
    return v


def cell(text: str) -> str:
    """Экранирует текст для ячейки Markdown-таблицы."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>").strip()


def format_location(block: Block | None, input_format: str) -> str:
    """«раздел «X», стр. N, строка M» -- ссылка на место в документе."""
    if block is None:
        return "место не определено"
    parts = [f"раздел «{block.section or 'без раздела'}»"]
    if block.page is not None:
        parts.append(f"стр. {block.page}")
    if block.line is not None:
        parts.append(f"{'абзац' if input_format == 'docx' else 'строка'} {block.line}")
    return ", ".join(parts)


class _Ctx:
    """Общие данные для рендеринга разделов."""

    def __init__(self, run: RunInfo, blocks: list[Block], reqs: list[Requirement], findings: list[Finding]):
        self.run = run
        self.blocks = blocks
        self.by_block = {b.block_id: b for b in blocks}
        self.reqs = reqs
        self.req_ids = {r.req_id for r in reqs}
        self.findings = findings
        self.index = DocIndex(blocks)

    def quote_location(self, quote: str) -> str:
        m = self.index.find(quote)
        return format_location(m.first if m else None, self.run.input_format)

    def req_location(self, req: Requirement) -> str:
        block = self.by_block.get(req.block_ids[0]) if req.block_ids else None
        return format_location(block, self.run.input_format)


def render_markdown(
    run: RunInfo, blocks: list[Block], reqs: list[Requirement], findings: list[Finding]
) -> str:
    """Собирает полный Markdown-отчёт."""
    ctx = _Ctx(run, blocks, reqs, findings)
    parts = [
        f"# Отчёт о проверке требований: {run.doc_name}",
        _passport(ctx),
        _segmentation(ctx),
        _item_checks(ctx),
        _set_checks(ctx),
        _summary(ctx),
        _conclusion(ctx),
    ]
    return "\n\n".join(p.rstrip() for p in parts) + "\n"


def _passport(ctx: _Ctx) -> str:
    r = ctx.run
    llm_calls = "нет журнала" if r.llm_calls is None else str(r.llm_calls)
    rows = [
        ("Документ", f"{r.doc_name} ({r.input_format.upper()}, {len(ctx.blocks)} блоков текста)"),
        ("SHA-256 документа", f"`{r.sha256}`"),
        ("Дата и время прогона", r.started_at.strftime("%d.%m.%Y %H:%M:%S") + " (Asia/Almaty)"),
        ("Провайдер / модель", f"{r.provider} / {r.model}"),
        ("Версия агента", f"`{r.agent_version}`"),
        ("Вызовов LLM", llm_calls),
        (
            "Отброшено верификатором",
            f"{r.dropped_no_quote + r.dropped_duplicates} (цитата не найдена: {r.dropped_no_quote}, "
            f"дубликаты: {r.dropped_duplicates})",
        ),
    ]
    lines = ["## 1. Паспорт прогона", "", "| Поле | Значение |", "| :--- | :--- |"]
    lines += [f"| {k} | {cell(v)} |" for k, v in rows]
    return "\n".join(lines)


def _segmentation(ctx: _Ctx) -> str:
    lines = [
        "## 2. Как агент нарезал требования",
        "",
        f"Выделено требований: **{len(ctx.reqs)}**. Если в документе у требования нет номера, "
        "в колонке «ID в документе» стоит «—», ID присвоен агентом, цитата сохранена.",
        "",
    ]
    if not ctx.reqs:
        lines.append(f"Требования не выделены, {NO_FINDINGS}.")
        return "\n".join(lines)
    lines += [
        "| ID в отчёте | ID в документе | Тип | Краткая формулировка | Цитата | Место |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in ctx.reqs:
        lines.append(
            f"| {r.req_id} | {cell(r.doc_id or '—')} | {KIND_RU.get(r.kind, r.kind)} | {cell(r.summary)} "
            f"| «{cell(r.quote)}» | {cell(ctx.req_location(r))} |"
        )
    return "\n".join(lines)


def _criterion_label(criterion: str) -> str:
    source, name = CRITERIA.get(criterion, ("", criterion))
    return f"{name} (`{criterion}`, {source})" if source else criterion


def render_finding(f: Finding, ctx: _Ctx, heading: str = "####") -> str:
    """Карточка одной находки с цитатами и ссылками на место."""
    lines = [
        f"{heading} {f.finding_id} · {SEVERITY_RU[f.severity]} · {_criterion_label(f.criterion)}",
        "",
    ]
    if f.req_ids:
        lines.append(f"- **Требования:** {', '.join(f.req_ids)}")
    for q in f.quotes:
        quoted = q.replace("\n", " / ")
        lines.append(f"- **Где:** {ctx.quote_location(q)}  \n  **Цитата:** «{quoted}»")
    lines += [
        f"- **Проблема:** {f.problem}",
        f"- **Последствия:** {f.impact}",
        f"- **Вопрос ({f.addressee}):** {f.question}",
    ]
    if f.options:
        lines.append("- **Варианты ответа:** " + "; ".join(f"({i}) {o}" for i, o in enumerate(f.options, 1)))
    lines += [
        f"- **Как исправить:** {f.fix}",
        f"- **Источник:** {SOURCE_RU.get(f.source, f.source)}, уверенность {f.confidence:.2f}",
    ]
    return "\n".join(lines)


def _item_checks(ctx: _Ctx) -> str:
    items = [f for f in ctx.findings if f.scope == "item"]
    lines = [
        "## 3. Проверка каждого требования",
        "",
        "Критерии: ISO/IEC/IEEE 29148:2018 п. 5.2.5 (необходимость, уместность, однозначность, полнота, "
        "единичность, выполнимость, проверяемость, корректность, соответствие шаблону) "
        "и IEEE 830-1998 п. 4.3 (ранжированность, модифицируемость, трассируемость).",
        "",
    ]
    if not items:
        lines.append(f"По {len(ctx.reqs)} требованиям из раздела 2 {NO_FINDINGS}.")
        return "\n".join(lines)
    with_findings: list[str] = []
    for r in ctx.reqs:
        own = [f for f in items if r.req_id in f.req_ids]
        if not own:
            continue
        with_findings.append(r.req_id)
        doc_id = f" ({r.doc_id})" if r.doc_id else ""
        lines += [f"### {r.req_id}{doc_id}: {r.summary}", "", f"Место: {ctx.req_location(r)}.", ""]
        lines += [render_finding(f, ctx) + "\n" for f in own]
    orphan = [f for f in items if not set(f.req_ids) & ctx.req_ids]
    if orphan:
        lines += ["### Находки без привязки к выделенному требованию", ""]
        lines += [render_finding(f, ctx) + "\n" for f in orphan]
    clean = [r.req_id for r in ctx.reqs if r.req_id not in with_findings]
    if clean:
        lines += [f"Требования без нарушений по этим критериям: {', '.join(clean)}."]
    return "\n".join(lines)


def _set_checks(ctx: _Ctx) -> str:
    sets = [f for f in ctx.findings if f.scope == "set"]
    lines = [
        "## 4. Проверка всего набора требований",
        "",
        "Критерии: ISO/IEC/IEEE 29148:2018 п. 5.2.6 (полнота, непротиворечивость, выполнимость, понятность, "
        "валидируемость набора).",
        "",
    ]
    if not sets:
        lines.append(f"По набору из {len(ctx.reqs)} требований {NO_FINDINGS}.")
        return "\n".join(lines)
    lines += [render_finding(f, ctx, heading="###") + "\n" for f in sets]
    return "\n".join(lines)


def _summary(ctx: _Ctx) -> str:
    sev = Counter(f.severity for f in ctx.findings)
    lines = [
        "## 5. Сводка",
        "",
        f"- Требований: **{len(ctx.reqs)}**",
        f"- Нарушений: **{len(ctx.findings)}** (критично: {sev['critical']}, существенно: {sev['major']}, "
        f"незначительно: {sev['minor']})",
        "",
    ]
    if ctx.findings:
        by_crit = Counter(f.criterion for f in ctx.findings)
        lines += ["| Критерий | Источник | Нарушений |", "| :--- | :--- | ---: |"]
        for crit in CRITERIA:
            if by_crit[crit]:
                source, name = CRITERIA[crit]
                lines.append(f"| {name} (`{crit}`) | {source} | {by_crit[crit]} |")
        lines.append("")
    critical = [f for f in ctx.findings if f.severity == "critical"]
    lines.append("**Критичные дефекты:**")
    lines.append("")
    if not critical:
        lines.append(f"Критичных дефектов: {NO_FINDINGS}.")
    for f in critical:
        lines.append(
            f"- {f.finding_id} ({CRITERIA[f.criterion][1].lower()}): {f.problem} "
            f"Место: {ctx.quote_location(f.quotes[0])}."
        )
    return "\n".join(lines)


def _conclusion(ctx: _Ctx) -> str:
    v = verdict(ctx.findings, ctx.run.provider)
    lines = [
        "## 6. Итог",
        "",
        f"**Можно ли начинать разработку и тестирование: {v.title}.** {v.text}",
        "",
        "**Что исправить в первую очередь:**",
        "",
    ]
    top = sorted(ctx.findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.finding_id))[:TOP_FIX]
    if not top:
        lines.append(f"Исправлений не требуется: {NO_FINDINGS}.")
    for i, f in enumerate(top, 1):
        where = ctx.quote_location(f.quotes[0])
        lines.append(f"{i}. {f.finding_id} ({SEVERITY_RU[f.severity]}): {f.fix} Место: {where}.")
    return "\n".join(lines)
