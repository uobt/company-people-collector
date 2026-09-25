"""Проверки CLI: dry-run план с --max-sites и честный отказ без --live."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from company_people.cli import main  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_discover_dry_run_plan_with_max_sites(capsys, tmp_path):
    code = main(
        [
            "--db",
            str(tmp_path / "collector.db"),
            "discover",
            "--input",
            str(EXAMPLES / "companies.example.csv"),
            "--dry-run",
            "--max-sites",
            "1",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "план: сайтов 1" in out
    assert "max-sites: 1" in out


def test_discover_without_live_refuses(capsys, tmp_path):
    code = main(
        [
            "--db",
            str(tmp_path / "collector.db"),
            "discover",
            "--input",
            str(EXAMPLES / "companies.example.csv"),
        ]
    )
    assert code == 2
    assert "--live" in capsys.readouterr().out
