# CI/CD: from a push to a running deploy

For whoever holds technical responsibility for the deployment. Written the same way as
[recovery-runbook.md](recovery-runbook.md): what happens, what it means, and what to do when it
doesn't.

---

## 0. Orientation

Pushing to the `local` branch runs [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml),
three jobs in sequence:

| Job | Runs on | Does |
|---|---|---|
| `test` | GitHub-hosted | `ruff`, `mypy --strict`, `pytest` (SQLite - no database service needed) |
| `build-and-push` | GitHub-hosted | Builds the image from [`Dockerfile`](../../Dockerfile), pushes it to GHCR tagged `latest` and with the commit SHA |
| `deploy` | **your home server** | Resets its checkout to `origin/local`, pulls the new image, `docker compose up -d` |

A failing `test` job stops everything after it - a broken push never reaches the home server. Only
`local` triggers this; pushes to any other branch build nothing and deploy nothing.

The `deploy` job runs on a **self-hosted GitHub Actions runner** installed on the home server
itself. It polls GitHub over an outbound connection, so nothing on the home server needs to be
reachable from the internet for CI/CD - only Caddy's ports 80/443 are exposed, exactly as before
(ADR 0012).

## 1. One-time setup

Already done once, on the home server, via
[`deploy/setup-home-server-runner.sh`](../../deploy/setup-home-server-runner.sh):

1. Confirmed Docker + the `docker compose` plugin work without `sudo`.
2. Created a permanent checkout of this repo at a fixed path (`DEPLOY_PATH`) with a real `.env`.
3. Registered the machine as a GitHub Actions runner (Settings → Actions → Runners) and installed
   it as a systemd service, so it survives reboots.
4. Set the `DEPLOY_PATH` repository variable (Settings → Secrets and variables → Actions →
   Variables) so the workflow knows where to run `docker compose` on that machine.
5. Ran the same pull-and-restart commands the workflow runs, by hand, once - to catch any problem
   before trusting it to run unattended.

Re-run that script (it's idempotent) if the home server is rebuilt, or to add a second runner.

**The `DEPLOY_PATH` checkout is deploy-only.** The `deploy` job runs `git reset --hard
origin/local` on it every time - never edit files there by hand except `.env`, which is
gitignored and untouched by the reset.

## 2. Registry access

The `deploy` job authenticates to `ghcr.io` automatically, using the same `GITHUB_TOKEN` the
workflow already has - no separate registry credential to manage or rotate.

Pulling the image **by hand** (as in the setup script's dry run, or if you ever debug on the
server directly) doesn't have that token, so either:

- make the package public once it exists (repo page → **Packages** → `fuel-predictor` → Package
  settings → Change visibility) - nothing sensitive is in the image; or
- `docker login ghcr.io` once on the server with a personal access token (`read:packages`).

## 3. Verifying a deploy

```bash
# On GitHub: did the workflow run, and which job (if any) failed?
# https://github.com/Officiel-TinkerThink/fuel-predictor/actions

# On the home server: is the new image actually running?
cd "$DEPLOY_PATH"
docker compose -f compose.prod.yaml images app
docker compose -f compose.prod.yaml logs --tail 50 app
```

`docker compose ... images app` shows the image tag currently running - compare it against the
commit SHA of the push you expect to have deployed.

## 4. Rollback

There is no automatic rollback. To go back to a known-good build:

```bash
cd "$DEPLOY_PATH"
IMAGE_TAG=<previous-good-commit-sha> docker compose -f compose.prod.yaml up -d --no-deps app mlflow monitor
```

Any commit SHA that a `build-and-push` job completed for is still pullable from GHCR (GHCR doesn't
expire tags on its own). Find the SHA from the Actions run history or `git log --oneline` on
`local`.

This only rolls back the **application image** - it does not touch the database or the active
model. If a bad deploy also requires a data rollback, that's
[recovery-runbook.md](recovery-runbook.md), not this.

## 5. Triage

| Symptom | What it means | What to do |
|---|---|---|
| `deploy` job stays queued forever | No runner is online for it to run on | On the home server: `sudo ./svc.sh status` in the runner's install directory; check it's `active (running)` |
| `deploy` job fails at `docker login` | `GITHUB_TOKEN` couldn't authenticate to GHCR | Check the job's `permissions:` block in `deploy.yml` still has `packages: write` on `build-and-push` (read access for `deploy` is implied) |
| `deploy` job fails at `docker compose pull` | The image tag doesn't exist yet, or the package visibility/auth changed | Confirm `build-and-push` actually completed for this commit in the Actions run |
| App comes up but looks like the old version | `git reset --hard` didn't run, or `docker compose up -d` didn't recreate the container | Re-run the `deploy` job's steps by hand on the server (Section 3) and read the output directly |
| Everything green on GitHub, but the site is down | Deploy succeeded; something else broke (bad migration, bad config) | [recovery-runbook.md](recovery-runbook.md) - this is no longer a CI/CD problem |
