# progress.md — company-people-collector

Старт: 2026-09-25 (лимит часа работы: старт ~12:xx, см. историю чата).

## Цель

Реализовать проект по `../company_linkedin_employees_spec.md`: discover LinkedIn-страниц компаний, импорт разрешённых людей, экспорт, тесты, пилот на dedicateddevelopers.com.

## Сделано

- Каркас проекта (pyproject, src-layout, config.example.yaml).
- `normalize.py` — канонизация LinkedIn-URL (профиль/компания), ключи сайтов, csv_safe.
- `linkedin_pages.py` — чистый разбор HTML (href + сырой скан), same-site приоритетные ссылки.
- `fetch.py` — httpx-транспорт без автоследования, PoliteCrawler: robots.txt (absent/ok/unknown), SSRF-защита (resolver, порты, редиректы с проверкой каждого хоста и robots), рейт-лимит, бюджет, 429/403/5xx-политика.
- `discover.py` — стадия A: BFS по приоритетным страницам, кандидаты /company/, статусы found/ambiguous/not_found/site_blocked/error + coverage_note.
- `storage.py` — SQLite (7 таблиц), реестр `source_access` (licensed_import=allowed, linkedin_direct_crawl=blocked, licensed_vendor_api=unknown), purge.
- `people_import.py` + `inputs.py` + `export.py` + `cli.py` — команды doctor/discover/import-people/collect/export/purge; collect честно отказывает.
- `docs/access_assessment.md` — матрица допуска от 2026-09-25.
- Примеры: companies.example.csv, licensed_people.example.csv (4 контрольные пары заказчика).

## Сделано (итог сеанса 2026-09-25)

- Реализованы и протестированы все модули; `uv run pytest -q` → **40 passed** (включая CLI dry-run/max-sites, resume, purge, конфиг).
- Исправлены по ходу: httpx + сломанные env-прокси (`trust_env=False`, явный `proxy` в конфиге), слияние `defaults:` и верхнего уровня конфига (тест `test_config.py`).
- Живой пилот `doctor` + `discover` на `https://dedicateddevelopers.com/`:
  - robots.txt `ok`, обход разрешён; запросов: 4;
  - результат `found`: `https://www.linkedin.com/company/dedicateddevelopers`, источники `/`, `/about-us/`, `/contact-us/`;
  - отчёт: `reports/pilot_dedicateddevelopers.md`.
- Демо `import-people` (4 контрольные пары заказчика): 4 связи, 0 дубликатов; экспорт `people.csv`/`review.jsonl`/`companies.jsonl`/pairs совпадает с контрольным примером (URL канонизированы, `?trk` убран, `co.linkedin.com` сохранён).
- Скрипты: `scripts/probe_transport.py` (диагностика сети), `scripts/pilot_summary.py` (сводка запусков).

## Дополнение 2026-09-25 (ход 2): команда enrich

- Новая команда `enrich --input base.csv [--people people.csv] [--website-column ...] [--confirmed-only] [--output ...]`: строка компании копируется по сотруднику, в конец добавляются `employee_profile_url`, `employee_full_name`; компания без людей остаётся одной строкой с пустыми колонками; исходные колонки и порядок сохраняются; UTF-8 BOM.
- Демо на примере заказчика (`examples/base.example.csv` + 4 импортированные пары) → `data/exports/enriched_demo.csv`: 1 строка → 4 строки. Отправлено пользователю на подтверждение формата.
- Попутно закрыта дыра нормализации: хост без точки/с пробелами ("not a url") теперь отклоняется в `split_url` (тест `test_unmatched_site_keeps_row`).
- Тесты: 46 passed.

## Дополнение 2026-09-25 (ход 3): люди с сайтов компаний + прогон на базе пользователя

- `discover` теперь собирает `/in/`-ссылки с сайтов самих компаний (team/about): имя из якорного текста/aria-label, блок-лист служебных якорей (`icon`, `linkedin`...), сохранение через `save_company_site_people` (`company_site`, `medium`, `listed_without_current_status`), пропуск без имени с наблюдением. `--website-column` в discover и enrich (кириллические колонки вроде `сайт`).
- Фиксы по живому прогону: robots.txt следует за редиректами (308/301 на bland.ai/algosolutions.com); `linkedin.com` без www канонизируется в `www.linkedin.com` (bland.ai: ambiguous → found).
- База пользователя `Новая таблица - Лист1.csv` (2 компании, колонка `сайт`): скопирована в `data/base_input/novaya_tablitsa.csv`; discover: bland.ai → company/bland-ai, algosolutions.com → company/algo-communication-products-ltd (оба found); людей на их сайтах нет (командных страниц с /in/ в лимите обхода не найдено).
- enrich: `data/exports/enriched_novaya.csv` — 27 исходных колонок + employee_profile_url/employee_full_name (пустые, людей нет). Колонки сотрудников заполняются импортом файла людей или после выбора лицензированного поставщика.
- Тесты: 50 passed.

