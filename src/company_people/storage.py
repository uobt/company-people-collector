"""SQLite-хранение: запуски, компании, люди, связи, реестр допуска источников."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from .models import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    params TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS source_access (
    source TEXT PRIMARY KEY,
    decision TEXT NOT NULL,          -- allowed | blocked | unknown
    assessed_at TEXT NOT NULL,
    basis_url TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS companies (
    website_key TEXT PRIMARY KEY,
    input_website_url TEXT,
    company_name TEXT,
    company_linkedin_url TEXT,
    company_linkedin_source_url TEXT,
    discovery_status TEXT NOT NULL DEFAULT 'not_attempted',
    people_status TEXT NOT NULL DEFAULT 'not_attempted',
    people_count INTEGER NOT NULL DEFAULT 0,
    pagination_exhausted TEXT,
    coverage_note TEXT,
    stop_reason TEXT,
    observed_at TEXT,
    run_id TEXT
);
CREATE TABLE IF NOT EXISTS company_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_key TEXT NOT NULL,
    candidate_url TEXT NOT NULL,
    found_on_url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    run_id TEXT,
    UNIQUE (website_key, candidate_url, found_on_url)
);
CREATE TABLE IF NOT EXISTS people (
    profile_slug TEXT PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    raw_url_first TEXT,
    full_name TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_key TEXT NOT NULL,
    profile_slug TEXT NOT NULL,
    profile_url_raw TEXT,
    affiliation_evidence TEXT NOT NULL,
    confidence TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_ref TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    run_id TEXT,
    UNIQUE (website_key, profile_slug, source_ref)
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_key TEXT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_company_people_company ON company_people(website_key);
"""

