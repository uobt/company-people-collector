import csv
from pathlib import Path

from company_people.export import format_pairs, write_people_csv
from company_people.inputs import read_rows
from company_people.people_import import import_people
from company_people.storage import Store

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _store(tmp_path) -> Store:
    return Store(tmp_path / "collector.db")


def _import_example(store: Store, run_id: str):
    rows = read_rows(EXAMPLES / "licensed_people.example.csv")
    return import_people(
        store,
        rows,
        run_id,
        source_label="customer_example",
        source_ref=f"customer_example:licensed_people.example.csv",
    )


def test_reference_four_pairs_import(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    stats = _import_example(store, run_id)
    assert stats.total == 4
    assert stats.imported == 4
    assert stats.duplicates == 0
    assert stats.rejected == []

    rows = store.export_people_rows(include_review=True)
    assert len(rows) == 4
    # канонический URL без ?trk, исходный сохранён в БД
    assert all("?trk=" not in r["profile_url"] for r in rows)
    raws = store._db.execute("SELECT profile_url_raw FROM company_people").fetchall()
    assert all("trk=org-employees" in r["profile_url_raw"] for r in raws)
    # локализованный хост сохранён
    hosts = {r["profile_url"].split("/")[2] for r in rows}
    assert "co.linkedin.com" in hosts
    # без подтверждения текущей связи — review
    assert all(r["confidence"] == "review" for r in rows)
    # порядок строк = порядку источника (демо-данные фиктивные)
    assert [r["full_name"] for r in rows] == [
        "Avery Stone",
        "Jordan Vale",
        "Riley Quinn",
        "Casey North",
    ]


def test_pairs_format_matches_reference(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    _import_example(store, run_id)
    rows = store.export_people_rows(include_review=True)
    expected = (
        "https://www.linkedin.com/in/avery-stone-example-co, Avery Stone; "
        "https://www.linkedin.com/in/jordan-vale-94844727, Jordan Vale; "
        "https://www.linkedin.com/in/riley-example-co, Riley Quinn; "
        "https://co.linkedin.com/in/casey-north, Casey North"
    )
    assert format_pairs(rows) == expected


def test_default_export_excludes_review(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    _import_example(store, run_id)
    assert store.export_people_rows() == []            # review не входит в подтверждённый список
    assert len(store.export_review_rows()) == 4        # весь пример — в review.jsonl


def test_reimport_is_idempotent(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    first = _import_example(store, run_id)
    second = _import_example(store, run_id)
    assert first.imported == 4 and second.imported == 0
    assert second.duplicates == 4
    assert len(store.export_people_rows(include_review=True)) == 4


def test_same_slug_different_hosts_is_one_person(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    rows = [
        {"website_url": "https://dedicateddevelopers.com/", "profile_url": "https://www.linkedin.com/in/casey-north", "full_name": "Casey North"},
        {"website_url": "https://dedicateddevelopers.com/", "profile_url": "https://co.linkedin.com/in/casey-north/", "full_name": "Casey North"},
    ]
    stats = import_people(store, rows, run_id, "t", "t:dual")
    assert stats.imported == 1 and stats.duplicates == 1
    assert len(store.export_people_rows(include_review=True)) == 1


def test_current_confirmed_gets_high_confidence(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    rows = [
        {
            "website_url": "https://dedicateddevelopers.com/",
            "profile_url": "https://www.linkedin.com/in/avery-stone-example-co",
            "full_name": "Avery Stone",
            "affiliation": "current_confirmed",
        }
    ]
    import_people(store, rows, run_id, "licensed", "licensed:f.csv")
    confirmed = store.export_people_rows()  # без include_review
    assert len(confirmed) == 1
    assert confirmed[0]["confidence"] == "high"
    assert confirmed[0]["source_type"] == "licensed_file"


def test_rejects_bad_rows(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    rows = [
        {"website_url": "https://dedicateddevelopers.com/", "profile_url": "not a url", "full_name": "John Doe"},
        {"website_url": "https://dedicateddevelopers.com/", "profile_url": "https://www.linkedin.com/in/john-doe", "full_name": " "},
        {"website_url": "", "profile_url": "https://www.linkedin.com/in/john-doe", "full_name": "John Doe"},
        {"website_url": "https://dedicateddevelopers.com/", "profile_url": "https://www.linkedin.com/in/john-doe", "full_name": "LinkedIn Member"},
        {"website_url": "https://dedicateddevelopers.com/", "profile_url": "https://www.linkedin.com/company/john-doe", "full_name": "John Doe"},
    ]
    stats = import_people(store, rows, run_id, "t", "t:bad.csv")
    assert stats.imported == 0
    assert len(stats.rejected) == 5
    assert all("некорректн" in reason or "компани" in reason for _, reason in stats.rejected)


def test_csv_export_bom_and_formula_guard(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("import-people", {})
    rows = [
        {
            "website_url": "https://dedicateddevelopers.com/",
            "profile_url": "https://www.linkedin.com/in/weird-name",
            "full_name": "=SUM(A1:A5)",
            "affiliation": "current_confirmed",
        }
    ]
    import_people(store, rows, run_id, "licensed", "licensed:f.csv")
    target = tmp_path / "people.csv"
    write_people_csv(target, store.export_people_rows())
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM для Excel
    with target.open("r", encoding="utf-8-sig", newline="") as fh:
        parsed = list(csv.DictReader(fh))
    assert len(parsed) == 1
    assert parsed[0]["full_name"].startswith("'=SUM")  # формула нейтрализована
    assert parsed[0]["profile_url"] == "https://www.linkedin.com/in/weird-name"
    assert list(parsed[0].keys())[:4] == [
        "input_website_url",
        "company_linkedin_url",
        "profile_url",
        "full_name",
    ]


def test_companies_jsonl_covers_every_input_row(tmp_path):
    store = _store(tmp_path)
    run_id = store.start_run("discover", {})
    store.upsert_company_discovery(
        "dedicateddevelopers.com",
        "https://dedicateddevelopers.com/",
        "Dedicated Developers",
        "https://www.linkedin.com/company/dedicated-developers",
        "https://dedicateddevelopers.com/",
        "found",
        "пилот",
        None,
        run_id,
    )
    store.update_people_status("dedicateddevelopers.com", "source_unavailable", None, "")
    companies = store.export_companies_rows()
    assert len(companies) == 1
    row = companies[0]
    assert row["discovery_status"] == "found"
    assert row["people_status"] == "source_unavailable"
    assert row["people_count"] == 0
    assert row["company_linkedin_url"].endswith("/company/dedicated-developers")
