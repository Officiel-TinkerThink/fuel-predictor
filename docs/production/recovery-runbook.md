# Recovery Runbook

For whoever holds technical responsibility for the deployment. The operator-facing counterpart is
[Panduan Operator](panduan-operator.md); nothing in this file is an operator's job.

Written to be usable at 2am by someone who did not build this. Every section states **what you
will see**, **what it means**, and **what to do**, in that order.

---

## 0. Orientation

Production runs from [`compose.prod.yaml`](../../compose.prod.yaml) on a single VM:

| Service | Purpose | Published? |
|---|---|---|
| `caddy` | TLS termination, automatic Let's Encrypt renewal | **Yes** — 80, 443 |
| `app` | The application | No — internal network only |
| `db` | PostgreSQL | No |
| `mlflow` | Baseline training/tracking (ADR 0011: removed once ingestion reaches parity) | No |
| `monitor` | Daily monitoring recompute and alert delivery | No |

Only Caddy is reachable from outside. Verify after any change:

```bash
docker compose -f compose.prod.yaml config | grep -c published
```

Three published entries are expected — 80, 443 tcp, 443 udp. Anything more means something is
exposed that should not be.

---

## 1. Triage — start here

```bash
docker compose -f compose.prod.yaml ps
```

| Symptom | Go to |
|---|---|
| A container is restarting or exited | [§2 Service down](#2-service-down) |
| All up, but HTTPS fails | [§3 TLS and gateway](#3-tls-and-gateway) |
| App up, predictions fail | [§4 No active model](#4-no-active-model) |
| Predictions wrong since an activation | [§5 Roll back a model](#5-roll-back-a-model) |
| "Kedaluwarsa" on Kesehatan Sistem | [§6 Monitoring stopped](#6-monitoring-stopped) |
| No alerts arriving | [§7 Alerts not delivering](#7-alerts-not-delivering) |
| Data loss or corruption | [§8 Restore from backup](#8-restore-from-backup) |
| Credential leaked | [§9 Revoke agent credentials](#9-revoke-agent-credentials) |

---

## 2. Service down

```bash
docker compose -f compose.prod.yaml logs --tail=100 app
```

**`alembic upgrade head` failed.** The app runs migrations at startup, so a failed migration means
it never starts. Read the actual error — do not re-run blindly. If a migration partially applied,
restore ([§8](#8-restore-from-backup)) rather than hand-editing `alembic_version`.

**Database unreachable.** `db` is likely unhealthy:

```bash
docker compose -f compose.prod.yaml logs --tail=50 db
docker compose -f compose.prod.yaml exec db pg_isready -U fuel_predictor
```

Disk full is the usual cause. Check `df -h`. Retained model packages and PostgreSQL WAL are the
things that grow.

> **Do not `docker compose down -v`.** The `-v` removes volumes, which deletes the database and
> every retained model package. `down` without `-v` is safe.

---

## 3. TLS and gateway

```bash
docker compose -f compose.prod.yaml logs --tail=100 caddy
```

**Certificate not issued.** Almost always one of:
- `DOMAIN` in `.env` does not resolve to this VM's public IP;
- port 80 is blocked upstream (Let's Encrypt needs it for the HTTP-01 challenge);
- Let's Encrypt rate limit hit from repeated redeploys.

Rate limits are why `caddy_data` is a volume. If you removed it, certificates are re-requested from
scratch. Wait out the limit rather than looping.

**Using an existing proxy instead of Caddy.** Remove the `caddy` service, point the existing proxy
at `app:8000`, and make sure it sets `X-Forwarded-Proto` and `X-Forwarded-For`. Set
`FUEL_PREDICTOR_FORWARDED_ALLOW_IPS` to that proxy's address — leaving it `*` lets any client
forge its own source address, which poisons the audit trail.

---

## 4. No active model

Symptom: predictions return `Belum ada kandidat baseline terlatih untuk membuat prediksi.`

The app serves from an in-process holder once a package is activated, and falls back to the MLflow
baseline store until then (ADR 0011). Both being empty produces this message.

1. Open **Pengelolaan Model**. If a candidate is listed, activate it.
2. If none is listed, either upload a package (**Unggah Model**) or train a baseline from a
   historical dataset.
3. If a candidate *is* active but predictions still fail, its retained bytes may be gone:

```bash
docker compose -f compose.prod.yaml exec app ls /data/model-packages
```

An active version with no directory here cannot be loaded. Restore the model archive
([§8](#8-restore-from-backup)).

---

## 5. Roll back a model

Activation runs an ordered sequence: load, warm, smoke-test, persist under optimistic concurrency,
swap, health-check (ADR 0010).

**A failure before the swap leaves the previous model active and loaded.** Nothing to do.

**A failure after the swap is reported loudly and never silently reverted** — the new model is
already serving. To go back:

1. **Pengelolaan Model** → activate the previous known-good version.
2. Confirm on **Ringkasan** that the active version is the one you expect.
3. Make one test prediction and sanity-check the number.

Rollback needs the target's bytes to still exist. This is why retention is a correctness concern
and not disk hygiene: never prune `/data/model-packages` by hand.

Every activation and rollback writes an audit record — check **Audit** to confirm what happened
and who did it.

---

## 6. Monitoring stopped

`Kedaluwarsa` means no successful monitoring run within `FUEL_PREDICTOR_MONITORING_STALE_AFTER_HOURS`
(default 26).

```bash
docker compose -f compose.prod.yaml logs --tail=50 monitor
docker compose -f compose.prod.yaml run --rm monitor python -m fuel_predictor monitor --trigger manual
```

Exit code 0 means it recovered. Non-zero prints a readable reason.

> **Known limitation.** Nothing inside this deployment can detect that the `monitor` service
> stopped running altogether — a dead-man's-switch has to live outside the thing it watches. If you
> need that guarantee, have an external uptime monitor check the deployment daily. The non-zero
> exit code is the hook for it.

---

## 7. Alerts not delivering

Alerts fire only when the picture **changes** — a new alert, a severity change, or one that
cleared. Silence during an unchanged, ongoing problem is correct behaviour, not a fault.

```bash
docker compose -f compose.prod.yaml logs monitor | grep -i peringatan
```

| Log line | Meaning |
|---|---|
| `Peringatan terkirim: …` | Delivered. |
| `Peringatan tidak terkirim: saluran pemberitahuan belum dikonfigurasi.` | No channel set. Nobody is being told. |
| `Peringatan tidak terkirim (pengiriman gagal): …` | Channel configured but failing. Retries next run. |

Nothing is recorded as sent on failure, so a fixed channel delivers the backlog rather than
starting clean. Configure `FUEL_PREDICTOR_ALERT_WEBHOOK_URL`, or the SMTP variables, in `.env`.

---

## 8. Restore from backup

An untested backup is not a backup. Rehearse this on a clean machine — do not let the first
attempt be during an incident.

```bash
export POSTGRES_PASSWORD=...           # the fuel_predictor role's password
export BACKUP_RCLONE_REMOTE=...        # same remote the backup job writes to
export BACKUP_AGE_KEY_FILE=/path/to/age.key   # the PRIVATE key, held off the VM

rclone lsf --dirs-only "$BACKUP_RCLONE_REMOTE/daily"
deploy/restore.sh 20260825T031500Z
```

The script fetches, decrypts, `pg_restore`s with `--clean --if-exists`, and unpacks the model
packages. It then prints the four checks that decide whether the restore actually worked — run
them. A restore that loads rows but leaves the active model unloadable is not a successful restore.

**The private key must not live on the production VM.** Backups are encrypted to a public key
precisely so a compromised VM cannot decrypt its own history. If you copy the key in for an
emergency restore, remove it afterwards.

Retention is 7 daily, 4 weekly, 3 monthly. Pruning never fails a backup: a copy that uploaded fine
must not be reported failed because an old one could not be deleted.

---

## 9. Revoke agent credentials

**Integrasi Agen** → **Cabut** on the affected client. Effective immediately; the next MCP call
gets 401.

Each client has its own credential and scopes, so revoking one does not disturb the others. A
revoked credential and a nonsense one are refused identically, so probing cannot distinguish them.

Issue a replacement with the narrowest scopes that still do the job. The raw token is shown **once**
— only its hash is stored, so a lost credential is reissued, never recovered.

Check **Audit** for what that credential did: every MCP call is recorded with caller, tool, and
outcome.

---

## 10. Routine checks

| When | Check |
|---|---|
| Daily | Kesehatan Sistem shows a recent monitoring success and a recent backup success. |
| Weekly | `df -h` — retained packages and WAL grow. |
| Monthly | Restore rehearsal ([§8](#8-restore-from-backup)) on a clean machine. |
| Monthly | Review **Integrasi Agen**; revoke credentials nobody uses. |
| Per release | `docker compose -f compose.prod.yaml config \| grep -c published` still returns 3. |
