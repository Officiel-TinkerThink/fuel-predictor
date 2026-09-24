"""Read-only MCP surface (Phase 4, ADR 0008).

MCP is a delivery adapter, nothing more: every tool calls the same
application use case the web pages and REST routes call, so a business rule
cannot drift between how a human sees it and how an agent does.

Read-only by design for this phase. Nothing here uploads a model, activates
one, or rolls back — those are Phase 5 and stay unavailable until read-only
operation has proven itself, per the plan.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fuel_predictor.application.catalog_resolution import (
    resolve_location,
    resolve_vehicle,
    search_locations,
)
from fuel_predictor.application.locations import LocationCatalog
from fuel_predictor.application.routing import RoutePreviewProvider, RoutingProviderUnavailable
from fuel_predictor.application.similar_operations import (
    FindSimilarOperations,
    SimilarOperation,
    SimilarOperationsQuery,
)
from fuel_predictor.application.vehicles import VehicleCatalog
from fuel_predictor.domain.daily_operation import ActivityMode, DistanceSource, VehicleCategory
from fuel_predictor.domain.identity import AgentClient, AgentScope, AuditOutcome

_BEARER = "bearer "
# Deliberately not prefixed with `mcp_tool:` — see the rate-limit check.
_RATE_LIMITED_ACTION = "mcp_rate_limited"
_TOOL_ACTION_PREFIX = "mcp_tool:"


class McpAuthenticationError(Exception):
    """No usable credential was presented."""


class McpUnknownToolError(Exception):
    """No tool by that name is registered.

    Deliberately not a ``LookupError``: the transport maps this to JSON-RPC
    "method not found", and a tool raising ``KeyError`` internally must not be
    mistaken for the tool itself being absent.
    """


class McpRateLimitError(Exception):
    """This client has made too many calls in the current window."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        super().__init__(
            f"Terlalu banyak panggilan: batas {limit} per {window_seconds} detik untuk "
            "satu klien agen. Tunggu sebentar lalu coba lagi."
        )
        self.limit = limit
        self.window_seconds = window_seconds


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


class _AuditCounter(Protocol):
    """The one thing McpRequestHandler needs from the audit repository directly."""

    def count_recent_by_actor(self, actor: str, action_prefix: str, since: datetime) -> int: ...


class _CredentialResolver(Protocol):
    """What McpRequestHandler needs to turn a bearer token into a caller.

    A Protocol rather than `ResolveAgentCredential` itself, so a test double can
    stand in without being that concrete class - the same reason `RoutingProvider`
    and `LocationCatalog` are ports elsewhere in this codebase.
    """

    def execute(self, token: str | None) -> AgentClient | None: ...


