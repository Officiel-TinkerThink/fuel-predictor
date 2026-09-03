from sqlalchemy import func, select

from fuel_predictor.application.locations import LocationOption
from fuel_predictor.infrastructure.database import LocationRow, SessionFactory


class SqlAlchemyLocationRepository:
    """Serves the location catalog out of the `locations` table."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def options(self) -> tuple[LocationOption, ...]:
        with self._session_factory() as session:
            rows = session.execute(select(LocationRow).order_by(LocationRow.name)).scalars().all()
        return tuple(
            LocationOption(name=row.name, latitude=row.latitude, longitude=row.longitude)
            for row in rows
        )

    def find(self, name: str) -> LocationOption | None:
        cleaned = name.strip()
        with self._session_factory() as session:
            row = session.execute(
                select(LocationRow).where(
                    func.lower(LocationRow.name) == func.lower(cleaned),
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return LocationOption(name=row.name, latitude=row.latitude, longitude=row.longitude)

    def replace_all(self, locations: tuple[LocationOption, ...]) -> int:
        """Reload the catalog from the sheet export, in one transaction.

        A wholesale replace rather than an upsert: the sheet is the source of
        truth, so a point deleted there must disappear here too.
        """
        with self._session_factory() as session:
            session.query(LocationRow).delete()
            session.add_all(
                LocationRow(
                    name=location.name,
                    latitude=location.latitude,
                    longitude=location.longitude,
                )
                for location in locations
            )
            session.commit()
        return len(locations)
