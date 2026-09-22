"""What an administrator sees of the people using the system.

A directory of accounts with a sign of life on each - when they last signed
in, how much they planned and reported lately - and a page per person that
adds their recent operations and their audit trail. Everything here is read
from what the system already records: the audit trail and the authorship
on operations and actual-fuel records.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fuel_predictor.application.identity import (
    AuditRepository,
    EmailAlreadyExistsError,
    RecordAuditEvent,
    UserRepository,
)
from fuel_predictor.domain.identity import (
    AuditOutcome,
    AuditRecord,
    IdentityValidationError,
    User,
    UserRole,
    normalize_email,
    validate_full_name,
)

ACTIVITY_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class RecentOperation:
    operation_id: str
    created_at: datetime | None
    vehicle: str | None
    total_distance_km: float
    has_actual: bool


class UserActivityReader(Protocol):
    """Counts and rows from the operations and actual records a person authored."""

    def operation_counts(self, since: datetime | None) -> dict[str, int]: ...

    def actual_counts(self, since: datetime | None) -> dict[str, int]: ...

    def recent_operations_by(self, username: str, limit: int) -> Sequence[RecentOperation]: ...


@dataclass(frozen=True, slots=True)
class UserActivity:
    last_sign_in: datetime | None
    sign_ins_recent: int
    failed_sign_ins_recent: int
    operations_total: int
    operations_recent: int
    actuals_total: int
    actuals_recent: int


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    user: User
    activity: UserActivity


@dataclass(frozen=True, slots=True)
class UserDirectory:
    entries: tuple[DirectoryEntry, ...]

    @property
    def active_count(self) -> int:
        return sum(1 for entry in self.entries if entry.user.is_active)

    @property
    def administrator_count(self) -> int:
        return sum(1 for entry in self.entries if entry.user.role is UserRole.ADMINISTRATOR)


@dataclass(frozen=True, slots=True)
class UserDetail:
    user: User
    activity: UserActivity
    recent_operations: tuple[RecentOperation, ...]
    trail: tuple[AuditRecord, ...]


@dataclass(frozen=True, slots=True)
class GetUserDirectory:
    users: UserRepository
    audit: AuditRepository
    activity: UserActivityReader
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self) -> UserDirectory:
        since = self.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)
        counts = _Counts(self.activity, since)
        entries = tuple(
            DirectoryEntry(user=user, activity=_activity_for(user, self.audit, counts, since))
            for user in sorted(self.users.list_users(), key=lambda user: user.username)
        )
        return UserDirectory(entries=entries)


@dataclass(frozen=True, slots=True)
class GetUserDetail:
    users: UserRepository
    audit: AuditRepository
    activity: UserActivityReader
    recent_operations_limit: int = 10
    trail_limit: int = 50
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, user_id: str) -> UserDetail:
        user = self.users.get(user_id)
        if user is None:
            raise IdentityValidationError("user_id", "Pengguna tidak ditemukan.")
        since = self.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)
        counts = _Counts(self.activity, since)
        return UserDetail(
            user=user,
            activity=_activity_for(user, self.audit, counts, since),
            recent_operations=tuple(
                self.activity.recent_operations_by(user.username, self.recent_operations_limit)
            ),
            trail=tuple(self.audit.list_for_user(user.username, self.trail_limit)),
        )


@dataclass(frozen=True, slots=True)
class UpdateUserProfile:
    """Name, email and role. The role of the account doing the editing is off
    limits: demoting yourself is how a system ends up without an administrator."""

    users: UserRepository
    record_audit: RecordAuditEvent

    def execute(
        self,
        user_id: str,
        *,
        full_name: str,
        email: str | None,
        role: UserRole,
        changed_by: User,
    ) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise IdentityValidationError("user_id", "Pengguna tidak ditemukan.")
        validated_name = validate_full_name(full_name)
        normalized_email = normalize_email(email)
        if user.user_id == changed_by.user_id and role is not user.role:
            raise IdentityValidationError(
                "role", "Anda tidak dapat mengubah peran Anda sendiri; minta administrator lain."
            )
        if normalized_email:
            holder = self.users.get_by_email(normalized_email)
            if holder is not None and holder.user_id != user.user_id:
                raise EmailAlreadyExistsError(normalized_email)
        updated = User(
            user_id=user.user_id,
            username=user.username,
            full_name=validated_name,
            role=role,
            password_hash=user.password_hash,
            is_active=user.is_active,
            created_at=user.created_at,
            email=normalized_email,
        )
        self.users.replace(updated)
        changes = {
            key: value
            for key, value in (
                ("full_name", validated_name if validated_name != user.full_name else None),
                ("email", normalized_email if normalized_email != user.email else None),
                ("role", str(role) if role is not user.role else None),
            )
            if value is not None
        }
        if changes:
            self.record_audit.execute(
                actor=changed_by.username,
                action="user_profile_changed",
                outcome=AuditOutcome.SUCCEEDED,
                subject=user.username,
                details=dict(changes),
            )
        return updated


class _Counts:
    """The per-author totals, fetched once for every user rather than per row."""

    def __init__(self, reader: UserActivityReader, since: datetime) -> None:
        self.operations_total = reader.operation_counts(None)
        self.operations_recent = reader.operation_counts(since)
        self.actuals_total = reader.actual_counts(None)
        self.actuals_recent = reader.actual_counts(since)


def _activity_for(
    user: User, audit: AuditRepository, counts: _Counts, since: datetime
) -> UserActivity:
    return UserActivity(
        last_sign_in=audit.last_occurrence("sign_in_succeeded", user.username),
        sign_ins_recent=audit.count_recent("sign_in_succeeded", user.username, since),
        failed_sign_ins_recent=audit.count_recent("sign_in_failed", user.username, since),
        operations_total=counts.operations_total.get(user.username, 0),
        operations_recent=counts.operations_recent.get(user.username, 0),
        actuals_total=counts.actuals_total.get(user.username, 0),
        actuals_recent=counts.actuals_recent.get(user.username, 0),
    )
