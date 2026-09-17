"""A user delegating part of their access to an agent they run (ADR 0014).

Three things exist here, in the order they come into being:

- A `RegisteredAgentClient` is a program (Claude Code, Cursor, ...) that has
  told this server who it is and where it may be sent back to. Registering
  grants nothing.
- An `AuthorizationCode` is the user's consent, in transit: minted when they
  click "allow", redeemed once by the client for a grant, and dead within
  minutes either way.
- An `AgentGrant` is the durable delegation: this user let this client act
  with these scopes. It carries the access token the client presents to
  `/mcp` and the refresh token it uses to get a new one.

Agent credentials (ADR 0008, `identity.AgentClient`) are the other way to
reach `/mcp` and are unchanged; a grant is *presented* to the MCP surface as
an `AgentClient` so the tools never learn which kind of token arrived.

Only hashes of codes and tokens exist here. The raw values live in the client
and nowhere else, so a leaked database cannot be replayed against `/mcp`.
"""

from base64 import urlsafe_b64encode
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from secrets import compare_digest
from urllib.parse import urlsplit

from fuel_predictor.domain.identity import (
    DEFAULT_AGENT_SCOPES,
    AgentClient,
    AgentScope,
    UserRole,
    capabilities_for,
    capabilities_for_scopes,
)


