# RateApp: safe schema changes and deploys

## Required order

1. Back up the production PostgreSQL database (and verify restore).
2. Review migration SQL on a copied/staging database containing historical rows.
3. Apply migrations with production DATABASE_URL: `python -m alembic upgrade head`.
4. Run `GET /api/health`; require HTTP 200 and `database.reachable=true`.
5. Deploy the application, check startup/login/library/collections with smoke tests.

**Never** invoke migration code inside the FastAPI app import/startup path.
Run migrations from a protected CI job with an authorized secret, or a trusted
DB admin machine. Keep secrets out of commits and logs. The Vercel Git integration builds code changes on main; documentation-only
commits are skipped by `vercel.json` → `scripts/ignore-docs-build.sh` (the
Vercel Ignored Build Step still creates a canceled/skipped deployment record
and can count against quota). Coordinate migrations *before* commits that
require new columns. Enable branch protection/deployment checks to enforce
this order before future migrations. This first baseline records the existing
production schema; it is compatible with the already-initialized database.

To initialize CI/test database: `python -m alembic upgrade head`.
Do not use `Base.metadata.create_all` as an application startup migration.

## Legacy migration limitation

The first versioned migration delegates to the existing idempotent bootstrap
as an **one-time baseline**. Historical user rows are left unchanged unless
already covered by the audited legacy repair. Further migrations must be
incremental, explicit and independently testable. The database must be
backed up before the initial baseline is marked as applied.

## Production smoke checks
`python scripts/smoke_production.py` checks that the public health endpoint,
auth bootstrapping (unauthenticated 401), deliberately invalid login (401, **not
500**) and private export (401) work. CI runs it after the backend, build and
mobile browser jobs on main. It never sends real user credentials.

## Recovery and backups
- Account users can download their own portable JSON backup under Profile.
- The JSON export is not a database disaster-recovery backup and does not
  contain session credentials.
- Before destructive migrations: take an encrypted provider-managed PostgreSQL
  snapshot; restore the snapshot into a separate staging database and verify
  row counts for users, library, collections, memberships, and scores.
- Enable automated daily snapshots, retention, and point-in-time recovery in
  the PostgreSQL provider. These provider settings cannot be enforced from
  the RateApp source repository alone; verify them in the DB administration
  console and set up failure notifications.
- Do not log auth PINs, raw cookie tokens, personal emails, or exported JSON.
- Optional Sentry: configure `SENTRY_DSN` for server errors and
  `VITE_SENTRY_DSN` for browser errors in Vercel's environment settings.
  Default personal information and request-body uploads are disabled.
- Release gating: protect main and configure Vercel Deployment Checks on
  the CI jobs; Vercel Git integration can otherwise deploy before CI finishes.

## VPS environment and rollback — active production (2026-10-21)

The VPS migration and cutover are described in [VPS_MIGRATION.md](VPS_MIGRATION.md). Active production is https://r-app.ru on local PostgreSQL 18. GitHub Actions deploy is gated on successful main CI and uses the pinned SSH host key + restricted deploy account. Release runs pre-migration local pg_dump, Alembic, containers update and health check; app-image rollback does not downgrade database schema. Daily server-side pg_dump uploads to owner-managed Google Drive at 03:40 UTC, with separate restore validation. Vercel is paused and Neon retained temporarily as an archive/rollback source; neither is on the request path. Never treat a local dump as the sole disaster-recovery copy, drop the persistent PostgreSQL volume, or automatically downgrade a DB schema during image rollback.

## Правило завершения задачи: PR → CI → main → VPS → smoke

Установленный в [AGENTS.md](../AGENTS.md) Definition of Done обязателен и для небольших исправлений, и для документационных изменений. Открытый PR — промежуточный этап, а не итог работы. Исполнитель дожидается всех требуемых проверок PR, исправляет ошибки и после успешного CI сливает PR в `main` без отдельной просьбы, кроме оговорённых исключений.

Затем исполнитель проверяет **фактическое окончание** CI `main` и workflow `VPS production deployment`, сверяет SHA новой версии с `/srv/rateapp/current-release` и выполняет `RATEAPP_SMOKE_BASE=https://r-app.ru python scripts/smoke_production.py`. В случае неудачного деплоя исправляет причину и повторяет цикл; нельзя завершать ответ на «PR готов» или «деплой запущен». Для docs-only изменений, которые не требуют смены исполняемого образа, проверяются обновление `main`, положенные проверки CI и доступность production; пропуск сборки по установленным правилам указывается явно.

Только завершённую и подтверждённую доставку можно называть опубликованной. Если необходимы внешний ручной шаг, отдельное разрешение на опасную операцию, проверка реального устройства либо недоступен инструмент — это явно отмечается как блокер/ограничение, а не маскируется под готовый релиз.

## Staging release flow (`dev.r-app.ru`)

1. Merge reviewed, green PR #44 into `main`, wait for main CI and normal VPS production deployment and smoke. The main deploy installs the audited staging dispatcher only after production health passes.
2. A distinct post-deploy `bootstrap-stage` command runs **once**. It validates the exact deployed `main` SHA, dumps production without modifying it, backs up any existing `rateapp_stage`, creates a limited `rateapp_stage` DB user, restores the snapshot into `rateapp_stage`, removes other users/sessions/push subscriptions *inside stage only*, and writes the initialization marker. Abnormal exit stops the staging rollout; it must never fall back to production DB credentials.
3. Create `develop` based on deployed main and trigger a commit/push. Its full CI runs frontend, backend PostgreSQL and mobile E2E. Successful runs build two new stage-only GHCR images tagged with the exact tested SHA; no stage image is used by production.
4. The restricted SSH command `deploy-stage <40-hex-sha>` accepts only the *current* `develop` HEAD. It deploys via the reviewed Compose file from `main`, makes a stage-only pre-migration dump, migrates only `rateapp_stage`, and verifies API health.
5. Smoke `https://dev.r-app.ru`: valid HTTPS; SPA/mobile; test banner; `/api/health` 200 + DB reachable; anonymous `/api/auth/me` 401; POST `/api/auth/register` 404; login with known owner PIN (requires owner device, do not collect PIN); library/collections; no stage push or cron traffic. Reconfirm `https://r-app.ru` and its API, compare production release SHA with `main`.
6. Further changes: PR into `develop` → CI → staging deploy → acceptance → PR into `main` → full production CI, backup, migration/deploy and smoke. Do not auto-promote a staging feature without acceptance.

### Cautions

- Same VPS/postgres service but **separate databases and roles**. Do not point stage API at the production superuser credentials. Never run stage migrations against `rateapp`.
- Stage data are a *snapshot*, not live-synced. A reset is a destructive operation and requires a fresh approval and stage backup.
- Staging login sessions are new, scoped to `dev.r-app.ru`; no real cookies/tokens move from production. UI/JS can be fetched without login, but private API requires authorization.
- If stage migrations fail, rolling back images cannot revert the schema. Restore the staging backup only after diagnosis and explicit approval.
- DNS A `dev.r-app.ru → 111.88.215.215`, TLS managed by existing Caddy. Staging does not start merely because DNS exists.
