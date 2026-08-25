"""Human identity, roles, and the audit trail that records what they did.

Roles are coarse on purpose: the production plan names three, and every route
declares the capability it needs rather than naming a role, so adding a role
later does not mean editing every route.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class UserRole(StrEnum):
    OPERATOR = "operator"
    MANAGER = "manager"
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


_OPERATOR_CAPABILITIES = frozenset(
    {
        Capability.CREATE_PREDICTION,
        Capability.RECORD_ACTUAL_FUEL,
        Capability.IMPORT_OPERATIONS,
        Capability.VIEW_MONITORING,
        Capability.VIEW_MODELS,
    }
)

_MANAGER_CAPABILITIES = _OPERATOR_CAPABILITIES | {Capability.VIEW_AUDIT}

_ADMINISTRATOR_CAPABILITIES = _MANAGER_CAPABILITIES | {
    Capability.MANAGE_MODELS,
    Capability.MANAGE_USERS,
}

_ROLE_CAPABILITIES: dict[UserRole, frozenset[Capability]] = {
    UserRole.OPERATOR: _OPERATOR_CAPABILITIES,
    UserRole.MANAGER: frozenset(_MANAGER_CAPABILITIES),
    UserRole.ADMINISTRATOR: frozenset(_ADMINISTRATOR_CAPABILITIES),
}


def capabilities_for(role: UserRole) -> frozenset[Capability]:
    return _ROLE_CAPABILITIES[role]


def role_allows(role: UserRole, capability: Capability) -> bool:
    return capability in _ROLE_CAPABILITIES[role]


class IdentityValidationError(ValueError):
    """A user or credential value violated a rule the operator must correct."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


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

    def allows(self, capability: Capability) -> bool:
        return self.is_active and role_allows(self.role, capability)


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
DEFAULT_AGENT_SCOPES = frozenset(
    {AgentScope.PREDICT, AgentScope.MONITOR, AgentScope.MODELS_READ}
)


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


def validate_full_name(value: str) -> str:
    full_name = value.strip()
    if not full_name:
        raise IdentityValidationError("full_name", "Nama lengkap wajib diisi.")
    if len(full_name) > 128:
        raise IdentityValidationError("full_name", "Nama lengkap maksimal 128 karakter.")
    return full_name
