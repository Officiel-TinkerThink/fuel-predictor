"""Privileged MCP tools: validate, activate, rollback (Phase 5).

Three properties make these safe enough for an agent to hold:

1. **They move identifiers, never bytes.** A model reaches the system only by
   an operator uploading a package through the web UI. Nothing here accepts an
   artefact, so a compromised agent cannot introduce a model — only choose
   among ones a human already vetted.
2. **They require a second call to take effect.** The first call answers what
   *would* happen and returns a confirmation token; nothing changes. An agent
   that misunderstands an instruction fails at the preview, and a human reading
   the transcript sees the intent before the change.
3. **They carry the caller's own view of the current state.** Activation and
   rollback pass `expected_active_version_id` into the same conditional UPDATE
   the web UI uses, so an agent acting on a stale reading loses the race
   instead of silently overwriting a change it never saw.

Off unless `FUEL_PREDICTOR_MCP_PRIVILEGED_TOOLS_ENABLED` is set, and even then
only for credentials holding `models:admin`, which is never granted by default.
"""

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from fuel_predictor.delivery.mcp_server import McpTool
from fuel_predictor.domain.identity import AgentScope

_CONFIRM_PURPOSE = "mcp-privileged-confirm"


@dataclass(frozen=True, slots=True)
class ConfirmationTokens:
    """Binds a confirmation to the exact operation that was previewed.

    Derived from the operation and its arguments rather than stored, so a token
    cannot be replayed against a *different* version than the one the preview
    described. The secret is process-local: a restart invalidates outstanding
    confirmations, which is the safe direction to fail.
    """

    secret: bytes

    def issue(self, operation: str, subject: str, expected: str | None) -> str:
        payload = f"{_CONFIRM_PURPOSE}|{operation}|{subject}|{expected or ''}"
        return hmac.new(self.secret, payload.encode("utf-8"), sha256).hexdigest()[:32]

    def verify(
        self, operation: str, subject: str, expected: str | None, supplied: str | None
    ) -> bool:
        if not supplied:
            return False
        return hmac.compare_digest(self.issue(operation, subject, expected), supplied)


def build_privileged_tools(
    activate_retained_package: Any,
    rollback_model_version: Any,
    model_reader: Any,
    validate_retained_package: Any,
    tokens: ConfirmationTokens,
) -> tuple[McpTool, ...]:
    def _active_id() -> str | None:
        active = model_reader.get_active()
        return active.model_version_id if active else None

    def validate_model_package(arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Re-check a retained package without changing anything.

        Read-only, so it needs no confirmation. Useful on its own: it answers
        "would this activate cleanly?" before anyone tries.
        """
        version_id = str(arguments["model_version_id"])
        result: dict[str, Any] = validate_retained_package(version_id)
        return result

    def activate_model_version(arguments: Mapping[str, Any]) -> dict[str, Any]:
        version_id = str(arguments["model_version_id"])
        expected = _active_id()
        supplied = arguments.get("confirm_token")

        if not tokens.verify("activate", version_id, expected, supplied):
            return {
                "status": "confirmation_required",
                "operation": "activate",
                "model_version_id": version_id,
                "currently_active_version_id": expected,
                "confirm_token": tokens.issue("activate", version_id, expected),
                "message": (
                    f"Aktivasi {version_id} akan menggantikan "
                    f"{expected or 'tidak ada model aktif'}. "
                    "Panggil ulang dengan confirm_token untuk melanjutkan. "
                    "Konfirmasikan dengan operator manusia sebelum melanjutkan."
                ),
            }

        result = activate_retained_package.execute(version_id)
        return {
            "status": "activated",
            "model_version_id": result.activated.model_version_id,
            "previous_version_id": result.previous_version_id,
        }

    def rollback_model_version_tool(arguments: Mapping[str, Any]) -> dict[str, Any]:
        version_id = str(arguments["model_version_id"])
        reason = str(arguments.get("reason", "")).strip()
        if not reason:
            raise ValueError("Alasan rollback wajib diisi.")

        expected = _active_id()
        supplied = arguments.get("confirm_token")
        if not tokens.verify("rollback", version_id, expected, supplied):
            return {
                "status": "confirmation_required",
                "operation": "rollback",
                "model_version_id": version_id,
                "currently_active_version_id": expected,
                "confirm_token": tokens.issue("rollback", version_id, expected),
                "message": (
                    f"Rollback ke {version_id} akan menggantikan "
                    f"{expected or 'tidak ada model aktif'}. Panggil ulang dengan confirm_token."
                ),
            }

        result = rollback_model_version(version_id, expected, reason)
        return {
            "status": "rolled_back",
            "model_version_id": result.activated.model_version_id,
            "previous_version_id": result.previous_version_id,
        }

    version_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["model_version_id"],
        "properties": {
            "model_version_id": {"type": "string"},
            "confirm_token": {
                "type": "string",
                "description": "Dari panggilan pertama. Tanpa ini tidak ada yang berubah.",
            },
        },
    }
    rollback_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["model_version_id", "reason"],
        "properties": {
            "model_version_id": {"type": "string"},
            "reason": {"type": "string", "minLength": 1},
            "confirm_token": {"type": "string"},
        },
    }

    return (
        McpTool(
            name="validate_model_package",
            description=(
                "Periksa ulang paket model yang tersimpan tanpa mengubah apa pun. "
                "Menjawab apakah versi tersebut dapat diaktifkan."
            ),
            scope=AgentScope.MODELS_ADMIN,
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["model_version_id"],
                "properties": {"model_version_id": {"type": "string"}},
            },
            handler=validate_model_package,
        ),
        McpTool(
            name="activate_model_version",
            description=(
                "Aktifkan versi model yang sudah diunggah dan divalidasi. Panggilan pertama "
                "hanya menjelaskan dampaknya dan mengembalikan confirm_token; tidak ada yang "
                "berubah sampai panggilan kedua menyertakan token itu."
            ),
            scope=AgentScope.MODELS_ADMIN,
            input_schema=version_schema,
            handler=activate_model_version,
        ),
        McpTool(
            name="rollback_model_version",
            description=(
                "Kembali ke versi model lama yang berkasnya masih tersimpan. Wajib menyertakan "
                "alasan, yang dicatat sebelum perubahan dicoba. Perlu confirm_token seperti "
                "activate_model_version."
            ),
            scope=AgentScope.MODELS_ADMIN,
            input_schema=rollback_schema,
            handler=rollback_model_version_tool,
        ),
    )
