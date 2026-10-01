from company_people.discover import discover_site
from company_people.fetch import PoliteCrawler

from conftest import FakeTransport

ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"

HOME_FOUND = """
<html><body>
<nav><a href="/about-us">About</a></nav>
<footer><a href="https://www.linkedin.com/company/dedicated-developers/">in</a></footer>
</body></html>
"""

ABOUT_SECOND_BRAND = """
<html><body>
<a href="https://www.linkedin.com/company/dd-latin-america/">Latin America</a>
</body></html>
"""

HOME_NO_LINKEDIN = """
<html><body><nav><a href="/about-us">About</a></nav><footer>no socials</footer></body></html>
"""


def _crawler(mapping, config):
    return PoliteCrawler(FakeTransport(mapping), config, resolver=lambda h: True)


def test_found_single_company_link(config):
    crawler = _crawler(
        {
            "https://dedicateddevelopers.com/robots.txt": ROBOTS_ALLOW,
            "https://dedicateddevelopers.com/": HOME_FOUND,
            "https://dedicateddevelopers.com/about-us": "<html>team page</html>",
        },
        config,
    )
    result = discover_site(crawler, "https://dedicateddevelopers.com/", config)
    assert result.discovery_status == "found"
    assert result.company_linkedin_url == "https://www.linkedin.com/company/dedicated-developers"
    assert result.company_linkedin_source_url == "https://dedicateddevelopers.com/"
    assert "/about-us" in " ".join(result.pages_visited) or len(result.pages_visited) >= 1


def test_ambiguous_two_company_pages(config):
    crawler = _crawler(
        {
            "https://dedicateddevelopers.com/robots.txt": ROBOTS_ALLOW,
            "https://dedicateddevelopers.com/": HOME_FOUND,
            "https://dedicateddevelopers.com/about-us": ABOUT_SECOND_BRAND,
        },
        config,
    )
    result = discover_site(crawler, "https://dedicateddevelopers.com/", config)
    assert result.discovery_status == "ambiguous"
    assert set(result.candidates) == {
        "https://www.linkedin.com/company/dedicated-developers",
        "https://www.linkedin.com/company/dd-latin-america",
    }
    assert result.company_linkedin_url is None  # автоматический выбор не делается


def test_not_found_without_company_link(config):
    crawler = _crawler(
        {
            "https://dedicateddevelopers.com/robots.txt": ROBOTS_ALLOW,
            "https://dedicateddevelopers.com/": HOME_NO_LINKEDIN,
            "https://dedicateddevelopers.com/about-us": "<html></html>",
        },
        config,
    )
    result = discover_site(crawler, "https://dedicateddevelopers.com/", config)
    assert result.discovery_status == "not_found"
    assert result.company_linkedin_url is None


def test_site_blocked_on_robots_unknown(config):
    crawler = _crawler({"https://dedicateddevelopers.com/robots.txt": 403}, config)
    result = discover_site(crawler, "https://dedicateddevelopers.com/", config)
    assert result.discovery_status == "site_blocked"
    assert result.stop_reason == "robots_unknown"


def test_invalid_input_url(config):
    crawler = _crawler({}, config)
    result = discover_site(crawler, "https://example.com:8080/", config)
    assert result.discovery_status == "error"
    assert result.stop_reason == "invalid_url"


def test_profile_links_do_not_become_company(config):
    html = "<a href='https://www.linkedin.com/in/avery-stone-example-co/'>founder</a>"
    crawler = _crawler(
        {
            "https://dedicateddevelopers.com/robots.txt": ROBOTS_ALLOW,
            "https://dedicateddevelopers.com/": html,
        },
        config,
    )
    result = discover_site(crawler, "https://dedicateddevelopers.com/", config)
    assert result.discovery_status == "not_found"
    assert result.profile_links_seen == 1
