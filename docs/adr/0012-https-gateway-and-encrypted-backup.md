# ADR 0012: Terminate HTTPS at Caddy and back up encrypted dumps to object storage

## Status

Accepted

## Context

The plan requires one maintained HTTPS entry point with automatic certificate renewal, and daily
encrypted backups copied off the VM with a rehearsed restore. It deliberately leaves the specific
gateway and backup destination open, because a VM that already has a managed proxy should keep it.

This project has to pick a default that works on a bare VM, because that is what the operator will
actually be handed.

## Decision

### HTTPS

Add Caddy to `compose.yaml` as the default public entry point, terminating TLS and reverse-proxying
to the application. Caddy obtains and renews certificates automatically from Let's Encrypt with no
cron job and no operator action. The application listens only on the internal Compose network; it is
not published on a host port in production.

Caddy is a default, not a requirement. A deployment whose VM already runs Nginx, Traefik, or a
provider-managed load balancer omits the Caddy service and points the existing proxy at the
application instead. The application must therefore trust `X-Forwarded-Proto` and
`X-Forwarded-For` only from the configured proxy, and must not assume Caddy specifically.

### Backup

A scheduled job produces, daily:

- a `pg_dump` custom-format dump of PostgreSQL;
- an archive of the versioned model directory and stored report summaries.

Both are encrypted before leaving the VM using `age` with a recipient public key. The private key is
held by the operator off the VM, so a compromised VM cannot decrypt its own backup history.
Encrypted files are uploaded to any S3-compatible object storage via `rclone`, which keeps the
destination a configuration choice rather than a hard-coded vendor.

Retention is 7 daily, 4 weekly, and 3 monthly copies. A failed backup raises the same alert channel
as a failed monitoring run. Restore is rehearsed on a clean machine and the rehearsal is part of the
Phase 6 handoff drill, because an untested backup is not a backup.

## Research and adaptation

- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) issues and renews
  certificates without configuration, which matches an operator who may have no technical support.
  Nginx would need Certbot plus a renewal timer plus a reload hook — three more things to fail
  quietly.
- [PostgreSQL `pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html) custom format
  supports selective restore and is the documented logical-backup path. At this data volume a
  logical dump restores fast enough that physical replication would be unjustified complexity.
- [age](https://github.com/FiloSottile/age) provides authenticated public-key file encryption with
  no key-management daemon. Encrypting to a public key means the backup job needs no secret capable
  of decryption, which is the property we actually want.
- [rclone](https://rclone.org/s3/) abstracts S3-compatible providers, so choosing or changing a
  provider is a config edit rather than a code change.

We rejected provider-managed database backups as the primary mechanism because they are tied to one
host and do not cover the model directory. We rejected unencrypted off-site copies outright: the
dump contains operational data and user password hashes.

## Consequences

Compose gains a Caddy service, a certificate volume, and a backup job, and the application stops
publishing port 8000 to the host in production. Deployments that supply their own proxy must set the
trusted-proxy configuration explicitly, and getting that wrong would let a client spoof its own
forwarded scheme — so it is validated at startup rather than assumed.

The operator now holds an `age` private key whose loss makes every backup unreadable. Key custody
and the restore rehearsal both belong in the Indonesian operator guide, not only in the technical
runbook.
