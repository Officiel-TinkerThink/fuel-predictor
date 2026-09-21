"""The OAuth 2.1 authorization server behind `/mcp` (ADR 0014).

One use case per step of the flow: a client registers, a user is shown what
the client asks for and consents, the client redeems the resulting code for
tokens, refreshes them, and someone revokes the grant. The delivery layer
translates HTTP parameters into these calls and OAuth error responses back
out; it never mints a token or decides what a role may delegate.

Raw codes and tokens exist only in the return values of the use cases that
mint them, on their way to the client.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from fuel_predictor.application.identity import RecordAuditEvent, UserRepository
from fuel_predictor.domain.agent_authorization import (
    AgentAuthorizationError,
    AgentGrant,
    AuthorizationCode,
    RegisteredAgentClient,
    delegable_scopes_for,
    granted_scopes,
    parse_scope_parameter,
    validate_redirect_uri,
    verify_code_verifier,
)
from fuel_predictor.domain.identity import (
    AgentClient,
    AgentScope,
    AuditOutcome,
    Capability,
    IdentityValidationError,
    User,
)

ACCESS_TOKEN_LIFETIME_SECONDS = 60 * 60
REFRESH_TOKEN_LIFETIME_SECONDS = 30 * 24 * 60 * 60
# RFC 6749 §4.1.2 recommends at most ten minutes; the user has already
# clicked, so the client redeems it within a second or not at all.
AUTHORIZATION_CODE_LIFETIME_SECONDS = 5 * 60

# Prefixed like `fpa_` credentials so a leaked token is recognisable and so
# the bearer resolver can tell the two kinds apart without a database hit.
ACCESS_TOKEN_PREFIX = "fpg_"
REFRESH_TOKEN_PREFIX = "fpr_"


class AgentRegistrationRepository(Protocol):
    def add(self, registration: RegisteredAgentClient) -> None: ...

    def get(self, registration_id: str) -> RegisteredAgentClient | None: ...


class AuthorizationCodeRepository(Protocol):
    def add(self, code: AuthorizationCode) -> None: ...

    def get(self, code_hash: str) -> AuthorizationCode | None: ...

    def replace(self, code: AuthorizationCode) -> None: ...

    def delete_expired(self, moment: datetime) -> None: ...


class AgentGrantRepository(Protocol):
    def add(self, grant: AgentGrant) -> None: ...

    def get(self, grant_id: str) -> AgentGrant | None: ...

    def get_by_access_token_hash(self, token_hash: str) -> AgentGrant | None: ...

    def get_by_refresh_token_hash(self, token_hash: str) -> AgentGrant | None:
        """Matches the current *or* the previous refresh token, so reuse can be seen."""
        ...

    def list_grants(self, user_id: str | None = None) -> Sequence[AgentGrant]: ...

    def replace(self, grant: AgentGrant) -> None: ...

    def delete(self, grant_id: str) -> None: ...


class RedirectableAuthorizationError(AgentAuthorizationError):
    """An authorization request that failed *after* the client and redirect checked out.

    OAuth has the server send these errors back to the client's redirect
    URI so the client can show them. Errors in the client or redirect
    themselves are never redirected: that would send the user to whatever
    address the request named.
    """

    def __init__(
        self, error: str, description: str, *, redirect_uri: str, state: str | None
    ) -> None:
        super().__init__(error, description)
        self.redirect_uri = redirect_uri
        self.state = state


# --- Registration ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegisterAgentClient:
    registrations: AgentRegistrationRepository
    record_audit: RecordAuditEvent
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self, *, client_name: str | None, redirect_uris: Sequence[str]
    ) -> RegisteredAgentClient:
        cleaned = (client_name or "").strip()
        if not cleaned:
            raise AgentAuthorizationError("invalid_client_metadata", "client_name wajib diisi.")
        if len(cleaned) > 128:
            raise AgentAuthorizationError(
                "invalid_client_metadata", "client_name maksimal 128 karakter."
            )
        if not redirect_uris:
            raise AgentAuthorizationError(
                "invalid_redirect_uri", "Sedikitnya satu redirect_uri wajib disertakan."
            )
        validated = frozenset(validate_redirect_uri(uri) for uri in redirect_uris)
        registration = RegisteredAgentClient(
            registration_id=f"REG-{uuid4().hex[:20]}",
            client_name=cleaned,
            redirect_uris=validated,
            registered_at=self.now(),
        )
        self.registrations.add(registration)
        self.record_audit.execute(
            actor=cleaned,
            actor_kind="agent",
            action="agent_client_registered",
            outcome=AuditOutcome.SUCCEEDED,
            subject=registration.registration_id,
            details={"redirect_uris": ",".join(sorted(validated))},
        )
        return registration


# --- Authorization request and consent -------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """A validated `/authorize` request: everything the consent step needs to know."""

    registration: RegisteredAgentClient
    redirect_uri: str
    requested_scopes: frozenset[AgentScope]
    code_challenge: str
    state: str | None

    @property
    def redirect_host(self) -> str:
        return urlsplit(self.redirect_uri).netloc

    def offered_scopes_for(self, user: User) -> frozenset[AgentScope]:
        """What the consent screen may show `user` as tickable: asked for and within their role."""
        return self.requested_scopes & delegable_scopes_for(user.role)


@dataclass(frozen=True, slots=True)
class ValidateAuthorizationRequest:
    registrations: AgentRegistrationRepository

    def execute(
        self,
        *,
        client_id: str | None,
        redirect_uri: str | None,
        response_type: str | None,
        code_challenge: str | None,
        code_challenge_method: str | None,
        scope: str | None,
        state: str | None,
        resource: str | None,
        expected_resource: str,
    ) -> AuthorizationRequest:
        # Client and redirect first, and without redirecting on failure.
        registration = self.registrations.get(client_id or "")
        if registration is None:
            raise AgentAuthorizationError("invalid_client", "client_id tidak dikenal.")
        if not redirect_uri:
            if len(registration.redirect_uris) != 1:
                raise AgentAuthorizationError(
                    "invalid_request",
                    "redirect_uri wajib diisi karena klien mendaftarkan lebih dari satu.",
                )
            (redirect_uri,) = registration.redirect_uris
        if not registration.accepts_redirect(redirect_uri):
            raise AgentAuthorizationError(
                "invalid_request", "redirect_uri tidak terdaftar untuk klien ini."
            )

        def refuse(error: str, description: str) -> RedirectableAuthorizationError:
            return RedirectableAuthorizationError(
                error, description, redirect_uri=redirect_uri, state=state
            )

        if response_type != "code":
            raise refuse("unsupported_response_type", "Hanya response_type=code yang didukung.")
        if not code_challenge:
            raise refuse("invalid_request", "code_challenge (PKCE) wajib disertakan.")
        if code_challenge_method != "S256":
            raise refuse("invalid_request", "Hanya code_challenge_method=S256 yang didukung.")
        if resource is not None and resource != expected_resource:
            raise refuse("invalid_target", f"resource harus {expected_resource}, bukan {resource}.")
        try:
            requested = parse_scope_parameter(scope)
        except AgentAuthorizationError as error:
            raise refuse(error.error, error.description) from None

        return AuthorizationRequest(
            registration=registration,
            redirect_uri=redirect_uri,
            requested_scopes=requested,
            code_challenge=code_challenge,
            state=state,
        )


@dataclass(frozen=True, slots=True)
class IssuedAuthorizationCode:
    code: str
    redirect_uri: str
    state: str | None


@dataclass(frozen=True, slots=True)
class IssueAuthorizationCode:
    """The user clicked "allow": pin what they allowed and hand the client a code."""

    codes: AuthorizationCodeRepository
    record_audit: RecordAuditEvent
    lifetime_seconds: int = AUTHORIZATION_CODE_LIFETIME_SECONDS
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self, request: AuthorizationRequest, user: User, consented: frozenset[AgentScope]
    ) -> IssuedAuthorizationCode:
        try:
            scopes = granted_scopes(
                requested=request.requested_scopes, consented=consented, role=user.role
            )
        except AgentAuthorizationError as error:
            raise RedirectableAuthorizationError(
                error.error,
                error.description,
                redirect_uri=request.redirect_uri,
                state=request.state,
            ) from None
        moment = self.now()
        code = token_urlsafe(32)
        self.codes.delete_expired(moment)
        self.codes.add(
            AuthorizationCode(
                code_hash=hash_grant_token(code),
                registration_id=request.registration.registration_id,
                user_id=user.user_id,
                scopes=scopes,
                redirect_uri=request.redirect_uri,
                code_challenge=request.code_challenge,
                issued_at=moment,
                expires_at=moment + timedelta(seconds=self.lifetime_seconds),
            )
        )
        self.record_audit.execute(
            actor=user.username,
            action="agent_consent_granted",
            outcome=AuditOutcome.SUCCEEDED,
            subject=request.registration.client_name,
            details={
                "registration_id": request.registration.registration_id,
                "scopes": ",".join(sorted(scopes)),
            },
        )
        return IssuedAuthorizationCode(
            code=code, redirect_uri=request.redirect_uri, state=request.state
        )


# --- Tokens ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssuedGrantTokens:
    """The token endpoint's answer, raw tokens included, on their way to the client."""

    access_token: str
    refresh_token: str
    expires_in: int
    scopes: frozenset[AgentScope]


