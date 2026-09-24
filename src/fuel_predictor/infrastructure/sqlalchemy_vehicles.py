from sqlalchemy import select

from fuel_predictor.application.vehicles import LineageIndex, VehicleLineage, VehicleOption
from fuel_predictor.infrastructure.database import SessionFactory, VehicleRow


class SqlAlchemyVehicleRepository:
    """Serves the fleet out of the `vehicles` table."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def _all(self) -> tuple[VehicleOption, ...]:
        with self._session_factory() as session:
            rows = session.execute(select(VehicleRow).order_by(VehicleRow.name)).scalars().all()
        return tuple(
            VehicleOption(
                name=row.name,
                group=row.vehicle_group,
                aliases=tuple(row.aliases or ()),
                type=row.vehicle_type,
                group_code=row.group_code,
                type_code=row.type_code,
            )
            for row in rows
        )

    def options(self) -> tuple[VehicleOption, ...]:
        return self._all()

    def find(self, name: str) -> VehicleOption | None:
        """Matched on any spelling the sheets use, so imported history resolves
        to one vehicle rather than fragmenting across its aliases."""
        return LineageIndex(self._all()).find(name)

    def lineage_of(self, name: str | None) -> VehicleLineage:
        return LineageIndex(self._all()).lineage_of(name)

    def replace_all(self, vehicles: tuple[VehicleOption, ...]) -> int:
        """Reload from the sheet export, in one transaction.

        A wholesale replace rather than an upsert: the sheet is the source of
        truth, so a vehicle retired there must disappear here too.
        """
        with self._session_factory() as session:
            session.query(VehicleRow).delete()
            session.add_all(
                VehicleRow(
                    name=vehicle.name,
                    vehicle_group=vehicle.group,
                    vehicle_type=vehicle.type,
                    aliases=list(vehicle.aliases),
                    group_code=vehicle.group_code,
                    type_code=vehicle.type_code,
                )
                for vehicle in vehicles
            )
            session.commit()
        return len(vehicles)