class AgentAuthorizationError(ValueError):
    """A request the authorization server must refuse, with the OAuth error code it answers."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


# --- Registered clients ----------------------------------------------------

# RFC 8252 §7.3: a native app listens on the loopback interface, and the
# port is whatever it managed to bind, so the scheme+host is what we pin.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def validate_redirect_uri(value: str) -> str:
    """Accept an https URL or a loopback http URL, both without a fragment.

    Anything else is a place a token could be sent that we cannot vouch for.
    A custom scheme (`cursor://`) is deliberately not accepted for now: the
    named clients all use loopback, and every scheme accepted is one more
    place a phishing client can register.
    """
    parts = urlsplit(value)
    if parts.fragment:
        raise AgentAuthorizationError(
            "invalid_redirect_uri", "URI pengalihan tidak boleh memuat fragmen (#)."
        )
    if not parts.netloc:
        raise AgentAuthorizationError(
            "invalid_redirect_uri", "URI pengalihan harus absolut, dengan skema dan host."
        )
    if parts.scheme == "https":
        return value
    if parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS:
        return value
    raise AgentAuthorizationError(
        "invalid_redirect_uri",
        "URI pengalihan harus https://, atau http:// ke alamat loopback (127.0.0.1, localhost).",
    )


@dataclass(frozen=True, slots=True)
class RegisteredAgentClient:
    """A public client (RFC 7591 dynamic registration, no secret).

    `client_name` is what the consent screen shows the user, so it is
    untrusted: the client chose it. What the user can actually verify is
    the redirect host, which is why both are displayed.
    """

    registration_id: str
    client_name: str
    redirect_uris: frozenset[str]
    registered_at: datetime

    def accepts_redirect(self, redirect_uri: str) -> bool:
        # Exact string match, per OAuth 2.1. A prefix match would let
        # `https://good.example/cb?x=` be satisfied by an attacker-chosen path.
        return redirect_uri in self.redirect_uris


# --- PKCE (RFC 7636) --------------------------------------------------------

CODE_VERIFIER_MIN_LENGTH = 43
CODE_VERIFIER_MAX_LENGTH = 128
_CODE_VERIFIER_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def code_challenge_for(verifier: str) -> str:
    """S256: BASE64URL(SHA256(verifier)) without padding, as the client computes it."""
    digest = sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_code_verifier(verifier: str, challenge: str) -> bool:
    """True when `verifier` is the secret behind `challenge`.

    Length and alphabet are checked first so a malformed verifier fails for
    a stated reason instead of merely hashing to the wrong value.
    """
    if not CODE_VERIFIER_MIN_LENGTH <= len(verifier) <= CODE_VERIFIER_MAX_LENGTH:
        return False
    if not set(verifier) <= _CODE_VERIFIER_ALPHABET:
        return False
    return compare_digest(code_challenge_for(verifier), challenge)


# --- Authorization codes ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationCode:
    """The user's consent on its way to the client. Single use, minutes to live.

    Everything the token request must agree with is pinned here: the client,
    the redirect it was sent to, the PKCE challenge, and the scopes the user
    actually approved (which may be fewer than the client asked for).
    """

    code_hash: str
    registration_id: str
    user_id: str
    scopes: frozenset[AgentScope]
    redirect_uri: str
    code_challenge: str
    issued_at: datetime
    expires_at: datetime
    redeemed_at: datetime | None = None

    def is_redeemable_at(self, moment: datetime) -> bool:
        return self.redeemed_at is None and moment < self.expires_at

    def redeemed(self, moment: datetime) -> "AuthorizationCode":
        return replace(self, redeemed_at=moment)


# --- Grants -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentGrant:
    """A user's standing delegation to one registered client.

    The grant is the unit of revocation: rotating tokens on refresh keeps the
    same grant, so the administration page shows one row per (user, client)
    consent rather than one per token ever issued.
    """

    grant_id: str
    registration_id: str
    user_id: str
    scopes: frozenset[AgentScope]
    access_token_hash: str
    access_token_expires_at: datetime
    refresh_token_hash: str
    refresh_token_expires_at: datetime
    granted_at: datetime
    refreshed_at: datetime | None = None
    revoked_at: datetime | None = None
    # The refresh token this one replaced. Presenting it again means someone
    # other than the client holds a copy, and the grant is revoked on sight.
    previous_refresh_token_hash: str | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def access_token_is_valid_at(self, moment: datetime) -> bool:
        return not self.is_revoked and moment < self.access_token_expires_at

    def refresh_token_is_valid_at(self, moment: datetime) -> bool:
        return not self.is_revoked and moment < self.refresh_token_expires_at

    def rotated(
        self,
        *,
        access_token_hash: str,
        access_token_expires_at: datetime,
        refresh_token_hash: str,
        refresh_token_expires_at: datetime,
        moment: datetime,
    ) -> "AgentGrant":
        """The same consent with fresh tokens; the previous refresh token dies with this."""
        return replace(
            self,
            access_token_hash=access_token_hash,
            access_token_expires_at=access_token_expires_at,
            refresh_token_hash=refresh_token_hash,
            refresh_token_expires_at=refresh_token_expires_at,
            refreshed_at=moment,
            previous_refresh_token_hash=self.refresh_token_hash,
        )

    def was_refreshed_with(self, refresh_token_hash: str) -> bool:
        return self.previous_refresh_token_hash == refresh_token_hash

    def revoked(self, moment: datetime) -> "AgentGrant":
        return replace(self, revoked_at=moment)

    def as_agent_client(self, *, username: str, client_name: str, moment: datetime) -> AgentClient:
        """How `/mcp` sees this grant: an agent client named after the person behind it.

        The audit trail and the rate limiter key on the name, so "andi via
        Claude Code" is both a readable actor and a bucket of its own.
        """
        return AgentClient(
            client_id=self.grant_id,
            name=f"{username} via {client_name}",
            scopes=self.scopes,
            token_hash=self.access_token_hash,
            created_at=self.granted_at,
            is_active=self.access_token_is_valid_at(moment),
            revoked_at=self.revoked_at,
        )


# --- What a user may delegate ------------------------------------------------


def delegable_scopes_for(role: UserRole) -> frozenset[AgentScope]:
    """Scopes a user of `role` may hand to an agent: never more than they hold themselves."""
    held = capabilities_for(role)
    return frozenset(
        scope for scope in AgentScope if capabilities_for_scopes(frozenset({scope})) <= held
    )


def granted_scopes(
    *, requested: frozenset[AgentScope], consented: frozenset[AgentScope], role: UserRole
) -> frozenset[AgentScope]:
    """The scopes a grant ends up with: asked for, ticked by the user, and within their role.

    Empty is an error rather than an empty grant: a token that can call
    nothing only ever confuses the client into retrying.
    """
    scopes = requested & consented & delegable_scopes_for(role)
    if not scopes:
        raise AgentAuthorizationError(
            "invalid_scope",
            "Tidak ada cakupan yang bisa diberikan; pilih sedikitnya satu cakupan yang "
            "termasuk hak akses Anda.",
        )
    return scopes


def parse_scope_parameter(value: str | None) -> frozenset[AgentScope]:
    """The space-separated `scope` request parameter, unknown names refused.

    An absent parameter asks for the read/compute defaults, which is what a
    client that has never heard of this server sends.
    """
    if value is None or not value.strip():
        return DEFAULT_AGENT_SCOPES
    scopes: set[AgentScope] = set()
    for name in value.split():
        try:
            scopes.add(AgentScope(name))
        except ValueError:
            raise AgentAuthorizationError(
                "invalid_scope", f"Cakupan '{name}' tidak dikenal."
            ) from None
    return frozenset(scopes)
