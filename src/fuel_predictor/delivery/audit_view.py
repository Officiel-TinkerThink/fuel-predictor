"""Audit records as a page shows them: actions in words, details listed."""

from fuel_predictor.delivery.rendering import format_decimal
from fuel_predictor.domain.identity import AuditRecord

# What each recorded action means, in words. The code itself stays on the
# page in small type so a log line can still be matched against it.
_ACTION_LABELS = {
    "sign_in_failed": "Masuk gagal",
    "operation_planned": "Operasi direncanakan dan diestimasi",
    "operation_cancelled": "Operasi dibatalkan",
    "actual_fuel_recorded": "BBM aktual dicatat",
    "bulk_prediction_imported": "Prediksi massal dari berkas",
    "bulk_actual_imported": "BBM aktual massal dari berkas",
    "historical_dataset_imported": "Data historis diimpor",
    "model_candidate_trained": "Kandidat model dilatih",
    "model_promoted": "Model dipromosikan menjadi aktif",
    "model_package_uploaded": "Paket model diunggah",
    "password_changed": "Kata sandi diubah",
    "password_reset_requested": "Tautan atur ulang kata sandi diminta",
    "user_created": "Pengguna dibuat",
    "user_activated": "Pengguna diaktifkan",
    "user_deactivated": "Pengguna dinonaktifkan",
    "user_profile_changed": "Profil pengguna diubah",
    "model_rollback_requested": "Pengembalian model diminta",
    "agent_credential_issued": "Kredensial agen diterbitkan",
    "agent_credential_revoked": "Kredensial agen dicabut",
    "agent_client_registered": "Klien agen mendaftar",
    "agent_consent_granted": "Izin agen diberikan",
    "agent_grant_issued": "Akses agen diberikan",
    "agent_grant_revoked": "Akses agen dicabut",
    "agent_grant_renamed": "Sambungan agen dinamai",
    "agent_grant_deleted": "Sambungan agen dihapus dari daftar",
    "mcp_rate_limited": "Agen melebihi batas laju",
}
# A person is the usual actor; only the others are worth a caption.
_ACTOR_KIND_LABELS = {"agent": "Agen", "system": "Sistem"}
_DETAIL_LABELS = {
    "reason": "alasan",
    "role": "peran",
    "note": "catatan",
    "client_id": "klien",
    "scopes": "cakupan",
    "username": "pengguna",
    "operation_id": "operasi",
    "kode": "kode operasi",
    "vehicle": "kendaraan",
    "liters": "liter",
    "jarak_km": "jarak (km)",
    "accepted": "diterima",
    "quarantined": "perlu diperbaiki",
    "source": "diukur dengan",
    "dataset": "dataset",
    "model": "model",
    "file": "berkas",
    "previous": "sebelumnya",
    "valid": "valid",
    "full_name": "nama",
    "email": "email",
    "from": "dari",
    "to": "menjadi",
    "registration_id": "klien",
    "user_id": "id pengguna",
}


# Stored values that are codes, in the words the pages use for them.
_VALUE_LABELS = {
    "fuel_meter": "Meter BBM",
    "receipt": "Nota",
    "manual_entry": "Catatan manual",
    "spreadsheet_import": "Impor berkas",
}


def _detail_value(value: object) -> object:
    if isinstance(value, float):
        return format_decimal(value)
    if isinstance(value, str):
        return _VALUE_LABELS.get(value, value)
    return value


def action_label(action: str) -> str:
    if action in _ACTION_LABELS:
        return _ACTION_LABELS[action]
    if action.startswith("mcp_tool:"):
        return f"Alat agen {action.removeprefix('mcp_tool:')}"
    return action.replace("_", " ").capitalize()


def audit_row(record: AuditRecord) -> dict[str, object]:
    # An operation is named by its code where the record has it; the code is
    # then the subject, not repeated among the details.
    code = record.details.get("kode") if (record.subject or "").startswith("OPR-") else None
    return {
        "occurred_at": record.occurred_at,
        "actor": record.actor,
        "actor_kind": _ACTOR_KIND_LABELS.get(record.actor_kind),
        "action": record.action,
        "action_label": action_label(record.action),
        "subject": record.subject,
        "subject_code": code or None,
        "outcome": record.outcome.value,
        "details": [
            (_DETAIL_LABELS.get(key, key), _detail_value(value))
            for key, value in record.details.items()
            if value not in (None, "") and not (code and key == "kode")
        ],
    }
