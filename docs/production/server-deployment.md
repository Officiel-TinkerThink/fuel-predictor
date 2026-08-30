# Server Deployment Guide

Step-by-step first deployment of Fuel Predictor onto your own server. Follow it top to bottom once;
after that, [§10 Updating a running deployment](#10-updating-a-running-deployment) is the loop you
repeat.

This guide is for standing the system **up**. When something is already up and has gone wrong, use
the [recovery runbook](recovery-runbook.md) instead — it is symptom-first and assumes the
deployment exists.

Decisions this guide implements are recorded in
[ADR 0012](../adr/0012-https-gateway-and-encrypted-backup.md) (HTTPS gateway and encrypted backup)
and [ADR 0011](../adr/0011-production-mlflow-topology.md) (MLflow topology). Read those if you want
to know *why* before you change anything here.

---

## 0. What you are deploying

Five containers on one VM, defined by [`compose.prod.yaml`](../../compose.prod.yaml):

| Service | Role |
|---|---|
| `caddy` | The only service that publishes ports (80, 443/tcp, 443/udp). Terminates TLS, obtains and renews Let's Encrypt certificates automatically, sets the security headers. |
| `app` | FastAPI application. Runs `alembic upgrade head` on start, then uvicorn. |
| `db` | PostgreSQL 16. |
| `mlflow` | MLflow tracking server, backed by SQLite on a volume. |
| `monitor` | Recomputes monitoring and delivers alerts once a day. Ships with the deployment so it cannot be forgotten. |

Only `caddy` is reachable from the internet. The application, the database, and MLflow live on the
internal Compose network and have no host port at all.

> **Do not turn `compose.prod.yaml` into an overlay** (`-f compose.yaml -f compose.prod.yaml`).
> Compose *merges* `ports` lists and cannot unpublish a port an earlier file published, so an
> overlay would leave the app and MLflow listening on the host, bypassing TLS entirely. The
> duplication between the two files is deliberate.

---

## 1. Requirements

- A Linux VM you control. 2 vCPU / 4 GB RAM is comfortable; 2 GB works but MLflow training will be
  tight. 20 GB disk minimum — model packages are retained for rollback and accumulate.
- **Docker Engine and the Compose plugin** installed.
- **Ports 80 and 443 open** inbound. Port 80 is not optional: Let's Encrypt's HTTP-01 challenge
  uses it, and Caddy will not get a certificate without it.
- **A domain name** with an A record pointing at this VM's public IP. Certificate issuance fails
  without it, and there is no way around that.
- SSH access.

Verify Docker before going further:

```bash
docker --version && docker compose version
```

---

## 2. Point DNS at the VM first

Create an A record for your domain (e.g. `fuel.example.com`) pointing at the VM's public IP, and
**wait for it to resolve** before you start the stack:

```bash
dig +short fuel.example.com
```

That must print your VM's IP. If you start Caddy before DNS resolves, it will fail to get a
certificate and retry — and repeated failures count against
[Let's Encrypt's rate limits](https://letsencrypt.org/docs/rate-limits/), which can lock you out
for hours. DNS first, always.

---

## 3. Get the code onto the server

```bash
git clone https://github.com/Officiel-TinkerThink/fuel-predictor.git
cd fuel-predictor
git checkout production-plan
```

`production-plan` is the branch carrying the production work. `main`, `develop`, and `local` are
currently behind it.

---

## 4. Write the `.env` file

```bash
cp .env.example .env
```

Then edit `.env`. Every variable is documented in the file itself; these are the ones a production
deployment **must** set.

### Required

| Variable | Value |
|---|---|
| `POSTGRES_PASSWORD` | A long random password. Generate it, do not invent it: `openssl rand -base64 32` |
| `DOMAIN` | The domain from §2, e.g. `fuel.example.com`. No scheme, no trailing slash. |
| `ACME_EMAIL` | A real address you read. Let's Encrypt sends expiry warnings here. |
| `FUEL_PREDICTOR_BOOTSTRAP_ADMIN_USERNAME` | The first administrator's username. |
| `FUEL_PREDICTOR_BOOTSTRAP_ADMIN_PASSWORD` | Its password. Also generated, also long. |

### Required, and easy to get wrong

| Variable | Value |
|---|---|
| `FUEL_PREDICTOR_ALLOW_UNPROVISIONED_ACCESS` | **`false`.** True means "an empty users table serves everyone as an administrator" — the local-MVP behaviour. `compose.prod.yaml` pins it to `false` regardless, so this is belt and braces, but leave it false in `.env` too. |
| `FUEL_PREDICTOR_FORWARDED_ALLOW_IPS` | Restricts which upstream may set `X-Forwarded-For`/`-Proto`. `.env.example` ships `*`, which is fine only because nothing but Caddy can reach the app container. If you ever expose the app port, or put a different proxy in front, set this to that proxy's address — otherwise any client can forge its own source address and poison the audit trail and the rate limiter. |
| `FUEL_PREDICTOR_MCP_PRIVILEGED_TOOLS_ENABLED` | **Leave `false` for now.** These tools let an agent activate and roll back models. They are implemented, tested, and audited, but the security review of that surface has not happened yet. See [§9](#9-optional-agent-mcp-access). |

### Recommended

| Variable | Value |
|---|---|
| `FUEL_PREDICTOR_ALERT_WEBHOOK_URL` | Where monitoring alerts go. Without this or SMTP, alerts are recorded in the database and shown on the Kesehatan Sistem page but nothing reaches you. |
| `FUEL_PREDICTOR_ALERT_SMTP_*`, `FUEL_PREDICTOR_ALERT_EMAIL_*` | Email alert delivery, as an alternative or an addition to the webhook. |
| `FUEL_PREDICTOR_GOOGLE_MAPS_API_KEY` | Distance lookup for stop sequences. Without it the application falls back to operator-entered manual distance and says so on screen — it degrades honestly rather than silently. |
| `BACKUP_AGE_RECIPIENT`, `BACKUP_RCLONE_REMOTE` | See [§7](#7-set-up-encrypted-backups). Skip only if you accept that the VM dying loses everything. |

Lock the file down — it holds the database password and the bootstrap admin password:

```bash
chmod 600 .env
```

---

## 5. Start the stack

```bash
docker compose -f compose.prod.yaml up -d --build
```

The first build takes several minutes. `app` waits for `db` and `mlflow` to report healthy, then
runs `alembic upgrade head` before uvicorn starts, so migrations are applied automatically on this
and every subsequent start.

Watch it come up:

```bash
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs -f caddy app
```

Caddy requests the certificate on the first inbound request. Give it a few seconds after the first
`https://` hit, then check the logs for a certificate-obtained line.

---

## 6. Verify the deployment

Run all five. Each one catches a different real failure mode.

**1. Only the gateway publishes ports.** This is the check that catches the overlay mistake from
§0:

```bash
docker compose -f compose.prod.yaml config | grep -c published
```

Must print `3` — 80, 443/tcp, 443/udp, and nothing else. Any other number means the application or
MLflow is exposed on the host.

**2. TLS works and the headers are set:**

```bash
curl -sSI https://fuel.example.com/sehat
```

Expect `200`, plus `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, and no `Server` header.

**3. HTTP redirects to HTTPS:**

```bash
curl -sSI http://fuel.example.com/ | head -1
```

Expect a `308`.

**4. The application is not reachable except through the gateway.** From your laptop, not the VM:

```bash
curl -sS --max-time 5 http://fuel.example.com:8000/sehat
```

This must **fail to connect**. If it answers, something is publishing the app port.

**5. Sign in.** Open `https://fuel.example.com/` in a browser and sign in with the bootstrap
administrator. You should land on the overview dashboard.

---

## 7. Set up encrypted backups

The design is deliberate: backups are encrypted to an `age` **public** key whose private half never
touches this VM. A compromised server cannot read its own backup history.
[`deploy/backup.sh`](../../deploy/backup.sh) dumps PostgreSQL *and* archives the retained model
packages — a database backup without them restores to a state that cannot roll back, because
rollback needs the target model's bytes.

**On your own machine, not the server**, generate the key pair:

```bash
age-keygen -o fuel-backup-key.txt
```

Keep `fuel-backup-key.txt` somewhere safe and off the VM — a password manager, an encrypted drive.
**If you lose it, every backup is unreadable.** Copy only the public key (the `age1…` line printed
as `Public key:`) into the server's `.env` as `BACKUP_AGE_RECIPIENT`.

Configure an `rclone` remote for off-VM storage (S3, Backblaze B2, a different provider than the
one hosting this VM — a backup on the same provider is not an off-site backup):

```bash
rclone config
```

Set `BACKUP_RCLONE_REMOTE` in `.env` to that destination, e.g. `s3remote:fuel-backups`.

Run one backup by hand and confirm it lands:

```bash
docker compose -f compose.prod.yaml exec app deploy/backup.sh
```

Retention is 7 daily, 4 weekly, 3 monthly, pruned automatically. Pruning never fails a backup: a
copy that uploaded fine is not reported failed because an old one could not be deleted.

Then schedule it, on the host:

```bash
sudo crontab -e
```

```
15 3 * * * cd /path/to/fuel-predictor && docker compose -f compose.prod.yaml exec -T app deploy/backup.sh >> /var/log/fuel-backup.log 2>&1
```

The script's exit code is the signal that the backup failed. The outcome is *also* recorded in the
database by `python -m fuel_predictor record-backup`, which is why the Kesehatan Sistem page can
show real backup status rather than guessing — the application cannot observe an off-VM upload on
its own, and a reassuring dashboard with no basis would be worse than an empty one.

---

## 8. Rehearse the restore — before you need it

This is the step everyone skips, and skipping it means you do not have backups, you have files.

Do it on a **clean machine**, not the production VM:

```bash
export BACKUP_AGE_KEY_FILE=/secure/path/fuel-backup-key.txt
export BACKUP_RCLONE_REMOTE=s3remote:fuel-backups
export POSTGRES_PASSWORD=...
deploy/restore.sh 20260825T031500Z
```

The script fetches, decrypts, `pg_restore`s with `--clean --if-exists`, unpacks the model packages,
and then prints four checks. Read them. A restore that loads rows but leaves the active model
unloadable is not a successful restore, and the script says so rather than exiting 0 and letting
you believe otherwise.

If you must run a restore on the production VM during a real incident, copy the private key in for
the restore and **remove it afterwards** — leaving it there defeats the entire reason backups are
encrypted to a public key.

---

## 9. Optional: agent (MCP) access

The read-only MCP tools ship enabled: `predict_fuel`, `get_service_health`, `get_drift_summary`,
`get_performance_summary`, `get_current_model`, `list_model_versions`,
`get_prediction_input_schema`. They are proxied through Caddy like any other path and authenticate
with their own bearer token.

Issue a credential at `/integrasi-agen` (requires the `MANAGE_USERS` capability). Every call is
audited and rate-limited per client via `FUEL_PREDICTOR_MCP_MAX_CALLS_PER_WINDOW` and
`FUEL_PREDICTOR_MCP_RATE_LIMIT_WINDOW_SECONDS`.

Verify a client end to end with:

```bash
python scripts/verify-mcp-client.py
```

**The privileged tools** — `validate_model_package`, `activate_model_version`,
`rollback_model_version` — stay off until the security review recorded in [HANDOFF.md
§5](../../HANDOFF.md#5-what-is-open) has been done by someone other than the person who wrote them.
They are gated behind `FUEL_PREDICTOR_MCP_PRIVILEGED_TOOLS_ENABLED` for exactly that reason.

---

## 10. Updating a running deployment

```bash
cd /path/to/fuel-predictor
git pull
docker compose -f compose.prod.yaml up -d --build
```

Migrations run automatically as part of the `app` container's start command, so there is no
separate migration step. Watch it settle:

```bash
docker compose -f compose.prod.yaml logs -f app
```

**Take a backup before an update that includes a migration.** `alembic upgrade head` runs before
uvicorn starts, and if it fails the container restarts in a loop rather than serving a half-migrated
database — recoverable, but only if you have the dump.

Volumes (`postgres_data`, `mlflow_data`, `model_packages`, `caddy_data`, `caddy_config`) survive
`up --build` and `down`. They do **not** survive `down -v`. There is almost never a reason to pass
`-v` here.

---

## 11. After the first successful deployment

Three things are worth doing while the deployment is still fresh:

1. **Remove the bootstrap admin variables from `.env`** once that account exists and you have
   signed in. Leaving them set re-asserts the password on every restart. Nothing will recreate an
   administrator afterwards, which is fine — and it is precisely why
   `FUEL_PREDICTOR_ALLOW_UNPROVISIONED_ACCESS` must stay `false`: a restore predating your accounts
   would otherwise bring the application up wide open rather than locked.
2. **Create the real user accounts** at `/pengguna`, with the narrowest role that fits each person:
   `operator`, `manager`, or `administrator`.
3. **Hand the operator the guide**, not this document:
   [panduan-operator.md](panduan-operator.md) (or the HTML build). It is in Indonesian, has no
   technical commands, and leads with the distinction that matters most — the number on screen is
   fuel *to prepare*, not fuel *consumed*.

Then bookmark the [recovery runbook](recovery-runbook.md). From here on, that is the document you
want at 2am.
