"""Люди с сайта самой компании: /in/-ссылки + имена из текста ссылок."""

from company_people.discover import discover_site
from company_people.fetch import PoliteCrawler
from company_people.inputs import read_companies
from company_people.people_import import save_company_site_people
from company_people.storage import Store

from conftest import FakeTransport

ROBOTS = "User-agent: *\nAllow: /\n"

TEAM_PAGE = """
<html><body><h1>Our team</h1>
<ul>
  <li><a href="https://www.linkedin.com/in/john-doe/">John Doe</a> — CEO</li>
  <li><a href="https://www.linkedin.com/in/jane-smith"><span>Jane Smith</span></a> — CTO</li>
  <li><a href="https://www.linkedin.com/in/icon-only/" aria-label="Sam Lee"></a> — advisor</li>
  <li><a href="https://www.linkedin.com/in/no-text/">icon</a></li>
</ul>
<footer><a href="https://www.linkedin.com/company/teamco/">company</a></footer>
</body></html>
"""


def _crawler(mapping, config):
    return PoliteCrawler(FakeTransport(mapping), config, resolver=lambda h: True)


def test_discover_collects_person_candidates(config):
    crawler = _crawler(
        {
            "https://teamco.com/robots.txt": ROBOTS,
            "https://teamco.com/": TEAM_PAGE,
        },
        config,
    )
    result = discover_site(crawler, "https://teamco.com/", config)
    assert result.discovery_status == "found"
    slugs = set(result.person_candidates)
    assert slugs == {"john-doe", "jane-smith", "icon-only", "no-text"}
    by_slug = result.person_candidates
    assert by_slug["john-doe"].full_name == "John Doe"
    assert by_slug["jane-smith"].full_name == "Jane Smith"  # имя из вложенного span
    assert by_slug["icon-only"].full_name == "Sam Lee"      # из aria-label
    assert by_slug["no-text"].full_name is None             # имя нет


def test_save_company_site_people(tmp_path, config):
    store = Store(tmp_path / "db.sqlite")
    run_id = store.start_run("discover", {})
    crawler = _crawler(
        {"https://teamco.com/robots.txt": ROBOTS, "https://teamco.com/": TEAM_PAGE},
        config,
    )
    result = discover_site(crawler, "https://teamco.com/", config)
    saved, skipped = save_company_site_people(store, "teamco.com", result.person_candidates, run_id)
    assert saved == 3
    assert skipped == 1  # no-text без имени
    people = store.company_people_rows("teamco.com")
    by_url = {p["canonical_url"]: p for p in people}
    assert by_url["https://www.linkedin.com/in/jane-smith"]["full_name"] == "Jane Smith"
    assert by_url["https://www.linkedin.com/in/icon-only"]["full_name"] == "Sam Lee"
    assert all(p["confidence"] == "medium" for p in people)
    # повторное сохранение тех же кандидатов — идемпотентно
    saved2, skipped2 = save_company_site_people(store, "teamco.com", result.person_candidates, run_id)
    assert saved2 == 0 and skipped2 == 1
    assert len(store.company_people_rows("teamco.com")) == 3
    # пропущенный без имени зафиксирован в наблюдениях
    obs = store._db.execute("SELECT COUNT(*) AS c FROM observations WHERE kind='person_skipped_no_name'").fetchone()
    assert obs["c"] == 2  # один и тот же пропуск в двух вызовах


def test_read_companies_custom_column(tmp_path):
    base = tmp_path / "base.csv"
    base.write_text(
        "компания,сайт\nBland,https://bland.ai\nAlgo,algosolutions.com\nNoSite,\n",
        encoding="utf-8",
    )
    rows, errors = read_companies(base, website_column="сайт")
    assert len(rows) == 2
    assert rows[0]["website_url"] == "https://bland.ai"
    assert rows[1]["website_url"] == "algosolutions.com"
    assert errors and "сайт" in errors[0][1]
