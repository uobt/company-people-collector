"""Стадия A: обход сайта компании и поиск ссылки на её страницу LinkedIn."""

from __future__ import annotations

from dataclasses import dataclass, field

from .fetch import FetchOutcome, PoliteCrawler
from .linkedin_pages import (
    extract_linkedin_company_links,
    extract_linkedin_profile_people,
    same_site_content_links,
)
from .normalize import normalize_input_website, registrable_suffix, split_url, website_key

_BLOCKED_REASONS = {"blocked", "robots_unknown", "robots_disallow"}
_ERROR_REASONS = {"budget_exhausted", "network_error", "error_status", "rate_limited", "invalid_url"}


@dataclass
class PersonCandidate:
    """Человек, найденный на сайте самой компании (team/about): ссылка /in/ + имя ссылки."""

    profile_url: str
    slug: str
    raw: str
    full_name: str | None
    found_on: str


@dataclass
class DiscoveryResult:
    input_website_url: str
    website_key: str | None
    discovery_status: str          # found | ambiguous | not_found | site_blocked | error
    company_linkedin_url: str | None = None
    company_linkedin_source_url: str | None = None
    candidates: dict[str, list[str]] = field(default_factory=dict)  # canonical url -> страницы находки
    person_candidates: dict[str, PersonCandidate] = field(default_factory=dict)  # slug -> кандидат
    pages_visited: list[str] = field(default_factory=list)
    profile_links_seen: int = 0
    stop_reason: str | None = None
    coverage_note: str = ""


def discover_site(crawler: PoliteCrawler, input_url: str, config) -> DiscoveryResult:
    start = normalize_input_website(input_url)
    key = website_key(input_url)
    if start is None or key is None:
        return DiscoveryResult(
            input_website_url=input_url,
            website_key=key,
            discovery_status="error",
            stop_reason="invalid_url",
            coverage_note="входной URL некорректен (схема/хост/порт/учётные данные)",
        )

    suffix = registrable_suffix(split_url(start).host)
    queue: list[str] = [start]
    visited: set[str] = set()
    candidates: dict[str, list[str]] = {}
    people: dict[str, PersonCandidate] = {}
    pages: list[str] = []
    profile_links = 0
    stop_reason: str | None = None

    while queue and len(pages) < config.max_pages_per_site:
        url = queue.pop(0)
        norm = _normalize_page(url)
        if norm in visited:
            continue
        visited.add(norm)

        outcome: FetchOutcome = crawler.fetch(url)
        if outcome.stop_reason is not None:
            stop_reason = outcome.stop_reason
            break
        resp = outcome.response
        assert resp is not None
        pages.append(resp.url)
        if resp.status != 200:
            continue  # страница отсутствует — фиксируем посещение без контента

        for link in extract_linkedin_company_links(resp.text, resp.url):
            candidates.setdefault(link.url, []).append(resp.url)
        for parsed, name in extract_linkedin_profile_people(resp.text, resp.url):
            profile_links += 1
            known = people.get(parsed.slug)
            if known is None:
                people[parsed.slug] = PersonCandidate(
                    profile_url=parsed.url,
                    slug=parsed.slug,
                    raw=parsed.raw,
                    full_name=name,
                    found_on=resp.url,
                )
            elif known.full_name is None and name:
                known.full_name = name  # имя нашлось на более поздней странице

        for child in same_site_content_links(resp.text, resp.url, suffix):
            child_norm = _normalize_page(child)
            if child_norm not in visited and child not in queue:
                queue.append(child)

    if stop_reason in _BLOCKED_REASONS:
        status = "site_blocked"
    elif stop_reason is not None:
        status = "error"
    elif len(candidates) == 1:
        status = "found"
    elif not candidates:
        status = "not_found"
    else:
        status = "ambiguous"

    company_url, source_url = None, None
    if status == "found":
        company_url = next(iter(candidates))
        source_url = candidates[company_url][0]

    note = _coverage_note(status, pages, candidates, stop_reason, profile_links, len(people))
    return DiscoveryResult(
        input_website_url=input_url,
        website_key=key,
        discovery_status=status,
        company_linkedin_url=company_url,
        company_linkedin_source_url=source_url,
        candidates=candidates,
        person_candidates=people,
        pages_visited=pages,
        profile_links_seen=profile_links,
        stop_reason=stop_reason,
        coverage_note=note,
    )


def _normalize_page(url: str) -> str:
    p = split_url(url)
    if p is None:
        return url
    return f"{p.scheme}://{p.host}{p.path.rstrip('/')}".lower()


def _coverage_note(
    status: str,
    pages: list[str],
    candidates: dict,
    stop: str | None,
    profiles: int,
    people_found: int,
) -> str:
    parts = [f"просмотрено страниц: {len(pages)}"]
    if stop:
        parts.append(f"причина остановки: {stop}")
    parts.append(f"кандидатов страницы компании: {len(candidates)}")
    if profiles:
        parts.append(f"ссылок /in/ на сайте компании: {profiles} (уникальных людей: {people_found})")
    if status == "ambiguous":
        parts.append("несколько разных страниц LinkedIn/company — сопоставление требует решения оператора")
    if status == "not_found":
        parts.append("явная ссылка linkedin.com/company/... не найдена в пределах лимита страниц")
    return "; ".join(parts)