@dataclass(frozen=True, slots=True)
class _TokenLifetimes:
    access_seconds: int = ACCESS_TOKEN_LIFETIME_SECONDS
    refresh_seconds: int = REFRESH_TOKEN_LIFETIME_SECONDS


@dataclass(frozen=True, slots=True)
class RedeemAuthorizationCode:
    codes: AuthorizationCodeRepository
    grants: AgentGrantRepository
    users: UserRepository
    record_audit: RecordAuditEvent
    lifetimes: _TokenLifetimes = _TokenLifetimes()
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self,
        *,
        code: str | None,
        client_id: str | None,
        redirect_uri: str | None,
        code_verifier: str | None,
        resource: str | None,
        expected_resource: str,
    ) -> IssuedGrantTokens:
        moment = self.now()
        # One error for every way the code can be wrong. Distinguishing
        # "unknown" from "expired" from "wrong client" tells a guesser which
        # part it got right.
        invalid = AgentAuthorizationError(
            "invalid_grant", "Kode otorisasi tidak valid, kedaluwarsa, atau sudah dipakai."
        )
        if not code or not client_id or not code_verifier:
            raise AgentAuthorizationError(
                "invalid_request", "code, client_id, dan code_verifier wajib disertakan."
            )
        if resource is not None and resource != expected_resource:
            raise AgentAuthorizationError(
                "invalid_target", f"resource harus {expected_resource}, bukan {resource}."
            )
        stored = self.codes.get(hash_grant_token(code))
        if stored is None or not stored.is_redeemable_at(moment):
            raise invalid
        if stored.registration_id != client_id:
            raise invalid
        if redirect_uri is not None and redirect_uri != stored.redirect_uri:
            raise invalid
        if not verify_code_verifier(code_verifier, stored.code_challenge):
            raise invalid

        user = self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise invalid

        # Spent before the grant exists, so a race between two redemptions
        # of the same code cannot both succeed.
        self.codes.replace(stored.redeemed(moment))

        access_token, refresh_token, grant = _mint(
            grant_id=f"GRT-{uuid4().hex[:20]}",
            registration_id=stored.registration_id,
            user_id=stored.user_id,
            scopes=stored.scopes,
            granted_at=moment,
            lifetimes=self.lifetimes,
            moment=moment,
        )
        self.grants.add(grant)
        self.record_audit.execute(
            actor=user.username,
            action="agent_grant_issued",
            outcome=AuditOutcome.SUCCEEDED,
            subject=grant.grant_id,
            details={
                "registration_id": grant.registration_id,
                "scopes": ",".join(sorted(grant.scopes)),
            },
        )
        return IssuedGrantTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.lifetimes.access_seconds,
            scopes=grant.scopes,
        )


