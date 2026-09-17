"""The authorization-server use cases (ADR 0014), against the real repositories on SQLite.

Registration, consent, redemption, refresh and revocation in the order a
client walks through them, plus each of the ways the token endpoint must
refuse: wrong client, wrong redirect, wrong verifier, spent code, replayed
refresh token, deactivated user.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fuel_predictor.application.agent_credentials import (
    IssueAgentCredential,
    ResolveAgentCredential,
)
from fuel_predictor.application.agent_grants import (
    ACCESS_TOKEN_PREFIX,
    REFRESH_TOKEN_PREFIX,
    AuthorizationRequest,
    IssueAuthorizationCode,
    IssuedGrantTokens,
    ListAgentGrants,
    RedeemAuthorizationCode,
    RedirectableAuthorizationError,
    RefreshGrant,
    RegisterAgentClient,
    ResolveAgentBearer,
    ResolveGrantAccessToken,
    RevokeAgentGrant,
    RevokeGrantByToken,
    ValidateAuthorizationRequest,
)
from fuel_predictor.application.identity import RecordAuditEvent
from fuel_predictor.domain.agent_authorization import (
    AgentAuthorizationError,
    code_challenge_for,
)
from fuel_predictor.domain.identity import (
    AgentScope,
    Capability,
    IdentityValidationError,
    User,
    UserRole,
)
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.sqlalchemy_agent_grants import (
    SqlAlchemyAgentGrantRepository,
    SqlAlchemyAgentRegistrationRepository,
    SqlAlchemyAuthorizationCodeRepository,
)
from fuel_predictor.infrastructure.sqlalchemy_identity import (
    SqlAlchemyAgentClientRepository,
    SqlAlchemyAuditRepository,
    SqlAlchemyUserRepository,
)

_RESOURCE = "https://fuel.example/mcp"
_REDIRECT = "http://127.0.0.1:52341/callback"
_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
_CHALLENGE = code_challenge_for(_VERIFIER)
_START = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.moment = _START

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta: int) -> None:
        self.moment += timedelta(**delta)


class _Server:
    """Every use case wired to one SQLite file and one adjustable clock."""

    def __init__(self, path: Path) -> None:
        engine = build_engine(f"sqlite+pysqlite:///{path.as_posix()}")
        create_schema_for_tests(engine)
        factory = build_session_factory(engine)
        self.clock = _Clock()
        self.users = SqlAlchemyUserRepository(factory)
        self.audit = SqlAlchemyAuditRepository(factory)
        record_audit = RecordAuditEvent(self.audit, now=self.clock)
        registrations = SqlAlchemyAgentRegistrationRepository(factory)
        codes = SqlAlchemyAuthorizationCodeRepository(factory)
        self.grants = SqlAlchemyAgentGrantRepository(factory)
        credentials = SqlAlchemyAgentClientRepository(factory)

        self.register = RegisterAgentClient(registrations, record_audit, now=self.clock)
        self.validate = ValidateAuthorizationRequest(registrations)
        self.issue_code = IssueAuthorizationCode(codes, record_audit, now=self.clock)
        self.redeem = RedeemAuthorizationCode(
            codes, self.grants, self.users, record_audit, now=self.clock
        )
        self.refresh = RefreshGrant(self.grants, self.users, record_audit, now=self.clock)
        self.resolve_grant = ResolveGrantAccessToken(
            self.grants, registrations, self.users, now=self.clock
        )
        self.resolve_bearer = ResolveAgentBearer(
            resolve_credential=ResolveAgentCredential(credentials),
            resolve_grant=self.resolve_grant,
        )
        self.issue_credential = IssueAgentCredential(credentials, record_audit, now=self.clock)
        self.list_grants = ListAgentGrants(self.grants, registrations, self.users)
        self.revoke_grant = RevokeAgentGrant(self.grants, record_audit, now=self.clock)
        self.revoke_by_token = RevokeGrantByToken(self.grants, record_audit, now=self.clock)

    def add_user(self, username: str, role: UserRole, *, is_active: bool = True) -> User:
        user = User(
            user_id=f"USR-{username}",
            username=username,
            full_name=username.title(),
            role=role,
            password_hash="",
            is_active=is_active,
            created_at=_START,
        )
        self.users.add(user)
        return user

    def authorize(
        self,
        *,
        user: User,
        scope: str | None = "fuel:predict fuel:monitor",
        consented: frozenset[AgentScope] | None = None,
        redirect_uri: str = _REDIRECT,
    ) -> tuple[str, str]:
        """Register a client and walk the user through consent; returns (client_id, code)."""
        registration = self.register.execute(
            client_name="Claude Code", redirect_uris=[redirect_uri]
        )
        request = self.validate.execute(
            client_id=registration.registration_id,
            redirect_uri=redirect_uri,
            response_type="code",
            code_challenge=_CHALLENGE,
            code_challenge_method="S256",
            scope=scope,
            state="xyz",
            resource=_RESOURCE,
            expected_resource=_RESOURCE,
        )
        issued = self.issue_code.execute(
            request, user, consented if consented is not None else request.requested_scopes
        )
        assert issued.state == "xyz"
        return registration.registration_id, issued.code


@pytest.fixture
def server(tmp_path: Path) -> _Server:
    return _Server(tmp_path / "grants.sqlite3")


def _redeem(server: _Server, *issued: str, **overrides: str | None) -> IssuedGrantTokens:
    """Redeem the (client_id, code) pair as a well-behaved client would, unless overridden."""
    registered_client, code = issued
    arguments: dict[str, str | None] = {
        "code": code,
        "client_id": registered_client,
        "redirect_uri": _REDIRECT,
        "code_verifier": _VERIFIER,
        "resource": _RESOURCE,
    }
    arguments.update(overrides)
    return server.redeem.execute(expected_resource=_RESOURCE, **arguments)


# --- the happy path, end to end ------------------------------------------------------


def test_a_user_can_connect_an_agent_and_it_reaches_mcp_as_them(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)

    tokens = server.redeem.execute(
        code=code,
        client_id=client_id,
        redirect_uri=_REDIRECT,
        code_verifier=_VERIFIER,
        resource=_RESOURCE,
        expected_resource=_RESOURCE,
    )
    assert tokens.access_token.startswith(ACCESS_TOKEN_PREFIX)
    assert tokens.refresh_token.startswith(REFRESH_TOKEN_PREFIX)
    assert tokens.expires_in == 3600
    assert tokens.scopes == frozenset({AgentScope.PREDICT, AgentScope.MONITOR})

    principal = server.resolve_bearer.execute(tokens.access_token)
    assert principal is not None
    assert principal.name == "andi via Claude Code"
    assert principal.has_scope(AgentScope.PREDICT)
    assert not principal.has_scope(AgentScope.MODELS_READ)
    assert principal.allows(Capability.CREATE_PREDICTION)

    actions = [record.action for record in server.audit.list_recent(10)]
    assert "agent_client_registered" in actions
    assert "agent_consent_granted" in actions
    assert "agent_grant_issued" in actions


def test_static_credentials_still_resolve_through_the_same_bearer_resolver(
    server: _Server,
) -> None:
    issued = server.issue_credential.execute(
        "CI bot", frozenset({AgentScope.MONITOR}), issued_by="admin"
    )
    principal = server.resolve_bearer.execute(issued.token)
    assert principal is not None
    assert principal.name == "CI bot"
    assert server.resolve_bearer.execute("fpg_not-a-real-grant") is None
    assert server.resolve_bearer.execute(None) is None


# --- the authorization request -------------------------------------------------------------


def test_an_unknown_client_or_unregistered_redirect_is_refused_without_redirecting(
    server: _Server,
) -> None:
    registration = server.register.execute(client_name="Cursor", redirect_uris=[_REDIRECT])
    with pytest.raises(AgentAuthorizationError) as unknown:
        server.validate.execute(
            client_id="REG-nope",
            redirect_uri=_REDIRECT,
            response_type="code",
            code_challenge=_CHALLENGE,
            code_challenge_method="S256",
            scope=None,
            state=None,
            resource=None,
            expected_resource=_RESOURCE,
        )
    assert unknown.value.error == "invalid_client"
    assert not isinstance(unknown.value, RedirectableAuthorizationError)

    with pytest.raises(AgentAuthorizationError) as wrong_redirect:
        server.validate.execute(
            client_id=registration.registration_id,
            redirect_uri="http://127.0.0.1:52341/elsewhere",
            response_type="code",
            code_challenge=_CHALLENGE,
            code_challenge_method="S256",
            scope=None,
            state=None,
            resource=None,
            expected_resource=_RESOURCE,
        )
    assert not isinstance(wrong_redirect.value, RedirectableAuthorizationError)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("response_type", "token", "unsupported_response_type"),
        ("code_challenge", None, "invalid_request"),
        ("code_challenge_method", "plain", "invalid_request"),
        ("scope", "fuel:predict openid", "invalid_scope"),
        ("resource", "https://other.example/mcp", "invalid_target"),
    ],
)
def test_other_request_faults_are_sent_back_to_the_registered_redirect(
    server: _Server, field: str, value: str | None, error: str
) -> None:
    registration = server.register.execute(client_name="Cursor", redirect_uris=[_REDIRECT])
    arguments: dict[str, str | None] = {
        "client_id": registration.registration_id,
        "redirect_uri": _REDIRECT,
        "response_type": "code",
        "code_challenge": _CHALLENGE,
        "code_challenge_method": "S256",
        "scope": None,
        "state": "abc",
        "resource": None,
    }
    arguments[field] = value
    with pytest.raises(RedirectableAuthorizationError) as raised:
        server.validate.execute(expected_resource=_RESOURCE, **arguments)
    assert raised.value.error == error
    assert raised.value.redirect_uri == _REDIRECT
    assert raised.value.state == "abc"


def test_the_only_registered_redirect_is_assumed_when_the_request_omits_it(
    server: _Server,
) -> None:
    registration = server.register.execute(client_name="Cursor", redirect_uris=[_REDIRECT])
    request = server.validate.execute(
        client_id=registration.registration_id,
        redirect_uri=None,
        response_type="code",
        code_challenge=_CHALLENGE,
        code_challenge_method="S256",
        scope=None,
        state=None,
        resource=None,
        expected_resource=_RESOURCE,
    )
    assert request.redirect_uri == _REDIRECT
    assert request.redirect_host == "127.0.0.1:52341"


def test_the_consent_screen_only_offers_what_the_user_may_delegate(server: _Server) -> None:
    operator = server.add_user("andi", UserRole.OPERATOR)
    admin = server.add_user("root", UserRole.ADMINISTRATOR)
    registration = server.register.execute(client_name="Cursor", redirect_uris=[_REDIRECT])
    request = AuthorizationRequest(
        registration=registration,
        redirect_uri=_REDIRECT,
        requested_scopes=frozenset({AgentScope.PREDICT, AgentScope.MODELS_ADMIN}),
        code_challenge=_CHALLENGE,
        state=None,
    )
    assert request.offered_scopes_for(operator) == frozenset({AgentScope.PREDICT})
    assert request.offered_scopes_for(admin) == frozenset(
        {AgentScope.PREDICT, AgentScope.MODELS_ADMIN}
    )


def test_consenting_to_nothing_usable_is_refused_back_to_the_client(server: _Server) -> None:
    operator = server.add_user("andi", UserRole.OPERATOR)
    with pytest.raises(RedirectableAuthorizationError) as raised:
        server.authorize(
            user=operator,
            scope="fuel:predict models:admin",
            consented=frozenset({AgentScope.MODELS_ADMIN}),
        )
    assert raised.value.error == "invalid_scope"


# --- redeeming the code -----------------------------------------------------------------------


def test_a_code_cannot_be_redeemed_twice(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    _redeem(server, client_id, code)
    with pytest.raises(AgentAuthorizationError) as raised:
        _redeem(server, client_id, code)
    assert raised.value.error == "invalid_grant"


def test_a_code_expires_after_five_minutes(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    server.clock.advance(minutes=5)
    with pytest.raises(AgentAuthorizationError) as raised:
        _redeem(server, client_id, code)
    assert raised.value.error == "invalid_grant"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("client_id", "REG-someone-else"),
        ("redirect_uri", "http://127.0.0.1:52341/other"),
        ("code_verifier", "wrong-wrong-wrong-wrong-wrong-wrong-wrong-wrong"),
        ("code", "not-the-code"),
    ],
)
def test_the_token_request_must_agree_with_the_authorization_request(
    server: _Server, field: str, value: str
) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    with pytest.raises(AgentAuthorizationError) as raised:
        _redeem(server, client_id, code, **{field: value})
    assert raised.value.error == "invalid_grant"
    # And the code was not spent by the failed attempt.
    _redeem(server, client_id, code)


def test_a_missing_verifier_is_a_malformed_request_not_a_bad_grant(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    with pytest.raises(AgentAuthorizationError) as raised:
        _redeem(server, client_id, code, code_verifier=None)
    assert raised.value.error == "invalid_request"


# --- refreshing ---------------------------------------------------------------------------------


def test_refreshing_rotates_both_tokens_and_the_old_access_token_stops_working(
    server: _Server,
) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    first = _redeem(server, client_id, code)
    server.clock.advance(hours=2)
    assert server.resolve_grant.execute(first.access_token) is None

    second = server.refresh.execute(
        refresh_token=first.refresh_token,
        client_id=client_id,
        scope=None,
    )
    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert server.resolve_grant.execute(second.access_token) is not None
    assert len(server.list_grants.execute()) == 1, "refresh keeps the grant, not a new one"


def test_replaying_a_rotated_refresh_token_revokes_the_whole_grant(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    first = _redeem(server, client_id, code)
    second = server.refresh.execute(
        refresh_token=first.refresh_token,
        client_id=client_id,
        scope=None,
    )

    with pytest.raises(AgentAuthorizationError) as raised:
        server.refresh.execute(
            refresh_token=first.refresh_token,
            client_id=client_id,
            scope=None,
        )
    assert raised.value.error == "invalid_grant"
    # The legitimate holder is locked out too, and has to re-consent.
    assert server.resolve_grant.execute(second.access_token) is None
    with pytest.raises(AgentAuthorizationError):
        server.refresh.execute(refresh_token=second.refresh_token, client_id=client_id, scope=None)
    (summary,) = server.list_grants.execute()
    assert not summary.is_active


def test_refresh_cannot_widen_scopes_and_belongs_to_one_client(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi, scope="fuel:predict")
    tokens = _redeem(server, client_id, code)
    refresh_token = tokens.refresh_token

    with pytest.raises(AgentAuthorizationError) as widened:
        server.refresh.execute(
            refresh_token=refresh_token, client_id=client_id, scope="models:read"
        )
    assert widened.value.error == "invalid_scope"

    with pytest.raises(AgentAuthorizationError) as other_client:
        server.refresh.execute(refresh_token=refresh_token, client_id="REG-other", scope=None)
    assert other_client.value.error == "invalid_grant"


def test_a_refresh_token_expires_after_thirty_days(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    tokens = _redeem(server, client_id, code)
    server.clock.advance(days=30)
    with pytest.raises(AgentAuthorizationError):
        server.refresh.execute(
            refresh_token=tokens.refresh_token,
            client_id=client_id,
            scope=None,
        )


# --- ending a grant -------------------------------------------------------------------------------


def test_a_deactivated_user_takes_their_agents_with_them(server: _Server) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    tokens = _redeem(server, client_id, code)
    server.users.replace(
        User(
            user_id=andi.user_id,
            username=andi.username,
            full_name=andi.full_name,
            role=andi.role,
            password_hash=andi.password_hash,
            is_active=False,
            created_at=andi.created_at,
        )
    )
    assert server.resolve_grant.execute(tokens.access_token) is None
    with pytest.raises(AgentAuthorizationError):
        server.refresh.execute(
            refresh_token=tokens.refresh_token,
            client_id=client_id,
            scope=None,
        )


def test_users_see_and_revoke_their_own_grants_and_administrators_anyone_s(
    server: _Server,
) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    budi = server.add_user("budi", UserRole.OPERATOR)
    admin = server.add_user("root", UserRole.ADMINISTRATOR)
    andi_client, andi_code = server.authorize(user=andi)
    budi_client, budi_code = server.authorize(user=budi)
    andi_tokens = _redeem(server, andi_client, andi_code)
    budi_tokens = _redeem(server, budi_client, budi_code)

    assert {summary.username for summary in server.list_grants.execute()} == {"andi", "budi"}
    (mine,) = server.list_grants.execute(user_id=andi.user_id)
    assert mine.username == "andi"
    assert mine.client_name == "Claude Code"
    assert mine.redirect_hosts == ("127.0.0.1:52341",)

    (budis,) = server.list_grants.execute(user_id=budi.user_id)
    with pytest.raises(IdentityValidationError):
        server.revoke_grant.execute(budis.grant_id, revoked_by=andi)
    assert server.resolve_grant.execute(budi_tokens.access_token) is not None

    server.revoke_grant.execute(mine.grant_id, revoked_by=andi)
    assert server.resolve_grant.execute(andi_tokens.access_token) is None

    server.revoke_grant.execute(budis.grant_id, revoked_by=admin)
    assert server.resolve_grant.execute(budi_tokens.access_token) is None


def test_a_client_can_hand_back_either_token_and_unknown_tokens_are_ignored(
    server: _Server,
) -> None:
    andi = server.add_user("andi", UserRole.OPERATOR)
    client_id, code = server.authorize(user=andi)
    tokens = _redeem(server, client_id, code)

    server.revoke_by_token.execute(token="fpr_nobody", client_id=client_id)
    server.revoke_by_token.execute(token=tokens.refresh_token, client_id="REG-other")
    assert server.resolve_grant.execute(tokens.access_token) is not None

    server.revoke_by_token.execute(token=tokens.refresh_token, client_id=client_id)
    assert server.resolve_grant.execute(tokens.access_token) is None


# --- registration ---------------------------------------------------------------------


def test_registration_needs_a_name_and_at_least_one_safe_redirect(server: _Server) -> None:
    with pytest.raises(AgentAuthorizationError) as nameless:
        server.register.execute(client_name="  ", redirect_uris=[_REDIRECT])
    assert nameless.value.error == "invalid_client_metadata"

    with pytest.raises(AgentAuthorizationError) as no_redirect:
        server.register.execute(client_name="Cursor", redirect_uris=[])
    assert no_redirect.value.error == "invalid_redirect_uri"

    with pytest.raises(AgentAuthorizationError) as unsafe:
        server.register.execute(
            client_name="Cursor", redirect_uris=[_REDIRECT, "http://evil.example/cb"]
        )
    assert unsafe.value.error == "invalid_redirect_uri"
