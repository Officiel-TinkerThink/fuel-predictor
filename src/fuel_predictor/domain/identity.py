"""Human identity, roles, and the audit trail that records what they did.

Roles are coarse on purpose: the production plan names three, and every route
declares the capability it needs rather than naming a role, so adding a role
later does not mean editing every route.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class UserRole(StrEnum):
    """Two roles. An operator plans the day and reports what was burned; an
    administrator does that and runs everything else. The plan's third role,
    manager, added one menu (the audit log) and was folded into administrator."""

    OPERATOR = "operator"
    ADMINISTRATOR = "administrator"


class Capability(StrEnum):
    """A single thing a caller may do, independent of who may do it."""

    CREATE_PREDICTION = "create_prediction"
    RECORD_ACTUAL_FUEL = "record_actual_fuel"
    IMPORT_OPERATIONS = "import_operations"
    VIEW_MONITORING = "view_monitoring"
    VIEW_MODELS = "view_models"
    MANAGE_MODELS = "manage_models"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT = "view_audit"
    # Connecting one's own coding agent and cutting it off again (ADR 0014).
    # Every role has it: the agent can never do more than the person could.
    MANAGE_OWN_AGENTS = "manage_own_agents"
    # Changing one's own password. Every role has it; it is never delegated
    # to an agent scope.
    MANAGE_OWN_ACCOUNT = "manage_own_account"


# The operator's whole job: make predictions (one at a time or from a sheet),
# record actual fuel, and keep their own password. Nothing they can see is
# about the model or the system.
_OPERATOR_CAPABILITIES = frozenset(
    {
        Capability.CREATE_PREDICTION,
        Capability.IMPORT_OPERATIONS,
        Capability.RECORD_ACTUAL_FUEL,
        Capability.MANAGE_OWN_ACCOUNT,
    }
)

_ADMINISTRATOR_CAPABILITIES = frozenset(Capability)

_ROLE_CAPABILITIES: dict[UserRole, frozenset[Capability]] = {
    UserRole.OPERATOR: _OPERATOR_CAPABILITIES,
    UserRole.ADMINISTRATOR: _ADMINISTRATOR_CAPABILITIES,
}


def capabilities_for(role: UserRole) -> frozenset[Capability]:
    return _ROLE_CAPABILITIES[role]


def role_allows(role: UserRole, capability: Capability) -> bool:
    return capability in _ROLE_CAPABILITIES[role]


class IdentityValidationError(ValueError):
    """A user or credential value violated a rule the operator must correct.

    `field` and `message` name the first problem; `problems` holds every one
    found in the same submission, so a form can name them all at once.
    """

    def __init__(
        self, field: str, message: str, also: tuple["IdentityValidationError", ...] = ()
    ) -> None:
        super().__init__(message)
        self.field = field
        self.message = message
        self.problems: tuple[IdentityValidationError, ...] = (self, *also)


MINIMUM_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    username: str
    full_name: str
    role: UserRole
    password_hash: str
    is_active: bool
    created_at: datetime
    # Optional: a shared desk or a service account has no address to give.
    # Stored normalised (trimmed, lower-cased) and unique when present, so it
    # can stand in for the username at sign-in.
    email: str | None = None
    # Kept here rather than as an audit row per sign-in: a sign of life is
    # one value per person, not a log entry per day.
    last_sign_in_at: datetime | None = None

    def allows(self, capability: Capability) -> bool:
        return self.is_active and role_allows(self.role, capability)


@dataclass(frozen=True, slots=True)
class PasswordResetToken:
    """One chance to choose a new password, mailed to the account's address.

    Only the hash is stored, as with sessions; the raw token lives in the
    link. Single use and short-lived: presenting it once, or after the
    deadline, is the end of it.
    """

    token_hash: str
    user_id: str
    issued_at: datetime
    expires_at: datetime
    used_at: datetime | None = None

    def is_usable_at(self, moment: datetime) -> bool:
        return self.used_at is None and moment < self.expires_at

    def used(self, moment: datetime) -> "PasswordResetToken":
        return replace(self, used_at=moment)


class AgentScope(StrEnum):
    """What an agent client may do (ADR 0008).

    Deliberately coarser and more restrictive than human capabilities: the
    initial set is read/compute only. Privileged model operations are Phase 5
    and stay unavailable until read-only MCP has proven itself in production.
    """

    PREDICT = "fuel:predict"
    MONITOR = "fuel:monitor"
    MODELS_READ = "models:read"
    # Phase 5. Never in DEFAULT_AGENT_SCOPES, and the tools it unlocks are
    # additionally gated by configuration: granting the scope alone is not
    # enough to enable them.
    MODELS_ADMIN = "models:admin"


_SCOPE_CAPABILITIES: dict[AgentScope, frozenset[Capability]] = {
    AgentScope.PREDICT: frozenset({Capability.CREATE_PREDICTION}),
    AgentScope.MONITOR: frozenset({Capability.VIEW_MONITORING}),
    AgentScope.MODELS_READ: frozenset({Capability.VIEW_MODELS}),
    AgentScope.MODELS_ADMIN: frozenset({Capability.VIEW_MODELS, Capability.MANAGE_MODELS}),
}

# Read/compute only. An administrator has to choose MODELS_ADMIN deliberately;
# it is not something a credential acquires by accepting the defaults.
DEFAULT_AGENT_SCOPES = frozenset({AgentScope.PREDICT, AgentScope.MONITOR, AgentScope.MODELS_READ})


def capabilities_for_scopes(scopes: frozenset[AgentScope]) -> frozenset[Capability]:
    granted: set[Capability] = set()
    for scope in scopes:
        granted |= _SCOPE_CAPABILITIES[scope]
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class AgentClient:
    """One MCP client with its own revocable credential and scope set.

    Each client gets a distinct identity so a compromised or misbehaving
    agent can be revoked without disturbing the others, and so every audited
    call names which agent made it.
    """

    client_id: str
    name: str
    scopes: frozenset[AgentScope]
    token_hash: str
    created_at: datetime
    is_active: bool
    revoked_at: datetime | None = None

    def allows(self, capability: Capability) -> bool:
        if not self.is_active:
            return False
        return capability in capabilities_for_scopes(self.scopes)

    def has_scope(self, scope: AgentScope) -> bool:
        return self.is_active and scope in self.scopes


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """A live browser session. `token_hash` is stored; the raw token never is."""

    token_hash: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    csrf_token: str

    def is_expired_at(self, moment: datetime) -> bool:
        return moment >= self.expires_at

    def is_idle_at(self, moment: datetime, idle_timeout_seconds: int) -> bool:
        return (moment - self.last_seen_at).total_seconds() >= idle_timeout_seconds


class AuditOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One durable statement of who did what, and whether it worked."""

    audit_id: str
    occurred_at: datetime
    actor: str
    actor_kind: str
    action: str
    outcome: AuditOutcome
    subject: str | None
    details: dict[str, str | int | float | bool | None]


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not username:
        raise IdentityValidationError("username", "Nama pengguna wajib diisi.")
    if len(username) > 64:
        raise IdentityValidationError("username", "Nama pengguna maksimal 64 karakter.")
    if not all(character.isalnum() or character in {".", "-", "_"} for character in username):
        raise IdentityValidationError(
            "username",
            "Nama pengguna hanya boleh berisi huruf, angka, titik, garis, dan garis bawah.",
        )
    return username


