# RateApp: safe schema changes and deploys

## Required order

1. Back up the production PostgreSQL database (and verify restore).
2. Review migration SQL on a copied/staging database containing historical rows.
3. Apply migrations with production DATABASE_URL: `python -m alembic upgrade head`.
4. Run `GET /api/health`; require HTTP 200 and `database.reachable=true`.
5. Deploy the application, check startup/login/library/collections with smoke tests.

**Never** invoke migration code inside the FastAPI app import/startup path.
Run migrations from a protected CI job with an authorized secret, or a trusted
DB admin machine. Keep secrets out of commits and logs. The current Vercel Git
integration deploys on every main push; coordinate migrations *before* commits
that require new columns. Enable branch protection/deployment checks to enforce
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
