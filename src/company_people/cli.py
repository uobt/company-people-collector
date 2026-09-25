"""CLI: doctor / discover / import-people / collect / export / purge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .discover import discover_site
from .enrich import (
    EMPLOYEE_NAME_COLUMN,
    EMPLOYEE_URL_COLUMN,
    enrich_base,
    optionally_import_people,
    read_base_rows,
    write_enriched_csv,
)
from .export import format_pairs, write_companies_jsonl, write_jsonl, write_people_csv
from .fetch import HttpxTransport, PoliteCrawler
from .inputs import read_companies, read_rows
from .models import CollectorConfig
from .people_import import import_people, save_company_site_people
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = ROOT / "config" / "config.yaml"

# Реестр live-коннекторов источников людей. linkedin_public — публичные
# guest-страницы компаний (решение владельца, docs/access_assessment.md).
def _run_linkedin_public(args, config, store) -> int:
    from .linkedin_public import collect_company_people

    rows, errors = read_companies(args.input, website_column=args.website_column)
    for line_no, reason in errors:
        print(f"вход, строка {line_no}: {reason}")
    if not rows:
        print(f"нет валидных строк с {args.website_column}")
        return 2
    run_id = store.start_run(
        "collect", {"input": str(args.input), "source": args.source}
    )
    crawler = PoliteCrawler(
        HttpxTransport(config.user_agent, config.timeout_seconds, config.proxy), config
    )
    any_saved = 0
    for row in rows:
        from .normalize import website_key

        key = website_key(row["website_url"])
        if key is None:
            print(f"{row['website_url']}: некорректный сайт, пропущено")
            continue
        company = store.get_company_by_key(key)
        if company is None or not company.get("company_linkedin_url"):
            print(f"{key}: страница компании LinkedIn неизвестна — сначала discover")
            continue
        summary = collect_company_people(
            store,
            crawler,
            key,
            company["company_linkedin_url"],
            run_id,
            config.max_people_per_company,
        )
        any_saved += summary["saved"]
        extra = f"; численность ~{summary['employee_count_raw'].strip()}" if summary["employee_count_raw"] else ""
        extra += f"; скрыто за логином: {summary['hidden']}" if summary["hidden"] else ""
        print(
            f"{key}: {summary['status']}; собрано видимых карточек: {summary['saved']}"
            f" (пропущено без имени: {summary['skipped']}){extra}"
            + (f"; причина: {summary['stop_reason']}" if summary["stop_reason"] else "")
        )
    store.finish_run(run_id, f"saved={any_saved}")
    print(f"итого новых людей: {any_saved}")
    return 0


PEOPLE_CONNECTORS: dict[str, object] = {"linkedin_public": _run_linkedin_public}


def _config(args) -> CollectorConfig:
    return CollectorConfig.load(args.config or (DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else None))


def _store(args, config: CollectorConfig) -> Store:
    path = getattr(args, "db", None) or ROOT / config.db_path
    return Store(path)


# ---------- doctor ----------

def cmd_doctor(args) -> int:
    config = _config(args)
    print(f"company-people-collector {__version__}")
    print(f"python: {sys.version.split()[0]}")
    print(f"база: {ROOT / config.db_path}")
    store = _store(args, config)
    print("реестр допуска источников:")
    for row in store.list_source_access():
        basis = f"; основание: {row['basis_url']}" if row["basis_url"] else ""
        print(f"  {row['source']:24s} {row['decision']:8s} ({row['note'][:90]}){basis}")
    if args.website:
        print(f"\nпроверка сайта {args.website}:")
        crawler = PoliteCrawler(
            HttpxTransport(config.user_agent, config.timeout_seconds, config.proxy), config
        )
        policy = crawler.robots_for(args.website)
        print(f"  robots.txt: {policy.status}")
        if policy.status == "ok":
            allowed = policy.allowed(args.website, crawler.ua_token)
            print(f"  обход по robots.txt для {crawler.ua_token}: {'разрешён' if allowed else 'запрещён'}")
        outcome = crawler.fetch(args.website)
        if outcome.response is not None:
            print(f"  главная страница: HTTP {outcome.response.status} ({outcome.response.url})")
        else:
            print(f"  главная страница: не получена; причина: {outcome.stop_reason}")
    print("\ndoctor не включает live-режим автоматически: решение фиксируется в docs/access_assessment.md.")
    return 0


# ---------- discover ----------

def cmd_discover(args) -> int:
    config = _config(args)
    if args.max_pages_per_site:
        config.max_pages_per_site = args.max_pages_per_site
    rows, errors = read_companies(args.input, website_column=args.website_column)
    for line_no, reason in errors:
        print(f"вход, строка {line_no}: {reason}")
    if not rows:
        print(f"нет валидных строк с {args.website_column}")
        return 2

    unique: dict[str, dict] = {}
    duplicates: list[str] = []
    for row in rows:
        from .normalize import website_key

        key = website_key(row.get(args.website_column, ""))
        if key in unique:
            duplicates.append(row["website_url"])
        else:
            unique[key] = row

    plan = (
        f"план: сайтов {len(unique)} (после дедупликации), дубликатов {len(duplicates)}; "
        f"лимит страниц на сайт: {config.max_pages_per_site}; запросов на запуск: {config.max_requests_per_run}"
    )
    if args.max_sites:
        unique = dict(list(unique.items())[: args.max_sites])
        plan += f"; max-sites: {args.max_sites}"
    if duplicates:
        plan += f"; дубликаты: {', '.join(duplicates)}"
    print(plan)
    if args.dry_run:
        return 0
    if not args.live:
        print("живой обход не разрешён: укажите --live (после проверки robots.txt и условий сайта)")
        return 2

    store = _store(args, config)
    if args.resume:
        done = {
            r["website_key"]
            for r in store._db.execute(
                "SELECT website_key FROM companies WHERE run_id = ?", (args.resume,)
            )
        }
        before = len(unique)
        unique = {k: v for k, v in unique.items() if k not in done}
        print(f"resume {args.resume}: пропущено уже обработанных компаний: {before - len(unique)}")
    run_id = store.start_run("discover", {"input": str(args.input), "sites": len(unique), "resume": args.resume})
    crawler = PoliteCrawler(
        HttpxTransport(config.user_agent, config.timeout_seconds, config.proxy), config
    )

    counts: dict[str, int] = {}
    for key, row in unique.items():
        result = discover_site(crawler, row[args.website_column], config)
        counts[result.discovery_status] = counts.get(result.discovery_status, 0) + 1
        store.upsert_company_discovery(
            website_key=key,
            input_website_url=row[args.website_column],
            company_name=row.get("company_name") or row.get("компания") or None,
            linkedin_url=result.company_linkedin_url,
            linkedin_source_url=result.company_linkedin_source_url,
            discovery_status=result.discovery_status,
            coverage_note=result.coverage_note,
            stop_reason=result.stop_reason,
            run_id=run_id,
        )
        store.save_candidates(key, result.candidates, run_id)
        # Люди, опубликованные самой компанией на её сайте (team/about): /in/ + имя ссылки.
        saved, skipped = save_company_site_people(store, key, result.person_candidates, run_id)
        if saved or skipped:
            store.update_people_status(
                key,
                "partial",
                None,
                f"с сайта компании: людей {saved}, без имени пропущено {skipped}",
            )
        else:
            store.update_people_status(key, "source_unavailable", None, "")
        shown = result.company_linkedin_url or ("; ".join(result.candidates.keys()) or "—")
        people_note = f"; люди с сайта: {saved} (без имени: {skipped})" if (saved or skipped) else ""
        print(
            f"{row[args.website_column]}: {result.discovery_status}; LinkedIn: {shown}; "
            f"{result.coverage_note}{people_note}"
        )
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    store.finish_run(run_id, summary)
    print(f"итог: {summary}")
    print("экспорт: company-people export --format jsonl|csv|pairs")
    return 0


# ---------- import-people ----------

def cmd_import_people(args) -> int:
    config = _config(args)
    rows = read_rows(args.input)
    if not rows:
        print("файл пуст")
        return 2
    if args.source_type not in ("licensed_file", "licensed_api"):
        print("source-type должен быть licensed_file или licensed_api")
        return 2
    store = _store(args, config)
    run_id = store.start_run(
        "import-people",
        {"input": str(args.input), "source": args.source_label, "type": args.source_type},
    )
    source_ref = f"{args.source_label}:{Path(args.input).name}"
    stats = import_people(
        store,
        rows,
        run_id,
        source_label=args.source_label,
        source_ref=source_ref,
        source_type=args.source_type,
        max_per_company=config.max_people_per_company,
    )
    for key in sorted(stats.companies):
        people_status = "complete_available_pages" if stats.imported or stats.duplicates else "no_people_observed"
        store.update_people_status(
            key,
            people_status,
            None,
            f"импорт {source_ref}: {stats.imported} новых, {stats.duplicates} дубликатов",
        )
    store.finish_run(run_id, stats.summary())
    print(stats.summary())
    for line_no, reason in stats.rejected:
        print(f"  отклонена строка {line_no}: {reason}")
    print("записи без подтверждённой текущей связи получают confidence=review и попадают в review.jsonl")
    return 0


# ---------- collect ----------

def cmd_collect(args) -> int:
    config = _config(args)
    store = _store(args, config)
    access = store.get_source_access(args.source)
    if access is None:
        print(f"источник '{args.source}' отсутствует в реестре допуска (docs/access_assessment.md)")
        return 2
    if access["decision"] != "allowed":
        print(f"источник '{args.source}' не допущен: decision={access['decision']}. {access['note']}")
        print("включение live-сбора людей требует положительного access_assessment и пилота.")
        return 2
    if not args.live:
        print("укажите --live для запуска сетевого сбора")
        return 2
    if args.source not in PEOPLE_CONNECTORS:
        print(f"для допущенного источника '{args.source}' нет реализованного коннектора.")
        print("Это ожидаемо: разрешённый канал людей ещё не выбран/не проверен (см. docs/access_assessment.md).")
        return 2
    return PEOPLE_CONNECTORS[args.source](args, config, store)


# ---------- export ----------

def cmd_export(args) -> int:
    config = _config(args)
    store = _store(args, config)
    out_dir = Path(args.output_dir) if args.output_dir else ROOT / config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    people_rows = store.export_people_rows(include_review=args.include_review)
    review_rows = store.export_review_rows()
    companies_rows = store.export_companies_rows()

    if args.format == "pairs":
        print(format_pairs(people_rows))
        return 0
    if args.format == "jsonl":
        target = Path(args.output) if args.output else out_dir / "people.jsonl"
        write_jsonl(target, people_rows)
    else:
        target = Path(args.output) if args.output else out_dir / "people.csv"
        write_people_csv(target, people_rows)
    review_path = out_dir / "review.jsonl"
    write_jsonl(review_path, review_rows)
    companies_path = out_dir / "companies.jsonl"
    write_companies_jsonl(companies_path, companies_rows)

    print(f"экспорт людей: {target} (строк: {len(people_rows)})")
    print(f"на проверку (confidence=review): {review_path} (строк: {len(review_rows)})")
    print(f"компании: {companies_path} (строк: {len(companies_rows)})")
    return 0


# ---------- enrich ----------

def cmd_enrich(args) -> int:
    """Обогащение базы: строка компании копируется по сотруднику, +2 колонки в конце."""
    config = _config(args)
    base_rows = read_base_rows(args.input)
    if not base_rows:
        print("файл базы пуст")
        return 2
    base_columns = list(base_rows[0].keys())
    if args.website_column not in base_columns:
        print(f"в базе нет колонки '{args.website_column}'. Доступные колонки: {', '.join(base_columns)}")
        return 2
    for i, row in enumerate(base_rows[1:], start=2):
        extra = [c for c in row.keys() if c not in base_columns]
        if extra:
            base_columns.extend(extra)
            print(f"внимание: строка {i} добавляет колонки {', '.join(extra)} (короткие строки)")

    store = _store(args, config)
    run_id = store.start_run("enrich", {"input": str(args.input), "people": str(args.people or "")})
    if args.people:
        optionally_import_people(store, args.people, args.source_label, run_id, config.max_people_per_company)

    out_rows, stats = enrich_base(
        base_rows,
        store,
        website_column=args.website_column,
        include_review=not args.confirmed_only,
    )
    out_dir = Path(args.output_dir) if args.output_dir else ROOT / config.output_dir
    target = Path(args.output) if args.output else out_dir / "enriched.csv"
    write_enriched_csv(target, out_rows, base_columns)
    store.finish_run(run_id, stats.summary())

    print(stats.summary())
    print(f"колонки базы сохранены ({len(base_columns)}), добавлены: {EMPLOYEE_URL_COLUMN}, {EMPLOYEE_NAME_COLUMN}")
    print(f"результат: {target} (строк: {len(out_rows)})")
    if stats.unmatched_rows:
        print(f"строк без распознанного сайта (оставлены без людей): {stats.unmatched_rows}")
    return 0


# ---------- purge ----------

def cmd_purge(args) -> int:
    config = _config(args)
    store = _store(args, config)
    deleted = store.purge_company_data(args.website_key)
    parts = ", ".join(f"{k}={v}" for k, v in deleted.items())
    print(f"удалено для {args.website_key}: {parts}")
    return 0


# ---------- парсер ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="company-people",
        description="Поиск LinkedIn-страниц компаний и импорт разрешённых данных о людях",
    )
    parser.add_argument("--config", default=None, help="путь к config.yaml")
    parser.add_argument("--db", default=None, help="путь к SQLite")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="проверка доступа и реестра источников (без массового обхода)")
    p.add_argument("--website", default=None, help="проверить robots.txt и главную одного сайта")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("discover", help="обход сайтов компаний: поиск LinkedIn-страницы компании")
    p.add_argument("--input", required=True, help="CSV/JSONL с колонкой сайта (по умолчанию website_url)")
    p.add_argument("--website-column", default="website_url", help="имя колонки с сайтом компании")
    p.add_argument("--live", action="store_true", help="разрешить сетевые запросы")
    p.add_argument("--dry-run", action="store_true", help="только план, без сети")
    p.add_argument("--max-pages-per-site", type=int, default=0)
    p.add_argument("--max-sites", type=int, default=0, help="обработать не больше N сайтов")
    p.add_argument("--resume", default=None, metavar="RUN_ID", help="пропустить компании, уже обработанные в этом запуске")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("import-people", help="импорт файла людей с подтверждёнными правами")
    p.add_argument("--input", required=True, help="CSV/JSONL: website_url/company_linkedin_url, profile_url, full_name[, affiliation, source_url]")
    p.add_argument("--source-label", required=True, help="метка происхождения (например, customer_example)")
    p.add_argument("--source-type", default="licensed_file", choices=["licensed_file", "licensed_api"])
    p.set_defaults(func=cmd_import_people)

    p = sub.add_parser("collect", help="живой сбор людей из допущенного источника")
    p.add_argument("--input", required=True)
    p.add_argument("--source", required=True, help="ключ источника из реестра допуска (linkedin_public)")
    p.add_argument("--website-column", default="website_url")
    p.add_argument("--live", action="store_true")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("export", help="экспорт people.csv/jsonl/pairs + companies.jsonl + review.jsonl")
    p.add_argument("--format", default="csv", choices=["csv", "jsonl", "pairs"])
    p.add_argument("--output", default=None)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--include-review", action="store_true", help="включить строки confidence=review в основной экспорт")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser(
        "enrich",
        help="обогащение базы: копия строки компании на каждого сотрудника + колонки ссылки и имени",
    )
    p.add_argument("--input", required=True, help="CSV базы компаний (колонки сохраняются)")
    p.add_argument("--people", default=None, help="необязательный файл людей для импорта перед обогащением")
    p.add_argument("--source-label", default="enrich", help="метка происхождения файла людей")
    p.add_argument("--output", default=None, help="итоговый CSV (по умолчанию data/exports/enriched.csv)")
    p.add_argument("--output-dir", default=None)
    p.add_argument("--website-column", default="website_url", help="имя колонки с сайтом компании")
    p.add_argument("--confirmed-only", action="store_true", help="не прикладывать записи confidence=review")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("purge", help="удалить данные компании по запросу (GDPR-стиль)")
    p.add_argument("--website-key", required=True, help="хост-ключ компании, например dedicateddevelopers.com")
    p.set_defaults(func=cmd_purge)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
