# Пилот: dedicateddevelopers.com (стадия discover)

Дата: 2026-09-25 · Запуск: `uv run company-people discover --input examples/companies.example.csv --live` · run_id `78e05d51`

## Условия

- Прокси: `http://127.0.0.1:10809` (явно в `config/config.yaml`; env-переменные прокси в системе продублированы и не читаются, `trust_env=False`).
- User-Agent: `company-people-collector/0.1 (research; contact: gleb@hyeta.local)`.
- Лимиты: ≤5 страниц на сайт, ≥3 с между запросами, бюджет ≤100 запросов.
- robots.txt: HTTP 200, статус `ok`, обход для нашего UA разрешён (Disallow только `/wp-admin/`, `/wp-login.php`, `/cgi-bin/`, `/trackback/` — не пересекаются с маршрутом).

## Результат

| Параметр | Значение |
|---|---|
| Статус | `found` |
| Страница компании LinkedIn | `https://www.linkedin.com/company/dedicateddevelopers` |
| Страницы-источники ссылки | `/` , `/about-us/`, `/contact-us/` (3 страницы, один уникальный кандидат) |
| Кандидатов всего | 1 (дублей одной ссылки с разных страниц не создал) |
| Запросов сделано | 4 (robots.txt + 3 страницы) |
| Причина остановки | нет: исчерпана очередь приоритетных страниц |

## Выводы по пилоту

1. Обход сайта компании и извлечение `/company/`-ссылки работают на реальном WordPress-сайте: ссылка продублирована в подвале нескольких страниц, дедупликация по каноническому URL даёт одного кандидата → `found` без ручного решения.
2. Политика robots/рейт-лимит не мешала; задержки не потребовались сверх минимальных.
3. Прямое сетевое соединение с этой машины не работает (таймауты) — обязателен явный прокси в конфиге; задокументировано в README/config.
4. Ссылки `/in/...` на страницах сайта в кандидаты компании не попадают (проверено юнит-тестами).

## Демо-импорт (стадия import)

`import-people --input examples/licensed_people.example.csv --source-label customer_example` → 4/4 записи, 0 дубликатов, 0 отклонённых; все получили `confidence=review` (текущая связь с компанией не подтверждена примером) и вошли в `people.csv` только с `--include-review`; `companies.jsonl` отражает `people_count=4`.

Живой сбор профилей людей из LinkedIn не выполнялся: `linkedin_direct_crawl = blocked` (docs/access_assessment.md).
