"""Audit records as a page shows them: actions in words, details listed."""

from fuel_predictor.domain.identity import AuditRecord

# What each recorded action means, in words. The code itself stays on the
# page in small type so a log line can still be matched against it.
_ACTION_LABELS = {
    "sign_in_succeeded": "Masuk berhasil",
    "sign_in_failed": "Masuk gagal",
    "sign_out": "Keluar",
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
_ACTOR_KIND_LABELS = {"user": "Pengguna", "agent": "Agen", "system": "Sistem"}
_DETAIL_LABELS = {
    "reason": "alasan",
    "role": "peran",
    "note": "catatan",
    "client_id": "klien",
    "scopes": "cakupan",
    "username": "pengguna",
    "full_name": "nama",
    "email": "email",
    "from": "dari",
    "to": "menjadi",
    "registration_id": "klien",
    "user_id": "id pengguna",
}


def action_label(action: str) -> str:
    if action in _ACTION_LABELS:
        return _ACTION_LABELS[action]
    if action.startswith("mcp_tool:"):
        return f"Alat agen {action.removeprefix('mcp_tool:')}"
    return action.replace("_", " ").capitalize()


def audit_row(record: AuditRecord) -> dict[str, object]:
    return {
        "occurred_at": record.occurred_at,
        "actor": record.actor,
        "actor_kind": _ACTOR_KIND_LABELS.get(record.actor_kind, record.actor_kind),
        "action": record.action,
        "action_label": action_label(record.action),
        "subject": record.subject,
        "outcome": record.outcome.value,
        "details": [
            (_DETAIL_LABELS.get(key, key), value)
            for key, value in record.details.items()
            if value not in (None, "")
        ],
    }