class _AuditRecorder(Protocol):
    """What McpRequestHandler needs to record and rate-limit against the audit trail."""

    # A read-only property, not a plain attribute: RecordAuditEvent is a frozen
    # dataclass, so a plain annotation here (which Protocol treats as requiring
    # a settable attribute) would reject it.
    @property
    def audit_repository(self) -> _AuditCounter: ...

    def execute(
        self,
        actor: str,
        action: str,
        outcome: AuditOutcome,
        *,
        actor_kind: str = "user",
        subject: str | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class McpRequestHandler:
    """Authenticates, authorises, audits, and dispatches one tool call."""

    registry: McpToolRegistry
    resolve_credential: _CredentialResolver
    record_audit: _AuditRecorder
    # Per client, so one runaway agent cannot deny service to the others — the
    # same reason each holds its own revocable credential. 0 disables it.
    max_calls_per_window: int = 0
    window_seconds: int = 60
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def authenticate(self, authorization_header: str | None) -> AgentClient:
        token = _bearer_token(authorization_header)
        client = self.resolve_credential.execute(token)
        if client is None:
            # Deliberately uniform: a revoked credential and a nonsense one
            # give the same answer, so probing cannot distinguish them.
            raise McpAuthenticationError("Kredensial agen tidak valid atau sudah dicabut.")
        return client

    def call(self, client: AgentClient, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        tool = self.registry.get(tool_name)
        if tool is None:
            self._audit(client, tool_name, AuditOutcome.FAILED, "alat tidak dikenal")
            raise McpUnknownToolError(f"Alat '{tool_name}' tidak dikenal.")

        if not client.has_scope(tool.scope):
            self._audit(client, tool_name, AuditOutcome.DENIED, f"butuh {tool.scope}")
            raise McpAuthorizationError(tool.scope)

        if self._is_rate_limited(client):
            # Recorded under a *different* action, deliberately. The counter
            # matches `mcp_tool:`, so auditing a rejection under that prefix
            # would let each rejection extend the block: an agent that keeps
            # polling would never leave the window, and only one that went
            # completely silent could recover. A polling agent is exactly the
            # case this exists to handle.
            self.record_audit.execute(
                actor=client.name,
                action=_RATE_LIMITED_ACTION,
                outcome=AuditOutcome.DENIED,
                actor_kind="agent",
                subject=tool_name,
                details={"client_id": client.client_id, "note": "melebihi batas laju"},
            )
            raise McpRateLimitError(self.max_calls_per_window, self.window_seconds)

        # The client's name is what an operation it creates is attributed to;
        # the handler signature stays a plain mapping of arguments.
        actor_token = current_actor.set(client.name)
        try:
            result = tool.handler(arguments)
        except Exception as error:  # noqa: BLE001 - audited, then re-raised
            self._audit(client, tool_name, AuditOutcome.FAILED, f"{type(error).__name__}: {error}")
            raise
        finally:
            current_actor.reset(actor_token)

        # A privileged tool's first call only previews; it returns a status and
        # changes nothing. Recording both calls as a bare "succeeded" would let
        # the trail read as though the agent activated a model twice, which is
        # exactly the wrong thing to be ambiguous about.
        self._audit(client, tool_name, AuditOutcome.SUCCEEDED, _outcome_note(result))
        return result

    def _is_rate_limited(self, client: AgentClient) -> bool:
        """Count this client's recent tool calls from the audit trail.

        The trail is already written on every call, so it is the natural
        counter and survives a restart — an in-memory tally would reset
        exactly when a crash-looping agent restarted it.
        """
        if self.max_calls_per_window <= 0:
            return False
        since = self.now() - timedelta(seconds=self.window_seconds)
        recent = self.record_audit.audit_repository.count_recent_by_actor(
            client.name, _TOOL_ACTION_PREFIX, since
        )
        return recent >= self.max_calls_per_window

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


# The agent client whose tool call is running, for the handlers that create
# something on its behalf. Set around each call by McpToolRegistry.
current_actor: ContextVar[str | None] = ContextVar("mcp_current_actor", default=None)


def _required(arguments: Mapping[str, Any], key: str) -> Any:
    """A missing argument is the agent's mistake, and the message should say
    which one rather than surface as a bare KeyError."""
    if key not in arguments or arguments[key] is None:
        raise ValueError(f"Argumen '{key}' wajib diisi.")
    return arguments[key]


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
    vehicle_catalog: VehicleCatalog | None = None,
    location_catalog: LocationCatalog | None = None,
    find_similar_operations: FindSimilarOperations | None = None,
    route_preview: RoutePreviewProvider | None = None,
) -> McpToolRegistry:
    """Wire the plan's initial read/compute tools onto existing use cases.

    The catalogs, the similar-history search and the route preview are
    optional only so that a registry can be built for the monitoring tools
    alone; a prediction credential without them gets tool errors that say what
    is missing rather than a registry that quietly lacks the tools.
    """

    def _vehicles() -> VehicleCatalog:
        if vehicle_catalog is None:
            raise RuntimeError("Katalog kendaraan tidak tersedia untuk alat ini.")
        return vehicle_catalog

    def _locations() -> LocationCatalog:
        if location_catalog is None:
            raise RuntimeError("Katalog lokasi tidak tersedia untuk alat ini.")
        return location_catalog

    def _resolved_stops(written: Sequence[str]) -> tuple[str, ...]:
        """Every stop as the catalog spells it, in the planner's order. An
        unknown one raises with candidates, and nothing has been created yet."""
        return tuple(resolve_location(_locations(), name).name for name in written)

    def _similar(
        vehicle: str,
        activity_mode: ActivityMode | None,
        lifting_hours: float | None,
        total_distance_km: float | None,
        limit: int,
        exclude_operation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if find_similar_operations is None or limit <= 0:
            return []
        results = find_similar_operations.execute(
            SimilarOperationsQuery(
                vehicle=vehicle,
                activity_mode=activity_mode,
                lifting_hours=lifting_hours,
                total_distance_km=total_distance_km,
                limit=limit,
                exclude_operation_id=exclude_operation_id,
            )
        )
        return [_similar_operation_payload(item) for item in results]

    def _written_vehicle(arguments: Mapping[str, Any]) -> str:
        """The vehicle is what the model keys on and what history is found by;
        without it the answer would be a fleet average dressed up as a
        recommendation for one unit, so its absence is refused up front."""
        written = arguments.get("vehicle")
        if not isinstance(written, str) or not written.strip():
            raise ValueError(
                "Kendaraan wajib disebutkan ('vehicle'). Gunakan alat list_vehicles "
                "untuk melihat armada yang tersedia."
            )
        return written

    def predict_fuel(arguments: Mapping[str, Any]) -> dict[str, Any]:
        from fuel_predictor.application.daily_operations import CreateDailyOperationCommand

        vehicle = resolve_vehicle(_vehicles(), _written_vehicle(arguments))
        stop_sequence = _resolved_stops(tuple(arguments.get("stop_sequence") or ()))
        raw_distance = arguments.get("total_distance_km")
        activity_mode = ActivityMode(_required(arguments, "activity_mode"))
        lifting_hours = arguments.get("lifting_hours")

        operation = create_operation.execute(
            CreateDailyOperationCommand(
                vehicle_category=VehicleCategory(arguments.get("vehicle_category", "ANGBER")),
                vehicle=vehicle.name,
                activity_mode=activity_mode,
                lifting_hours=lifting_hours,
                total_distance_km=float(raw_distance) if raw_distance is not None else None,
                distance_source=DistanceSource(arguments.get("distance_source", "manual")),
                stop_sequence=stop_sequence,
                created_by=current_actor.get(),
            )
        )
        prediction = generate_prediction.execute(operation.operation_id)
        similar_limit = int(arguments.get("similar_limit", _DEFAULT_SIMILAR_ON_PREDICT))
        return {
            "operation_id": prediction.operation_id,
            # What the planner writes down and later records actual fuel against.
            "operation_code": operation.operation_code,
            "estimated_fuel_requirement_liters": prediction.estimated_fuel_requirement_liters,
            "recommended_allocation_liters": prediction.recommended_allocation_liters,
            "uncertainty_interval_liters": {
                "lower": prediction.uncertainty_lower_liters,
                "upper": prediction.uncertainty_upper_liters,
            },
            "model_version_id": prediction.model.model_version_id,
            "model_code": prediction.model.model_code,
            # Carried deliberately: an agent must be able to tell an estimate
            # of prepared fuel from verified consumption.
            "safety_policy": prediction.safety_policy,
            # What the number was computed from, as resolved — the planner
            # said "truck crane 01" and "SP II"; this is what that became.
            "details": {
                "vehicle": vehicle.name,
                "vehicle_type": vehicle.type or None,
                "vehicle_group": vehicle.group or None,
                "vehicle_category": operation.vehicle_category.value,
                "activity_mode": operation.activity_mode.value,
                "lifting_hours": operation.lifting_hours,
                "total_distance_km": operation.total_distance_km,
                "distance_source": operation.distance_source.value,
                "route_distance_manual_fallback": operation.route_distance_manual_fallback,
                "stop_sequence": list(operation.stop_sequence),
                "model": {
                    "model_version_id": prediction.model.model_version_id,
                    "algorithm": prediction.model.algorithm,
                    "feature_version": prediction.model.feature_version,
                    "trained_at": prediction.model.trained_at.isoformat(),
                    "training_row_count": prediction.model.training_row_count,
                    "uncertainty_liters": prediction.model.uncertainty_liters,
                },
            },
            # Attached to the recommendation rather than left to a second
            # call: history the agent has to remember to ask for is history
            # the planner will sometimes not be shown.
            "similar_operations": _similar(
                vehicle.name,
                operation.activity_mode,
                operation.lifting_hours,
                operation.total_distance_km,
                min(max(similar_limit, 0), _MAX_SIMILAR_ON_PREDICT),
                exclude_operation_id=operation.operation_id,
            ),
        }

    def find_similar(arguments: Mapping[str, Any]) -> dict[str, Any]:
        if find_similar_operations is None:
            raise RuntimeError("Pencarian riwayat serupa tidak tersedia.")
        vehicle = resolve_vehicle(_vehicles(), _written_vehicle(arguments))
        mode = arguments.get("activity_mode")
        distance = arguments.get("total_distance_km")
        lifting = arguments.get("lifting_hours")
        limit = min(max(int(arguments.get("limit", _DEFAULT_SIMILAR)), 0), _MAX_SIMILAR)
        return {
            "vehicle": vehicle.name,
            "vehicle_type": vehicle.type or None,
            "vehicle_group": vehicle.group or None,
            "similar_operations": _similar(
                vehicle.name,
                ActivityMode(mode) if mode is not None else None,
                float(lifting) if lifting is not None else None,
                float(distance) if distance is not None else None,
                limit,
            ),
        }

    def list_vehicles(_arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            {"name": option.name, "group": option.group or None, "aliases": list(option.aliases)}
            for option in _vehicles().options()
        ]

    def search_locations_tool(arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
        limit = min(max(int(arguments.get("limit", 10)), 0), 50)
        return [
            {"name": option.name, "latitude": option.latitude, "longitude": option.longitude}
            for option in search_locations(_locations(), str(_required(arguments, "query")), limit)
        ]

    def estimate_route_distance(arguments: Mapping[str, Any]) -> dict[str, Any]:
        stops = _resolved_stops(tuple(_required(arguments, "stop_sequence")))
        if len(stops) < 2:
            raise ValueError("Urutan pemberhentian harus berisi setidaknya dua lokasi.")
        hint = "Minta jarak total (total_distance_km) kepada perencana untuk melanjutkan."
        if route_preview is None:
            raise RuntimeError(f"Penyedia rute tidak tersedia. {hint}")
        try:
            preview = route_preview.preview_route(stops)
        except RoutingProviderUnavailable as error:
            # Unreachable is, for the agent's next step, the same as absent.
            raise RuntimeError(f"{error} {hint}") from error
        return {
            "stop_sequence": list(stops),
            "total_distance_km": round(preview.total_distance_km, 1),
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
                    "Buat rekomendasi bahan bakar untuk satu operasi harian sebuah kendaraan. "
                    "Kendaraan wajib disebutkan. Mengembalikan estimasi, alokasi yang "
                    "direkomendasikan, rincian masukan yang terpakai, serta operasi lampau "
                    "yang serupa sebagai pembanding. Nilai estimasi adalah bahan bakar "
                    "disiapkan, bukan konsumsi aktual. Sebutkan stop_sequence (termasuk "
                    "perjalanan pulang) agar jarak dihitung dari rute, atau isi "
                    "total_distance_km bila jarak sudah diketahui."
                ),
                scope=AgentScope.PREDICT,
                input_schema=_PREDICT_INPUT_SCHEMA,
                handler=predict_fuel,
            ),
            McpTool(
                name="find_similar_operations",
                description=(
                    "Cari operasi lampau yang mirip dengan spesifikasi yang diminta "
                    "(kendaraan sama, lalu jenis mesin sama, lalu kategori sama; mode "
                    "aktivitas sama; jarak terdekat). Menampilkan bahan bakar disiapkan "
                    "dari riwayat impor serta estimasi dan bahan bakar aktual dari operasi "
                    "yang tercatat. Tidak membuat operasi baru."
                ),
                scope=AgentScope.PREDICT,
                input_schema=_SIMILAR_INPUT_SCHEMA,
                handler=find_similar,
            ),
            McpTool(
                name="list_vehicles",
                description=(
                    "Daftar kendaraan armada beserta jenis mesin dan nama aliasnya. "
                    "Gunakan untuk memastikan nama kendaraan sebelum predict_fuel."
                ),
                scope=AgentScope.PREDICT,
                input_schema=_EMPTY_SCHEMA,
                handler=list_vehicles,
            ),
            McpTool(
                name="search_locations",
                description=(
                    "Cari lokasi pemberhentian dari katalog berdasarkan potongan nama "
                    "(tidak peka huruf besar/kecil, tanda hubung, atau spasi). Gunakan "
                    "untuk memastikan ejaan pemberhentian sebelum predict_fuel."
                ),
                scope=AgentScope.PREDICT,
                input_schema=_SEARCH_LOCATIONS_SCHEMA,
                handler=search_locations_tool,
            ),
            McpTool(
                name="estimate_route_distance",
                description=(
                    "Hitung jarak rute (km) untuk urutan pemberhentian sesuai urutan "
                    "perencana, tanpa membuat operasi. Gagal bila penyedia rute tidak "
                    "dikonfigurasi; saat itu minta jarak total kepada perencana."
                ),
                scope=AgentScope.PREDICT,
                input_schema=_ROUTE_INPUT_SCHEMA,
                handler=estimate_route_distance,
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

_ACTIVITY_MODES = ["transport", "lifting", "transport_and_lifting"]

_PREDICT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vehicle", "activity_mode"],
    "properties": {
        "vehicle": {
            "type": "string",
            "description": (
                "Nama kendaraan sebagaimana disebut perencana, misalnya 'Truck Crane 01' "
                "atau alias 'T CRANE 01'. Lihat list_vehicles."
            ),
        },
        "activity_mode": {"type": "string", "enum": _ACTIVITY_MODES},
        "lifting_hours": {
            "type": ["number", "null"],
            "minimum": 0,
            "description": "Wajib untuk mode yang mencakup lifting.",
        },
        "stop_sequence": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "description": (
                "Pemberhentian sesuai urutan perencana, termasuk perjalanan pulang bila "
                "kendaraan kembali, misalnya ['POOL LIMAU', 'SP-II', 'POOL LIMAU']. "
                "Nama dicocokkan ke katalog lokasi; lihat search_locations."
            ),
        },
        "total_distance_km": {
            "type": ["number", "null"],
            "exclusiveMinimum": 0,
            "description": (
                "Jarak total bila sudah diketahui, atau cadangan bila rute tidak dapat "
                "dihitung. Wajib bila stop_sequence tidak diberikan."
            ),
        },
        "vehicle_category": {"type": "string", "enum": ["ANGBER"], "default": "ANGBER"},
        "distance_source": {"type": "string", "enum": ["manual", "routing_provider"]},
        "similar_limit": {
            "type": "integer",
            "minimum": 0,
            "maximum": 20,
            "default": 5,
            "description": "Berapa operasi lampau serupa yang disertakan.",
        },
    },
}

_SIMILAR_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vehicle"],
    "properties": {
        "vehicle": {"type": "string"},
        "activity_mode": {"type": ["string", "null"], "enum": [*_ACTIVITY_MODES, None]},
        "lifting_hours": {"type": ["number", "null"], "minimum": 0},
        "total_distance_km": {"type": ["number", "null"], "exclusiveMinimum": 0},
        "limit": {"type": "integer", "minimum": 0, "maximum": 50, "default": 10},
    },
}

