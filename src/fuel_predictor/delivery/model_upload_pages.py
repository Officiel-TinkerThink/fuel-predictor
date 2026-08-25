"""Uploading and reviewing external model packages (Phase 2 UI).

Upload never activates anything (ADR 0004). A package that validates and
clears the promotion policy becomes an *eligible candidate*; making it the
active model stays a separate, deliberate act on the model governance page.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse

from fuel_predictor.application.model_package_records import (
    ModelPackageValidationRecord,
    ModelPackageValidationRepository,
    ValidationOutcome,
)
from fuel_predictor.application.model_package_validation import ValidateModelPackage
from fuel_predictor.application.retained_package_activation import RegisterIngestedPackage
from fuel_predictor.delivery.rendering import render
from fuel_predictor.delivery.security import SecurityGuard
from fuel_predictor.domain.model_package import ModelPackageValidationError
from fuel_predictor.domain.prediction import ModelLifecycleStatus, ModelVersion

if TYPE_CHECKING:
    from fuel_predictor.application.identity import ActiveCaller

_UPLOAD_FILE = File(...)

_PAGE_LEAD = (
    "Unggah paket model (.zip) dari lingkungan pelatihan. Paket diperiksa lengkap sebelum "
    "diterima; mengunggah tidak pernah langsung mengaktifkan model."
)


@dataclass(frozen=True, slots=True)
class ArtifactStore:
    """Minimal shape the upload flow needs from a store."""

    store: Any


def build_model_upload_pages_router(
    validate_package: ValidateModelPackage,
    validation_records: ModelPackageValidationRepository,
    artifact_store: Any,
    register_package: RegisterIngestedPackage,
    guard: SecurityGuard,
) -> APIRouter:
    router = APIRouter()

    @router.get("/model/unggah", response_class=HTMLResponse)
    def show_upload(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_upload(guard.require_caller(request), None))

    @router.post("/model/unggah", response_class=HTMLResponse)
    async def submit_upload(request: Request, file: UploadFile = _UPLOAD_FILE) -> HTMLResponse:
        caller = guard.require_caller(request)
        archive_bytes = await file.read()
        validation_id = f"VAL-{uuid4().hex[:20]}"
        now = datetime.now(UTC)

        try:
            validated = validate_package.execute(
                archive_bytes,
                active_metrics=None,
                probe_version=_probe_version(),
            )
        except ModelPackageValidationError as error:
            # Recorded before the response is rendered: a rejection is the
            # thing an operator asks about later, and it must survive even
            # though nothing was accepted.
            validation_records.add(
                ModelPackageValidationRecord(
                    validation_id=validation_id,
                    model_version="(tidak diketahui)",
                    validated_at=now,
                    actor=caller.user.username,
                    outcome=ValidationOutcome.REJECTED,
                    eligible=False,
                    reasons=tuple(f"{field}: {message}" for field, message in error.errors),
                    warnings=(),
                )
            )
            return HTMLResponse(
                _render_upload(caller, error.errors),
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        stored_path = artifact_store.store(
            validated.manifest.model_version, dict(validated.members)
        )
        # Registered as a candidate straight away. Retained bytes with no model
        # version row are unreachable: nothing could activate them, and nothing
        # could roll back to them.
        register_package.execute(validated.manifest, artifact_uri=str(stored_path))
        validation_records.add(
            ModelPackageValidationRecord(
                validation_id=validation_id,
                model_version=validated.manifest.model_version,
                validated_at=now,
                actor=caller.user.username,
                outcome=ValidationOutcome.VALIDATED,
                eligible=validated.eligibility.eligible,
                reasons=validated.eligibility.reasons,
                warnings=validated.eligibility.warnings,
                artifact_path=str(stored_path),
            )
        )

        return HTMLResponse(
            render(
                "model-unggah-selesai.html",
                caller=caller,
                page_title="Paket Model Diterima",
                active_path="/model/unggah",
                eyebrow="VALIDASI SELESAI",
                page_lead="Paket lolos pemeriksaan. Aktivasi tetap merupakan tindakan manual.",
                manifest=validated.manifest,
                eligibility=validated.eligibility,
            ),
            status_code=status.HTTP_201_CREATED,
        )

    @router.get("/model/riwayat", response_class=HTMLResponse)
    def show_history(request: Request) -> HTMLResponse:
        caller = guard.require_caller(request)
        return HTMLResponse(
            render(
                "model-riwayat.html",
                caller=caller,
                page_title="Riwayat Paket Model",
                active_path="/model/riwayat",
                eyebrow="TATA KELOLA MODEL",
                page_lead="Setiap unggahan tercatat, termasuk yang ditolak beserta alasannya.",
                records=validation_records.list_recent(100),
            )
        )

    return router


def _render_upload(
    caller: "ActiveCaller", errors: tuple[tuple[str, str], ...] | None
) -> str:
    return render(
        "model-unggah.html",
        caller=caller,
        page_title="Unggah Kandidat Model",
        active_path="/model/unggah",
        eyebrow="TATA KELOLA MODEL",
        page_lead=_PAGE_LEAD,
        errors=[{"field": field, "message": message} for field, message in (errors or ())],
    )


def _probe_version() -> ModelVersion:
    """A throwaway identity used only to load the candidate during validation.

    The real `ModelVersion` is created when an administrator activates the
    package; validation must not mint one, because that would imply the
    candidate had been accepted into the lifecycle before anyone decided so.
    """
    return ModelVersion(
        model_version_id="MDL-VALIDATION-PROBE",
        version=0,
        dataset_version_id="(validasi)",
        feature_version="(validasi)",
        algorithm="(validasi)",
        artifact_uri="memory://validation",
        trained_at=datetime.now(UTC),
        training_row_count=0,
        uncertainty_liters=0.0,
        lifecycle_status=ModelLifecycleStatus.CANDIDATE,
    )
