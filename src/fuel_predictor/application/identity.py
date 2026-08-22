"""Sign-in, session lifetime, user administration, and the audit trail (ADR 0008).

Delivery adapters call these use cases; they never hash a password, mint a
session token, or decide what a role may do on their own.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol
from uuid import uuid4

from fuel_predictor.domain.identity import (
    AuditOutcome,
    AuditRecord,
    AuthenticatedSession,
    Capability,
    IdentityValidationError,
    User,
    UserRole,
    normalize_username,
    validate_full_name,
    validate_password,
)

SESSION_LIFETIME_SECONDS = 12 * 60 * 60
SESSION_IDLE_TIMEOUT_SECONDS = 60 * 60
MAX_FAILED_SIGN_IN_ATTEMPTS = 5
FAILED_SIGN_IN_WINDOW_SECONDS = 15 * 60


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, stored_hash: str) -> bool: ...


class UserRepository(Protocol):
    def add(self, user: User) -> None: ...

    def get(self, user_id: str) -> User | None: ...

    def get_by_username(self, username: str) -> User | None: ...

    def list_users(self) -> Sequence[User]: ...

    def replace(self, user: User) -> None: ...


class SessionRepository(Protocol):
    def add(self, session: AuthenticatedSession) -> None: ...

    def get(self, token_hash: str) -> AuthenticatedSession | None: ...

    def touch(self, token_hash: str, last_seen_at: datetime) -> None: ...

    def delete(self, token_hash: str) -> None: ...

    def delete_for_user(self, user_id: str) -> None: ...

    def delete_expired(self, moment: datetime) -> None: ...


class AuditRepository(Protocol):
    def add(self, record: AuditRecord) -> None: ...

    def list_recent(self, limit: int) -> Sequence[AuditRecord]: ...

    def count_recent(self, action: str, subject: str, since: datetime) -> int: ...


class SignInFailedError(Exception):
    """Credentials did not match, or the account cannot sign in."""

    def __init__(self, message: str = "Nama pengguna dan kata sandi tidak cocok.") -> None:
        super().__init__(message)
        self.message = message


class SignInThrottledError(SignInFailedError):
    def __init__(self) -> None:
        super().__init__(
            "Terlalu banyak percobaan masuk yang gagal. Coba lagi dalam 15 menit "
            "atau hubungi administrator."
        )


class UsernameAlreadyExistsError(IdentityValidationError):
    def __init__(self, username: str) -> None:
        super().__init__("username", f"Nama pengguna {username} sudah digunakan.")


@dataclass(frozen=True, slots=True)
class SignedInSession:
    """What the delivery layer needs after a successful sign-in."""

    session_token: str
    csrf_token: str
    user: User
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ActiveCaller:
    """The resolved identity behind the current request."""

    user: User
    csrf_token: str

    def allows(self, capability: Capability) -> bool:
        return self.user.allows(capability)


@dataclass(frozen=True, slots=True)
class RecordAuditEvent:
    audit_repository: AuditRepository
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self,
        actor: str,
        action: str,
        outcome: AuditOutcome,
        *,
        actor_kind: str = "user",
        subject: str | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            audit_id=f"AUD-{uuid4().hex[:20]}",
            occurred_at=self.now(),
            actor=actor,
            actor_kind=actor_kind,
            action=action,
            outcome=outcome,
            subject=subject,
            details=details or {},
        )
        self.audit_repository.add(record)
        return record


@dataclass(frozen=True, slots=True)
class SignIn:
    user_repository: UserRepository
    session_repository: SessionRepository
    password_hasher: PasswordHasher
    record_audit: RecordAuditEvent
    session_lifetime_seconds: int = SESSION_LIFETIME_SECONDS
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, username: str, password: str) -> SignedInSession:
        moment = self.now()
        try:
            normalized = normalize_username(username)
        except IdentityValidationError:
            # Never reveal which half of the credential pair was wrong.
            self._audit_failure(username, "invalid_username")
            raise SignInFailedError() from None

        if self._is_throttled(normalized, moment):
            self._audit_failure(normalized, "throttled")
            raise SignInThrottledError()

        user = self.user_repository.get_by_username(normalized)
        if user is None or not user.is_active:
            self._audit_failure(normalized, "unknown_or_inactive")
            raise SignInFailedError()
        if not self.password_hasher.verify(password, user.password_hash):
            self._audit_failure(normalized, "bad_password")
            raise SignInFailedError()

        session_token = token_urlsafe(32)
        csrf_token = token_urlsafe(32)
        expires_at = moment + timedelta(seconds=self.session_lifetime_seconds)
        self.session_repository.delete_expired(moment)
        self.session_repository.add(
            AuthenticatedSession(
                token_hash=hash_session_token(session_token),
                user_id=user.user_id,
                created_at=moment,
                expires_at=expires_at,
                last_seen_at=moment,
                csrf_token=csrf_token,
            )
        )
        self.record_audit.execute(
            actor=user.username,
            action="sign_in_succeeded",
            outcome=AuditOutcome.SUCCEEDED,
            subject=user.username,
            details={"role": str(user.role)},
        )
        return SignedInSession(
            session_token=session_token,
            csrf_token=csrf_token,
            user=user,
            expires_at=expires_at,
        )

    def _is_throttled(self, username: str, moment: datetime) -> bool:
        since = moment - timedelta(seconds=FAILED_SIGN_IN_WINDOW_SECONDS)
        recent = self.audit_repository.count_recent("sign_in_failed", username, since)
        return recent >= MAX_FAILED_SIGN_IN_ATTEMPTS

    @property
    def audit_repository(self) -> AuditRepository:
        return self.record_audit.audit_repository

    def _audit_failure(self, username: str, reason: str) -> None:
        self.record_audit.execute(
            actor=username,
            action="sign_in_failed",
            outcome=AuditOutcome.FAILED,
            subject=username,
            details={"reason": reason},
        )


@dataclass(frozen=True, slots=True)
class SignOut:
    session_repository: SessionRepository
    record_audit: RecordAuditEvent

    def execute(self, session_token: str, username: str) -> None:
        self.session_repository.delete(hash_session_token(session_token))
        self.record_audit.execute(
            actor=username,
            action="sign_out",
            outcome=AuditOutcome.SUCCEEDED,
            subject=username,
        )


@dataclass(frozen=True, slots=True)
class ResolveSession:
    """Turn a raw cookie value into a caller, refusing expired and idle sessions."""

    user_repository: UserRepository
    session_repository: SessionRepository
    idle_timeout_seconds: int = SESSION_IDLE_TIMEOUT_SECONDS
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def is_system_provisioned(self) -> bool:
        """False until the first administrator account is created.

        Before that point the application behaves as the original
        unauthenticated local MVP; production deployments always provision an
        administrator at startup (see ``EnsureBootstrapAdministrator``), so
        this state is never reached once a system is actually deployed.
        """
        return bool(self.user_repository.list_users())

    def execute(self, session_token: str | None) -> ActiveCaller | None:
        if not session_token:
            return None
        token_hash = hash_session_token(session_token)
        session = self.session_repository.get(token_hash)
        if session is None:
            return None
        moment = self.now()
        if session.is_expired_at(moment) or session.is_idle_at(moment, self.idle_timeout_seconds):
            self.session_repository.delete(token_hash)
            return None
        user = self.user_repository.get(session.user_id)
        if user is None or not user.is_active:
            self.session_repository.delete(token_hash)
            return None
        self.session_repository.touch(token_hash, moment)
        return ActiveCaller(user=user, csrf_token=session.csrf_token)


@dataclass(frozen=True, slots=True)
class CreateUser:
    user_repository: UserRepository
    password_hasher: PasswordHasher
    record_audit: RecordAuditEvent
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self,
        username: str,
        full_name: str,
        password: str,
        role: UserRole,
        created_by: str,
    ) -> User:
        normalized = normalize_username(username)
        validated_name = validate_full_name(full_name)
        validate_password(password)
        if self.user_repository.get_by_username(normalized) is not None:
            raise UsernameAlreadyExistsError(normalized)
        user = User(
            user_id=f"USR-{uuid4().hex[:20]}",
            username=normalized,
            full_name=validated_name,
            role=role,
            password_hash=self.password_hasher.hash(password),
            is_active=True,
            created_at=self.now(),
        )
        self.user_repository.add(user)
        self.record_audit.execute(
            actor=created_by,
            action="user_created",
            outcome=AuditOutcome.SUCCEEDED,
            subject=normalized,
            details={"role": str(role)},
        )
        return user


@dataclass(frozen=True, slots=True)
class SetUserActivation:
    user_repository: UserRepository
    session_repository: SessionRepository
    record_audit: RecordAuditEvent

    def execute(self, user_id: str, is_active: bool, changed_by: str) -> User:
        user = self.user_repository.get(user_id)
        if user is None:
            raise IdentityValidationError("user_id", "Pengguna tidak ditemukan.")
        updated = User(
            user_id=user.user_id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            password_hash=user.password_hash,
            is_active=is_active,
            created_at=user.created_at,
        )
        self.user_repository.replace(updated)
        if not is_active:
            # Deactivation must end access now, not when the session expires.
            self.session_repository.delete_for_user(user.user_id)
        self.record_audit.execute(
            actor=changed_by,
            action="user_activated" if is_active else "user_deactivated",
            outcome=AuditOutcome.SUCCEEDED,
            subject=user.username,
        )
        return updated


@dataclass(frozen=True, slots=True)
class ChangePassword:
    user_repository: UserRepository
    session_repository: SessionRepository
    password_hasher: PasswordHasher
    record_audit: RecordAuditEvent

    def execute(self, user_id: str, new_password: str, changed_by: str) -> User:
        user = self.user_repository.get(user_id)
        if user is None:
            raise IdentityValidationError("user_id", "Pengguna tidak ditemukan.")
        validate_password(new_password)
        updated = User(
            user_id=user.user_id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            password_hash=self.password_hasher.hash(new_password),
            is_active=user.is_active,
            created_at=user.created_at,
        )
        self.user_repository.replace(updated)
        self.session_repository.delete_for_user(user.user_id)
        self.record_audit.execute(
            actor=changed_by,
            action="password_changed",
            outcome=AuditOutcome.SUCCEEDED,
            subject=user.username,
        )
        return updated


@dataclass(frozen=True, slots=True)
class ListUsers:
    user_repository: UserRepository

    def execute(self) -> tuple[User, ...]:
        return tuple(self.user_repository.list_users())


@dataclass(frozen=True, slots=True)
class ListAuditRecords:
    audit_repository: AuditRepository
    default_limit: int = 200

    def execute(self, limit: int | None = None) -> tuple[AuditRecord, ...]:
        return tuple(self.audit_repository.list_recent(limit or self.default_limit))


@dataclass(frozen=True, slots=True)
class EnsureBootstrapAdministrator:
    """Create the first administrator so a fresh deployment can be signed into.

    Does nothing when any user already exists, so it cannot be used to
    re-create an administrator on a running system.
    """

    user_repository: UserRepository
    create_user: CreateUser

    def execute(self, username: str, password: str) -> User | None:
        if self.user_repository.list_users():
            return None
        return self.create_user.execute(
            username=username,
            full_name="Administrator",
            password=password,
            role=UserRole.ADMINISTRATOR,
            created_by="system",
        )


def hash_session_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()
