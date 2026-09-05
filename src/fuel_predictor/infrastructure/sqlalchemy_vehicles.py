from sqlalchemy import select

from fuel_predictor.application.vehicles import VehicleOption
from fuel_predictor.infrastructure.database import SessionFactory, VehicleRow


def _keys(option: VehicleOption) -> tuple[str, ...]:
    written = (option.name, *option.aliases)
    return tuple(name.casefold().replace(" ", "") for name in written if name)


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
            )
            for row in rows
        )

    def options(self) -> tuple[VehicleOption, ...]:
        return self._all()

    def find(self, name: str) -> VehicleOption | None:
        """Matched on any spelling the sheets use, so imported history resolves
        to one vehicle rather than fragmenting across its aliases."""
        wanted = name.strip().casefold().replace(" ", "")
        for option in self._all():
            if wanted in _keys(option):
                return option
        return None

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
                    aliases=list(vehicle.aliases),
                )
                for vehicle in vehicles
            )
            session.commit()
        return len(vehicles)
