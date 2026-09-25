from pathlib import Path

from company_people.models import CollectorConfig


def test_config_merges_defaults_and_toplevel(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
defaults:
  max_pages_per_site: 3
  min_interval_seconds: 0.5
user_agent: "custom-agent/1.0"
proxy: "http://127.0.0.1:10809"
db_path: "data/custom.db"
unknown_key: "ignored"
""",
        encoding="utf-8",
    )
    cfg = CollectorConfig.load(cfg_file)
    assert cfg.max_pages_per_site == 3
    assert cfg.min_interval_seconds == 0.5
    assert cfg.user_agent == "custom-agent/1.0"
    assert cfg.proxy == "http://127.0.0.1:10809"
    assert cfg.db_path == "data/custom.db"


def test_config_defaults_without_file(tmp_path):
    cfg = CollectorConfig.load(tmp_path / "missing.yaml")
    assert cfg.proxy is None
    assert cfg.max_pages_per_site == 5