_SEARCH_LOCATIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "minLength": 2},
        "limit": {"type": "integer", "minimum": 0, "maximum": 50, "default": 10},
    },
}

_ROUTE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["stop_sequence"],
    "properties": {
        "stop_sequence": {"type": "array", "items": {"type": "string"}, "minItems": 2},
    },
}

_DEFAULT_SIMILAR_ON_PREDICT = 5
_MAX_SIMILAR_ON_PREDICT = 20
_DEFAULT_SIMILAR = 10
_MAX_SIMILAR = 50


def _similar_operation_payload(item: SimilarOperation) -> dict[str, Any]:
    record = item.record
    return {
        "source": record.source.value,
        "operation_id": record.operation_id,
        "vehicle": record.vehicle,
        "vehicle_type": item.vehicle_type,
        "vehicle_group": item.vehicle_group,
        "activity_mode": record.activity_mode.value,
        "lifting_hours": record.lifting_hours,
        "total_distance_km": record.total_distance_km,
        "distance_source": record.distance_source.value,
        "stop_sequence": list(record.stop_sequence) if record.stop_sequence else None,
        "prepared_fuel_liters": record.prepared_fuel_liters,
        "estimated_fuel_requirement_liters": record.estimated_fuel_requirement_liters,
        "recommended_allocation_liters": record.recommended_allocation_liters,
        "actual_fuel_liters": record.actual_fuel_liters,
        "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
        "operation_date": record.operation_date,
        "source_reference": record.source_reference,
        "match": {
            "vehicle": item.match.vehicle.value,
            "activity_mode": item.match.activity_mode,
            "distance_delta_km": item.match.distance_delta_km,
            "lifting_hours_delta": item.match.lifting_hours_delta,
            "score": item.match.score,
        },
    }


def tool_result_to_text(result: Any) -> str:
    """MCP content is text; serialise deterministically so results diff cleanly."""
    return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
