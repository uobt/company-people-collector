import pytest

from company_people.fetch import FetchError, PoliteCrawler, Response, host_is_public

from conftest import FakeTransport


def _crawler(mapping, config, resolver=lambda h: True) -> PoliteCrawler:
    return PoliteCrawler(FakeTransport(mapping), config, resolver=resolver)


def test_robots_absent_allows_crawl(config):
    crawler = _crawler(
        {
            "https://example.com/robots.txt": 404,
            "https://example.com/": "<html>ok</html>",
        },
        config,
    )
    outcome = crawler.fetch("https://example.com/")
    assert outcome.stop_reason is None
    assert outcome.response.status == 200


def test_robots_403_is_unknown_and_blocks(config):
    crawler = _crawler({"https://example.com/robots.txt": 403}, config)
    outcome = crawler.fetch("https://example.com/")
    assert outcome.stop_reason == "robots_unknown"
    assert outcome.response is None


def test_robots_disallow_blocks_page(config):
    crawler = _crawler(
        {
            "https://example.com/robots.txt": "User-agent: *\nDisallow: /private/\n",
            "https://example.com/private/page": "<html>x</html>",
        },
        config,
    )
    assert crawler.fetch("https://example.com/private/page").stop_reason == "robots_disallow"
    assert crawler.fetch("https://example.com/public").response is not None


def test_403_and_429_handling(config):
    crawler = _crawler(
        {
            "https://example.com/robots.txt": 404,
            "https://example.com/blocked": 403,
            "https://example.com/rate": Response(
                url="https://example.com/rate", status=429, headers={}
            ),
        },
        config,
    )
    assert crawler.fetch("https://example.com/blocked").stop_reason == "blocked"
    outcome = crawler.fetch("https://example.com/rate")
    assert outcome.stop_reason == "rate_limited"


def test_budget_exhaustion(config):
    config.max_requests_per_run = 1
    crawler = _crawler({"https://example.com/robots.txt": 404, "https://example.com/": "x"}, config)
    assert crawler.fetch("https://example.com/").response is not None
    assert crawler.fetch("https://example.com/").stop_reason == "budget_exhausted"


def test_redirect_to_private_ip_blocked(config):
    # резолвер как в реальном режиме: example.com публичен, приватный IP — нет
    crawler = _crawler(
        {
            "https://example.com/robots.txt": 404,
            "https://example.com/hop": Response(
                url="https://example.com/hop",
                status=302,
                headers={"location": "http://192.168.0.1/secret"},
            ),
        },
        config,
        resolver=lambda h: h == "example.com",
    )
    outcome = crawler.fetch("https://example.com/hop")
    assert outcome.stop_reason == "invalid_url"  # редирект в приватную сеть отклонён


def test_redirect_chain_followed(config):
    crawler = _crawler(
        {
            "https://example.com/robots.txt": 404,
            "https://example.com/old": Response(
                url="https://example.com/old", status=301, headers={"location": "/new"}
            ),
            "https://example.com/new": "<html>final</html>",
        },
        config,
    )
    outcome = crawler.fetch("https://example.com/old")
    assert outcome.response is not None and outcome.response.url.endswith("/new")


def test_transient_error_retried(config):
    calls = {"n": 0}

    class Flaky:
        def get(self, url, headers=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return Response(url=url, status=999)
            return Response(url=url, status=200, text="<html>ok</html>")

    crawler = PoliteCrawler(Flaky(), config, resolver=lambda h: True, sleep=lambda s: None)
    outcome = crawler.fetch("https://www.linkedin.com/company/x", respect_robots=False)
    assert outcome.stop_reason is None
    assert outcome.response.status == 200
    assert calls["n"] == 2


def test_host_is_public_rejects_private_and_unresolvable(monkeypatch):
    def fake_addrinfo(host, *args, **kwargs):
        import socket

        ip = "10.0.0.5" if host == "internal.local" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr("socket.getaddrinfo", fake_addrinfo)
    assert host_is_public("internal.local") is False
    assert host_is_public("example.org") is True
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket_gaierror())
    )
    assert host_is_public("nope.invalid") is False


def socket_gaierror():
    import socket

    return socket.gaierror("dns fail")
