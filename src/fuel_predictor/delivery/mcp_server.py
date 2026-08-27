"""Read-only MCP surface (Phase 4, ADR 0008).

MCP is a delivery adapter, nothing more: every tool calls the same
application use case the web pages and REST routes call, so a business rule
cannot drift between how a human sees it and how an agent does.

Read-only by design for this phase. Nothing here uploads a model, activates
one, or rolls back — those are Phase 5 and stay unavailable until read-only
operation has proven itself, per the plan.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fuel_predictor.application.agent_credentials import ResolveAgentCredential
from fuel_predictor.application.identity import RecordAuditEvent
from fuel_predictor.domain.identity import AgentClient, AgentScope, AuditOutcome

_BEARER = "bearer "


class McpAuthenticationError(Exception):
    """No usable credential was presented."""


class McpUnknownToolError(Exception):
    """No tool by that name is registered.

    Deliberately not a ``LookupError``: the transport maps this to JSON-RPC
    "method not found", and a tool raising ``KeyError`` internally must not be
    mistaken for the tool itself being absent.
    """


class McpAuthorizationError(Exception):
    def __init__(self, scope: AgentScope) -> None:
        super().__init__(f"Cakupan {scope} diperlukan untuk alat ini.")
        self.scope = scope


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    description: str
    scope: AgentScope
    input_schema: dict[str, Any]
    handler: Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class McpToolRegistry:
    """The read/compute tools the plan lists for the initial launch.

    Each declares the single scope it needs, so authorising a call is a
    lookup rather than a judgement made at each call site.
    """

    tools: tuple[McpTool, ...]

    def get(self, name: str) -> McpTool | None:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def visible_to(self, client: AgentClient) -> tuple[McpTool, ...]:
        """Only advertise what this client could actually call.

        Listing a tool the caller cannot use invites an agent to plan around
        a capability it does not have, then fail partway through.
        """
        return tuple(tool for tool in self.tools if client.has_scope(tool.scope))


@dataclass(frozen=True, slots=True)
class McpRequestHandler:
    """Authenticates, authorises, audits, and dispatches one tool call."""

    registry: McpToolRegistry
    resolve_credential: ResolveAgentCredential
    record_audit: RecordAuditEvent

    def authenticate(self, authorization_header: str | None) -> AgentClient:
        token = _bearer_token(authorization_header)
        client = self.resolve_credential.execute(token)
        if client is None:
            # Deliberately uniform: a revoked credential and a nonsense one
            # give the same answer, so probing cannot distinguish them.
            raise McpAuthenticationError("Kredensial agen tidak valid atau sudah dicabut.")
        return client

    def call(
        self, client: AgentClient, tool_name: str, arguments: Mapping[str, Any]
    ) -> Any:
        tool = self.registry.get(tool_name)
        if tool is None:
            self._audit(client, tool_name, AuditOutcome.FAILED, "alat tidak dikenal")
            raise McpUnknownToolError(f"Alat '{tool_name}' tidak dikenal.")

        if not client.has_scope(tool.scope):
            self._audit(client, tool_name, AuditOutcome.DENIED, f"butuh {tool.scope}")
            raise McpAuthorizationError(tool.scope)

        try:
            result = tool.handler(arguments)
        except Exception as error:  # noqa: BLE001 - audited, then re-raised
            self._audit(
                client, tool_name, AuditOutcome.FAILED, f"{type(error).__name__}: {error}"
            )
            raise

        # A privileged tool's first call only previews; it returns a status and
        # changes nothing. Recording both calls as a bare "succeeded" would let
        # the trail read as though the agent activated a model twice, which is
        # exactly the wrong thing to be ambiguous about.
        self._audit(client, tool_name, AuditOutcome.SUCCEEDED, _outcome_note(result))
        return result

    def _audit(
        self,
        client: AgentClient,
        tool_name: str,
        outcome: AuditOutcome,
        note: str | None,
    ) -> None:
        # Records caller, tool, outcome and a short note. Arguments are
        # summarised rather than stored verbatim: an audit trail that copies
        # whole payloads becomes its own data-retention problem.
        details: dict[str, str | int | float | bool | None] = {
            "client_id": client.client_id,
            "tool": tool_name,
        }
        if note is not None:
            details["note"] = note[:500]
        self.record_audit.execute(
            actor=client.name,
            action=f"mcp_tool:{tool_name}",
            outcome=outcome,
            actor_kind="agent",
            subject=tool_name,
            details=details,
        )


def _outcome_note(result: Any) -> str | None:
    """The tool's own status, when it reports one, so the audit is unambiguous."""
    if isinstance(result, Mapping):
        status = result.get("status")
        if isinstance(status, str):
            return status
    return None


