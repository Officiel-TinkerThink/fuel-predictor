#!/usr/bin/env sh
# Restore from an encrypted backup (ADR 0012).
#
#   deploy/restore.sh 20260825T031500Z
#
# Run this on a clean machine as a rehearsal, not only in an emergency. An
# untested backup is not a backup: the first time you find out whether a dump
# restores must not be the day you need it.
#
# Required environment:
#   POSTGRES_PASSWORD        password for the fuel_predictor role
#   BACKUP_RCLONE_REMOTE     the same remote the backup job writes to
#   BACKUP_AGE_KEY_FILE      path to the age *private* key
#
# The private key lives with the operator, off the production VM. If this
# script is being run on the production VM during a real incident, copy the key
# in for the restore and remove it afterwards — leaving it there would undo the
# reason backups are encrypted to a public key in the first place.

set -eu

STAMP="${1:?Sebutkan stempel waktu cadangan, misalnya 20260825T031500Z}"

: "${POSTGRES_PASSWORD:?RESTORE: POSTGRES_PASSWORD belum diatur}"
: "${BACKUP_RCLONE_REMOTE:?RESTORE: BACKUP_RCLONE_REMOTE belum diatur}"
: "${BACKUP_AGE_KEY_FILE:?RESTORE: BACKUP_AGE_KEY_FILE belum diatur}"

DB_HOST="${BACKUP_DB_HOST:-db}"
DB_USER="${BACKUP_DB_USER:-fuel_predictor}"
DB_NAME="${BACKUP_DB_NAME:-fuel_predictor}"
MODEL_DIR="${FUEL_PREDICTOR_MODEL_ARTIFACT_DIRECTORY:-/data/model-packages}"
SOURCE="${BACKUP_SOURCE_PREFIX:-daily}"
WORK="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '$WORK'" EXIT

echo "Mengambil cadangan $SOURCE/$STAMP ..."
rclone copy "$BACKUP_RCLONE_REMOTE/$SOURCE/$STAMP" "$WORK"

echo "Mendekripsi ..."
for encrypted in "$WORK"/*.age; do
	age --decrypt --identity "$BACKUP_AGE_KEY_FILE" --output "${encrypted%.age}" "$encrypted"
done

DUMP="$(ls "$WORK"/db-*.dump 2>/dev/null | head -1)"
[ -n "$DUMP" ] || {
	echo "Cadangan tidak memuat berkas dump basis data." >&2
	exit 1
}

echo "Memulihkan basis data ..."
# --clean --if-exists so a rehearsal onto a database that already has tables
# works. Without it the restore half-applies and leaves a confusing mixture of
# old and new rows, which is worse than a clean failure.
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
	--host "$DB_HOST" --username "$DB_USER" --dbname "$DB_NAME" \
	--clean --if-exists --no-owner "$DUMP"

MODELS="$(ls "$WORK"/models-*.tar.gz 2>/dev/null | head -1)"
if [ -n "$MODELS" ]; then
	echo "Memulihkan paket model ke $MODEL_DIR ..."
	mkdir -p "$MODEL_DIR"
	tar -xzf "$MODELS" -C "$MODEL_DIR"
fi

echo ""
echo "Pemulihan selesai. Periksa hal berikut sebelum menyatakan berhasil:"
echo "  1. Masuk ke aplikasi dan buka halaman Ringkasan."
echo "  2. Buka Pengelolaan Model — model aktif harus sama seperti sebelum insiden."
echo "  3. Buat satu prediksi percobaan dan pastikan angkanya masuk akal."
echo "  4. Buka Kesehatan Sistem dan jalankan 'python -m fuel_predictor monitor'."
echo ""
echo "Kalau langkah 2 menunjukkan model aktif yang berkasnya tidak ada, paket"
echo "model tidak ikut terpulihkan — ulangi dengan cadangan yang memuat"
echo "models-*.tar.gz, karena rollback hanya bisa kembali ke versi yang"
echo "berkasnya masih ada."
