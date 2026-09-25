"""Гейт live-сбора: collect отказывает без допущенного источника и коннектора."""

from company_people.cli import main
from company_people.storage import Store


def test_collect_refuses_blocked_source(tmp_path):
    db = tmp_path / "collector.db"
    Store(db).close()
    code = main(
        [
            "--db",
            str(db),
            "collect",
            "--input",
            "examples/companies.example.csv",
            "--source",
            "linkedin_direct_crawl",
            "--live",
        ]
    )
    assert code == 2  # решение по источнику: blocked — честный отказ


def test_collect_refuses_unknown_connector(tmp_path):
    db = tmp_path / "collector.db"
    Store(db).close()
    code = main(
        [
            "--db",
            str(db),
            "collect",
            "--input",
            "examples/companies.example.csv",
            "--source",
            "licensed_vendor_api",
            "--live",
        ]
    )
    assert code == 2  # источнику unknown/нет коннектора — отказ с объяснением
