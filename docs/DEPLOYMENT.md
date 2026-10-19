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