def validate_password(value: str) -> str:
    if len(value) < MINIMUM_PASSWORD_LENGTH:
        raise IdentityValidationError(
            "password",
            f"Kata sandi minimal {MINIMUM_PASSWORD_LENGTH} karakter.",
        )
    if len(value) > 256:
        raise IdentityValidationError("password", "Kata sandi maksimal 256 karakter.")
    return value


def normalize_email(value: str | None) -> str | None:
    """Trimmed and lower-cased, or None when nothing was given.

    The check is deliberately shallow - one "@" with something either side and
    a dot in the domain - because the only thing an address is used for here
    is to be typed again at sign-in; a bounce is not something this system
    could act on.
    """
    email = (value or "").strip().lower()
    if not email:
        return None
    if len(email) > 254:
        raise IdentityValidationError("email", "Email maksimal 254 karakter.")
    local, separator, domain = email.partition("@")
    malformed = (
        not separator
        or not local
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
        or any(character.isspace() for character in email)
    )
    if malformed:
        raise IdentityValidationError("email", "Alamat email tidak valid.")
    return email


def validate_full_name(value: str) -> str:
    full_name = value.strip()
    if not full_name:
        raise IdentityValidationError("full_name", "Nama lengkap wajib diisi.")
    if len(full_name) > 128:
        raise IdentityValidationError("full_name", "Nama lengkap maksimal 128 karakter.")
    return full_name
