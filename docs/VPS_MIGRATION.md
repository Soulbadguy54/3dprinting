# VPS migration: Rate APP

**2026-10-21 status: PREPARATION ONLY.** Vercel + Neon remain production. The new deployment job is disabled until explicitly enabled, and no DNS cutover or production database switch has been performed.

## Verified inventory
- VPS `FN_ztv_server`: Ubuntu 24.04, 2 vCPU, ~2 GiB RAM, 40 GB disk, Docker 29, Compose 2.40, 2 GiB swap. SSH password login is deliberately retained by owner request.
- Domain `r-app.ru` and `www.r-app.ru` both resolved to `111.88.215.215` on 2026-10-21. HTTPS and serving the site are not yet active.
- Neon main / neondb PostgreSQL 18.6 is currently production. Pre-migration manual snapshot: `pre-vps-migration-2026-10-21`.
- A custom-format initial archive is saved privately on VPS at `/srv/rateapp/backups/initial/neon-initial.dump`. Validated and restored in **staging** database `rateapp_stage` on container `rateapp-postgres`. Source/restored table counts: 3 users, 1165 games, 251 user_games, 10 collections, 112 collection_games, 6 auth_sessions, 3 push_subscriptions. The active production database was not modified.
- Manual PostgreSQL container stores data in persistent volume `rateapp_pg18_data`; port 5432 is NOT host-published. Initial `rateapp` database is not yet restored from final source.
- Neon production lacked `alembic_version` on audit. Test the legacy Alembic baseline on a restored copy, not by directly altering Neon.

## Local staging validation (2026-10-21)
- Docker images for API and web built successfully from feature branch; Caddy configuration validated.
- Containers `rateapp-api-stage` and `rateapp-web-stage` run on internal Docker network; stage web is exposed **only** on loopback `127.0.0.1:18080`. API connects to `rateapp_stage`. HTTP main page 200, /api/health 200 with DB reachable, anonymous /api/bootstrap 401, export 401, invalid login 401. Full read-only/invalid-login smoke PASS.
- Alembic revision `20261016_01` applied **only to restored `rateapp_stage`**, with row counts unchanged and healthy API afterwards. Neon production remains untouched.
- Docker Compose production is not enabled. On October 21, the owner placed IGDB ID and refreshed secret into the protected Gateway value `rateapp-app-env`. They were merged into root-owned `/srv/rateapp/secrets/app.env` with an independently generated matching VAPID P-256 key pair and a random CRON_SECRET; the temporary Gateway-import file was removed. All five keys are present without being logged. The staging API was restarted with this environment: /api/health HTTP 200, database reachable, IGDB configured; Twitch OAuth `client_credentials` returned HTTP 200 and the local VAPID public/private match was checked cryptographically. No IGDB/VAPID/cron secrets are in GitHub. Signed-in browser and real push delivery remain to be verified.
- `rclone` and `fail2ban` installed; sshd jail reported enabled. Dedicated `rateapp-deploy` service account created, with an SSH key and forced-command auth verified over localhost. Root-owned dispatch scripts installed, restricted sudoers validated, account removed from the Docker group. The owner's GitHub Actions secret `VPS_DEPLOY_SSH_KEY` was verified on an actual GitHub-hosted runner (success: https://github.com/Soulbadguy54/RateApp/actions/runs/39576778292). The temporary private key file `/srv/rateapp/secrets/gh_actions_deploy_key` was **deleted from the VPS** after verification; the public key remains authorized. No private keys were displayed in chat or stored in the repository. Owner's existing password SSH remains enabled.
- PR #39: https://github.com/Soulbadguy54/RateApp/pull/39 ; original CI jobs build, backend tests and mobile E2E passed. Vercel preview deployment had a provisioning error, probably connected to the limit of 10 Neon branches; this does not prove a code failure and no old Neon branches have been deleted.

