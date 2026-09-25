"""Импорт разрешённых данных о людях: CSV/JSONL от оператора или лицензированного поставщика."""

from __future__ import annotations

from dataclasses import dataclass, field

from .inputs import read_rows
from .models import AFFILIATION_KINDS
from .normalize import canonical_linkedin_company, canonical_linkedin_profile, website_key
from .storage import Store

_INVALID_NAMES = {"", "linkedin member", "private member", "n/a", "null", "none", "unknown"}


@dataclass
class ImportStats:
    total: int = 0
    imported: int = 0
    duplicates: int = 0
    companies: set[str] = field(default_factory=set)
    rejected: list[tuple[int, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"строк: {self.total}; новых связей: {self.imported}; дубликатов: {self.duplicates}; "
            f"отклонено: {len(self.rejected)}; компаний: {len(self.companies)}"
        )


def _confidence_for(affiliation: str, source_type: str) -> str:
    if affiliation == "current_confirmed":
        if source_type in ("licensed_api", "licensed_file"):
            return "high"
        if source_type == "permitted_linkedin":
            return "medium"
    return "review"


def valid_full_name(value: str) -> str | None:
    name = " ".join((value or "").split())
    if name.lower() in _INVALID_NAMES or len(name) < 2:
        return None
    if not any(ch.isalpha() for ch in name):
        return None
    return name


_valid_name = valid_full_name  # обратная совместимость


def save_company_site_people(store: Store, website_key: str, candidates, run_id: str) -> tuple[int, int]:
    """Сохранить людей, найденных на сайте самой компании.

    Пары без валидного имени не сохраняются (нечем заполнить full_name),
    но учитываются в возвращаемом счётчике пропущенных. Якорный текст из
    >5 слов именем человека не считается.
    """
    saved = 0
    skipped = 0
    for cand in candidates.values():
        raw_name = cand.full_name or ""
        name = valid_full_name(raw_name)
        if name is not None and len(name.split()) > 5:
            name = None
        if name is None:
            skipped += 1
            store.record_observation(
                website_key,
                "person_skipped_no_name",
                {"profile_url": cand.profile_url, "found_on": cand.found_on, "anchor": raw_name},
                run_id,
            )
            continue
        store.upsert_person(cand.slug, cand.profile_url, cand.raw, name)
        created = store.link_person(
            website_key=website_key,
            slug=cand.slug,
            raw_url=cand.raw,
            affiliation="listed_without_current_status",
            confidence="medium",
            source_type="company_site",
            source_url=cand.found_on,
            source_ref=f"company_site:{website_key}",
            run_id=run_id,
        )
        if created:
            saved += 1
    return saved, skipped


def import_people(
    store: Store,
    rows: list[dict],
    run_id: str,
    source_label: str,
    source_ref: str,
    source_type: str = "licensed_file",
    max_per_company: int = 100,
) -> ImportStats:
    stats = ImportStats(total=len(rows))
    for idx, row in enumerate(rows, start=1):
        reason = _import_row(store, row, run_id, source_label, source_ref, source_type, max_per_company, stats)
        if reason:
            stats.rejected.append((idx, reason))
    return stats


def _import_row(store, row, run_id, source_label, source_ref, source_type, max_per_company, stats) -> str | None:
    # 1. Компания: по website_url (ключ) или по ссылке на страницу компании.
    key = website_key(row.get("website_url", "")) if row.get("website_url") else None
    company_linkedin = row.get("company_linkedin_url", "")
    if key is None and company_linkedin:
        canonical_company = canonical_linkedin_company(company_linkedin)
        if canonical_company is not None:
            found = store.find_company_by_linkedin_slug(canonical_company.slug)
            if found:
                key = found["website_key"]
    if key is None:
        return "не удалось определить компанию (нет корректного website_url/company_linkedin_url)"
    store.ensure_company(key, row.get("website_url") or key, row.get("company_name") or None)

    # 2. Профиль.
    parsed = canonical_linkedin_profile(row.get("profile_url", ""))
    if parsed is None:
        return "некорректный URL профиля (ожидается linkedin.com/in/<slug>)"
    name = valid_full_name(row.get("full_name", ""))
    if name is None:
        return "некорректное или отсутствующее полное имя"

    # 3. Связь с компанией.
    affiliation = (row.get("affiliation") or "").strip().lower()
    if affiliation and affiliation not in AFFILIATION_KINDS:
        affiliation = "unclear"
    if not affiliation:
        affiliation = "listed_without_current_status"
    confidence = _confidence_for(affiliation, source_type)

    if store.count_company_people(key) >= max_per_company:
        return f"достигнут лимит людей на компанию ({max_per_company})"

    store.upsert_person(parsed.slug, parsed.url, parsed.raw, name)
    created = store.link_person(
        website_key=key,
        slug=parsed.slug,
        raw_url=parsed.raw,
        affiliation=affiliation,
        confidence=confidence,
        source_type=source_type,
        source_url=row.get("source_url") or None,
        source_ref=source_ref,
        run_id=run_id,
    )
    stats.companies.add(key)
    if created:
        stats.imported += 1
    else:
        stats.duplicates += 1
    return None