@dataclass(frozen=True, slots=True)
class RefreshGrant:
    grants: AgentGrantRepository
    users: UserRepository
    record_audit: RecordAuditEvent
    lifetimes: _TokenLifetimes = _TokenLifetimes()
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(
        self, *, refresh_token: str | None, client_id: str | None, scope: str | None
    ) -> IssuedGrantTokens:
        moment = self.now()
        invalid = AgentAuthorizationError(
            "invalid_grant", "Refresh token tidak valid, kedaluwarsa, atau sudah dicabut."
        )
        if not refresh_token or not client_id:
            raise AgentAuthorizationError(
                "invalid_request", "refresh_token dan client_id wajib disertakan."
            )
        token_hash = hash_grant_token(refresh_token)
        grant = self.grants.get_by_refresh_token_hash(token_hash)
        if grant is None or grant.registration_id != client_id:
            raise invalid
        if grant.was_refreshed_with(token_hash):
            # A token that was already rotated away is being presented again.
            # Either the client lost track, or someone copied it; in both
            # cases the safe answer is the same, and the user re-consents.
            if not grant.is_revoked:
                self.grants.replace(grant.revoked(moment))
                self.record_audit.execute(
                    actor=grant.grant_id,
                    actor_kind="agent",
                    action="agent_grant_revoked",
                    outcome=AuditOutcome.SUCCEEDED,
                    subject=grant.grant_id,
                    details={"reason": "refresh_token_reused"},
                )
            raise invalid
        if not grant.refresh_token_is_valid_at(moment):
            raise invalid
        user = self.users.get(grant.user_id)
        if user is None or not user.is_active:
            raise invalid
        if scope is not None and not parse_scope_parameter(scope) <= grant.scopes:
            raise AgentAuthorizationError(
                "invalid_scope", "Cakupan yang diminta melebihi cakupan grant."
            )

        access_token = f"{ACCESS_TOKEN_PREFIX}{token_urlsafe(32)}"
        new_refresh_token = f"{REFRESH_TOKEN_PREFIX}{token_urlsafe(32)}"
        rotated = grant.rotated(
            access_token_hash=hash_grant_token(access_token),
            access_token_expires_at=moment + timedelta(seconds=self.lifetimes.access_seconds),
            refresh_token_hash=hash_grant_token(new_refresh_token),
            refresh_token_expires_at=moment + timedelta(seconds=self.lifetimes.refresh_seconds),
            moment=moment,
        )
        self.grants.replace(rotated)
        return IssuedGrantTokens(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=self.lifetimes.access_seconds,
            scopes=rotated.scopes,
        )