## First deployment prerequisites
1. Complete VPS security without disabling SSH password login. Set host firewall allowing required 22/80/443, configure SSH rate limiting; add separate deploy SSH key/account and pin host key for Actions. The dedicated deploy account uses a forced SSH command that validates the release SHA, and sudoers permits only the installed root deployment dispatcher. Docker group access is effectively root.
2. Prepare `/srv/rateapp/source` Git checkout and protected `/srv/rateapp/secrets/app.env` with IGDB, VAPID and CRON settings. The API entrypoint creates the local `DATABASE_URL` inside its container using `/run/secrets/postgres_password`; do not copy the Neon URL into `app.env`. Keep secrets out of source control and logs.
3. The current manually created `rateapp-postgres` container must be **stopped/removed by explicit migration procedure** before Compose can own a container of the same name; the named volume must NOT be removed. Preserve the verified `rateapp_stage`.
4. Configure GitHub environment `vps-production` and one repository secret `VPS_DEPLOY_SSH_KEY` (private SSH key securely transferred by owner, never to chat). Host `111.88.215.215`, service account `rateapp-deploy` and verified ED25519 host public key are pinned in the workflow and `deploy/ssh_known_hosts`. Leave repo variable `RATEAPP_VPS_DEPLOY_ENABLED` unset or false until tests pass. Workflow will build GHCR images and SSH to VPS directly; routine deployments do not need Gateway.
5. Before production cutover, take **a fresh** Neon dump under a controlled write freeze. Restore to local `rateapp` DB and compare integrity, extensions, constraints, login, library, collections and PWA. Never have both locations accepting independent writes.
6. Run the full mobile E2E, backend tests, production smoke and HTTPS checks against `r-app.ru`. Configure `RATEAPP_PRODUCTION_URL` GitHub variable to switch smoke target only after cutover. Enable local release alerts only after disabling Vercel Cron to prevent duplicates.

## Autonomous plain Google Drive backups (owner choice, 2026-10-21)
The owner explicitly chose **not** to enable `plain Drive` at this stage. The data includes account emails, hashed PINs, and session metadata; Google Drive backups will be stored without separate end-to-end archive encryption. Keep the Google account private, never share the backup folder publicly, and preserve a separately accessible disaster-recovery copy.

The rclone Drive remote `rateapp-drive:` was authorized through personal Google OAuth on the VPS and its root folder listing succeeded. Script `deploy/scripts/backup-to-gdrive.sh` uses `pg_dump -Fc`, checks `pg_restore --list`, uploads to `rateapp-drive:RateApp/backups`, then downloads a stream to validate SHA-256. The timer is designed for 03:40 UTC daily on the VPS; there is no automated deletion of backups in Drive. Use `RATEAPP_BACKUP_DB=rateapp_stage RATEAPP_BACKUP_SUBDIR=staging` to test safely before production. Perform a full restore test of the uploaded backup before enabling the timer.

## Rollback
Version-pin API/web GHCR images by tested Git commit. Deploy takes local pre-migration archive and health-checks new release, and may roll back app images if health fails. Database schema is **not** automatically downgraded, because some migration changes are irreversible. Keep prior Vercel and Neon intact until the new site passes user acceptance; session cookies and PWA/push registrations are origin-bound.

## Further verified server preparation
- The systemd unit files for backup and release notifications have been copied to `/etc/systemd/system/` and `daemon-reload` completed. Both timers are **disabled** until Drive OAuth, backup recovery drill, and the production cutover have been verified. VAPID/CRON secret material exists on the VPS; release notifications must not run alongside the old Vercel cron.
- The forced SSH command was tested twice. An invalid command failed with exit code 64. A SHA outside the current `main` lineage was rejected with exit code 3, **without deploying**.
- The latest local resource check while all three staging containers ran showed ~1.3 GiB RAM available, 11 MiB swap used, and ~32 GiB disk free. Both the old Vercel endpoint and local staging `/api/health` returned HTTP 200.

## One-time GitHub Actions secret enrollment
1. **Completed:** the owner added repository secret `VPS_DEPLOY_SSH_KEY` to GitHub Actions. An authenticated probe from GitHub's runner succeeded, and the temporary private SSH key file on the VPS was removed. The public key remains in `authorized_keys`.
2. Server host key is pinned in `deploy/ssh_known_hosts` (fingerprint `SHA256:JS86gvQKTulRmLSQ1AMp0+OQHcZMxinHnHirk8ryb3k`). Dedicated account accepts only restricted deploy commands.
3. Leave `RATEAPP_VPS_DEPLOY_ENABLED` unset/false until the supervised production cutover. A successful authentication probe does **not** certify the full deployment procedure. On any key loss, generate and enroll a **new** key pair; do not expect to recover the deleted VPS private key.
