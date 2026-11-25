"""HTML-отчёт. Этап 0: самодостаточная обёртка над Markdown-отчётом; полноценный интерфейс -- этап 2."""

from __future__ import annotations

import html


def render_html(markdown_report: str, title: str) -> str:
    """Один HTML-файл без внешних зависимостей; весь текст экранирован."""
    return (
        '<!doctype html>\n<html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#fff;color:#111}"
        "pre{white-space:pre-wrap;word-break:break-word;font-size:14px;line-height:1.45}"
        "@media (prefers-color-scheme: dark){body{background:#111;color:#eee}}</style>"
        f"</head><body><pre>{html.escape(markdown_report)}</pre></body></html>\n"
    )