def _mint(
    *,
    grant_id: str,
    registration_id: str,
    user_id: str,
    scopes: frozenset[AgentScope],
    granted_at: datetime,
    lifetimes: _TokenLifetimes,
    moment: datetime,
) -> tuple[str, str, AgentGrant]:
    access_token = f"{ACCESS_TOKEN_PREFIX}{token_urlsafe(32)}"
    refresh_token = f"{REFRESH_TOKEN_PREFIX}{token_urlsafe(32)}"
    grant = AgentGrant(
        grant_id=grant_id,
        registration_id=registration_id,
        user_id=user_id,
        scopes=scopes,
        access_token_hash=hash_grant_token(access_token),
        access_token_expires_at=moment + timedelta(seconds=lifetimes.access_seconds),
        refresh_token_hash=hash_grant_token(refresh_token),
        refresh_token_expires_at=moment + timedelta(seconds=lifetimes.refresh_seconds),
        granted_at=granted_at,
    )
    return access_token, refresh_token, grant


# --- Presenting a grant to /mcp -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolveGrantAccessToken:
    grants: AgentGrantRepository
    registrations: AgentRegistrationRepository
    users: UserRepository
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, token: str | None) -> AgentClient | None:
        if not token:
            return None
        moment = self.now()
        grant = self.grants.get_by_access_token_hash(hash_grant_token(token))
        if grant is None or not grant.access_token_is_valid_at(moment):
            return None
        # A deactivated user's agents stop with them, without waiting for
        # every grant to be revoked one by one.
        user = self.users.get(grant.user_id)
        if user is None or not user.is_active:
            return None
        registration = self.registrations.get(grant.registration_id)
        if registration is None:
            return None
        return grant.as_agent_client(
            username=user.username, client_name=registration.client_name, moment=moment
        )


