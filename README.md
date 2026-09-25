# company-people-collector

Поиск **LinkedIn-страницы компании** по её сайту и импорт **разрешённых** данных о людях (полное имя + ссылка на профиль). Реализация спецификации [docs/spec.md](docs/spec.md).

## Что делает и чего не делает

- **discover**: вежливый обход сайта компании (главная + about/contact/team в лимитах, robots.txt с редиректами, паузы) → каноническая ссылка `linkedin.com/company/<slug>` со страницей-источником; при нескольких кандидатах — честный `ambiguous`. Заодно собирает людей, которых компания сама публикует на своём сайте (team/about): ссылки `/in/` + имя из текста ссылки (`source_type=company_site`, `confidence=medium`). Поддерживает `--website-column` для колонок вроде `сайт`.
- **import-people**: импорт CSV/JSONL с подтверждёнными правами (`website_url|company_linkedin_url, profile_url, full_name[, affiliation, source_url]`); без подтверждённой текущей связи запись получает `confidence=review`.
- **collect**: живой сбор людей. Работает канал `linkedin_public` — публичные guest-страницы компаний LinkedIn (видимые карточки секции «Employees at»: ссылка + имя; решение владельца с задокументированным ToS-риском, без логина/cookies/обхода блокировок — [docs/access_assessment.md](docs/access_assessment.md)). Полный список сотрудников остаётся за логином, поэтому статус канала всегда `partial` с численностью: `company-people collect --input base.csv --website-column сайт --source linkedin_public --live`.
- **enrich**: обогащение базы компаний — строка компании копируется по одному на каждого сотрудника, в конец добавляются колонки `employee_profile_url` и `employee_full_name`; можно сразу передать файл людей (`--people`) для импорта. Пример: `uv run company-people enrich --input base.csv --people people.csv --source-label vendor --output enriched.csv`.
- **export**: `people.csv` (UTF-8 BOM), `people.jsonl`, `review.jsonl`, `companies.jsonl`, компактный `--format pairs`.
- Не собирает email/телефоны/фото, не обходит логин, CAPTCHA и блокировки, не ротирует прокси/аккаунты, не отправляет сообщения.

## Быстрый старт

```powershell
cd company-people-collector
uv sync            # окружение .venv
uv run company-people doctor
uv run company-people doctor --website https://dedicateddevelopers.com/
uv run company-people discover --input examples/companies.example.csv --dry-run
uv run company-people discover --input examples/companies.example.csv --live
uv run company-people import-people --input examples/licensed_people.example.csv --source-label customer_example
uv run company-people export --format pairs --include-review
uv run company-people export --format csv            # data/exports/people.csv + companies.jsonl + review.jsonl
```

Конфигурация: скопируйте `config/config.example.yaml` → `config/config.yaml` (защитные лимиты, User-Agent с контактом).

## Выход

`people.csv` (порядок колонок фиксирован):

```
input_website_url,company_linkedin_url,profile_url,full_name,source_url,source_type,affiliation_evidence,observed_at,confidence
```

- `profile_url` — канонический: `?trk=...` и фрагменты удалены (исходный URL хранится в БД в `company_people.profile_url_raw`); локализованные хосты (`co.linkedin.com`) сохраняются.
- `confidence`: `high` (лицензированный источник + подтверждённая текущая связь), `medium` (разрешённый LinkedIn-канал), `review` (связь не подтверждена — попадает в `review.jsonl`, в основном экспорте только с `--include-review`).
- `companies.jsonl` — статус каждой компании, включая нулевые результаты и причины остановки.

## Хранение и удаление

SQLite `data/collector.db`: `runs, companies, company_candidates, people, company_people, observations, source_access`. Удаление данных компании по запросу:

```powershell
uv run company-people purge --website-key dedicateddevelopers.com
```

## Границы (важно)

- Список сотрудников нельзя «дозапросить» из LinkedIn: `people_status=source_unavailable` — честный статус, пока не выбран лицензированный канал.
- `complete_available_pages` означает конец разрешённой доступной выдачи, а не «все сотрудники».
- Тесты: `uv run pytest -q` (офлайн, без сети).
