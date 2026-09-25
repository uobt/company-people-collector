"""Канал linkedin_public: публичная (guest) страница компании LinkedIn.

Решение владельца от 2026-09-25 (docs/access_assessment.md, прецедент JobSpy
в job-search-collector): обход robots-запрета LinkedIn принят осознанно,
с сохранением остальных границ — без логина, без cookies, без обхода
CAPTCHA/блокировок, с паузами и бюджетом.

Публичная страница отдаёт: заголовок, численность и секцию «Employees at X»,
в которой видима часть карточек (ссылка /in/ + имя); остальные карточки
приходят как «LinkedIn Member» без ссылок. Полный список сотрудников
доступен только в логине — канал честно помечается как partial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .linkedin_pages import _iter_hrefs  # noqa: F401  (переиспользуем общий обход <a>)
from .normalize import canonical_linkedin_profile, is_linkedin_host, split_url

_ALT_NAME_RE = re.compile(r"^Click here to view (.+?)[’']s profile$", re.IGNORECASE)
_COUNT_RE = re.compile(r"([0-9][0-9,.\-\u2013\s]{0,14}?)\s*(?:employees|associates)\b", re.IGNORECASE)


@dataclass
class PublicPerson:
    profile_url: str
    slug: str
    raw: str
    full_name: str
    found_via: str  # employees-at | alt


@dataclass
class PublicCompanyPeople:
    employees: list[PublicPerson] = field(default_factory=list)
    employee_count_raw: str | None = None
    hidden_members: int = 0  # карточки «LinkedIn Member» без ссылок
    note: str = ""


def parse_public_company_people(html: str) -> PublicCompanyPeople:
    """Разбор секции «Employees at» публичной страницы компании."""
    result = PublicCompanyPeople()
    count = _COUNT_RE.search(html)
    if count:
        result.employee_count_raw = " ".join(count.group(1).split())
    result.hidden_members = html.count(">LinkedIn Member<") + html.count("> LinkedIn Member <")

    section = _employees_section(html)
    scope = section if section is not None else html
    seen: dict[str, PublicPerson] = {}
    for person in _people_from_scope(scope):
        seen.setdefault(person.slug, person)
    result.employees = list(seen.values())
    return result


def _employees_section(html: str) -> str | None:
    marker = 'data-test-id="employees-at"'
    idx = html.find(marker)
    if idx == -1:
        return None
    # секция заканчивается следующим </section> после маркера
    end = html.find("</section>", idx)
    return html[idx : end if end != -1 else len(html)]


def _people_from_scope(scope: str) -> list[PublicPerson]:
    from selectolax.parser import HTMLParser

    people: list[PublicPerson] = []
    tree = HTMLParser(scope)
    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        parsed = canonical_linkedin_profile(href)
        if parsed is None:
            continue
        name = ""
        for h3 in node.css("h3"):
            name = " ".join(h3.text(separator=" ", strip=True).split())
            if name:
                break
        if not name:
            for img in node.css("img[alt]"):
                m = _ALT_NAME_RE.match((img.attributes.get("alt") or "").strip())
                if m:
                    name = m.group(1).strip()
                    break
        if not name or name.lower() == "linkedin member":
            continue
        people.append(
            PublicPerson(
                profile_url=parsed.url,
                slug=parsed.slug,
                raw=parsed.raw,
                full_name=name,
                found_via="employees-at",
            )
        )
    return people


def is_linkedin_authwall(response) -> bool:
    """Страница login/authwall вместо контента (302 на /uas/login или authwall)."""
    url = getattr(response, "url", "") or ""
    p = split_url(url)
    if p is not None and "authwall" in p.host:
        return True
    if p is not None and p.path.startswith("/uas/login"):
        return True
    text = (getattr(response, "text", "") or "")[:4000].lower()
    return "authwall" in text or "sign in to continue" in text


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def collect_company_people(
    store,
    crawler,
    website_key: str,
    company_linkedin_url: str,
    run_id: str,
    max_people: int,
) -> dict:
    """Собрать людей с публичной страницы компании LinkedIn (канал linkedin_public).

    robots-проверка отключена осознанно (решение владельца, docs/access_assessment.md);
    паузы/бюджет/SSRF-защита сохраняются. Возвращает сводку для отчёта.
    """
    from .people_import import valid_full_name

    summary = {
        "website_key": website_key,
        "company_url": company_linkedin_url,
        "status": "error",
        "saved": 0,
        "skipped": 0,
        "hidden": 0,
        "employee_count_raw": None,
        "stop_reason": None,
    }
    outcome = crawler.fetch(company_linkedin_url, respect_robots=False, headers=BROWSER_HEADERS)
    if outcome.stop_reason is not None:
        summary["stop_reason"] = outcome.stop_reason
        summary["status"] = "blocked" if outcome.stop_reason in ("blocked", "rate_limited") else "error"
        store.update_people_status(website_key, summary["status"], None, f"linkedin_public: {outcome.stop_reason}")
        return summary
    resp = outcome.response
    if is_linkedin_authwall(resp):
        summary["stop_reason"] = "authwall"
        summary["status"] = "blocked"
        store.update_people_status(website_key, "blocked", None, "linkedin_public: authwall")
        return summary

    parsed = parse_public_company_people(resp.text)
    summary["employee_count_raw"] = parsed.employee_count_raw
    summary["hidden"] = parsed.hidden_members

    for person in parsed.employees:
        if store.count_company_people(website_key) >= max_people:
            summary["stop_reason"] = "max_people"
            break
        name = valid_full_name(person.full_name)
        if name is None:
            summary["skipped"] += 1
            continue
        store.upsert_person(person.slug, person.profile_url, person.raw, name)
        created = store.link_person(
            website_key=website_key,
            slug=person.slug,
            raw_url=person.raw,
            affiliation="current_confirmed",
            confidence="medium",
            source_type="permitted_linkedin",
            source_url=resp.url,
            source_ref=f"linkedin_public:{website_key}",
            run_id=run_id,
        )
        if created:
            summary["saved"] += 1

    total = store.count_company_people(website_key)
    coverage = f"linkedin_public: собрано {summary['saved']} видимых карточек"
    if parsed.employee_count_raw:
        coverage += f" (численность на странице: ~{parsed.employee_count_raw.strip()})"
    if parsed.hidden_members:
        coverage += f"; скрыто за логином: {parsed.hidden_members}"
    summary["status"] = "partial"
    store.update_people_status(website_key, "partial", "false", coverage)
    return summary
