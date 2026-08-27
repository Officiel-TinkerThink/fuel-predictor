"""Privileged MCP tools stay off unless deliberately enabled (Phase 5).

The plan gates validate/activate/rollback on the read-only surface proving
itself in production and on a security review. These tests hold that gate in
place: it is enforced by configuration, not by the absence of code, and a
regression that quietly opened it would otherwise be invisible.
"""

import json
from typing import Any

import pytest

from fuel_predictor.delivery.mcp_privileged import ConfirmationTokens, build_privileged_tools
from fuel_predictor.domain.identity import (
    DEFAULT_AGENT_SCOPES,
    AgentClient,
    AgentScope,
    Capability,
    capabilities_for_scopes,
)
from tests.test_agent_mcp_surface import _issue, _rpc, _signed_in, _tool_names

_SECRET = b"kunci-uji-yang-cukup-panjang-32b"


class _Result:
    def __init__(self, activated: Any, previous: str | None) -> None:
        self.activated = activated
        self.previous_version_id = previous


class _Model:
    def __init__(self, model_version_id: str) -> None:
        self.model_version_id = model_version_id


class _FakeActivation:
    def __init__(self) -> None:
        self.activated: list[str] = []
        self.rollbacks: list[tuple[str, str]] = []

    def execute(self, model_version_id: str) -> _Result:
        self.activated.append(model_version_id)
        return _Result(_Model(model_version_id), "MDL-lama")

    def rollback(
        self,
        target_version_id: str,
        expected_active_version_id: str | None,
        actor: str,
        reason: str,
    ) -> _Result:
        self.rollbacks.append((target_version_id, reason))
        return _Result(_Model(target_version_id), expected_active_version_id)

    def inspect(self, model_version_id: str) -> dict[str, Any]:
        return {"model_version_id": model_version_id, "activatable": True}


class _FakeReader:
    def get_active(self) -> _Model:
        return _Model("MDL-aktif")


@pytest.fixture
def tools() -> tuple[dict[str, Any], _FakeActivation]:
    activation = _FakeActivation()
    built = build_privileged_tools(
        activate_retained_package=activation,
        rollback_model_version=lambda v, e, r: activation.rollback(v, e, "mcp-agent", r),
        model_reader=_FakeReader(),
        validate_retained_package=activation.inspect,
        tokens=ConfirmationTokens(secret=_SECRET),
    )
    return {tool.name: tool for tool in built}, activation


def test_privileged_scope_is_never_granted_by_default() -> None:
    assert AgentScope.MODELS_ADMIN not in DEFAULT_AGENT_SCOPES


def test_the_privileged_scope_is_the_only_one_granting_model_management() -> None:
    for scope in AgentScope:
        granted = capabilities_for_scopes(frozenset({scope}))
        if scope is AgentScope.MODELS_ADMIN:
            assert Capability.MANAGE_MODELS in granted
        else:
            assert Capability.MANAGE_MODELS not in granted


def test_privileged_tools_are_absent_unless_configuration_enables_them(tmp_path: Any) -> None:
    """The default deployment must not expose these at all."""
    with _signed_in(tmp_path) as client:
        token = _issue(client, "Agen Admin", ["fuel:predict", "models:read"])
        listed = _tool_names(_rpc(client, token, "tools/list"))

    assert "activate_model_version" not in listed
    assert "rollback_model_version" not in listed
    assert "validate_model_package" not in listed


def test_activation_does_nothing_without_a_confirmation(tools: tuple) -> None:
    registry, activation = tools

    response = registry["activate_model_version"].handler({"model_version_id": "MDL-baru"})

    assert response["status"] == "confirmation_required"
    assert response["currently_active_version_id"] == "MDL-aktif"
    # The decisive assertion: nothing happened.
    assert activation.activated == []


def test_activation_proceeds_once_confirmed(tools: tuple) -> None:
    registry, activation = tools
    preview = registry["activate_model_version"].handler({"model_version_id": "MDL-baru"})

    response = registry["activate_model_version"].handler(
        {"model_version_id": "MDL-baru", "confirm_token": preview["confirm_token"]}
    )

    assert response["status"] == "activated"
    assert activation.activated == ["MDL-baru"]