def _bearer_token(header: str | None) -> str | None:
    if not header or not header.lower().startswith(_BEARER):
        return None
    return header[len(_BEARER) :].strip() or None


def build_registry(
    generate_prediction: Any,
    create_operation: Any,
    monitoring_dashboard: Any,
    prediction_performance: Any,
    model_reader: Any,
    monitoring_runs: Any,
    has_retained_package: Callable[[str], bool] = lambda _version: False,
) -> McpToolRegistry:
    """Wire the plan's initial read/compute tools onto existing use cases."""

    def predict_fuel(arguments: Mapping[str, Any]) -> dict[str, Any]:
        from fuel_predictor.application.daily_operations import CreateDailyOperationCommand
        from fuel_predictor.domain.daily_operation import (
            ActivityMode,
            DistanceSource,
            VehicleCategory,
        )

        operation = create_operation.execute(
            CreateDailyOperationCommand(
                vehicle_category=VehicleCategory(arguments["vehicle_category"]),
                activity_mode=ActivityMode(arguments["activity_mode"]),
                lifting_hours=arguments.get("lifting_hours"),
                total_distance_km=float(arguments["total_distance_km"]),
                distance_source=DistanceSource(arguments.get("distance_source", "manual")),
                stop_sequence=tuple(arguments.get("stop_sequence", ())),
            )
        )
        prediction = generate_prediction.execute(operation.operation_id)
        return {
            "operation_id": prediction.operation_id,
            "estimated_fuel_requirement_liters": prediction.estimated_fuel_requirement_liters,
            "recommended_allocation_liters": prediction.recommended_allocation_liters,
            "uncertainty_interval_liters": {
                "lower": prediction.uncertainty_lower_liters,
                "upper": prediction.uncertainty_upper_liters,
            },
            "model_version_id": prediction.model.model_version_id,
            # Carried deliberately: an agent must be able to tell an estimate
            # of prepared fuel from verified consumption.
            "safety_policy": prediction.safety_policy,
        }

    def get_service_health(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        latest = monitoring_runs.latest()
        successful = monitoring_runs.latest_successful()
        return {
            "last_monitoring_success": successful.finished_at.isoformat() if successful else None,
            "last_monitoring_attempt": latest.finished_at.isoformat() if latest else None,
            "last_attempt_succeeded": latest.succeeded if latest else None,
            "summary": successful.summary if successful else None,
        }

    def get_drift_summary(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        drift = monitoring_dashboard.execute().feature_drift
        return {
            "status": drift.status,
            "drift_share": drift.drift_share,
            "threshold": drift.threshold,
            "drifting_features": list(drift.drifting_features),
            # Both window sizes travel with the verdict so a caller can judge
            # how much confidence it deserves.
            "reference_row_count": drift.reference_row_count,
            "current_row_count": drift.current_row_count,
        }

    def get_performance_summary(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        report = prediction_performance.execute()
        overall = report.overall
        return {
            "matched_record_count": overall.matched_record_count,
            "mae_liters": overall.mae_liters,
            "rmse_liters": overall.rmse_liters,
            "smape_percent": overall.smape_percent,
            "interval_coverage_percent": overall.interval_coverage_percent,
            "by_vehicle_category": [
                {
                    "vehicle_category": category.value,
                    "matched_record_count": metrics.matched_record_count,
                    "mae_liters": metrics.mae_liters,
                }
                for category, metrics in report.by_vehicle_category
            ],
        }

    def get_current_model(_arguments: Mapping[str, Any]) -> dict[str, Any] | None:
        active = model_reader.get_active()
        if active is None:
            return None
        return {
            "model_version_id": active.model_version_id,
            "algorithm": active.algorithm,
            "feature_version": active.feature_version,
            "dataset_version_id": active.dataset_version_id,
            "trained_at": active.trained_at.isoformat(),
        }

    def list_model_versions(_arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Every version, not just the ones awaiting review.

        This listed candidates only, which made retired versions invisible —
        and `rollback_model_version` takes a version id, so an agent asked to
        roll back had no way to discover a target. `retired_at` is carried so
        the most recently retired version, the usual rollback target, can be
        identified without guessing.
        """
        return [
            {
                "model_version_id": model.model_version_id,
                "lifecycle_status": model.lifecycle_status.value,
                "trained_at": model.trained_at.isoformat(),
                "promoted_at": model.promoted_at.isoformat() if model.promoted_at else None,
                "retired_at": model.retired_at.isoformat() if model.retired_at else None,
                # Rollback needs the target's bytes to still exist (ADR 0010).
                # Models trained in this process have no package, so listing
                # them without this flag would advertise rollback targets that
                # cannot be rolled back to — the same trap `visible_to` avoids
                # for tools.
                "rollback_available": has_retained_package(model.model_version_id),
            }
            for model in model_reader.list_all()
        ]

    def get_prediction_input_schema(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        return _PREDICT_INPUT_SCHEMA

    return McpToolRegistry(
        tools=(
            McpTool(
                name="predict_fuel",
                description=(
                    "Perkirakan kebutuhan bahan bakar satu operasi harian. Nilai yang "
                    "dikembalikan adalah estimasi bahan bakar disiapkan, bukan konsumsi aktual."
                ),
                scope=AgentScope.PREDICT,
                input_schema=_PREDICT_INPUT_SCHEMA,
                handler=predict_fuel,
            ),
            McpTool(
                name="get_service_health",
                description="Status pemantauan terjadwal terakhir dan ringkasannya.",
                scope=AgentScope.MONITOR,
                input_schema=_EMPTY_SCHEMA,
                handler=get_service_health,
            ),
            McpTool(
                name="get_drift_summary",
                description="Ringkasan pergeseran distribusi fitur beserta ukuran jendelanya.",
                scope=AgentScope.MONITOR,
                input_schema=_EMPTY_SCHEMA,
                handler=get_drift_summary,
            ),
            McpTool(
                name="get_performance_summary",
                description=(
                    "Kinerja model dari bahan bakar aktual yang tercocokkan. Kosong bila "
                    "belum ada hasil aktual."
                ),
                scope=AgentScope.MONITOR,
                input_schema=_EMPTY_SCHEMA,
                handler=get_performance_summary,
            ),
            McpTool(
                name="get_current_model",
                description="Model yang sedang aktif melayani prediksi.",
                scope=AgentScope.MODELS_READ,
                input_schema=_EMPTY_SCHEMA,
                handler=get_current_model,
            ),
            McpTool(
                name="list_model_versions",
                description=(
                    "Semua versi model beserta status siklus hidupnya (kandidat, aktif, "
                    "pensiun). Hanya versi dengan rollback_available bernilai true yang "
                    "dapat dijadikan sasaran rollback."
                ),
                scope=AgentScope.MODELS_READ,
                input_schema=_EMPTY_SCHEMA,
                handler=list_model_versions,
            ),
            McpTool(
                name="get_prediction_input_schema",
                description="Skema masukan yang diterima predict_fuel.",
                scope=AgentScope.PREDICT,
                input_schema=_EMPTY_SCHEMA,
                handler=get_prediction_input_schema,
            ),
        )
    )


_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}

_PREDICT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vehicle_category", "activity_mode", "total_distance_km"],
    "properties": {
        "vehicle_category": {"type": "string", "enum": ["ANGBER"]},
        "activity_mode": {
            "type": "string",
            "enum": ["transport", "lifting", "transport_and_lifting"],
        },
        "lifting_hours": {
            "type": ["number", "null"],
            "minimum": 0,
            "description": "Wajib untuk mode yang mencakup lifting.",
        },
        "total_distance_km": {"type": "number", "exclusiveMinimum": 0},
        "distance_source": {"type": "string", "enum": ["manual", "routing_provider"]},
        "stop_sequence": {"type": "array", "items": {"type": "string"}},
    },
}


def tool_result_to_text(result: Any) -> str:
    """MCP content is text; serialise deterministically so results diff cleanly."""
    return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