DEFAULT_SOURCE_ACCESS = [
    (
        "licensed_import",
        "allowed",
        "файлы, предоставленные оператором/владельцем данных с подтверждёнными правами (docs/access_assessment.md)",
        None,
    ),
    (
        "linkedin_public",
        "allowed",
        "решение владельца 2026-09-25 (прецедент JobSpy в job-search-collector): "
        "публичные guest-страницы компаний LinkedIn, без логина/cookies/обхода "
        "CAPTCHA; robots-запрет LinkedIn преодолён осознанно, риск ToS задокументирован",
        "https://www.linkedin.com/legal/user-agreement",
    ),
    (
        "linkedin_direct_crawl",
        "blocked",
        "массовое автоматическое извлечение профилей людей не разрешено условиями LinkedIn; обхода блокировок нет",
        "https://www.linkedin.com/legal/user-agreement",
    ),
    (
        "licensed_vendor_api",
        "unknown",
        "поставщик не выбран; перед подключением требуется проверка прав, лимитов и пилот (docs/access_assessment.md)",
        None,
    ),
]


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._seed_source_access()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    # ---------- запуски ----------

    def start_run(self, command: str, params: dict) -> str:
        run_id = str(uuid.uuid4())
        self._db.execute(
            "INSERT INTO runs(run_id, command, params, started_at) VALUES (?,?,?,?)",
            (run_id, command, json.dumps(params, ensure_ascii=False), utcnow()),
        )
        self._db.commit()
        return run_id

    def finish_run(self, run_id: str, note: str = "") -> None:
        self._db.execute(
            "UPDATE runs SET finished_at=?, note=? WHERE run_id=?", (utcnow(), note, run_id)
        )
        self._db.commit()

    # ---------- реестр допуска ----------

    def _seed_source_access(self) -> None:
        for source, decision, note, basis in DEFAULT_SOURCE_ACCESS:
            self._db.execute(
                "INSERT OR IGNORE INTO source_access(source, decision, assessed_at, basis_url, note)"
                " VALUES (?,?,?,?,?)",
                (source, decision, "2026-09-25", basis, note),
            )
        self._db.commit()

    def get_source_access(self, source: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM source_access WHERE source=?", (source,)
        ).fetchone()
        return dict(row) if row else None

    def list_source_access(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM source_access ORDER BY source")]

    # ---------- компании ----------

    def upsert_company_discovery(
        self,
        website_key: str,
        input_website_url: str,
        company_name: str | None,
        linkedin_url: str | None,
        linkedin_source_url: str | None,
        discovery_status: str,
        coverage_note: str,
        stop_reason: str | None,
        run_id: str,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO companies(website_key, input_website_url, company_name,
                                  company_linkedin_url, company_linkedin_source_url,
                                  discovery_status, coverage_note, stop_reason,
                                  observed_at, run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(website_key) DO UPDATE SET
                input_website_url=excluded.input_website_url,
                company_name=COALESCE(excluded.company_name, companies.company_name),
                company_linkedin_url=excluded.company_linkedin_url,
                company_linkedin_source_url=excluded.company_linkedin_source_url,
                discovery_status=excluded.discovery_status,
                coverage_note=excluded.coverage_note,
                stop_reason=excluded.stop_reason,
                observed_at=excluded.observed_at,
                run_id=excluded.run_id
            """,
            (
                website_key,
                input_website_url,
                company_name,
                linkedin_url,
                linkedin_source_url,
                discovery_status,
                coverage_note,
                stop_reason,
                utcnow(),
                run_id,
            ),
        )
        self._db.commit()

    def ensure_company(self, website_key: str, input_website_url: str, company_name: str | None = None) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO companies(website_key, input_website_url, company_name,"
            " discovery_status, people_status, observed_at) VALUES (?,?,?,'not_attempted','not_attempted',?)",
            (website_key, input_website_url, company_name, utcnow()),
        )
        self._db.commit()

    def get_company_by_key(self, website_key: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM companies WHERE website_key=?", (website_key,)
        ).fetchone()
        return dict(row) if row else None

    def find_company_by_linkedin_slug(self, slug: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM companies WHERE LOWER(COALESCE(company_linkedin_url,'')) LIKE ?",
            (f"%/company/{slug}",),
        ).fetchone()
        return dict(row) if row else None

    def save_candidates(self, website_key: str, candidates: dict[str, list[str]], run_id: str) -> None:
        now = utcnow()
        for cand, pages in candidates.items():
            for page in pages:
                self._db.execute(
                    "INSERT OR IGNORE INTO company_candidates(website_key, candidate_url,"
                    " found_on_url, observed_at, run_id) VALUES (?,?,?,?,?)",
                    (website_key, cand, page, now, run_id),
                )
        self._db.commit()

    def update_people_status(
        self,
        website_key: str,
        status: str,
        pagination_exhausted: str | None,
        note: str,
    ) -> None:
        count = self._db.execute(
            "SELECT COUNT(*) AS c FROM company_people WHERE website_key=?", (website_key,)
        ).fetchone()["c"]
        self._db.execute(
            "UPDATE companies SET people_status=?, people_count=?, pagination_exhausted=?,"
            " coverage_note=COALESCE(?, coverage_note) WHERE website_key=?",
            (status, count, pagination_exhausted, note, website_key),
        )
        self._db.commit()

    # ---------- люди ----------

    def upsert_person(self, slug: str, canonical_url: str, raw_url: str, full_name: str) -> None:
        now = utcnow()
        self._db.execute(
            """
            INSERT INTO people(profile_slug, canonical_url, raw_url_first, full_name,
                               first_observed_at, last_observed_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(profile_slug) DO UPDATE SET
                last_observed_at=excluded.last_observed_at,
                canonical_url=CASE WHEN people.canonical_url IS NULL
                                   THEN excluded.canonical_url
                                   ELSE people.canonical_url END
            """,
            (slug, canonical_url, raw_url, full_name.strip(), now, now),
        )
        self._db.commit()

    def link_person(
        self,
        website_key: str,
        slug: str,
        raw_url: str,
        affiliation: str,
        confidence: str,
        source_type: str,
        source_url: str | None,
        source_ref: str,
        run_id: str,
    ) -> bool:
        """Возвращает True, если связь новая; False — дубликат по ключу источника."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO company_people(website_key, profile_slug, profile_url_raw,"
            " affiliation_evidence, confidence, source_type, source_url, source_ref,"
            " observed_at, run_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                website_key,
                slug,
                raw_url,
                affiliation,
                confidence,
                source_type,
                source_url,
                source_ref,
                utcnow(),
                run_id,
            ),
        )
        self._db.commit()
        return cur.rowcount > 0

    def count_company_people(self, website_key: str) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) AS c FROM company_people WHERE website_key=?", (website_key,)
        ).fetchone()
        return row["c"]

    def company_people_rows(self, website_key: str, include_review: bool = True) -> list[dict]:
        """Люди компании в порядке добавления (для обогащения базы)."""
        query = (
            "SELECT p.canonical_url, p.full_name, cp.confidence"
            " FROM company_people cp JOIN people p ON p.profile_slug = cp.profile_slug"
            " WHERE cp.website_key = ?"
        )
        if not include_review:
            query += " AND cp.confidence != 'review'"
        query += " ORDER BY cp.id"
        return [dict(r) for r in self._db.execute(query, (website_key,))]

    # ---------- экспорт ----------

    def export_people_rows(self, include_review: bool = False) -> list[dict]:
        query = """
            SELECT c.input_website_url, c.company_linkedin_url,
                   p.canonical_url AS profile_url, p.full_name,
                   cp.source_url, cp.source_type, cp.affiliation_evidence,
                   cp.observed_at, cp.confidence
            FROM company_people cp
            JOIN people p ON p.profile_slug = cp.profile_slug
            JOIN companies c ON c.website_key = cp.website_key
        """
        if not include_review:
            query += " WHERE cp.confidence != 'review'"
        query += " ORDER BY c.website_key, cp.id"
        return [dict(r) for r in self._db.execute(query)]

    def export_review_rows(self) -> list[dict]:
        return [r for r in self.export_people_rows(include_review=True) if r["confidence"] == "review"]

    def export_companies_rows(self) -> list[dict]:
        rows = [
            dict(r)
            for r in self._db.execute(
                """
                SELECT input_website_url, company_name, company_linkedin_url,
                       company_linkedin_source_url, discovery_status, people_status,
                       people_count, pagination_exhausted, coverage_note, stop_reason,
                       observed_at, run_id
                FROM companies ORDER BY input_website_url
                """
            )
        ]
        return rows

    # ---------- служебное ----------

    def record_observation(self, website_key: str | None, kind: str, payload: dict, run_id: str) -> None:
        self._db.execute(
            "INSERT INTO observations(website_key, kind, payload, observed_at, run_id)"
            " VALUES (?,?,?,?,?)",
            (website_key, kind, json.dumps(payload, ensure_ascii=False), utcnow(), run_id),
        )
        self._db.commit()

    def purge_company_data(self, website_key: str) -> dict[str, int]:
        """Удаление данных компании и её связей с людьми (запрос на удаление)."""
        deleted = {}
        cur = self._db.execute("DELETE FROM company_people WHERE website_key=?", (website_key,))
        deleted["links"] = cur.rowcount
        cur = self._db.execute("DELETE FROM company_candidates WHERE website_key=?", (website_key,))
        deleted["candidates"] = cur.rowcount
        cur = self._db.execute("DELETE FROM observations WHERE website_key=?", (website_key,))
        deleted["observations"] = cur.rowcount
        cur = self._db.execute("DELETE FROM companies WHERE website_key=?", (website_key,))
        deleted["company"] = cur.rowcount
        cur = self._db.execute(
            "DELETE FROM people WHERE profile_slug NOT IN (SELECT DISTINCT profile_slug FROM company_people)"
        )
        deleted["orphan_people"] = cur.rowcount
        self._db.commit()
        return deleted
