# Rate APP

Мобильная игровая библиотека и дневник прохождений (React/Vite PWA + FastAPI + PostgreSQL/Neon + IGDB). Production: https://rateapp-delta.vercel.app/ Репозиторий: https://github.com/Soulbadguy54/RateApp

## Документация — источник контекста между чатами

- [AGENTS.md](AGENTS.md) — что должен прочитать новый чат и как безопасно изменять Rate APP.
- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) — актуальная архитектура, UX, данные, ограничения, маршруты и риски.
- [CHANGELOG.md](CHANGELOG.md) — хронология разработки и PR.
- [docs/DECISIONS.md](docs/DECISIONS.md) — причины архитектурных/продуктовых решений.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — миграции, резервные копии, production smoke.
- [docs/import-audit-2026-10-15.md](docs/import-audit-2026-10-15.md) — исторические импорты, Stash и пропущенные игры.
- [docs/stability-audit-2026-10-16.md](docs/stability-audit-2026-10-16.md) — аудит и непроверенные операционные настройки.

**Правило:** после релевантного изменения обновлять контекст и changelog в том же PR. Не считать документацию автоматически актуальной без сравнения с `main` и production.

## Как устроено

- `src/` — React 19/TypeScript/Vite, мобильный PWA, коллекции, поиск, карточки, четыре оценочных барабана с шагом 0,5.
- `api/` — FastAPI, вход по email/nickname/PIN, библиотека/коллекции, IGDB и Push.
- `api/models.py` — SQLAlchemy с ID, FK, уникальными индексами и проверками.
- `migrations/` — Alembic для PostgreSQL; не запускать DDL при обработке HTTP.
- `e2e/` и `tests/` — мобильные Playwright и backend тесты.

## Локально

`npm ci` · `npm run dev` — фронтенд; `npm run build` — production сборка. Для полного API требуется PostgreSQL и настроенный `DATABASE_URL`: применять `python -m alembic upgrade head` в тестовой/разрешённой среде, затем запускать `python -m uvicorn api.index:app --reload`. Тесты: `python -m unittest discover -s tests -v` и `npm run test:e2e` (последние требуют API+БД и браузеров).

Vercel разворачивает прикладные изменения из `main`. Изменения только Markdown-документации пропускают новый build благодаря `ignoreCommand` в `vercel.json`; правила, тесты и оговорки — [PROJECT_CONTEXT](docs/PROJECT_CONTEXT.md).
