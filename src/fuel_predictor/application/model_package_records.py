"""Recording what happened to an uploaded package (plan validation step 9).

Every upload leaves a record, accepted or refused. A rejection is often the
more useful of the two later: "why was this package turned away?" is a
question someone asks days afterwards, and it can only be answered if the
refusal was written down at the time.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class ValidationOutcome(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ModelPackageValidationRecord:
    validation_id: str
    model_version: str
    validated_at: datetime
    actor: str
    outcome: ValidationOutcome
    eligible: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest: dict[str, Any] | None = None
    artifact_path: str | None = None

    @property
    def was_accepted(self) -> bool:
        return self.outcome is ValidationOutcome.VALIDATED


class ModelPackageValidationRepository(Protocol):
    def add(self, record: ModelPackageValidationRecord) -> None: ...

    def list_recent(self, limit: int) -> Sequence[ModelPackageValidationRecord]: ...

    def get(self, validation_id: str) -> ModelPackageValidationRecord | None: ...
