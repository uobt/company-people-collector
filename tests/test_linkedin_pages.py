from company_people.linkedin_pages import (
    count_profile_links,
    extract_linkedin_company_links,
    same_site_content_links,
)

HOME = """
<html><body>
<nav><a href="/about-us">About Us</a> <a href="/contact">Contact</a></nav>
<footer>
  <a href="https://www.linkedin.com/company/dedicated-developers/">LinkedIn</a>
  <a href="https://www.linkedin.com/in/someone-else/">Founder profile</a>
  <a href="/privacy">Privacy</a>
</footer>
<script>var cfg = {"social":"https:\\/\\/www.linkedin.com\\/company\\/dedicated-developers\\/"};</script>
</body></html>
"""

JSON_EMBEDDED = """
<html><body>
<div data-block='{"link":"https://www.linkedin.com/company/acme-soft/"}'>block</div>
</body></html>
"""


def test_company_links_from_href_and_raw_scan():
    links = extract_linkedin_company_links(HOME, "https://example.com/")
    urls = [link.url for link in links]
    # одна и та же ссылка из <a> и из JSON-скрипта не даёт дубликат
    assert urls == ["https://www.linkedin.com/company/dedicated-developers"]
    links2 = extract_linkedin_company_links(JSON_EMBEDDED, "https://example.com/")
    assert [l.url for l in links2] == ["https://www.linkedin.com/company/acme-soft"]


def test_profile_links_counted_not_treated_as_company():
    assert count_profile_links(HOME, "https://example.com/") == 1
    assert extract_linkedin_company_links(
        "<a href='https://www.linkedin.com/in/john-doe/'>john</a>", "https://example.com/"
    ) == []


def test_escaped_and_relative_links():
    html = "<a href='https://www.linkedin.com/company/a%20b'>x</a>"
    links = extract_linkedin_company_links(html, "https://example.com/")
    assert links and links[0].url.endswith("/company/a%20b")


def test_same_site_priority_links():
    links = same_site_content_links(HOME, "https://example.com/", "example.com")
    paths = sorted(link.split("example.com", 1)[1] for link in links)
    assert paths == ["/about-us", "/contact"]
    # внешние и не-приоритетные страницы отфильтрованы
    external = same_site_content_links(
        "<a href='https://other.com/about'>x</a><a href='/careers'>y</a>",
        "https://example.com/",
        "example.com",
    )
    assert external == []