class _TokenResolver(Protocol):
    def execute(self, token: str | None) -> AgentClient | None: ...


@dataclass(frozen=True, slots=True)
class ResolveAgentBearer:
    """Whichever kind of bearer arrived at `/mcp`, resolved to the one principal the tools know."""

    resolve_credential: _TokenResolver
    resolve_grant: _TokenResolver

    def execute(self, token: str | None) -> AgentClient | None:
        if not token:
            return None
        if token.startswith(ACCESS_TOKEN_PREFIX):
            return self.resolve_grant.execute(token)
        return self.resolve_credential.execute(token)


# --- Seeing and revoking grants ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentGrantSummary:
    """A grant as a person reads it: whose, to what, allowed to do what, until when."""

    grant: AgentGrant
    username: str
    full_name: str
    client_name: str
    redirect_hosts: tuple[str, ...]

    @property
    def grant_id(self) -> str:
        return self.grant.grant_id

    @property
    def is_active(self) -> bool:
        return not self.grant.is_revoked

    @property
    def display_name(self) -> str:
        """The person's own label when they gave one, else the client's name."""
        return self.grant.label or self.client_name


@dataclass(frozen=True, slots=True)
class ListAgentGrants:
    grants: AgentGrantRepository
    registrations: AgentRegistrationRepository
    users: UserRepository

    def execute(self, *, user_id: str | None = None) -> tuple[AgentGrantSummary, ...]:
        summaries: list[AgentGrantSummary] = []
        for grant in self.grants.list_grants(user_id):
            user = self.users.get(grant.user_id)
            registration = self.registrations.get(grant.registration_id)
            if user is None or registration is None:
                continue
            summaries.append(
                AgentGrantSummary(
                    grant=grant,
                    username=user.username,
                    full_name=user.full_name,
                    client_name=registration.client_name,
                    redirect_hosts=tuple(
                        sorted({urlsplit(uri).netloc for uri in registration.redirect_uris})
                    ),
                )
            )
        return tuple(summaries)


@dataclass(frozen=True, slots=True)
class RevokeAgentGrant:
    """A user ends their own grant; an administrator may end anyone's."""

    grants: AgentGrantRepository
    record_audit: RecordAuditEvent
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, grant_id: str, *, revoked_by: User) -> AgentGrant:
        grant = _owned_or_administered(self.grants, grant_id, revoked_by)
        if grant.is_revoked:
            return grant
        revoked = grant.revoked(self.now())
        self.grants.replace(revoked)
        self.record_audit.execute(
            actor=revoked_by.username,
            action="agent_grant_revoked",
            outcome=AuditOutcome.SUCCEEDED,
            subject=grant.grant_id,
            details={"registration_id": grant.registration_id, "user_id": grant.user_id},
        )
        return revoked


