#!/bin/sh
# Daily local database dump, run by the `backup` service in compose.prod.yaml.
#
# The encrypted off-site backup (deploy/backup.sh, ADR 0012) needs an age
# public key and an rclone remote; until those are configured nothing backed
# the database up at all. This keeps the last seven daily dumps in the
# `db_backups` volume on the same machine: it does not survive losing the
# machine, but it does survive a mistaken deletion, a bad migration or a
# corrupted table - and it costs nothing to configure. Restoring one is §8a
# of docs/production/recovery-runbook.md.
#
# Runs in the postgres:16-alpine image, so pg_dump matches the server. Each
# attempt is recorded in backup_runs, the table Kesehatan Sistem reads.

set -u

DIR="${LOCAL_BACKUP_DIRECTORY:-/backups}"
KEEP_DAYS="${LOCAL_BACKUP_KEEP_DAYS:-7}"
EVERY_SECONDS="${LOCAL_BACKUP_EVERY_SECONDS:-86400}"
export PGHOST="${PGHOST:-db}" PGUSER="${PGUSER:-fuel_predictor}" PGDATABASE="${PGDATABASE:-fuel_predictor}"

record() {
	# $1 outcome, $2 size in bytes or NULL, $3 failure reason (SQL literal) or NULL.
	# Best effort: when the database is what failed, the log line still stands.
	psql --quiet --no-psqlrc --command "INSERT INTO backup_runs
		(run_id, finished_at, outcome, destination, size_bytes, failure_reason)
		VALUES ('BAK-' || substr(md5(random()::text || clock_timestamp()::text), 1, 20),
			now(), '$1', 'lokal: volume db_backups (${KEEP_DAYS} hari)', $2, $3)" \
		|| echo "Hasil pencadangan lokal tidak dapat dicatat." >&2
}

while true; do
	stamp="$(date -u +%Y%m%dT%H%M%SZ)"
	target="$DIR/fuel_predictor-$stamp.dump"
	# Custom format, so a restore can be selective; written under a temporary
	# name so a dump cut short is never mistaken for a complete one.
	if pg_dump --format=custom --file "$target.partial" && mv "$target.partial" "$target"; then
		size="$(wc -c < "$target" | tr -d ' ')"
		record succeeded "$size" NULL
		echo "Pencadangan lokal selesai: $target ($size bita)"
	else
		rm -f "$target.partial"
		record failed NULL "'pg_dump tidak berhasil'"
		echo "Pencadangan lokal gagal." >&2
	fi
	find "$DIR" -name 'fuel_predictor-*.dump' -mtime +"$KEEP_DAYS" -delete
	sleep "$EVERY_SECONDS"
done
