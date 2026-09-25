"""Транспорт и вежливый обход: robots.txt, SSRF-защита, рейт-лимит, бюджет, ретраи."""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .normalize import split_url


class FetchError(Exception):
    """Сетевая ошибка транспорта (таймаут, соединение, DNS)."""


@dataclass
class Response:
    url: str
    status: int
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str] | None = None) -> Response: ...


class HttpxTransport:
    """Реальный HTTP-транспорт на httpx, без автоследования за редиректами.

    trust_env=False: переменные прокси-окружения не читаются (в сломанном
    окружении они ломают создание клиента); прокси задаётся явно конфигом.
    """

    def __init__(self, user_agent: str, timeout_seconds: float, proxy: str | None = None):
        import httpx

        kwargs: dict = dict(
            follow_redirects=False,
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent, "Accept-Language": "en"},
            trust_env=False,
        )
        if proxy:
            kwargs["proxy"] = proxy
        self._client = httpx.Client(**kwargs)

    def get(self, url: str, headers: dict[str, str] | None = None) -> Response:
        try:
            resp = self._client.get(url, headers=headers)
        except Exception as exc:  # httpx.HTTPError, таймауты, соединения
            raise FetchError(str(exc)) from exc
        merged = {k.lower(): v for k, v in resp.headers.items()}
        if headers:
            merged.setdefault("x-sent-ua", headers.get("User-Agent", ""))
        return Response(url=url, status=resp.status_code, text=resp.text, headers=merged)


def host_is_public(host: str) -> bool:
    """True, если хост разрешается только в глобальные IP (SSRF-защита)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


@dataclass
class RobotsPolicy:
    status: str  # "ok" | "absent" | "unknown"
    parser: RobotFileParser | None = None
    crawl_delay: float | None = None

    def allowed(self, url: str, user_agent_token: str) -> bool:
        if self.status == "absent":
            return True
        if self.status != "ok" or self.parser is None:
            return False  # unknown => консервативно запрещаем
        return bool(self.parser.can_fetch(user_agent_token, url))


@dataclass
class FetchOutcome:
    response: Response | None = None
    stop_reason: str | None = None  # invalid_url | robots_disallow | robots_unknown | blocked | rate_limited | budget_exhausted | network_error | error_status


class _FetchStopped(Exception):
    """Внутренняя остановка обхода с причиной stop_reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class PoliteCrawler:
    """Обход с проверкой robots.txt, лимитом частоты, бюджетом запросов и защитой от SSRF."""

    ua_token = "company-people-collector"

    def __init__(
        self,
        transport: Transport,
        config,
        resolver: Callable[[str], bool] = host_is_public,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.transport = transport
        self.config = config
        self.resolver = resolver
        self._sleep = sleep
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotsPolicy] = {}
        self._now: Callable[[], float] = time.monotonic
        self.requests_used = 0

    # ---------- публичное ----------

    def robots_for(self, site_url: str) -> RobotsPolicy:
        p = split_url(site_url)
        if p is None:
            return RobotsPolicy("unknown")
        origin = f"{p.scheme}://{p.host}"
        if origin in self._robots:
            return self._robots[origin]
        policy = self._load_robots(origin)
        self._robots[origin] = policy
        return policy

    def fetch(
        self,
        url: str,
        respect_robots: bool = True,
        headers: dict[str, str] | None = None,
    ) -> FetchOutcome:
        p = split_url(url)
        if p is None or p.port not in (None, 80, 443):
            return FetchOutcome(stop_reason="invalid_url")
        if not self.resolver(p.host):
            return FetchOutcome(stop_reason="invalid_url")
        if respect_robots:
            policy = self.robots_for(url)
            if policy.status == "unknown":
                return FetchOutcome(stop_reason="robots_unknown")
            if not policy.allowed(url, self.ua_token):
                return FetchOutcome(stop_reason="robots_disallow")

        if self.requests_used >= self.config.max_requests_per_run:
            return FetchOutcome(stop_reason="budget_exhausted")

        self._throttle(p.host)
        self.requests_used += 1

        attempts = max(1, int(getattr(self.config, "retries", 0)) + 1)
        last: FetchOutcome | None = None
        for attempt in range(attempts):
            try:
                resp = self._get_with_redirects(url, respect_robots=respect_robots, headers=headers)
            except _FetchStopped as stopped:
                last = FetchOutcome(stop_reason=stopped.reason)
            else:
                last = self._handle_final(resp, url)
            if last.stop_reason not in ("error_status", "network_error"):
                return last
            if attempt < attempts - 1:
                self._sleep(2.0)
        assert last is not None
        return last

    # ---------- внутреннее ----------

    def _get_with_redirects(
        self, url: str, respect_robots: bool = False, headers: dict[str, str] | None = None
    ) -> Response:
        """GET с ручным следованием редиректами; каждый хост проверяется (SSRF,
        robots для чужих хостов при respect_robots=True)."""
        current = url
        for _ in range(5):
            np_check = split_url(current)
            if np_check is None or np_check.port not in (None, 80, 443):
                raise _FetchStopped("invalid_url")
            if not self.resolver(np_check.host):
                raise _FetchStopped("invalid_url")
            if respect_robots and current != url:
                hop_policy = self.robots_for(current)
                if hop_policy.status == "unknown":
                    raise _FetchStopped("robots_unknown")
                if not hop_policy.allowed(current, self.ua_token):
                    raise _FetchStopped("robots_disallow")
            try:
                resp = self.transport.get(current, headers=headers)
            except FetchError as exc:
                raise _FetchStopped("network_error") from exc
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise _FetchStopped("error_status")
                current = _join(current, location)
                continue
            return resp
        raise _FetchStopped("error_status")

    def _handle_final(self, resp: Response, original_url: str) -> FetchOutcome:
        if resp.status == 429:
            retry_after = _parse_seconds(resp.headers.get("retry-after"))
            if retry_after is not None:
                self._sleep(min(retry_after, 30.0))
                try:
                    resp = self._get_with_redirects(resp.url)
                except _FetchStopped:
                    return FetchOutcome(stop_reason="network_error")
                if resp.status == 429:
                    return FetchOutcome(stop_reason="rate_limited")
            else:
                return FetchOutcome(stop_reason="rate_limited")
        if resp.status in (401, 403):
            return FetchOutcome(stop_reason="blocked")
        if resp.status >= 500 or resp.status < 200:
            return FetchOutcome(stop_reason="error_status")
        return FetchOutcome(response=resp)

    def _load_robots(self, origin: str) -> RobotsPolicy:
        robots_url = origin + "/robots.txt"
        try:
            resp = self._get_with_redirects(robots_url)
        except _FetchStopped:
            return RobotsPolicy("unknown")
        if resp.status in (404, 410):
            return RobotsPolicy("absent")
        if not (200 <= resp.status < 300):
            return RobotsPolicy("unknown")
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        delay = parser.crawl_delay(self.ua_token)
        return RobotsPolicy("ok", parser, float(delay) if delay else None)

    def _throttle(self, host: str):
        interval = self.config.min_interval_seconds
        policy = self._robots.get(self._origin_of(host))
        if policy and policy.crawl_delay:
            interval = max(interval, policy.crawl_delay)
        if interval <= 0:
            return
        now = self._now()
        wait = self._last_hit.get(host, 0.0) + interval - now
        if wait > 0:
            self._sleep(wait)
        self._last_hit[host] = self._now()

    def _origin_of(self, host: str) -> str:
        return f"https://{host}"


def _join(base: str, location: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, location)


def _parse_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
