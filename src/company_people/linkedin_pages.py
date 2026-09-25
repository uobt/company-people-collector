"""Чистый разбор сохранённого HTML: извлечение ссылок на LinkedIn без сети."""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from .normalize import canonical_linkedin_company, canonical_linkedin_profile, LinkedInUrl

# Резервный скан сырого разметки: URL часто зашиты в JSON/атрибуты виджетов.
_RAW_LINKEDIN_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9\u00c0-\u024f%._-]+/?",
    re.IGNORECASE,
)

_ASSET_RE = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js|pdf|zip|ico|woff2?)$", re.IGNORECASE)

# Якорные тексты, которые именем человека не являются (иконки/служебные надписи).
_ANCHOR_STOPWORDS = {
    "icon", "icons", "linkedin", "in", "profile", "view", "views", "connect",
    "follow", "here", "link", "bio", "team", "about", "contact", "website",
    "learn", "more", "join", "apply", "share", "click", "logo", "image",
    "member", "members", "employee", "employees",
}


def extract_linkedin_company_links(page_html: str, page_url: str) -> list[LinkedInUrl]:
    """Все ссылки на /company/<slug>/ со страницы: из <a href> плюс сырой скан."""
    found: dict[str, LinkedInUrl] = {}
    for href in _iter_hrefs(page_html):
        resolved = urljoin(page_url, href)
        parsed = canonical_linkedin_company(resolved)
        if parsed is not None and parsed.url not in found:
            found[parsed.url] = parsed
    for match in _RAW_LINKEDIN_RE.finditer(page_html):
        resolved = urljoin(page_url, html_lib.unescape(match.group(0)))
        parsed = canonical_linkedin_company(resolved)
        if parsed is not None and parsed.url not in found:
            found[parsed.url] = parsed
    return list(found.values())


def count_profile_links(page_html: str, page_url: str) -> int:
    """Сколько на странице ссылок /in/... — они НЕ являются страницами компании."""
    return len(extract_linkedin_profile_people(page_html, page_url))


def extract_linkedin_profile_people(
    page_html: str, page_url: str
) -> list[tuple[LinkedInUrl, str | None]]:
    """Ссылки /in/... с якорным текстом как кандидатом полного имени (без имени -> None)."""
    from .normalize import canonical_linkedin_profile

    found: dict[str, tuple[LinkedInUrl, str | None]] = {}
    tree = HTMLParser(page_html)
    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        parsed = canonical_linkedin_profile(urljoin(page_url, html_lib.unescape(href)))
        if parsed is None:
            continue
        name = " ".join(node.text(separator=" ", strip=True).split()) if node.text() else ""
        if not name or name.lower() in _ANCHOR_STOPWORDS:
            label = node.attributes.get("aria-label") or node.attributes.get("title") or ""
            name = " ".join(label.split())
            if name.lower() in _ANCHOR_STOPWORDS:
                name = ""
        existing = found.get(parsed.slug)
        if existing is None or (existing[1] is None and name):
            found[parsed.slug] = (parsed, name or None)
    return list(found.values())


def same_site_content_links(page_html: str, page_url: str, site_suffix: str) -> list[str]:
    """Ссылки того же сайта на приоритетные страницы (about/team/contact/people/company)."""
    from .normalize import split_url

    priority = re.compile(r"/(about|team|contact|people|company)(?:[-_/]|$)", re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for href in _iter_hrefs(page_html):
        resolved = urljoin(page_url, href)
        p = split_url(resolved)
        if p is None:
            continue
        if not p.host.endswith(site_suffix) and p.host != site_suffix:
            continue
        if p.scheme not in ("http", "https"):
            continue
        if _ASSET_RE.search(p.path):
            continue
        if not priority.search(p.path):
            continue
        key = (p.host, p.path.rstrip("/").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(urljoin(page_url, resolved))
    return out


def _iter_hrefs(page_html: str):
    tree = HTMLParser(page_html)
    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if href and not href.lower().startswith(("javascript:", "mailto:", "tel:")):
            yield html_lib.unescape(href)
