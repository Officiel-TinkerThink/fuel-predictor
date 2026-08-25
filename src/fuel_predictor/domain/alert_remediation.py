"""What an operator should actually do about each kind of alert (Phase 3).

An alert that only says something is wrong makes the reader search for someone
who knows what to do. These texts name the next action in plain Indonesian, in
the order a non-specialist would take them, and they say when *not* acting is
the right answer — a drift warning during a genuine change in operations is
information, not a fault to be fixed.

Kept in the domain because the wording is part of what the system promises an
operator, not a detail of how a message happens to be delivered.
"""

from fuel_predictor.domain.monitoring import MonitoringAlertKind, MonitoringAlertSeverity

_REMEDIATION: dict[MonitoringAlertKind, str] = {
    MonitoringAlertKind.DATA_QUALITY: (
        "Buka halaman Pemantauan, lihat daftar baris bermasalah, dan perbaiki barisnya di "
        "berkas sumber. Setelah diperbaiki, impor ulang berkas tersebut. Baris bermasalah "
        "tidak ikut melatih model, jadi membiarkannya membuat model belajar dari data yang "
        "lebih sedikit daripada yang Anda kira."
    ),
    MonitoringAlertKind.MISSING_ACTUAL: (
        "Catat bahan bakar aktual untuk operasi yang sudah selesai melalui halaman Catat "
        "Aktual atau Impor Massal. Tanpa angka aktual, sistem tidak dapat mengukur seberapa "
        "tepat prediksinya, sehingga penurunan mutu model tidak akan terdeteksi."
    ),
    MonitoringAlertKind.FEATURE_DRIFT: (
        "Periksa apakah pola operasi memang berubah — rute baru, kendaraan baru, atau musim "
        "yang berbeda. Bila perubahan itu nyata dan akan berlanjut, latih ulang model dengan "
        "data terbaru. Bila tidak ada yang berubah di lapangan, periksa dulu cara data "
        "dimasukkan sebelum melatih ulang. Pergeseran bukan selalu kesalahan."
    ),
    MonitoringAlertKind.MODEL_DEGRADATION: (
        "Prediksi mulai meleset lebih jauh dari biasanya. Buka Pengelolaan Model, bandingkan "
        "kandidat yang tersedia, dan aktifkan yang lebih baik. Bila tidak ada kandidat yang "
        "lebih baik, kembalikan ke versi model sebelumnya yang hasilnya masih baik, lalu "
        "siapkan pelatihan ulang. Sementara itu, tambahkan margin pada alokasi bahan bakar."
    ),
}

_URGENCY: dict[MonitoringAlertSeverity, str] = {
    MonitoringAlertSeverity.WARNING: (
        "Tangani dalam beberapa hari kerja. Prediksi masih dapat dipakai."
    ),
    MonitoringAlertSeverity.CRITICAL: (
        "Tangani hari ini. Periksa ulang alokasi bahan bakar sebelum dipakai."
    ),
}


def remediation_for(kind: MonitoringAlertKind) -> str:
    return _REMEDIATION[kind]


def urgency_for(severity: MonitoringAlertSeverity) -> str:
    return _URGENCY[severity]
