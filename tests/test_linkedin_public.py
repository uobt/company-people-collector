"""Канал linkedin_public: публичная guest-страница компании LinkedIn."""

from company_people.fetch import PoliteCrawler, Response
from company_people.linkedin_public import (
    collect_company_people,
    is_linkedin_authwall,
    parse_public_company_people,
)
from company_people.storage import Store

from conftest import FakeTransport

# Структура воспроизводит живую страницу linkedin.com/company/bland-ai (2026-09-25):
# одна видимая карточка с h3-именем, размытые "LinkedIn Member" без ссылок,
# счётчик "120 employees", упоминание человека в тексте поста.
PUBLIC_PAGE = """
<html><body>
<section data-test-id="org-page" class="...">
  <h1>Bland</h1>
  <p>120 employees</p><span>51-200 employees</span>
</section>
<section class="core-section-container" data-test-id="employees-at">
  <h2 class="core-section-container__title"> Employees at Bland </h2>
  <div class="blurred-overlay">
    <ul class="babybear:pb-4">
      <li>
        <a href="https://www.linkedin.com/in/leo-de-luna-313226?trk=org-employees" class="base-card">
          <img alt="Click here to view Leo de Luna\u2019s profile">
          <div><h3 class="base-main-card__title"> Leo de Luna </h3></div>
        </a>
      </li>
    </ul>
    <div class="blurred-content blur" aria-hidden="true">
      <ul><li><div><img alt="Click here to view LinkedIn Member\u2019s profile">
        <h3> LinkedIn Member </h3></div></li></ul>
      <ul><li><div><img alt="Click here to view LinkedIn Member\u2019s profile">
        <h3> LinkedIn Member </h3></div></li></ul>
    </div>
  </div>
</section>
<p>Bland is FedRAMP certified. CIO <a href="https://www.linkedin.com/in/juan-e-riojas-3a544018?trk=organization_guest_main-feed-card-text">Juan E. Riojas</a> shares why.</p>
</body></html>
"""


def test_parse_public_company_people():
    parsed = parse_public_company_people(PUBLIC_PAGE)
    assert parsed.employee_count_raw == "120"
    assert parsed.hidden_members == 2
    # только видимые карточки секции employees-at; упоминание из поста не попало
    assert [p.full_name for p in parsed.employees] == ["Leo de Luna"]
    person = parsed.employees[0]
    assert person.profile_url == "https://www.linkedin.com/in/leo-de-luna-313226"
    assert "trk=org-employees" in person.raw


def test_parse_name_from_alt_when_no_h3():
    html = """
    <section data-test-id="employees-at"><ul><li>
      <a href="https://www.linkedin.com/in/jane-doe-123?trk=org-employees">
        <img alt="Click here to view Jane Doe's profile">
      </a>
    </li></ul></section>
    """
    parsed = parse_public_company_people(html)
    assert [p.full_name for p in parsed.employees] == ["Jane Doe"]


def test_authwall_detection():
    assert is_linkedin_authwall(Response(url="https://www.linkedin.com/uas/login?session_redirect=x", status=200))
    assert is_linkedin_authwall(Response(url="https://authwall.linkedin.com/some", status=200))
    assert is_linkedin_authwall(Response(url="https://www.linkedin.com/company/x/", status=200, text="Sign in to continue"))
    assert not is_linkedin_authwall(Response(url="https://www.linkedin.com/company/x/", status=200, text=PUBLIC_PAGE))


def test_collect_company_people_end_to_end(config, tmp_path):
    store = Store(tmp_path / "db.sqlite")
    run_id = store.start_run("collect", {})
    store.upsert_company_discovery(
        "bland.ai", "https://bland.ai/", "Bland",
        "https://www.linkedin.com/company/bland-ai", "https://bland.ai/",
        "found", "пилот", None, run_id,
    )
    crawler = PoliteCrawler(
        FakeTransport({"https://www.linkedin.com/company/bland-ai": PUBLIC_PAGE}),
        config,
        resolver=lambda h: True,
    )
    summary = collect_company_people(
        store, crawler, "bland.ai",
        "https://www.linkedin.com/company/bland-ai", run_id,
        max_people=100,
    )
    assert summary["status"] == "partial"
    assert summary["saved"] == 1
    assert summary["employee_count_raw"] == "120"
    assert summary["hidden"] == 2
    people = store.company_people_rows("bland.ai")
    assert len(people) == 1
    assert people[0]["full_name"] == "Leo de Luna"
    assert people[0]["confidence"] == "medium"
    # robots.txt LinkedIn не запрашивался: канал работает с осознанным override
    assert all("robots.txt" not in u for u in crawler.transport.requests)


def test_collect_blocked_on_authwall(config, tmp_path):
    store = Store(tmp_path / "db.sqlite")
    run_id = store.start_run("collect", {})
    crawler = PoliteCrawler(
        FakeTransport(
            {"https://www.linkedin.com/company/x/": Response(
                url="https://www.linkedin.com/uas/login?session_redirect=x", status=200, text="login"
            )}
        ),
        config,
        resolver=lambda h: True,
    )
    summary = collect_company_people(
        store, crawler, "x.com", "https://www.linkedin.com/company/x/", run_id, 100
    )
    assert summary["status"] == "blocked"
    assert summary["stop_reason"] == "authwall"
    assert store.get_company_by_key("x.com") is None  # компания не создана, людей нет
