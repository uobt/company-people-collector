"""Чтение входных файлов: список компаний и файлы людей (CSV/JSONL)."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def read_rows(path: str | Path) -> list[dict]:
    """Прочитать CSV (UTF-8, допускается BOM) или JSONL; ключи в нижнем регистре."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    suffix = p.suffix.lower()
    rows: list[dict] = []
    if suffix == ".jsonl":
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line:
                rows.append({str(k).strip().lower(): v for k, v in json.loads(line).items()})
    else:
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items()})
    return rows


def read_companies(
    path: str | Path, website_column: str = "website_url"
) -> tuple[list[dict], list[tuple[int, str]]]:
    """Строки с компаниями; второе — строки с ошибками (без сайта в нужной колонке).

    Ключи строк приводятся к нижнему регистру, значение колонки сайта
    дублируется в website_url для единообразной дальнейшей обработки.
    """
    rows = read_rows(path)
    valid: list[dict] = []
    errors: list[tuple[int, str]] = []
    for i, row in enumerate(rows, start=2 if Path(path).suffix.lower() != ".jsonl" else 1):
        site = row.get(website_column, "")
        if not site:
            errors.append((i, f"нет обязательной колонки {website_column}"))
            continue
        row["website_url"] = site
        valid.append(row)
    return valid, errors
