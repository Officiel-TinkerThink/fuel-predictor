#!/usr/bin/env sh
# Daily encrypted backup (ADR 0012).
#
#   deploy/backup.sh
#
# Produces a pg_dump custom-format dump and an archive of the retained model
# packages, encrypts both to an age recipient public key, and uploads them with
# rclone. The private key is never on this machine, so a compromised VM cannot
# decrypt its own backup history.
#
# Required environment (see .env.example):
#   POSTGRES_PASSWORD        password for the fuel_predictor role
#   BACKUP_AGE_RECIPIENT     age public key (age1...) to encrypt to
#   BACKUP_RCLONE_REMOTE     rclone destination, e.g. s3remote:fuel-backups
#
# Exits non-zero when the backup did not reach the remote. That exit code is
# the signal a scheduler watches; the outcome is also recorded in the database
# so the Kesehatan Sistem page shows it.

set -eu

: "${POSTGRES_PASSWORD:?BACKUP: POSTGRES_PASSWORD belum diatur}"
: "${BACKUP_AGE_RECIPIENT:?BACKUP: BACKUP_AGE_RECIPIENT belum diatur}"
: "${BACKUP_RCLONE_REMOTE:?BACKUP: BACKUP_RCLONE_REMOTE belum diatur}"

DB_HOST="${BACKUP_DB_HOST:-db}"
DB_USER="${BACKUP_DB_USER:-fuel_predictor}"
DB_NAME="${BACKUP_DB_NAME:-fuel_predictor}"
MODEL_DIR="${FUEL_PREDICTOR_MODEL_ARTIFACT_DIRECTORY:-/data/model-packages}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '$WORK'" EXIT

fail() {
	reason="$1"
	echo "Pencadangan gagal: $reason" >&2
	# Recorded before exiting: a failed backup an operator never hears about
	# is indistinguishable from no backup at all. Recording is best-effort —
	# if the database is the thing that is down, the exit code still stands.
	python -m fuel_predictor record-backup \
		--outcome failed \
		--destination "$BACKUP_RCLONE_REMOTE" \
		--failure-reason "$reason" || true
	exit 1
}

# --- dump -------------------------------------------------------------------
# Custom format (-Fc) so a restore can be selective, and so pg_restore can
# reorder to satisfy constraints. A plain SQL dump cannot do either.
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
	--host "$DB_HOST" --username "$DB_USER" --dbname "$DB_NAME" \
	--format=custom --file "$WORK/db-$STAMP.dump" \
	|| fail "pg_dump tidak berhasil"

# --- model packages ---------------------------------------------------------
# Retained package bytes are a correctness concern, not just disk hygiene:
# rollback can only return to a version whose bytes still exist, so a database
# backup without these would restore to a state that cannot roll back.
if [ -d "$MODEL_DIR" ]; then
	tar -czf "$WORK/models-$STAMP.tar.gz" -C "$MODEL_DIR" . || fail "arsip paket model gagal dibuat"
else
	echo "Direktori paket model tidak ada, dilewati: $MODEL_DIR" >&2
	tar -czf "$WORK/models-$STAMP.tar.gz" -T /dev/null
fi

# --- encrypt ----------------------------------------------------------------
# Encrypting to a public key means this job holds no secret capable of
# decryption, which is the property that makes an on-VM backup job safe.
for file in "$WORK/db-$STAMP.dump" "$WORK/models-$STAMP.tar.gz"; do
	age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$file.age" "$file" \
		|| fail "enkripsi age gagal untuk $(basename "$file")"
	rm -f "$file"
done

# --- upload -----------------------------------------------------------------
rclone copy "$WORK" "$BACKUP_RCLONE_REMOTE/daily/$STAMP" --include '*.age' \
	|| fail "unggahan rclone gagal"

SIZE="$(du -sb "$WORK" 2>/dev/null | cut -f1 || echo 0)"

# --- retention --------------------------------------------------------------
# 7 daily, 4 weekly, 3 monthly (ADR 0012). Weekly and monthly copies are
# promoted from a daily rather than dumped again, so a restore is always
# exercising the same artefact shape.
if [ "$(date -u +%u)" = "7" ]; then
	rclone copy "$WORK" "$BACKUP_RCLONE_REMOTE/weekly/$STAMP" --include '*.age' || true
fi
if [ "$(date -u +%d)" = "01" ]; then
	rclone copy "$WORK" "$BACKUP_RCLONE_REMOTE/monthly/$STAMP" --include '*.age' || true
fi

prune() {
	prefix="$1"
	keep="$2"
	# Never fails the backup: pruning is housekeeping, and a today's backup
	# that uploaded fine must not be reported as failed because an old copy
	# could not be deleted.
	rclone lsf --dirs-only "$BACKUP_RCLONE_REMOTE/$prefix" 2>/dev/null \
		| sort -r \
		| tail -n +"$((keep + 1))" \
		| while read -r old; do
			rclone purge "$BACKUP_RCLONE_REMOTE/$prefix/$old" || true
		done
}
prune daily 7
prune weekly 4
prune monthly 3

python -m fuel_predictor record-backup \
	--outcome succeeded \
	--destination "$BACKUP_RCLONE_REMOTE" \
	--size-bytes "$SIZE" || true

echo "Pencadangan selesai: $BACKUP_RCLONE_REMOTE/daily/$STAMP"
