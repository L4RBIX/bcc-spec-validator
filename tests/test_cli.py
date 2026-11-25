"""E2E: CLI с провайдером fake на синтетических фикстурах и на примере из examples/."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_report import SECTIONS

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "validator", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("fixture", ["sample_md", "sample_pdf", "sample_docx"])
def test_e2e_fake_provider(fixture, request, tmp_path):
    doc = request.getfixturevalue(fixture)
    report = tmp_path / "out" / "report.md"
    html = tmp_path / "out" / "report.html"
    res = run_cli(str(doc), str(report), "--html", str(html), "--provider", "fake", cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "требований" in res.stdout and f"отчёт: {report}" in res.stdout
    text = report.read_text(encoding="utf-8")
    for s in SECTIONS:
        assert s in text
    assert (tmp_path / "out" / "dropped.jsonl").exists()
    assert html.read_text(encoding="utf-8").startswith("<!doctype html>")


@pytest.mark.parametrize("name", ["requirements.pdf", "requirements.md"])
def test_e2e_example_document(name, tmp_path):
    res = run_cli(str(ROOT / "examples" / name), str(tmp_path / "r.md"), "--provider", "fake", cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    m = re.match(r"(\d+) требований, (\d+) находок", res.stdout)
    assert m and int(m.group(1)) > 0 and int(m.group(2)) > 0, res.stdout
    report = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "## 7. Чек-лист ревью, заполненный агентом" in report
    dropped = (tmp_path / "out" / "dropped.jsonl").read_text(encoding="utf-8")
    assert dropped == "", "все цитаты правил должны подтверждаться документом"


def test_missing_file(tmp_path):
    res = run_cli("nope.pdf", "out/r.md", "--provider", "fake", cwd=tmp_path)
    assert res.returncode == 1
    assert "не найден" in res.stderr


def test_unsupported_format(tmp_path):
    (tmp_path / "doc.txt").write_text("x", encoding="utf-8")
    res = run_cli("doc.txt", "out/r.md", "--provider", "fake", cwd=tmp_path)
    assert res.returncode == 1 and "не поддерживается" in res.stderr


def test_gemini_without_key(tmp_path, sample_md):
    res = run_cli(str(sample_md), "out/r.md", "--provider", "gemini", cwd=tmp_path)
    assert res.returncode == 1 and "GEMINI_API_KEY" in res.stderr
