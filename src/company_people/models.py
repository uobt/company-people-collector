"""Конфигурация и доменные статусы проекта."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

import yaml

DISCOVERY_STATUSES = ("found", "ambiguous", "not_found", "site_blocked", "error", "not_attempted")
PEOPLE_STATUSES = (
    "complete_available_pages",
    "partial",
    "source_unavailable",
    "blocked",
    "no_people_observed",
    "not_attempted",
    "error",
)
SOURCE_TYPES = ("licensed_api", "licensed_file", "company_site", "permitted_linkedin")
AFFILIATION_KINDS = ("current_confirmed", "listed_without_current_status", "former", "unclear")
CONFIDENCE_LEVELS = ("high", "medium", "review")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CollectorConfig:
    max_pages_per_site: int = 5
    max_people_per_company: int = 100
    max_requests_per_run: int = 100
    min_interval_seconds: float = 3.0
    timeout_seconds: float = 20.0
    retries: int = 2
    user_agent: str = "company-people-collector/0.1 (research; contact: set-yours@example.invalid)"
    browser_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    proxy: str | None = None
    db_path: str = "data/collector.db"
    output_dir: str = "data/exports"

    @classmethod
    def load(cls, path: str | Path | None) -> "CollectorConfig":
        defaults = cls()
        if not path:
            return defaults
        p = Path(path)
        if not p.exists():
            return defaults
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            return defaults
        # значения из defaults: + верхний уровень (верхний приоритетнее)
        merged = {**raw.get("defaults", {}), **{k: v for k, v in raw.items() if k != "defaults"}}
        known = {f.name for f in fields(defaults)}
        kwargs = {}
        for key, value in merged.items():
            snake = key.replace("-", "_")
            if snake in known:
                kwargs[snake] = value
        return cls(**kwargs)  # type: ignore[arg-type]
