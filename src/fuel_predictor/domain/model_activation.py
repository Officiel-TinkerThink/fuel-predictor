"""Failures that can stop an activation or rollback (ADR 0010).

These are business outcomes, not transport errors: each one tells the
operator something specific about why the active model did not change, and
each maps to a distinct recovery action.
"""


class ModelActivationError(Exception):
    """Base for every reason an activation or rollback did not take effect."""


class ModelActivationConflictError(ModelActivationError):
    """Someone else changed the active model since the caller last looked.

    Names the version that is *actually* active so the caller can re-read and
    decide again, rather than retrying blindly into the same conflict.
    """

    def __init__(self, expected: str | None, actual: str | None) -> None:
        super().__init__(
            f"Model aktif sudah berubah: diharapkan {expected or 'tidak ada'}, "
            f"saat ini {actual or 'tidak ada'}."
        )
        self.expected = expected
        self.actual = actual


class ModelCapacityError(ModelActivationError):
    """The candidate and the active model cannot be resident at the same time.

    Rejecting here is deliberate: the alternative is loading anyway and
    risking the serving process being killed for running out of memory, which
    would take the currently-healthy active model down with it.
    """

    def __init__(self, required_bytes: int, available_bytes: int) -> None:
        super().__init__(
            f"Memori tidak cukup untuk memuat kandidat: butuh {required_bytes} byte, "
            f"tersedia {available_bytes} byte. Aktivasi dibatalkan dan model aktif "
            "tidak diubah."
        )
        self.required_bytes = required_bytes
        self.available_bytes = available_bytes


class ModelSmokeTestFailedError(ModelActivationError):
    """The candidate loaded but produced wrong answers on its own declared cases."""

    def __init__(self, failures: tuple[str, ...]) -> None:
        super().__init__(
            "Kandidat gagal uji asap dan tidak diaktifkan: " + "; ".join(failures)
        )
        self.failures = failures


class ModelLoadFailedError(ModelActivationError):
    """The candidate artefact could not be loaded at all."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Kandidat tidak dapat dimuat: {reason}")
        self.reason = reason


class PostActivationHealthCheckFailedError(ModelActivationError):
    """The swap happened, then the new active model failed its health check.

    Deliberately *not* auto-reverted (ADR 0010): an automatic revert would
    hide a real problem behind a system that looks fine. The operator is told
    what happened and offered rollback as an explicit decision.
    """

    def __init__(self, activated_version: str, reason: str) -> None:
        super().__init__(
            f"Model {activated_version} sudah aktif tetapi gagal pemeriksaan kesehatan: "
            f"{reason}. Tinjau segera dan pertimbangkan rollback."
        )
        self.activated_version = activated_version
        self.reason = reason