## Дополнение 2026-09-25 (ход 4): заполнение company_linkedin_url из подвала сайтов

- Пользователь указал, что у компаний есть LinkedIn-ссылки в подвале. Проверка (`scripts/probe_footer.py`): да, обе — но это `/company/`-страницы (bland.ai: company/bland-ai ×2 написания, algosolutions.com: company/algo-communication-products-ltd); `/in/`-ссылок на их сайтах нет. Discover их уже нашёл ранее.
- enrich теперь заполняет пустую колонку `company_linkedin_url` из БД (непустое значение базы не перезаписывается; `--fill` не нужен — включено всегда, счётчик в сводке). Тесты: 51 passed.
- `data/exports/enriched_novaya.csv`: обе строки получили company_linkedin_url; employee-колонки пусты — источников людей для этих компаний нет (LinkedIn за логином, сайт team-страниц без /in/).

## Дополнение 2026-09-25 (ход 5): канал linkedin_public — сотрудники с публичной страницы компании

- Решение владельца (указание в чате, прецедент JobSpy): собирать сотрудников прямо со страницы компании LinkedIn. Эмпирика: `/company/<slug>/` без логина отдаёт 200 с секцией «Employees at» (видимые карточки /in/ + имя, `?trk=org-employees`), полный список `/people/` — 302 на логин; часть карточек приходит как «LinkedIn Member» без ссылок.
- Реализовано: `linkedin_public.py` (парсер секции employees-at: h3/alt-имена, счётчик численности, hidden-счётчик, authwall-детект) + коннектор `collect --source linkedin_public --live` (respect_robots=False как осознанный override, браузерные заголовки, паузы/бюджет/SSRF сохранены, сохранение `permitted_linkedin`, `current_confirmed`, `medium`); ретрай временных ошибок (999/5xx/сеть) в PoliteCrawler; ключ реестра выровнен с коннектором.
- Живой прогон базы пользователя: bland.ai — 4 сотрудника (численность ~120), algosolutions.com — 4 (~93, включая uk/ca-хосты); повторный прогон идемпотентен (0 новых). `enriched_novaya.csv`: 8 строк (по сотруднику на строку, 27 исходных колонок + 2 новые).
- Границы канала: видимые карточки публичной страницы (обычно ≤10) — не полный штат; полный список за логином (linkedin_direct_crawl остаётся blocked). Отмечается people_status=partial с численностью.
- Тесты: 57 passed.

## Текущее состояние

Проект работоспособен и закрыт по стадии 1 спеки + импорт. Стадия 2 (live-канал людей) осознанно не включена: `linkedin_direct_crawl=blocked`, `licensed_vendor_api=unknown` (docs/access_assessment.md).

## Следующие шаги (при продолжении)

1. Выбрать и проверить лицензированного поставщика данных о сотрудниках → обновить `docs/access_assessment.md` и `source_access`.
2. Пилот поставщика ≤20 записей → коннектор в `PEOPLE_CONNECTORS` → `collect --live`.
3. Пакетный прогон на реальном списке компаний (CSV) через `discover --live`.

## Проверки

- pytest: 40 passed (офлайн).
- `--resume` проверен живым повторным запуском: компания из run 78e05d51 корректно пропущена.
- Живой пилот: см. reports/pilot_dedicateddevelopers.md (фактические URL, статусы, счётчики).
- Контрольный пример: pairs-вывод совпадает с примером заказчика с точностью до документированной канонизации.

## Ограничения

- Live-сбор людей из LinkedIn запрещён (access_assessment); `collect` честно отказывает.
- Список сотрудников компании получить из LinkedIn нельзя: без лицензированного канала `people_status=source_unavailable`/review — это ожидаемое поведение, не сбой.
- Прямой интернет с машины недоступен: только через прокси из `config/config.yaml`.