def test_a_confirmation_cannot_be_replayed_against_a_different_version(tools: tuple) -> None:
    """A token approving one model must not approve another."""
    registry, activation = tools
    preview = registry["activate_model_version"].handler({"model_version_id": "MDL-baru"})

    response = registry["activate_model_version"].handler(
        {"model_version_id": "MDL-lain", "confirm_token": preview["confirm_token"]}
    )

    assert response["status"] == "confirmation_required"
    assert activation.activated == []


def test_a_confirmation_for_activation_does_not_authorise_a_rollback(tools: tuple) -> None:
    registry, activation = tools
    preview = registry["activate_model_version"].handler({"model_version_id": "MDL-baru"})

    response = registry["rollback_model_version"].handler(
        {
            "model_version_id": "MDL-baru",
            "reason": "prediksi meleset",
            "confirm_token": preview["confirm_token"],
        }
    )

    assert response["status"] == "confirmation_required"
    assert activation.rollbacks == []


def test_rollback_requires_a_reason(tools: tuple) -> None:
    registry, _ = tools

    with pytest.raises(ValueError, match="Alasan"):
        registry["rollback_model_version"].handler(
            {"model_version_id": "MDL-lama", "reason": "   "}
        )


def test_rollback_records_its_reason_when_confirmed(tools: tuple) -> None:
    registry, activation = tools
    preview = registry["rollback_model_version"].handler(
        {"model_version_id": "MDL-lama", "reason": "prediksi meleset jauh"}
    )

    response = registry["rollback_model_version"].handler(
        {
            "model_version_id": "MDL-lama",
            "reason": "prediksi meleset jauh",
            "confirm_token": preview["confirm_token"],
        }
    )

    assert response["status"] == "rolled_back"
    assert activation.rollbacks == [("MDL-lama", "prediksi meleset jauh")]


def test_no_privileged_tool_accepts_model_bytes(tools: tuple) -> None:
    """An acceptance criterion: model binaries never travel through MCP arguments.

    A model reaches the system only by a human uploading a package, so a
    compromised agent can choose among vetted models but cannot introduce one.
    """
    registry, _ = tools
    for tool in registry.values():
        schema = json.dumps(tool.input_schema).lower()
        assert tool.input_schema["additionalProperties"] is False
        for forbidden in ("bytes", "artifact", "artefak", "base64", "content", "payload", "file"):
            assert forbidden not in schema, (tool.name, forbidden)


def test_every_privileged_tool_requires_the_privileged_scope(tools: tuple) -> None:
    registry, _ = tools
    read_only = AgentClient(
        client_id="AGT-1",
        name="Agen Baca",
        scopes=DEFAULT_AGENT_SCOPES,
        token_hash="x",
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        is_active=True,
    )
    for tool in registry.values():
        assert tool.scope is AgentScope.MODELS_ADMIN
        assert not read_only.has_scope(tool.scope)


def test_the_issue_form_does_not_pre_tick_the_privileged_scope(tmp_path: Any) -> None:
    """An administrator must choose `models:admin`, not inherit it from the form.

    The form pre-checked every scope at one point, which would have handed the
    privileged scope to every credential issued by someone accepting the page
    as presented.
    """
    with _signed_in(tmp_path) as client:
        page = client.get("/integrasi-agen").text

    admin_input = page[page.index('value="models:admin"') :]
    admin_input = admin_input[: admin_input.index(">") + 1]
    assert "checked" not in admin_input

    read_input = page[page.index('value="models:read"') :]
    read_input = read_input[: read_input.index(">") + 1]
    assert "checked" in read_input


def test_the_audit_trail_distinguishes_a_preview_from_a_real_activation(tmp_path: Any) -> None:
    """Two calls recorded as a bare "succeeded" read as two activations.

    The first call to a privileged tool only previews and changes nothing. An
    auditor reconstructing an incident must be able to tell which of an agent's
    calls actually moved the active model.
    """
    from fuel_predictor.delivery.mcp_server import _outcome_note

    assert _outcome_note({"status": "confirmation_required"}) == "confirmation_required"
    assert _outcome_note({"status": "activated"}) == "activated"
    assert _outcome_note({"status": "rolled_back"}) == "rolled_back"
    # Read-only tools return lists or plain values and simply have no status.
    assert _outcome_note([{"model_version_id": "MDL-1"}]) is None
    assert _outcome_note(None) is None
