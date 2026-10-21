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
- Docker Compose production is not enabled. The local staging API has no IGDB credentials yet; functional integrations and signed-in browser flow still require verification.
- `rclone` and `fail2ban` installed; sshd jail reported enabled. Dedicated `rateapp-deploy` service account created, with an SSH key and forced-command auth verified over localhost. Root-owned dispatch scripts installed, restricted sudoers validated, account removed from the Docker group. The private key is temporarily stored root-only at `/srv/rateapp/secrets/gh_actions_deploy_key` for secure one-time enrollment into the GitHub Actions secret. Never print its contents into chat or logs; remove it from the server after GitHub secret enrollment. Owner's existing password SSH remains enabled.
- PR #39: https://github.com/Soulbadguy54/RateApp/pull/39 ; original CI jobs build, backend tests and mobile E2E passed. Vercel preview deployment had a provisioning error, probably connected to the limit of 10 Neon branches; this does not prove a code failure and no old Neon branches have been deleted.

## First deployment prerequisites
1. Complete VPS security without disabling SSH password login. Set host firewall allowing required 22/80/443, configure SSH rate limiting; add separate deploy SSH key/account and pin host key for Actions. The dedicated deploy account uses a forced SSH command that validates the release SHA, and sudoers permits only the installed root deployment dispatcher. Docker group access is effectively root.
2. Prepare `/srv/rateapp/source` Git checkout and protected `/srv/rateapp/secrets/app.env` with IGDB, VAPID and CRON settings. The API entrypoint creates the local `DATABASE_URL` inside its container using `/run/secrets/postgres_password`; do not copy the Neon URL into `app.env`. Keep secrets out of source control and logs.
3. The current manually created `rateapp-postgres` container must be **stopped/removed by explicit migration procedure** before Compose can own a container of the same name; the named volume must NOT be removed. Preserve the verified `rateapp_stage`.
4. Configure GitHub environment `vps-production` and one repository secret `VPS_DEPLOY_SSH_KEY` (private SSH key securely transferred by owner, never to chat). Host `111.88.215.215`, service account `rateapp-deploy` and verified ED25519 host public key are pinned in the workflow and `deploy/ssh_known_hosts`. Leave repo variable `RATEAPP_VPS_DEPLOY_ENABLED` unset or false until tests pass. Workflow will build GHCR images and SSH to VPS directly; routine deployments do not need Gateway.
5. Before production cutover, take **a fresh** Neon dump under a controlled write freeze. Restore to local `rateapp` DB and compare integrity, extensions, constraints, login, library, collections and PWA. Never have both locations accepting independent writes.
6. Run the full mobile E2E, backend tests, production smoke and HTTPS checks against `r-app.ru`. Configure `RATEAPP_PRODUCTION_URL` GitHub variable to switch smoke target only after cutover. Enable local release alerts only after disabling Vercel Cron to prevent duplicates.

## Independent Google Drive backups
The VPS executes `deploy/scripts/backup-to-gdrive.sh` using PostgreSQL `pg_dump -Fc` and `pg_restore --list` validation. Uploads use **rclone crypt** remote `rateapp-crypt` to encrypt files before they arrive in the owner's Google Drive. Configure rclone Drive OAuth and crypt key locally through protected setup, never by chat or repo commit. Confirm a real download **and restore** test before enabling `deploy/systemd/rateapp-backup.timer`; initial suggested schedule is daily 03:40 UTC. Remote file deletion is not enabled until retention is agreed.

## Rollback
Version-pin API/web GHCR images by tested Git commit. Deploy takes local pre-migration archive and health-checks new release, and may roll back app images if health fails. Database schema is **not** automatically downgraded, because some migration changes are irreversible. Keep prior Vercel and Neon intact until the new site passes user acceptance; session cookies and PWA/push registrations are origin-bound.

## Further verified server preparation
- The systemd unit files for backup and release notifications have been copied to `/etc/systemd/system/` and `daemon-reload` completed. Both timers are **disabled** until Drive OAuth and VAPID/CRON configuration and a recovery drill have been verified.
- The forced SSH command was tested twice. An invalid command failed with exit code 64. A SHA outside the current `main` lineage was rejected with exit code 3, **without deploying**.
- The latest local resource check while all three staging containers ran showed ~1.3 GiB RAM available, 11 MiB swap used, and ~32 GiB disk free. Both the old Vercel endpoint and local staging `/api/health` returned HTTP 200.

## One-time GitHub Actions secret enrollment
1. The owner opens the GitHub repository **Settings → Secrets and variables → Actions** and adds `VPS_DEPLOY_SSH_KEY` containing the complete ED25519 private key from root-only file `/srv/rateapp/secrets/gh_actions_deploy_key`. Retrieve it directly using the owner's private SSH session, not through a chat response or repository file.
2. Verify the action can authenticate with the forced SSH command to `rateapp-deploy@111.88.215.215`. The public server host key is already pinned in `deploy/ssh_known_hosts` (verified server fingerprint `SHA256:JS86gvQKTulRmLSQ1AMp0+OQHcZMxinHnHirk8ryb3k`).
3. Delete the server copy of the GH Actions **private** key only after the Actions secret has been enrolled and validated. Do not delete `authorized_keys`.
4. Continue to leave `RATEAPP_VPS_DEPLOY_ENABLED` unset/false until the supervised production cutover succeeds.
