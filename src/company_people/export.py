"""Экспорт: people.csv (UTF-8 BOM), JSONL, companies.jsonl, review.jsonl, формат pairs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .normalize import csv_safe

PEOPLE_COLUMNS = [
    "input_website_url",
    "company_linkedin_url",
    "profile_url",
    "full_name",
    "source_url",
    "source_type",
    "affiliation_evidence",
    "observed_at",
    "confidence",
]

COMPANY_COLUMNS = [
    "input_website_url",
    "company_name",
    "company_linkedin_url",
    "company_linkedin_source_url",
    "discovery_status",
    "people_status",
    "people_count",
    "pagination_exhausted",
    "coverage_note",
    "stop_reason",
    "observed_at",
    "run_id",
]


def write_people_csv(path: str | Path, rows: list[dict]) -> None:
    _ensure_parent(path)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(PEOPLE_COLUMNS)
        for row in rows:
            writer.writerow([csv_safe(str(row.get(col) or "")) for col in PEOPLE_COLUMNS])


def write_jsonl(path: str | Path, rows: list[dict], columns: list[str] | None = None) -> None:
    _ensure_parent(path)
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        for row in rows:
            item = {col: row.get(col) for col in columns} if columns else dict(row)
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_companies_jsonl(path: str | Path, rows: list[dict]) -> None:
    write_jsonl(path, rows, COMPANY_COLUMNS)


def format_pairs(rows: list[dict]) -> str:
    """Компактный человекочитаемый вывод: 'url, Name; url, Name'."""
    return "; ".join(f"{row['profile_url']}, {row['full_name']}" for row in rows)


def _ensure_parent(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
