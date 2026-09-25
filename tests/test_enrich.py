"""Обогащение базы: по сотруднику на строку, две новые колонки (спека пользователя)."""

from pathlib import Path

from company_people.enrich import (
    EMPLOYEE_NAME_COLUMN,
    EMPLOYEE_URL_COLUMN,
    enrich_base,
    read_base_rows,
    write_enriched_csv,
)
from company_people.inputs import read_rows
from company_people.people_import import import_people
from company_people.storage import Store

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

BASE = [
    {"company_name": "Dedicated Developers", "website_url": "https://dedicateddevelopers.com/", "country": "US", "segment": "dev agency"},
    {"company_name": "No People Co", "website_url": "https://nopeople.example/", "country": "DE", "segment": "saas"},
]


def _store_with_reference_people(tmp_path) -> Store:
    store = Store(tmp_path / "collector.db")
    run_id = store.start_run("import-people", {})
    rows = read_rows(EXAMPLES / "licensed_people.example.csv")
    import_people(store, rows, run_id, "customer_example", "customer_example:f.csv")
    return store


def test_fan_out_one_row_per_employee(tmp_path):
    store = _store_with_reference_people(tmp_path)
    out_rows, stats = enrich_base(BASE, store)
    # 4 строки Dedicated Developers (по сотруднику) + 1 строка компании без людей
    assert len(out_rows) == 5
    dd = [r for r in out_rows if r["company_name"] == "Dedicated Developers"]
    assert len(dd) == 4
    assert [r[EMPLOYEE_NAME_COLUMN] for r in dd] == [
        "Vishal Bhatia",
        "Aline Ghazarian",
        "Tina Morgan",
        "Carolina Giraldo",
    ]
    assert dd[0][EMPLOYEE_URL_COLUMN] == "https://www.linkedin.com/in/vishal-bhatia-dedicated-developers"
    assert dd[3][EMPLOYEE_URL_COLUMN] == "https://co.linkedin.com/in/carolinagiraldoh"
    # исходные колонки компании скопированы в каждую строку без изменений
    for row in dd:
        assert row["country"] == "US" and row["segment"] == "dev agency"
        assert row["website_url"] == "https://dedicateddevelopers.com/"
    # компания без людей остаётся одной строкой с пустыми новыми колонками
    no_people = [r for r in out_rows if r["company_name"] == "No People Co"]
    assert len(no_people) == 1
    assert no_people[0][EMPLOYEE_URL_COLUMN] == "" and no_people[0][EMPLOYEE_NAME_COLUMN] == ""
    assert stats.employees_attached == 4
    assert stats.companies_with_people == 1 and stats.companies_without_people == 1


def test_enriched_csv_structure_and_bom(tmp_path):
    store = _store_with_reference_people(tmp_path)
    out_rows, _ = enrich_base(BASE, store)
    target = tmp_path / "enriched.csv"
    write_enriched_csv(target, out_rows, list(BASE[0].keys()))
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == (
        "company_name,website_url,country,segment,employee_profile_url,employee_full_name"
    )
    assert lines[1].startswith("Dedicated Developers,https://dedicateddevelopers.com/,US,dev agency,https://www.linkedin.com/in/vishal")
    assert len(lines) == 6  # заголовок + 5 строк


def test_confirmed_only_excludes_review(tmp_path):
    store = Store(tmp_path / "collector.db")
    run_id = store.start_run("import-people", {})
    rows = [
        {
            "website_url": "https://dedicateddevelopers.com/",
            "profile_url": "https://www.linkedin.com/in/vishal-bhatia-dedicated-developers",
            "full_name": "Vishal Bhatia",
            "affiliation": "current_confirmed",
        },
        {
            "website_url": "https://dedicateddevelopers.com/",
            "profile_url": "https://www.linkedin.com/in/aline-ghazarian-94844727",
            "full_name": "Aline Ghazarian",
        },
    ]
    import_people(store, rows, run_id, "licensed", "licensed:f.csv")
    out_rows, stats = enrich_base(BASE[:1], store, include_review=False)
    assert len(out_rows) == 1  # только подтверждённый сотрудент
    assert out_rows[0][EMPLOYEE_NAME_COLUMN] == "Vishal Bhatia"
    assert stats.employees_attached == 1


def test_unmatched_site_keeps_row(tmp_path):
    store = _store_with_reference_people(tmp_path)
    base = [{"company_name": "Broken", "website_url": "not a url", "country": "X"}]
    out_rows, stats = enrich_base(base, store)
    assert len(out_rows) == 1
    assert out_rows[0][EMPLOYEE_NAME_COLUMN] == ""
    assert stats.unmatched_rows == 1


def test_custom_website_column(tmp_path):
    store = _store_with_reference_people(tmp_path)
    base = [{"Компания": "DD", "домен": "dedicateddevelopers.com"}]
    out_rows, _ = enrich_base(base, store, website_column="домен")
    assert len(out_rows) == 4
    assert out_rows[0]["Компания"] == "DD"


def test_duplicate_company_rows_fan_out_each(tmp_path):
    store = _store_with_reference_people(tmp_path)
    base = [BASE[0], dict(BASE[0])]
    out_rows, stats = enrich_base(base, store)
    assert len(out_rows) == 8  # каждая строка базы размножается независимо
    assert stats.employees_attached == 8


def test_fills_empty_company_linkedin_column(tmp_path):
    store = Store(tmp_path / "collector.db")
    run_id = store.start_run("discover", {})
    store.upsert_company_discovery(
        "bland.ai",
        "https://bland.ai/",
        "Bland",
        "https://www.linkedin.com/company/bland-ai",
        "https://bland.ai/",
        "found",
        "пилот",
        None,
        run_id,
    )
    base = [
        {"компания": "Bland", "сайт": "bland.ai", "company_linkedin_url": ""},
        {"компания": "Bland2", "сайт": "bland.ai", "company_linkedin_url": "https://www.linkedin.com/company/kept"},
    ]
    out_rows, stats = enrich_base(base, store, website_column="сайт")
    assert out_rows[0]["company_linkedin_url"] == "https://www.linkedin.com/company/bland-ai"
    assert out_rows[1]["company_linkedin_url"] == "https://www.linkedin.com/company/kept"  # не перезаписано
    assert stats.company_linkedin_filled == 1
    # колонки сотрудника пустые, но строка сохранена
    assert out_rows[0][EMPLOYEE_NAME_COLUMN] == ""
