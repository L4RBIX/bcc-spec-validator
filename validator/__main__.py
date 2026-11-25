"""CLI: python -m validator <путь_к_ТЗ> <путь_к_отчёту.md> [опции]."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from validator import ingest, llm
from validator.check_item import check_items
from validator.check_set import check_set
from validator.checklist import fill_checklist
from validator.facts import extract_facts
from validator.questions import make_questions
from validator.report_html import render_html
from validator.report_md import render_markdown
from validator.rules import run_rules
from validator.runinfo import RunInfo, agent_version, almaty_now, count_lines, file_sha256
from validator.segment import segment
from validator.simulate import simulate
from validator.verify import attach_req_ids, verify, write_dropped

ARTIFACTS_DIR = Path("out")
LLM_LOG = ARTIFACTS_DIR / "llm_log.jsonl"
DROPPED_LOG = ARTIFACTS_DIR / "dropped.jsonl"


class CliError(Exception):
    """Ошибка ввода пользователя: печатается одной строкой без трассировки."""


def build_parser() -> argparse.ArgumentParser:
    """Аргументы командной строки."""
    p = argparse.ArgumentParser(
        prog="python -m validator",
        description="Статическая проверка документа требований (ТЗ) с отчётом на русском.",
    )
    p.add_argument("doc", type=Path, help="путь к документу требований (PDF, MD, DOCX)")
    p.add_argument("report", type=Path, help="путь к Markdown-отчёту, например out/report.md")
    p.add_argument("--html", type=Path, help="дополнительно записать HTML-отчёт по этому пути")
    p.add_argument("--interactive", action="store_true", help="задать вопросы авторам в терминале")
    p.add_argument("--answers", type=Path, help="YAML с ответами на вопросы (вместо --interactive)")
    p.add_argument("--no-cache", action="store_true", help="не использовать кэш ответов LLM")
    p.add_argument("--provider", choices=llm.PROVIDERS, default="gemini", help="провайдер LLM (fake -- без ключа)")
    return p


def _check_inputs(args: argparse.Namespace) -> None:
    if not args.doc.is_file():
        raise CliError(f"файл документа не найден: {args.doc}")
    if args.doc.suffix.lower() not in ingest.SUPPORTED_SUFFIXES:
        raise CliError(f"формат «{args.doc.suffix or 'без расширения'}» не поддерживается, нужен PDF, MD или DOCX")
    if args.report.suffix.lower() != ".md":
        raise CliError(f"отчёт должен быть файлом .md: {args.report}")
    if args.answers is not None and not args.answers.is_file():
        raise CliError(f"файл ответов не найден: {args.answers}")
    if args.provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
        raise CliError(
            "не задан GEMINI_API_KEY. Скопируйте .env.example в .env и впишите ключ "
            "или запустите без LLM: --provider fake"
        )


def run(args: argparse.Namespace) -> tuple[int, int, int]:
    """Прогон пайплайна. Возвращает (требований, находок, критичных)."""
    _check_inputs(args)
    started = almaty_now()
    llm.configure(args.provider, use_cache=not args.no_cache)
    llm_log_before = count_lines(LLM_LOG)

    blocks = ingest.load(args.doc)
    if not blocks:
        raise CliError(f"в документе не найден текст (возможно, скан без текстового слоя): {args.doc}")
    reqs = segment(blocks)
    facts = extract_facts(reqs)
    raw = run_rules(blocks) + check_items(reqs, blocks) + simulate(facts, reqs) + check_set(reqs, facts, blocks)
    findings, dropped = verify(raw, blocks)
    findings = attach_req_ids(findings, reqs, blocks)
    checklist = fill_checklist(blocks, findings, reqs)
    write_dropped(dropped, DROPPED_LOG)
    make_questions(findings)  # вопросы попадут в отчёт на этапе 2
    if args.interactive or args.answers:
        print(
            "Предупреждение: --interactive и --answers заработают на этапе 2, сейчас игнорируются.",
            file=sys.stderr,
        )

    status = Counter(d.status for d in dropped)
    info = RunInfo(
        doc_path=args.doc,
        sha256=file_sha256(args.doc),
        started_at=started,
        provider=args.provider,
        model=llm.model_name(),
        agent_version=agent_version(),
        llm_calls=(count_lines(LLM_LOG) - llm_log_before) if LLM_LOG.exists() else None,
        dropped_no_quote=status["dropped"],
        dropped_duplicates=status["duplicate"],
        partial_quotes=sum(len(d.lost_quotes) for d in dropped if d.status == "partial"),
    )
    md = render_markdown(info, blocks, reqs, findings, checklist)
    _write(args.report, md)
    if args.html:
        _write(args.html, render_html(md, f"Отчёт: {info.doc_name}"))
    critical = Counter(f.severity for f in findings)["critical"]
    return len(reqs), len(findings), critical


def _write(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        raise CliError(f"не удалось записать {path}: {e.strerror}") from e


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI. Код возврата: 0 -- отчёт записан, 1 -- ошибка."""
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        n_reqs, n_findings, n_critical = run(args)
    except CliError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 -- пользователю нужна понятная строка, а не трассировка
        print(f"Ошибка: {type(e).__name__}: {e}", file=sys.stderr)
        if os.getenv("VALIDATOR_DEBUG"):
            traceback.print_exc()
        else:
            print("Подробности: запустите с VALIDATOR_DEBUG=1", file=sys.stderr)
        return 1
    extra = f", HTML: {args.html}" if args.html else ""
    print(f"{n_reqs} требований, {n_findings} находок ({n_critical} критичных), отчёт: {args.report}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
