"""Нормализация URL и имён: канонизация LinkedIn-ссылок, ключи сайтов, защита CSV."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = {"http", "https"}


@dataclass(frozen=True)
class ParsedUrl:
    scheme: str
    host: str
    port: int | None
    path: str
    query: str
    fragment: str


def split_url(url: str) -> ParsedUrl | None:
    """Разобрать URL с проверками: схема http/https, есть хост, без учетных данных."""
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port  # может бросить ValueError для некорректного порта
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    if "." not in host or not re.fullmatch(r"[a-z0-9._-]+", host):
        return None  # мусорный/неполный хост ("not a url" -> "not" и т.п.)
    if parts.username or parts.password:
        return None
    if scheme == "http" and port == 443:
        return None
    if scheme == "https" and port == 80:
        return None
    return ParsedUrl(scheme, host, port, parts.path or "/", parts.query, parts.fragment)


def is_linkedin_host(host: str) -> bool:
    """Хост принадлежит LinkedIn: linkedin.com или поддомен (www, co, ...)."""
    host = host.lower().rstrip(".")
    return host == "linkedin.com" or host.endswith(".linkedin.com")


_SLUG_RE = re.compile(r"^[A-Za-z0-9\u00c0-\u024f%._-]+$")
_PROFILE_PATH = re.compile(r"^/in/([^/?#]+)/?$")
_COMPANY_PATH = re.compile(r"^/company/([^/?#]+)/?$")


@dataclass(frozen=True)
class LinkedInUrl:
    url: str          # канонический URL (https, исходный хост LinkedIn, без query/fragment)
    slug: str         # идентификатор (slug профиля или страницы компании)
    host: str
    raw: str


def _linkedin_canonical_host(host: str) -> str:
    """linkedin.com без поддомена — это то же, что www.linkedin.com; локализованные хосты сохраняются."""
    return "www.linkedin.com" if host == "linkedin.com" else host


def canonical_linkedin_profile(raw_url: str) -> LinkedInUrl | None:
    """Канонизировать ссылку на персональный профиль /in/<slug>/.

    Принимает локализованные хосты (www.linkedin.com, co.linkedin.com, ...).
    Возвращает None для /company/, /posts/, чужих доменов и мусора.
    """
    p = split_url(raw_url)
    if p is None or not is_linkedin_host(p.host):
        return None
    m = _PROFILE_PATH.match(p.path)
    if m is None:
        return None
    slug = m.group(1)
    if not _SLUG_RE.match(slug):
        return None
    host = _linkedin_canonical_host(p.host)
    url = urlunsplit(("https", host, f"/in/{slug}", "", ""))
    return LinkedInUrl(url, slug.lower(), host, raw_url.strip())


def canonical_linkedin_company(raw_url: str) -> LinkedInUrl | None:
    """Канонизировать ссылку на страницу компании /company/<slug>/."""
    p = split_url(raw_url)
    if p is None or not is_linkedin_host(p.host):
        return None
    m = _COMPANY_PATH.match(p.path)
    if m is None:
        return None
    slug = m.group(1)
    if not _SLUG_RE.match(slug):
        return None
    host = _linkedin_canonical_host(p.host)
    url = urlunsplit(("https", host, f"/company/{slug}", "", ""))
    return LinkedInUrl(url, slug.lower(), host, raw_url.strip())


def normalize_input_website(url: str) -> str | None:
    """Нормализовать входной сайт: добавить https:// для голого домена."""
    candidate = url.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate
    p = split_url(candidate)
    if p is None:
        return None
    if p.port not in (None, 80, 443):
        return None
    return urlunsplit((p.scheme, p.host, p.path or "/", "", ""))


def website_key(url: str) -> str | None:
    """Ключ дедупликации компании: хост без www, без схемы/порта."""
    normalized = normalize_input_website(url) if "://" not in url else url
    p = split_url(normalized) if normalized else None
    if p is None:
        return None
    host = p.host[4:] if p.host.startswith("www.") else p.host
    return host


def registrable_suffix(host: str) -> str:
    """Грубая зона сайта: последние две метки хоста (эвристика для same-site ссылок)."""
    labels = host.lower().rstrip(".").split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


_FORMULA_PREFIXES = "=+@\t\r"
_LEADING_DIGIT = re.compile(r"^-\d")


def csv_safe(value: str) -> str:
    """Нейтрализовать CSV-инъекцию формул в текстовых полях."""
    if not value:
        return value
    first = value[0]
    if first in _FORMULA_PREFIXES or _LEADING_DIGIT.match(value):
        return "'" + value
    return value
