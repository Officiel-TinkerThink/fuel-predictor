"""The rules behind an OAuth grant to an agent (ADR 0014), independent of any HTTP.

These are the checks whose failure is a security hole rather than a bug:
which redirects a client may register, that PKCE actually binds the token
request to the authorization request, that a code is spent exactly once,
and that a user cannot hand an agent more than they hold.
"""

from datetime import UTC, datetime, timedelta

import pytest

from fuel_predictor.domain.agent_authorization import (
    AgentAuthorizationError,
    AgentGrant,
    AuthorizationCode,
    RegisteredAgentClient,
    code_challenge_for,
    delegable_scopes_for,
    granted_scopes,
    parse_scope_parameter,
    validate_redirect_uri,
    verify_code_verifier,
)
from fuel_predictor.domain.identity import DEFAULT_AGENT_SCOPES, AgentScope, UserRole

_NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)


# --- redirect URIs -----------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "http://127.0.0.1:52341/callback",
        "http://localhost:3000/oauth/callback",
        "http://[::1]:8080/cb",
    ],
)
def test_https_and_loopback_http_redirects_are_accepted(uri: str) -> None:
    assert validate_redirect_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "http://example.com/callback",  # plain http to the internet
        "cursor://anysphere.cursor-retrieval/oauth/callback",  # custom scheme, not yet
        "https://good.example/cb#fragment",
        "/relative/path",
        "javascript:alert(1)",
    ],
)
def test_unsafe_redirects_are_refused_with_the_oauth_error_code(uri: str) -> None:
    with pytest.raises(AgentAuthorizationError) as raised:
        validate_redirect_uri(uri)
    assert raised.value.error == "invalid_redirect_uri"


def test_registered_redirects_match_exactly_never_by_prefix() -> None:
    client = RegisteredAgentClient(
        registration_id="REG-1",
        client_name="Claude Code",
        redirect_uris=frozenset({"http://127.0.0.1:5000/callback"}),
        registered_at=_NOW,
    )
    assert client.accepts_redirect("http://127.0.0.1:5000/callback")
    assert not client.accepts_redirect("http://127.0.0.1:5000/callback/../evil")
    assert not client.accepts_redirect("http://127.0.0.1:5000/callback?next=x")
    assert not client.accepts_redirect("http://127.0.0.1:5001/callback")


# --- PKCE ---------------------------------------------------------------------


def test_s256_challenge_matches_the_rfc_7636_worked_example() -> None:
    # RFC 7636 appendix B.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert verify_code_verifier(verifier, "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")


def test_wrong_verifier_does_not_satisfy_the_challenge() -> None:
    challenge = code_challenge_for("a" * 43)
    assert not verify_code_verifier("b" * 43, challenge)


@pytest.mark.parametrize("verifier", ["a" * 42, "a" * 129, ("a" * 42) + "!"])
def test_malformed_verifiers_fail_even_if_the_hash_would_match(verifier: str) -> None:
    assert not verify_code_verifier(verifier, code_challenge_for(verifier))


# --- authorization codes -------------------------------------------------------


