"""Детерминированные правила проверки требований (без LLM).

Каждое правило -- отдельная функция `rule_*(doc) -> list[Finding]`. Правила универсальные: они опираются
только на структуру документа и справочники из validator/rules_data/, а не на конкретное ТЗ.
Цитата каждой находки -- дословный фрагмент блока документа.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from validator.doc import Doc, Table, cells, sentence_at
from validator.schema import Block, Finding

DATA_DIR = Path(__file__).parent / "rules_data"

Rule = Callable[[Doc], list[Finding]]


# ---------------------------------------------------------------- справочники


@lru_cache
def lexicon() -> dict:
    """Общий словарь правил (rules_data/lexicon.yaml)."""
    return yaml.safe_load((DATA_DIR / "lexicon.yaml").read_text(encoding="utf-8"))


@lru_cache
def unit_families() -> dict:
    """Семейства единиц измерения (rules_data/units.yaml)."""
    return yaml.safe_load((DATA_DIR / "units.yaml").read_text(encoding="utf-8"))


def word_pattern(entry: str) -> str:
    """Запись словаря -> regex с границами слова; «*» в конце -- любое окончание."""
    if entry.endswith("*"):
        return rf"(?<!\w){re.escape(entry[:-1])}\w*"
    return rf"(?<!\w){re.escape(entry)}(?!\w)"


@lru_cache
def vague_regex() -> re.Pattern[str]:
    """Один regex по всем размытым выражениям (длинные записи первыми)."""
    lines = (DATA_DIR / "vague_ru.txt").read_text(encoding="utf-8").splitlines()
    entries = sorted({ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}, key=len, reverse=True)
    return re.compile("|".join(word_pattern(e) for e in entries), re.IGNORECASE)


def _any_regex(words: list[str], flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile("|".join(word_pattern(w + "*") for w in words), flags)


# ---------------------------------------------------------------- конструктор находки


def make_finding(
    *,
    criterion: str,
    severity: str,
    quotes: list[str],
    problem: str,
    impact: str,
    question: str,
    options: list[str],
    fix: str,
    scope: str = "item",
    addressee: str = "аналитик",
) -> Finding:
    """Находка правила: source=rule, confidence=1.0, цитаты без повторов."""
    uniq = list(dict.fromkeys(q.strip() for q in quotes if q.strip()))
    return Finding(
        finding_id="",
        req_ids=[],
        scope=scope,  # type: ignore[arg-type]
        criterion=criterion,
        severity=severity,  # type: ignore[arg-type]
        quotes=uniq,
        problem=problem,
        impact=impact,
        question=question,
        addressee=addressee,  # type: ignore[arg-type]
        options=options,
        fix=fix,
        source="rule",
        confidence=1.0,
    )


SHORT_BLOCK = 120


def quote_at(block: Block, start: int, end: int) -> str:
    """Цитата для найденного фрагмента: короткий блок целиком, иначе предложение вокруг фрагмента."""
    return block.text if len(block.text) <= SHORT_BLOCK else sentence_at(block.text, start, end)


def inline(quote: str) -> str:
    """Цитата для вставки в текст находки: без завершающей точки (точку ставит сама фраза)."""
    return quote.strip().rstrip(".").rstrip()


def _choice_regex() -> re.Pattern[str]:
    return re.compile(r"^\s*(?:" + "|".join(lexicon()["choice_patterns"]) + r")\s*$", re.IGNORECASE)


def _is_choice_row(block: Block) -> bool:
    rx = _choice_regex()
    return block.kind == "table_row" and any(rx.match(c) for c in cells(block))


# ---------------------------------------------------------------- 1. плейсхолдеры

_SUBFIELD_RE = re.compile(
    r"(?P<label>[A-Za-zА-Яа-яЁё][\w\- ]{0,30}?)\s*:\s*(?P<val>[—–-]{1,3}|TBD|TODO|N/A|\?{2,3})\s*(?=$|[.;,])"
)


def _is_technical(name: str) -> bool:
    low = name.lower()
    return any(re.search(rf"(?<![a-zа-яё]){re.escape(t)}", low) for t in lexicon()["technical_fields"])


def _placeholder_finding(doc: Doc, row: Block, field: str, value: str) -> Finding:
    shown = f"стоит «{value}»" if value else "значение пустое"
    technical = _is_technical(field)
    impact = (
        f"Без значения поля «{field}» разработчик не знает, куда и как обращаться, а тестировщик не может "
        "настроить окружение и проверить вызов."
        if technical
        else f"Поле «{field}» предусмотрено шаблоном документа; без него документ нельзя согласовать, "
        "а разработчик и тестировщик будут опираться на догадки."
    )
    return make_finding(
        criterion="conforming",
        severity="major" if technical else "minor",
        quotes=[row.text],
        problem=f"В разделе «{doc.where(row)}» поле «{field}» не заполнено ({shown}).",
        impact=impact,
        question=f"Какое значение поля «{field}» должно быть в разделе «{doc.where(row)}»?",
        options=["Указать значение", "Пометить как «не применимо» с причиной"],
        fix=f"Заполнить поле «{field}» или явно указать, почему оно не применимо.",
    )


def _placeholders_in_row(doc: Doc, row: Block) -> Iterator[Finding]:
    row_cells = cells(row)
    if len(row_cells) != 2 or not row_cells[0]:
        return
    key, value = row_cells
    if value.lower() in lexicon()["placeholder_values"]:
        yield _placeholder_finding(doc, row, key, value)
        return
    for m in _SUBFIELD_RE.finditer(value):
        yield _placeholder_finding(doc, row, f"{key} › {m.group('label').strip()}", m.group("val"))


def rule_placeholders(doc: Doc) -> list[Finding]:
    """Незаполненные поля: прочерки, TBD/TODO/N/A/???, пустые значения в таблицах «поле | значение»."""
    out: list[Finding] = []
    for table in doc.tables:
        for row in table.data:
            out.extend(_placeholders_in_row(doc, row))
    tokens = re.compile("|".join(rf"(?<![\w?<\[]){re.escape(t)}(?![\w?>\]])" for t in lexicon()["placeholder_tokens"]))
    for b in doc.blocks:
        if b.kind in ("heading", "code", "table_row"):  # таблицы разобраны выше
            continue
        for m in tokens.finditer(b.text):
            out.append(
                make_finding(
                    criterion="conforming",
                    severity="minor",
                    quotes=[quote_at(b, m.start(), m.end())],
                    problem=f"В разделе «{doc.where(b)}» оставлена пометка-заглушка «{m.group(0)}».",
                    impact="Часть требования не определена: разработчик реализует её по своему усмотрению, "
                    "а тестировщику не с чем сравнить результат.",
                    question=f"Что должно стоять вместо «{m.group(0)}» в разделе «{doc.where(b)}»?",
                    options=["Дописать недостающую часть требования", "Удалить пометку, если вопрос закрыт"],
                    fix=f"Заменить «{m.group(0)}» окончательной формулировкой.",
                )
            )
    return out


# ---------------------------------------------------------------- 2. неотмеченные варианты и подписи


def _header_label(table: Table) -> str:
    return cells(table.header)[0] or "без заголовка"


def rule_unchecked_choices(doc: Doc) -> list[Finding]:
    """Шаблонные варианты «Да / Нет» без выбора; пустые таблицы подписей и согласования."""
    out: list[Finding] = []
    for table in doc.tables:
        unchecked = [r for r in table.data if _is_choice_row(r)]
        if unchecked:
            sample = next(c for c in cells(unchecked[0]) if _choice_regex().match(c))
            out.append(
                make_finding(
                    criterion="conforming",
                    severity="minor",
                    quotes=[unchecked[0].text],
                    problem=f"В разделе «{doc.where(table.header)}» в {len(unchecked)} из {len(table.data)} "
                    f"пунктов таблицы «{_header_label(table)}» не сделан выбор: оставлены все варианты "
                    f"(«{sample}»).",
                    impact="Непонятно, пройдены ли проверки: документ выглядит прошедшим ревью, хотя отметок нет, "
                    "и разработка может начаться по непроверенным требованиям.",
                    question=f"Кто проводит проверку по таблице «{_header_label(table)}» и какие пункты выполнены?",
                    options=[
                        "Провести проверку и оставить по каждому пункту один вариант",
                        "Удалить таблицу, если проверка ведётся в другом инструменте, и дать ссылку",
                    ],
                    fix="По каждому пункту оставить один вариант и заполнить примечания.",
                )
            )
        out.extend(_empty_signature_table(doc, table))
    return out


def _empty_signature_table(doc: Doc, table: Table) -> list[Finding]:
    markers = lexicon()["signature_markers"]
    context = (table.header.text + " " + table.section).lower()
    if not any(m in context for m in markers):
        return []
    if any(any(c for c in cells(r)) for r in table.data):
        return []
    return [
        make_finding(
            criterion="conforming",
            severity="major",
            quotes=[table.header.text],
            problem=f"В разделе «{doc.where(table.header)}» таблица согласования («{table.header.text}») пустая: "
            "нет ни одного подразделения, ответственного и подписи.",
            impact="Неизвестно, кто утвердил требования: разработка может начаться по несогласованному документу, "
            "а спорные места некому разрешить.",
            question="Кто должен согласовать документ и подписал ли он текущую версию?",
            options=[
                "Внести согласующих и получить подписи",
                "Указать, где ведётся согласование, и дать ссылку",
            ],
            fix="Заполнить таблицу согласования: подразделение, ответственный, отметка о подписи.",
            addressee="BO",
        )
    ]


# ---------------------------------------------------------------- 3. пустые разделы


def _is_stub(block: Block) -> bool:
    low = block.text.strip().lower()
    return len(low) <= 80 and any(low.startswith(p) for p in lexicon()["stub_phrases"])


def rule_empty_sections(doc: Doc) -> list[Finding]:
    """Заголовок без содержимого до следующего заголовка или только с фразой-заглушкой."""
    out: list[Finding] = []
    for h in doc.headings:
        content: list[Block] = []
        nxt = doc.next(h)
        while nxt is not None and nxt.kind != "heading":
            content.append(nxt)
            nxt = doc.next(nxt)
        if not content and nxt is not None and doc.depth(nxt) > doc.depth(h):
            continue  # раздел-родитель: содержимое в подразделах
        if content and not all(_is_stub(b) for b in content):
            continue
        stub = content[0].text if content else None
        what = f"вместо содержания стоит «{stub}»" if stub else "после заголовка нет текста"
        out.append(
            make_finding(
                criterion="set_complete",
                severity="major",
                scope="set",
                quotes=[stub or h.text],
                problem=f"Раздел «{doc.where(h)}» не заполнен: {what}.",
                impact=f"Требования раздела «{h.text}» не определены: разработчику и тестировщику нечего "
                "реализовывать и проверять в этой части.",
                question=f"Что должно быть в разделе «{h.text}» и кто заполнит его до начала разработки?",
                options=[
                    "Заполнить раздел до старта разработки",
                    "Удалить раздел, если он не применим, и указать причину",
                ],
                fix=f"Заполнить раздел «{h.text}» или явно пометить его как неприменимый с причиной.",
            )
        )
    return out


# ---------------------------------------------------------------- 4. версия и дата

HEAD_BLOCKS = 30


def _has_pattern(doc: Doc, patterns: list[str]) -> bool:
    rx = re.compile("|".join(patterns), re.IGNORECASE)
    head = doc.blocks[:HEAD_BLOCKS]
    keyed = [b for b in doc.blocks if b.kind == "table_row" and _is_version_key(cells(b)[0])]
    return any(rx.search(" ".join(cells(b))) for b in head + keyed)


def _is_version_key(name: str) -> bool:
    low = name.lower()
    return any(low.startswith(k) for k in lexicon()["version_keys"])


def rule_version_date(doc: Doc) -> list[Finding]:
    """Нет версии и/или даты документа; явное «не заполнено» -- major."""
    lex = lexicon()
    explicit = re.compile(lex["version_missing"], re.IGNORECASE)
    for b in doc.blocks:
        m = explicit.search(b.text)
        if m and not _is_choice_row(b):
            quote = quote_at(b, m.start(), m.end())
            return [
                _version_finding(
                    f"В документе прямо сказано, что версия или дата не заполнены: «{inline(quote)}».",
                    quote,
                    "major",
                )
            ]
    missing = [
        name
        for name, key in (("версия", "version_patterns"), ("дата", "date_patterns"))
        if not _has_pattern(doc, lex[key])
    ]
    if not missing or not doc.blocks:
        return []
    return [_version_finding(f"В начале документа не указаны: {' и '.join(missing)}.", doc.blocks[0].text, "minor")]


def _version_finding(problem: str, quote: str, severity: str) -> Finding:
    return make_finding(
        criterion="modifiable",
        severity=severity,
        scope="set",
        quotes=[quote],
        problem=problem,
        impact="Нельзя однозначно сослаться на редакцию документа: разработка, тестирование и согласование могут "
        "идти по разным версиям требований, изменения не отследить.",
        question="Какая версия и дата у текущей редакции документа и где ведётся история изменений?",
        options=[
            "Добавить в шапку номер версии и дату, вести лист изменений",
            "Сослаться на систему, где хранится версия документа",
        ],
        fix="Добавить в шапку документа номер версии, дату и лист изменений.",
    )


# ---------------------------------------------------------------- 5. размытые формулировки


def rule_vague_words(doc: Doc) -> list[Finding]:
    """Размытые слова и обороты (словарь vague_ru.txt) -> unambiguous, по находке на предложение."""
    out: list[Finding] = []
    rx = vague_regex()
    for b in doc.blocks:
        if b.kind in ("heading", "code") or _is_choice_row(b):
            continue
        by_sentence: dict[str, list[str]] = {}
        for m in rx.finditer(b.text):
            by_sentence.setdefault(quote_at(b, m.start(), m.end()), []).append(m.group(0))
        for sentence, words in by_sentence.items():
            w = "», «".join(dict.fromkeys(words))
            out.append(
                make_finding(
                    criterion="unambiguous",
                    severity="major",
                    quotes=[sentence],
                    problem=f"В разделе «{doc.where(b)}» формулировка содержит размытое выражение «{w}»: "
                    "из него нельзя однозначно понять, что именно требуется.",
                    impact=f"Разработчик и тестировщик поймут «{w}» по-разному; без конкретного значения "
                    "требование нельзя проверить тестом.",
                    question=f"Что конкретно означает «{w}»: какое значение, полный перечень или условие?",
                    options=[
                        "Заменить на измеримое значение или полный перечень",
                        "Удалить выражение, если оно не несёт требования",
                    ],
                    fix=f"Заменить «{w}» на конкретное значение, перечень или условие, которое можно проверить.",
                )
            )
    return out


# ---------------------------------------------------------------- 6. единицы измерения


@dataclass(frozen=True)
class _UnitHit:
    group: str
    block: Block
    sentence: str


def _unit_hits(doc: Doc, groups: list[dict], with_number: bool) -> dict[str, list[_UnitHit]]:
    hits: dict[str, list[_UnitHit]] = {}
    for g in groups:
        alt = "|".join(word_pattern(p) for p in g["patterns"])
        rx = re.compile(rf"\d\s*(?:{alt})" if with_number else alt)
        for b in doc.blocks:
            if b.kind == "code":
                continue
            for m in rx.finditer(b.text):
                hits.setdefault(g["name"], []).append(_UnitHit(g["name"], b, sentence_at(b.text, m.start(), m.end())))
    return hits


def _pick_quotes(hits: dict[str, list[_UnitHit]]) -> list[str]:
    """По цитате на группу; для второй группы предпочитаем тот же блок или раздел, что у первой."""
    names = list(hits)
    anchor = hits[names[1]][0]
    first = next(
        (h for h in hits[names[0]] if h.block == anchor.block),
        next((h for h in hits[names[0]] if h.block.section == anchor.block.section), hits[names[0]][0]),
    )
    return [first.sentence, anchor.sentence]


def rule_mixed_units(doc: Doc) -> list[Finding]:
    """Одна величина в разных единицах одного семейства (валюта и её дробная единица, мс/с/мин и т.п.)."""
    out: list[Finding] = []
    for kind, spec in unit_families().items():
        with_number = spec["mode"] == "number"
        for family, groups in spec["families"].items():
            hits = _unit_hits(doc, groups, with_number)
            if with_number:  # без валют: единицы должны встретиться в одном разделе
                sections = [{h.block.section for h in v} for v in hits.values()]
                if len(sections) < 2 or not set.intersection(*sections):
                    continue
            if len(hits) < 2:
                continue
            out.append(_units_finding(kind, family, list(hits), _pick_quotes(hits)))
    return out


def _units_finding(kind: str, family: str, groups: list[str], quotes: list[str]) -> Finding:
    g1, g2 = groups[0], groups[1]
    money = kind == "currency"
    what = f"Денежные суммы ({family})" if money else f"Величины одного типа ({family})"
    impact = (
        "Разработчик может сравнить или сложить значения в разных единицах без пересчёта (ошибка в 100 раз), "
        "тестировщик не знает, какие значения ожидать в базе, API и на экране."
        if money
        else "Разработчик может сравнить значения в разных единицах без пересчёта, тестировщик не знает, "
        "какое значение проверять."
    )
    return make_finding(
        criterion="unambiguous",
        severity="major",
        scope="set",
        quotes=quotes,
        problem=f"{what} указаны в разных единицах: «{g1}» и «{g2}». Не сказано, где какая единица используется "
        "и как они пересчитываются.",
        impact=impact,
        question=f"В каких единицах хранить, передавать и показывать значения: «{g1}» или «{g2}», "
        "и где выполняется пересчёт?",
        options=[
            f"Везде использовать «{g1}»",
            f"Хранить в «{g2}», показывать в «{g1}» с явным правилом пересчёта",
        ],
        fix="Зафиксировать единицу для каждого поля (хранение, API, экран) и правило пересчёта между ними.",
    )


# ---------------------------------------------------------------- 7. HTTP / API

_URL_RE = re.compile(r"https?://\S+|(?<![\w/.])/[A-Za-z_{][\w\-{}.]*(?:/[\w\-{}.]+)*")
_CODE_RE = re.compile(r"(?<![\w.,])([1-5]\d{2})(?![\w])")
_DECLARATION_RE = re.compile(r"^\s*([1-5]\d{2})\b[.:)\s—–-]*(?P<rest>.+)$")
_EXAMPLE_LABEL_MAX = 80


def _methods_regex() -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(lexicon()["http_methods"]) + r")\b")


def _api_signal(doc: Doc, b: Block) -> bool:
    words = lexicon()["api_section_words"]
    section = b.section.lower()
    if any(re.search(rf"(?<![a-zа-яё]){re.escape(w)}", section) for w in words):
        return True
    return bool(_methods_regex().search(b.text) or _URL_RE.search(b.text) or re.search(r"(?i)\bstatus|статус", b.text))


def api_zone(doc: Doc) -> list[Block]:
    """Блоки глав, похожих на описание API: есть HTTP-метод, URL или слово «статус»/«status»."""
    chapters = {doc.chapter(b) for b in doc.blocks if _api_signal(doc, b)}
    return [b for b in doc.blocks if doc.chapter(b) in chapters]


@lru_cache
def unit_after_regex() -> re.Pattern[str]:
    """Единица сразу после числа (все единицы из units.yaml и общие: %, бит, знак...) -- значит, это не код."""
    patterns = [
        p
        for spec in unit_families().values()
        for groups in spec["families"].values()
        for g in groups
        for p in g["patterns"]
    ]
    generic = ["%", "бит*", "bit*", "знак*", "символ*", "шт", "шт.", "$"]
    return re.compile(r"\s*(?:" + "|".join(word_pattern(p) for p in patterns + generic) + ")", re.IGNORECASE)


def status_codes(text: str) -> list[tuple[str, int, int]]:
    """Трёхзначные HTTP-коды в тексте, кроме частей чисел с разрядами и величин с единицами."""
    out = []
    for m in _CODE_RE.finditer(text):
        before, after = text[max(0, m.start() - 2) : m.start()], text[m.end() : m.end() + 2]
        if re.fullmatch(r"\d\s", before) or re.fullmatch(r"\s\d", after) or unit_after_regex().match(text[m.end() :]):
            continue
        out.append((m.group(1), m.start(), m.end()))
    return out


def _is_example_label(doc: Doc, b: Block) -> bool:
    """Короткий блок с кодом, за которым (возможно, через «или») идёт пример в блоке кода."""
    if b.kind == "code" or len(b.text) > _EXAMPLE_LABEL_MAX or not status_codes(b.text):
        return False
    nxt = doc.next(b)
    if nxt is not None and nxt.kind != "code" and len(nxt.text.split()) <= 2:
        nxt = doc.next(b, 2)
    return nxt is not None and nxt.kind == "code"


def _declared_code(doc: Doc, b: Block) -> str | None:
    """Код из строки списка статусов: «200. Ответ в случае ...» или строка таблицы «200 | описание»."""
    if b.kind == "table_row":
        row = cells(b)
        return row[0] if len(row) >= 2 and re.fullmatch(r"[1-5]\d{2}", row[0]) and row[1] else None
    m = _DECLARATION_RE.match(b.text)
    if m and len(m.group("rest").split()) >= 3 and not _is_example_label(doc, b):
        return m.group(1)
    return None


def rule_http(doc: Doc) -> list[Finding]:
    """Проверки описания API: метод vs операция, статусы, Created, Content-Type, идентификаторы в query."""
    zone = api_zone(doc)
    if not zone:
        return []
    return (
        _http_method_mismatch(doc, zone)
        + _http_undeclared_statuses(doc, zone)
        + _http_created_code(doc, zone)
        + _http_body_content_type(doc, zone)
        + _http_identifiers_in_query(doc, zone)
    )


def _mutation_regexes(method: str) -> list[re.Pattern[str]]:
    lex = lexicon()
    skip = set(lex["delete_verbs"]) if method == "DELETE" else set()
    ru = [w for w in lex["mutation_ru"] if w not in skip]
    en = [w for w in lex["mutation_en"] if w not in skip]
    en_alt = "|".join(f"[{w[0]}{w[0].upper()}]{w[1:]}" for w in en)
    return [_any_regex(ru), re.compile(rf"(?<![A-Za-z])(?:{en_alt})(?![a-z])")]


def _block_method(b: Block) -> str | None:
    if re.search(r"(?<!\w)curl\b.*\s-G\b", b.text):
        return "GET"
    m = re.search(r"\b(GET|DELETE)\b", b.text)
    return m.group(1) if m else None


def _http_method_mismatch(doc: Doc, zone: list[Block]) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for mb in zone:
        method = _block_method(mb)
        if method is None or (mb.section, method) in seen:
            continue
        evidence = _mutation_evidence(zone, mb, method)
        if evidence is None:
            continue
        seen.add((mb.section, method))
        eb, word = evidence
        out.append(
            make_finding(
                criterion="correct",
                severity="major",
                quotes=[mb.text, eb.text],
                problem=f"В разделе «{doc.where(mb)}» метод {method} описан для операции, которая меняет данные "
                f"(«{word}»). По HTTP-семантике {method} "
                + ("должен только читать данные." if method == "GET" else "должен только удалять ресурс."),
                impact="Изменение данных через небезопасный метод могут повторить кэши, прокси, предзагрузка и "
                "повторы клиента, параметры попадут в логи; тестировщик не знает, какое поведение считать верным.",
                question=f"Каким HTTP-методом должна выполняться операция «{word}»: POST/PUT/PATCH или {method}?",
                options=[
                    "Заменить на POST (создание) или PUT/PATCH (изменение) с телом запроса",
                    f"Оставить {method}, но описать операцию как не меняющую данные",
                ],
                fix="Привести метод в соответствие с операцией: изменение данных -- POST/PUT/PATCH, "
                "параметры -- в теле запроса.",
                addressee="архитектор",
            )
        )
    return out


def _mutation_evidence(zone: list[Block], mb: Block, method: str) -> tuple[Block, str] | None:
    """Блок того же раздела, где описано изменение данных, и найденное слово."""
    method_rx = _methods_regex()
    candidates = [b for b in zone if b.section == mb.section and b.kind != "heading"]
    for b in candidates:
        text = method_rx.sub(" ", b.text) if b is mb else b.text
        for rx in _mutation_regexes(method):
            m = rx.search(text)
            if m:
                return b, m.group(0)
    return None


def _http_undeclared_statuses(doc: Doc, zone: list[Block]) -> list[Finding]:
    declared: dict[str, Block] = {}
    for b in zone:
        code = _declared_code(doc, b)
        if code:
            declared.setdefault(code, b)
    if not declared:
        return []
    context = _any_regex(lexicon()["status_context"])
    mentions: dict[str, list[str]] = {}
    for b in zone:
        if b.kind == "code" or _declared_code(doc, b):
            continue
        label = _is_example_label(doc, b)
        if not label and not context.search(b.text):
            continue
        for code, s, e in status_codes(b.text):
            if code not in declared:
                mentions.setdefault(code, []).append(b.text if label else quote_at(b, s, e))
    anchor = next(iter(declared.values()))
    listed = ", ".join(sorted(declared))
    return [
        make_finding(
            criterion="set_consistent",
            severity="major",
            scope="set",
            quotes=quotes[:2] + [anchor.text],
            problem=f"Код ответа {code} упоминается в описании API («{inline(quotes[0])}»), "
            "но его нет в списке статусов "
            f"раздела «{doc.where(anchor)}» (объявлены: {listed}).",
            impact=f"Разработчик не знает, должен ли сервис возвращать {code}, тестировщик -- какой код ожидать "
            "в этом сценарии; клиентское приложение может не обработать ответ.",
            question=f"Возвращает ли метод код {code}, и если да, в каком случае и с каким телом ответа?",
            options=[
                f"Добавить {code} в список статусов с условием и примером",
                f"Убрать {code} из описания и примеров, заменить на объявленный код",
            ],
            fix="Синхронизировать список статусов и примеры: каждый упомянутый код объявить с условием возникновения.",
        )
        for code, quotes in mentions.items()
    ]


def _http_created_code(doc: Doc, zone: list[Block]) -> list[Finding]:
    out: list[Finding] = []
    for b in zone:
        m = re.search(r"\bCreated\b", b.text, re.IGNORECASE)
        if b.kind == "code" or not m:
            continue
        for code, _, _ in status_codes(b.text):
            if code == "201":
                continue
            out.append(
                make_finding(
                    criterion="correct",
                    severity="minor",
                    quotes=[quote_at(b, m.start(), m.end())],
                    problem=f"В разделе «{doc.where(b)}» код {code} подписан как «Created», но по HTTP "
                    "«Created» -- это код 201.",
                    impact="Разработчик и тестировщик по-разному поймут, какой код вернуть при успехе: "
                    f"{code} или 201.",
                    question=f"Какой код возвращается при успешном выполнении: {code} или 201 Created?",
                    options=[
                        f"{code}: исправить подпись кода",
                        "201 Created: исправить код и список статусов",
                    ],
                    fix="Согласовать код ответа и его название по RFC 9110.",
                )
            )
    return out


def _http_body_content_type(doc: Doc, zone: list[Block]) -> list[Finding]:
    absent = [p.lower() for p in lexicon()["body_absent"]]
    ct_blocks = [b for b in zone if re.search(r"(?i)content-type", b.text)]
    out: list[Finding] = []
    for ct in ct_blocks:
        nb = next(
            (b for b in zone if b.section == ct.section and any(p in b.text.lower() for p in absent)),
            None,
        )
        if nb is None:
            continue
        out.append(
            make_finding(
                criterion="set_consistent",
                severity="minor",
                scope="set",
                quotes=[ct.text, nb.text],
                problem=f"В разделе «{doc.where(ct)}» для запроса указан «{inline(ct.text)}», но там же сказано "
                f"«{inline(nb.text)}». Неясно, есть ли у запроса тело.",
                impact="Разработчик не знает, отправлять ли тело и заголовок Content-Type; тестировщик не знает, "
                "какой запрос считать корректным.",
                question="Есть ли у запроса тело? Если нет, нужен ли заголовок Content-Type?",
                options=["Тела нет: убрать Content-Type из описания", "Тело есть: описать его поля"],
                fix="Убрать противоречие между Content-Type и отсутствием тела запроса.",
            )
        )
    return out


def _name_tokens(name: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}


def _is_identifier(name: str, description: str = "") -> bool:
    lex = lexicon()
    if _name_tokens(name) & set(lex["identifier_tokens"]):
        return True
    desc = description.lower()
    return "идентификатор" in desc and any(w in desc for w in lex["identifier_ru"])


def _query_params(doc: Doc, zone: list[Block]) -> dict[str, list[Block]]:
    """Параметры строки запроса: из таблиц query-параметров, URL с «?» и curl -G --data."""
    words = lexicon()["query_section_words"]
    found: dict[str, list[Block]] = {}
    for table in doc.tables:
        if table.header not in zone or not any(w in table.section.lower() for w in words):
            continue
        for row in table.data:
            row_cells = cells(row)
            if _is_identifier(row_cells[0], " ".join(row_cells[1:])):
                found.setdefault(row_cells[0], []).append(row)
    for b in zone:
        query = re.findall(r"\?([\w\-]+=[^\s'\"]*)", b.text)
        if _block_method(b) == "GET" and "curl" in b.text:
            query += re.findall(r"(?:--data(?:-urlencode)?|-d)\s+['\"]?([^'\"\s]+)", b.text)
        for q in query:
            for name in re.findall(r"([\w\-]+)=", q):
                if _is_identifier(name):
                    found.setdefault(name, []).append(b)
    return found


def _http_identifiers_in_query(doc: Doc, zone: list[Block]) -> list[Finding]:
    out: list[Finding] = []
    for name, blocks in _query_params(doc, zone).items():
        out.append(
            make_finding(
                criterion="correct",
                severity="major",
                quotes=[b.text for b in blocks[:2]],
                problem=f"В разделе «{doc.where(blocks[0])}» идентификатор «{name}» передаётся "
                "в строке запроса (query).",
                impact="Идентификаторы клиента и его продуктов из URL оседают в логах серверов и прокси, истории "
                "браузера и мониторинге: это риск утечки персональных и платёжных данных.",
                question=f"Можно ли передавать «{name}» в теле запроса или заменить на непрозрачный токен?",
                options=[
                    "Перенести параметр в тело запроса (POST/PUT)",
                    "Передавать внутренний токен вместо идентификатора и маскировать его в логах",
                ],
                fix=f"Убрать «{name}» из строки запроса: передавать в теле или токеном, согласовать с ИБ.",
                addressee="ИБ",
            )
        )
    return out


# ---------------------------------------------------------------- 8. дубли идентификаторов

_DOC_ID_RE = re.compile(r"^\s*([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё]{0,5}[-.]?\d+(?:\.\d+)*)(?:[.)]\s|\s|$)")


def doc_id(block: Block) -> str | None:
    """Идентификатор требования в начале блока («ТР-1.», «FR-2.1») или в первой ячейке таблицы."""
    if block.kind not in ("list", "para", "table_row"):
        return None
    m = _DOC_ID_RE.match(cells(block)[0] if block.kind == "table_row" else block.text)
    return m.group(1) if m else None


def rule_duplicate_ids(doc: Doc) -> list[Finding]:
    """Один идентификатор у нескольких требований."""
    seen: dict[str, list[Block]] = {}
    for b in doc.blocks:
        rid = doc_id(b)
        if rid:
            seen.setdefault(rid, []).append(b)
    out: list[Finding] = []
    for rid, blocks in seen.items():
        if len(blocks) < 2:
            continue
        w1, w2 = doc.where(blocks[0]), doc.where(blocks[1])
        out.append(
            make_finding(
                criterion="traceable",
                severity="major",
                scope="set",
                quotes=[blocks[0].text, blocks[1].text],
                problem=f"Идентификатор «{rid}» присвоен нескольким требованиям ({len(blocks)}): "
                f"в разделах «{w1}» и «{w2}».",
                impact="Ссылки на требование из тестов, задач и других документов становятся неоднозначными: "
                "нельзя проследить, какое из требований реализовано и проверено.",
                question=f"Какой идентификатор должен быть у второго требования «{rid}»?",
                options=[
                    "Перенумеровать повторяющееся требование",
                    "Объединить требования, если это одно и то же",
                ],
                fix="Сделать идентификаторы требований уникальными и обновить ссылки на них.",
            )
        )
    return out


# ---------------------------------------------------------------- запуск

RULES: tuple[Rule, ...] = (
    rule_placeholders,
    rule_unchecked_choices,
    rule_empty_sections,
    rule_version_date,
    rule_vague_words,
    rule_mixed_units,
    rule_http,
    rule_duplicate_ids,
)


def run_rules(blocks: list[Block]) -> list[Finding]:
    """Прогоняет все правила по документу. source=rule, confidence=1.0."""
    doc = Doc(blocks)
    out: list[Finding] = []
    for rule in RULES:
        out.extend(rule(doc))
    return out
