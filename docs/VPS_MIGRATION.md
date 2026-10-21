# VPS migration: Rate APP

**2026-10-21 status: PREPARATION ONLY.** Vercel + Neon remain production. The new deployment job is disabled until explicitly enabled, and no DNS cutover or production database switch has been performed.

## Verified inventory
- VPS `FN_ztv_server`: Ubuntu 24.04, 2 vCPU, ~2 GiB RAM, 40 GB disk, Docker 29, Compose 2.40, 2 GiB swap. SSH password login is deliberately retained by owner request.
- Domain `r-app.ru` and `www.r-app.ru` both resolved to `111.88.215.215` on 2026-10-21. HTTPS and serving the site are not yet active.
- Neon main / neondb PostgreSQL 18.6 is currently production. Pre-migration manual snapshot: `pre-vps-migration-2026-10-21`.
- A custom-format initial archive is saved privately on VPS at `/srv/rateapp/backups/initial/neon-initial.dump`. Validated and restored in **staging** database `rateapp_stage` on container `rateapp-postgres`. Source/restored table counts: 3 users, 1165 games, 251 user_games, 10 collections, 112 collection_games, 6 auth_sessions, 3 push_subscriptions. The active production database was not modified.
- Manual PostgreSQL container stores data in persistent volume `rateapp_pg18_data`; port 5432 is NOT host-published. Initial `rateapp` database is not yet restored from final source.
- Neon production lacked `alembic_version` on audit. Test the legacy Alembic baseline on a restored copy, not by directly altering Neon.

## First deployment prerequisites
1. Complete VPS security without disabling SSH password login. Set host firewall allowing required 22/80/443, configure SSH rate limiting; add separate deploy SSH key/account and pin host key for Actions. Docker group access is effectively root.
2. Prepare `/srv/rateapp/source` Git checkout and protected `/srv/rateapp/secrets/app.env` with local PostgreSQL `DATABASE_URL` and current IGDB / VAPID configuration where enabled. Keep secrets out of source control and logs.
3. The current manually created `rateapp-postgres` container must be **stopped/removed by explicit migration procedure** before Compose can own a container of the same name; the named volume must NOT be removed. Preserve the verified `rateapp_stage`.
4. Configure GitHub environment `vps-production`, secrets `VPS_DEPLOY_SSH_KEY`, `VPS_SSH_KNOWN_HOSTS`, `VPS_HOST`, `VPS_SSH_USER`. Leave repo variable `RATEAPP_VPS_DEPLOY_ENABLED` unset or false until tests pass. Workflow will build GHCR images and SSH to VPS directly; routine deployments do not need Gateway.
5. Before production cutover, take **a fresh** Neon dump under a controlled write freeze. Restore to local `rateapp` DB and compare integrity, extensions, constraints, login, library, collections and PWA. Never have both locations accepting independent writes.
6. Run the full mobile E2E, backend tests, production smoke and HTTPS checks against `r-app.ru`. Configure `RATEAPP_PRODUCTION_URL` GitHub variable to switch smoke target only after cutover. Enable local release alerts only after disabling Vercel Cron to prevent duplicates.

## Independent Google Drive backups
The VPS executes `deploy/scripts/backup-to-gdrive.sh` using PostgreSQL `pg_dump -Fc` and `pg_restore --list` validation. Uploads use **rclone crypt** remote `rateapp-crypt` to encrypt files before they arrive in the owner's Google Drive. Configure rclone Drive OAuth and crypt key locally through protected setup, never by chat or repo commit. Confirm a real download **and restore** test before enabling `deploy/systemd/rateapp-backup.timer`; initial suggested schedule is daily 03:40 UTC. Remote file deletion is not enabled until retention is agreed.

## Rollback
Version-pin API/web GHCR images by tested Git commit. Deploy takes local pre-migration archive and health-checks new release, and may roll back app images if health fails. Database schema is **not** automatically downgraded, because some migration changes are irreversible. Keep prior Vercel and Neon intact until the new site passes user acceptance; session cookies and PWA/push registrations are origin-bound.
