"""Паспорт прогона: что, когда, чем и какой версией агента проверяли."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from validator import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RunInfo:
    """Сведения о прогоне для паспорта в отчёте."""

    doc_path: Path
    sha256: str
    started_at: datetime
    provider: str
    model: str
    agent_version: str
    llm_calls: int | None = None
    dropped_no_quote: int = 0
    dropped_duplicates: int = 0

    @property
    def doc_name(self) -> str:
        return self.doc_path.name

    @property
    def input_format(self) -> str:
        return self.doc_path.suffix.lower().lstrip(".")


def almaty_now() -> datetime:
    """Текущее время в Asia/Almaty (UTC+5); без базы часовых поясов -- фиксированное смещение."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Almaty"))
    except Exception:  # noqa: BLE001 -- на Windows без tzdata ZoneInfo недоступен
        return datetime.now(timezone(timedelta(hours=5), "Asia/Almaty"))


def file_sha256(path: Path) -> str:
    """SHA-256 содержимого файла."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def agent_version() -> str:
    """Версия агента: `git describe --tags --always --dirty`, без git -- версия пакета."""
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        res = None
    if res is not None and res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    return f"v{__version__} (git недоступен)"


def count_lines(path: Path) -> int:
    """Число непустых строк в файле (0, если файла нет)."""
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if line.strip())
