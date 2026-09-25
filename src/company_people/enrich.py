"""Обогащение базы компаний людьми: по сотруднику на строку + две новые колонки.

Семантика: каждая исходная строка базы копируется N раз (N = число найденных
сотрудников компании); в каждую копию добавляются значения employee_profile_url
и employee_full_name. Компания без сотрудников остаётся одной строкой с пустыми
новыми колонками (чтобы не терять строки базы).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .inputs import read_rows
from .normalize import csv_safe, website_key
from .people_import import import_people
from .storage import Store

EMPLOYEE_URL_COLUMN = "employee_profile_url"
EMPLOYEE_NAME_COLUMN = "employee_full_name"
COMPANY_LINKEDIN_COLUMN = "company_linkedin_url"


@dataclass
class EnrichStats:
    rows_in: int = 0
    rows_out: int = 0
    employees_attached: int = 0
    companies_with_people: int = 0
    companies_without_people: int = 0
    unmatched_rows: int = 0  # строка без корректного/известного сайта
    company_linkedin_filled: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"строк базы: {self.rows_in} -> строк с сотрудниками: {self.rows_out}; "
            f"компаний с людьми: {self.companies_with_people}, без людей: {self.companies_without_people}, "
            f"без распознанного сайта: {self.unmatched_rows}; "
            f"заполнено company_linkedin_url: {self.company_linkedin_filled}"
        )


def read_base_rows(path: str | Path) -> list[dict]:
    """Прочитать базу, сохраняя исходные заголовки и порядок колонок как есть."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def enrich_base(
    base_rows: list[dict],
    store: Store,
    website_column: str = "website_url",
    include_review: bool = True,
) -> tuple[list[dict], EnrichStats]:
    stats = EnrichStats(rows_in=len(base_rows))
    out_rows: list[dict] = []
    seen_keys: set[str] = set()

    for row in base_rows:
        raw_site = (row.get(website_column) or "").strip()
        key = website_key(raw_site) if raw_site else None
        if key is None:
            stats.unmatched_rows += 1
            stats.notes.append(f"строка без корректного '{website_column}': {raw_site or '—'}")
            out_rows.append(_empty_copy(row))
            continue
        seen_keys.add(key)
        _fill_company_linkedin(row, key, store, stats)
        people = store.company_people_rows(key, include_review=include_review)
        if not people:
            stats.companies_without_people += 1
            out_rows.append(_empty_copy(row))
            continue
        stats.companies_with_people += 1
        stats.employees_attached += len(people)
        for person in people:
            copy = dict(row)
            copy[EMPLOYEE_URL_COLUMN] = csv_safe(person["canonical_url"])
            copy[EMPLOYEE_NAME_COLUMN] = csv_safe(person["full_name"])
            out_rows.append(copy)
    stats.rows_out = len(out_rows)
    return out_rows, stats


def write_enriched_csv(path: str | Path, rows: list[dict], base_columns: list[str]) -> None:
    """CSV UTF-8 BOM: исходные колонки в исходном порядке + две новые в конце."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    header = base_columns + [EMPLOYEE_URL_COLUMN, EMPLOYEE_NAME_COLUMN]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(col, "") for col in header])


def optionally_import_people(store: Store, people_file: str | None, source_label: str, run_id: str, max_per_company: int) -> None:
    """Если указан файл людей — импортировать его перед обогащением (удобство одного вызова)."""
    if not people_file:
        return
    rows = read_rows(people_file)
    stats = import_people(
        store,
        rows,
        run_id,
        source_label=source_label,
        source_ref=f"{source_label}:{Path(people_file).name}",
        max_per_company=max_per_company,
    )


def _fill_company_linkedin(row: dict, key: str, store: Store, stats: EnrichStats) -> None:
    """Заполнить пустую колонку company_linkedin_url из найденной при обходе страницы.

    Непустое значение базы никогда не перезаписывается.
    """
    if COMPANY_LINKEDIN_COLUMN not in row:
        return
    if (row.get(COMPANY_LINKEDIN_COLUMN) or "").strip():
        return
    company = store.get_company_by_key(key)
    if company and company.get("company_linkedin_url"):
        row[COMPANY_LINKEDIN_COLUMN] = company["company_linkedin_url"]
        stats.company_linkedin_filled += 1


def _empty_copy(row: dict) -> dict:
    copy = dict(row)
    copy[EMPLOYEE_URL_COLUMN] = ""
    copy[EMPLOYEE_NAME_COLUMN] = ""
    return copy