GRANT_LABEL_MAX_LENGTH = 80


def _owned_or_administered(grants: AgentGrantRepository, grant_id: str, by: User) -> AgentGrant:
    """The grant, if it is this person's own or they administer users.

    The same answer whether it does not exist or is not theirs, so the page
    cannot be used to probe which grant ids exist.
    """
    grant = grants.get(grant_id)
    if grant is None or not (grant.user_id == by.user_id or by.allows(Capability.MANAGE_USERS)):
        raise IdentityValidationError("grant_id", "Grant agen tidak ditemukan.")
    return grant


@dataclass(frozen=True, slots=True)
class RenameAgentGrant:
    """Give a connection a name of one's own; an empty name clears it.

    The label is for people telling two "Claude Code" connections apart.
    Nothing the client holds - id, tokens, scopes - changes, which is why
    this is safe to offer freely; the audit trail records the old and new
    label so a renamed row can still be followed.
    """

    grants: AgentGrantRepository
    record_audit: RecordAuditEvent

    def execute(self, grant_id: str, label: str, *, renamed_by: User) -> AgentGrant:
        grant = _owned_or_administered(self.grants, grant_id, renamed_by)
        cleaned = " ".join(label.split())
        if len(cleaned) > GRANT_LABEL_MAX_LENGTH:
            raise IdentityValidationError(
                "label", f"Nama maksimal {GRANT_LABEL_MAX_LENGTH} karakter."
            )
        renamed = grant.labelled(cleaned or None)
        self.grants.replace(renamed)
        self.record_audit.execute(
            actor=renamed_by.username,
            action="agent_grant_renamed",
            outcome=AuditOutcome.SUCCEEDED,
            subject=grant.grant_id,
            details={"from": grant.label, "to": renamed.label},
        )
        return renamed


@dataclass(frozen=True, slots=True)
class DeleteAgentGrant:
    """Take a dead grant off the list.

    Only a revoked or expired grant may go: deleting a live one would end
    access with no revocation on record. Afterwards its tokens are unknown
    tokens, refused like any other.
    """

    grants: AgentGrantRepository
    record_audit: RecordAuditEvent
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, grant_id: str, *, deleted_by: User) -> None:
        grant = _owned_or_administered(self.grants, grant_id, deleted_by)
        if not grant.is_dead_at(self.now()):
            raise IdentityValidationError(
                "grant_id", "Cabut sambungan ini dulu; yang masih aktif tidak bisa dihapus."
            )
        self.grants.delete(grant.grant_id)
        self.record_audit.execute(
            actor=deleted_by.username,
            action="agent_grant_deleted",
            outcome=AuditOutcome.SUCCEEDED,
            subject=grant.grant_id,
            details={"registration_id": grant.registration_id, "user_id": grant.user_id},
        )


@dataclass(frozen=True, slots=True)
class RevokeGrantByToken:
    """RFC 7009: a client handing back a token it no longer wants.

    Succeeds silently whatever the token was: the specification says an
    unknown token is not an error, and saying otherwise would confirm which
    tokens exist.
    """

    grants: AgentGrantRepository
    record_audit: RecordAuditEvent
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def execute(self, *, token: str | None, client_id: str | None) -> None:
        if not token or not client_id:
            return
        token_hash = hash_grant_token(token)
        grant = self.grants.get_by_access_token_hash(token_hash)
        if grant is None:
            grant = self.grants.get_by_refresh_token_hash(token_hash)
        if grant is None or grant.registration_id != client_id or grant.is_revoked:
            return
        self.grants.replace(grant.revoked(self.now()))
        self.record_audit.execute(
            actor=grant.grant_id,
            actor_kind="agent",
            action="agent_grant_revoked",
            outcome=AuditOutcome.SUCCEEDED,
            subject=grant.grant_id,
            details={"reason": "client_revocation", "registration_id": grant.registration_id},
        )


def hash_grant_token(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