def _code(**overrides: object) -> AuthorizationCode:
    values: dict[str, object] = {
        "code_hash": "hash",
        "registration_id": "REG-1",
        "user_id": "USR-1",
        "scopes": frozenset({AgentScope.PREDICT}),
        "redirect_uri": "http://127.0.0.1:5000/callback",
        "code_challenge": "challenge",
        "issued_at": _NOW,
        "expires_at": _NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    return AuthorizationCode(**values)  # type: ignore[arg-type]


def test_a_code_is_redeemable_once_and_only_before_it_expires() -> None:
    code = _code()
    assert code.is_redeemable_at(_NOW + timedelta(minutes=1))
    assert not code.is_redeemable_at(_NOW + timedelta(minutes=5))

    spent = code.redeemed(_NOW + timedelta(minutes=1))
    assert not spent.is_redeemable_at(_NOW + timedelta(minutes=2))
    assert spent.redeemed_at == _NOW + timedelta(minutes=1)


# --- grants --------------------------------------------------------------------


def _grant(**overrides: object) -> AgentGrant:
    values: dict[str, object] = {
        "grant_id": "GRT-1",
        "registration_id": "REG-1",
        "user_id": "USR-1",
        "scopes": frozenset({AgentScope.PREDICT, AgentScope.MONITOR}),
        "access_token_hash": "access-1",
        "access_token_expires_at": _NOW + timedelta(hours=1),
        "refresh_token_hash": "refresh-1",
        "refresh_token_expires_at": _NOW + timedelta(days=30),
        "granted_at": _NOW,
    }
    values.update(overrides)
    return AgentGrant(**values)  # type: ignore[arg-type]


def test_access_and_refresh_tokens_expire_on_their_own_clocks() -> None:
    grant = _grant()
    later = _NOW + timedelta(hours=2)
    assert not grant.access_token_is_valid_at(later)
    assert grant.refresh_token_is_valid_at(later)
    assert not grant.refresh_token_is_valid_at(_NOW + timedelta(days=31))


def test_revoking_a_grant_kills_both_tokens_immediately() -> None:
    revoked = _grant().revoked(_NOW)
    assert revoked.is_revoked
    assert not revoked.access_token_is_valid_at(_NOW)
    assert not revoked.refresh_token_is_valid_at(_NOW)


def test_rotation_keeps_the_grant_and_replaces_both_tokens() -> None:
    rotated = _grant().rotated(
        access_token_hash="access-2",
        access_token_expires_at=_NOW + timedelta(hours=3),
        refresh_token_hash="refresh-2",
        refresh_token_expires_at=_NOW + timedelta(days=32),
        moment=_NOW + timedelta(hours=2),
    )
    assert rotated.grant_id == "GRT-1"
    assert rotated.scopes == frozenset({AgentScope.PREDICT, AgentScope.MONITOR})
    assert rotated.access_token_hash == "access-2"
    assert rotated.refresh_token_hash == "refresh-2"
    assert rotated.refreshed_at == _NOW + timedelta(hours=2)
    assert rotated.granted_at == _NOW
    # The token that was just spent is remembered so a replay can be recognised.
    assert rotated.was_refreshed_with("refresh-1")
    assert not rotated.was_refreshed_with("refresh-2")


def test_a_grant_presents_itself_to_mcp_as_an_agent_client_named_after_the_user() -> None:
    client = _grant().as_agent_client(username="andi", client_name="Claude Code", moment=_NOW)
    assert client.client_id == "GRT-1"
    assert client.name == "andi via Claude Code"
    assert client.has_scope(AgentScope.PREDICT)
    assert not client.has_scope(AgentScope.MODELS_READ)
    assert client.is_active

    expired = _grant().as_agent_client(
        username="andi", client_name="Claude Code", moment=_NOW + timedelta(hours=2)
    )
    assert not expired.is_active
    assert not expired.has_scope(AgentScope.PREDICT)


# --- what a user may delegate ------------------------------------------------------


def test_every_role_may_delegate_the_read_compute_scopes() -> None:
    for role in UserRole:
        assert delegable_scopes_for(role) >= DEFAULT_AGENT_SCOPES


def test_only_an_administrator_may_delegate_model_administration() -> None:
    assert AgentScope.MODELS_ADMIN in delegable_scopes_for(UserRole.ADMINISTRATOR)
    assert AgentScope.MODELS_ADMIN not in delegable_scopes_for(UserRole.MANAGER)
    assert AgentScope.MODELS_ADMIN not in delegable_scopes_for(UserRole.OPERATOR)


def test_granted_scopes_are_the_intersection_of_request_consent_and_role() -> None:
    scopes = granted_scopes(
        requested=frozenset({AgentScope.PREDICT, AgentScope.MODELS_ADMIN}),
        consented=frozenset({AgentScope.PREDICT, AgentScope.MODELS_ADMIN, AgentScope.MONITOR}),
        role=UserRole.OPERATOR,
    )
    assert scopes == frozenset({AgentScope.PREDICT})


def test_a_grant_that_could_call_nothing_is_refused() -> None:
    with pytest.raises(AgentAuthorizationError) as raised:
        granted_scopes(
            requested=frozenset({AgentScope.MODELS_ADMIN}),
            consented=frozenset({AgentScope.MODELS_ADMIN}),
            role=UserRole.OPERATOR,
        )
    assert raised.value.error == "invalid_scope"


def test_scope_parameter_defaults_to_read_compute_and_refuses_unknown_names() -> None:
    assert parse_scope_parameter(None) == DEFAULT_AGENT_SCOPES
    assert parse_scope_parameter("   ") == DEFAULT_AGENT_SCOPES
    assert parse_scope_parameter("fuel:predict models:read") == frozenset(
        {AgentScope.PREDICT, AgentScope.MODELS_READ}
    )
    with pytest.raises(AgentAuthorizationError) as raised:
        parse_scope_parameter("fuel:predict openid")
    assert raised.value.error == "invalid_scope"
