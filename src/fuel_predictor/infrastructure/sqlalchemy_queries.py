"""Query fragments that more than one repository needs."""

from sqlalchemy import ScalarSelect, select
from sqlalchemy.orm import InstrumentedAttribute

from fuel_predictor.infrastructure.database import DailyOperationRow, PredictionRow


def latest_prediction_id(
    operation_id: InstrumentedAttribute[str] = DailyOperationRow.operation_id,
) -> ScalarSelect[str]:
    """The id of an operation's newest prediction, correlated to the row the
    enclosing query holds the operation's id on - the operation itself, or an
    actual-fuel record of it.

    An operation estimated again keeps every prediction it was given; the
    waiting list, the history, the overdue check, similar days and the
    measured error all read the last one."""
    return (
        select(PredictionRow.prediction_id)
        .where(PredictionRow.operation_id == operation_id)
        .order_by(PredictionRow.created_at.desc(), PredictionRow.prediction_id.desc())
        .limit(1)
        .correlate(operation_id.class_)
        .scalar_subquery()
    )
