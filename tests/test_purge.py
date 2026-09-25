"""Удаление данных компании по запросу (спецификация §6.2.7)."""

from company_people.inputs import read_rows
from company_people.people_import import import_people
from company_people.storage import Store

from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_purge_removes_company_links_and_orphans(tmp_path):
    store = Store(tmp_path / "collector.db")
    run_id = store.start_run("import-people", {})
    rows = read_rows(EXAMPLES / "licensed_people.example.csv")
    import_people(store, rows, run_id, "customer_example", "customer_example:f.csv")
    assert store.count_company_people("dedicateddevelopers.com") == 4

    deleted = store.purge_company_data("dedicateddevelopers.com")
    assert deleted["company"] == 1
    assert deleted["links"] == 4
    # люди-сироты удалены вместе со связями
    orphan_count = store._db.execute("SELECT COUNT(*) AS c FROM people").fetchone()["c"]
    assert orphan_count == 0
    assert store.export_companies_rows() == []
    assert store.export_people_rows(include_review=True) == []
