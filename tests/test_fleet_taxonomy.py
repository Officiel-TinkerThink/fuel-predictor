"""The fleet catalog carries the owner's real taxonomy, with a short code at
every level, and agrees with the "Data Ratio" sheet it was synced from.

The type level used to be a placeholder - every unit's type was its group. The
owner's sheet names each unit's machine ("Type Kendaraan"): the vacuum trucks
alone are four different trucks. Group and type each get a short code, so a
vehicle code reads group - type - unit: `VT-P410-VT01`.
"""

import csv
import re
from pathlib import Path

import pytest

from fuel_predictor.application.vehicles import VehicleCatalogError, VehicleOption
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.packaged_vehicle_catalog import PackagedVehicleCatalog
from fuel_predictor.infrastructure.sqlalchemy_vehicles import SqlAlchemyVehicleRepository

_DATA_RATIO = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "fuel_predictor"
    / "examples"
    / "data-ratio-angber.csv"
)


def _data_ratio_units() -> list[tuple[str, str]]:
    """(name as the sheet writes it, type) for every unit the Data Ratio tab lists.

    The tab holds two blocks (heavy equipment, vacuum trucks), each under its
    own header; a unit row starts with its number. The vacuum trucks carry
    their size after the name - "VT 01 - 12 Ton 6x6" - which is not part of it.
    """
    with _DATA_RATIO.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    units = []
    for row in rows:
        if row and re.fullmatch(r"\d+(\.0)?", row[0].strip()):
            name = row[1].split(" - ")[0].strip()
            units.append((name, row[2].strip()))
    return units


def test_every_unit_in_the_data_ratio_sheet_is_in_the_catalog_with_its_type() -> None:
    catalog = PackagedVehicleCatalog()
    units = _data_ratio_units()

    assert len(units) == 19
    for written, sheet_type in units:
        option = catalog.find(written)
        assert option is not None, f"{written!r} from the Data Ratio sheet is not in the catalog"
        assert option.type == sheet_type, written


@pytest.mark.parametrize(
    ("written", "unit"),
    [
        ("PM 01", "Prime Mover"),
        ("OFT Tronton", "Oil Field Truck"),
        ("Tronton OFT", "Oil Field Truck"),
        ("OFT Winch Truck", "Winch Truck"),
        ("Whinch Truck OFT", "Winch Truck"),
        ("Whellcrane", "Wheel Crane"),
        ("SCM", "Forklift SCM"),
    ],
)
def test_the_sheets_spellings_resolve_to_the_catalog_unit(written: str, unit: str) -> None:
    option = PackagedVehicleCatalog().find(written)

    assert option is not None
    assert option.name == unit


@pytest.mark.parametrize(
    ("unit", "code"),
    [
        ("VT 01", "VT-P410-VT01"),
        ("VT 05", "VT-UDQ-VT05"),
        ("VT 09", "VT-FE-VT09"),
        ("VT 10", "VT-P380-VT10"),
        ("Truck Crane 01", "CR-P410B-TC01"),
        ("Wheel Crane", "CR-KATO-WC"),
        ("Prime Mover", "TR-P460-PM"),
        ("Oil Field Truck", "TR-HINO-OFT"),
        ("Winch Truck", "TR-P410CB-WT"),
        # Not in the sheet: its type is only its group, so the code skips it.
        ("VT 14", "VT-VT14"),
        ("Forklift SCM", "FL-FSCM"),
    ],
)
def test_the_vehicle_code_reads_group_type_unit(unit: str, code: str) -> None:
    option = PackagedVehicleCatalog().find(unit)

    assert option is not None
    assert option.vehicle_code == code


def test_every_bundled_vehicle_code_is_unique() -> None:
    codes = [option.vehicle_code for option in PackagedVehicleCatalog().options()]

    assert len(codes) == len(set(codes))


def _catalog(tmp_path: Path, body: str) -> Path:
    source = tmp_path / "kendaraan.csv"
    source.write_text("nama_kendaraan,grup,kode_grup,tipe,kode_tipe,alias\n" + body)
    return source


def test_one_type_with_two_codes_is_refused(tmp_path: Path) -> None:
    source = _catalog(
        tmp_path,
        "VT 01,Vacuum Truck,VT,Scania P410 6X6,P410,\n"
        "VT 02,Vacuum Truck,VT,Scania P410 6X6,S410,\n",
    )

    with pytest.raises(VehicleCatalogError, match="VT 02"):
        PackagedVehicleCatalog(source)


def test_one_group_with_two_codes_is_refused(tmp_path: Path) -> None:
    source = _catalog(
        tmp_path,
        "VT 01,Vacuum Truck,VT,Scania P410 6X6,P410,\n"
        "VT 02,Vacuum Truck,VAC,Scania P410 6X6,P410,\n",
    )

    with pytest.raises(VehicleCatalogError, match="VT 02"):
        PackagedVehicleCatalog(source)


def test_a_code_must_be_capitals_and_digits(tmp_path: Path) -> None:
    source = _catalog(tmp_path, "VT 01,Vacuum Truck,VT,Scania P410 6X6,p-410,\n")

    with pytest.raises(VehicleCatalogError, match="VT 01"):
        PackagedVehicleCatalog(source)


def test_a_real_type_needs_a_code(tmp_path: Path) -> None:
    """A type that is only the group needs none; one the owner named does, or
    the code could not tell two vacuum trucks of different makes apart."""
    source = _catalog(tmp_path, "VT 01,Vacuum Truck,VT,Scania P410 6X6,,\n")

    with pytest.raises(VehicleCatalogError, match="kode_tipe"):
        PackagedVehicleCatalog(source)


def test_the_codes_round_trip_through_the_vehicles_table(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'fleet.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    repository = SqlAlchemyVehicleRepository(build_session_factory(engine))

    repository.replace_all(PackagedVehicleCatalog().options())
    stored = repository.find("oft tronton")

    assert stored == VehicleOption(
        name="Oil Field Truck",
        group="Truck",
        aliases=stored.aliases if stored else (),
        type="HINO FM 260",
        group_code="TR",
        type_code="HINO",
    )
