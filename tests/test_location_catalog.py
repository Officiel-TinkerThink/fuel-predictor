from importlib import resources
from pathlib import Path

from fuel_predictor.application.locations import LocationOption
from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)
from fuel_predictor.infrastructure.packaged_location_catalog import PackagedLocationCatalog
from fuel_predictor.infrastructure.sqlalchemy_locations import SqlAlchemyLocationRepository

_PACKAGE_ROOT = Path(str(resources.files("fuel_predictor")))


def _repository(tmp_path: Path) -> SqlAlchemyLocationRepository:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'locations.sqlite3').as_posix()}")
    create_schema_for_tests(engine)
    return SqlAlchemyLocationRepository(build_session_factory(engine))


def test_the_seed_export_is_packaged_data() -> None:
    from fuel_predictor.infrastructure.packaged_location_catalog import _CATALOG_PATH

    assert _CATALOG_PATH.is_file()
    assert _PACKAGE_ROOT in _CATALOG_PATH.parents


def test_the_seed_export_holds_every_location_from_data_lokasi() -> None:
    options = PackagedLocationCatalog().options()

    assert len(options) > 1000
    assert len(options) == len({option.name for option in options})


def test_importing_the_seed_fills_the_table(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    seed = PackagedLocationCatalog().options()

    imported = repository.replace_all(seed)

    assert imported == len(seed)
    assert len(repository.options()) == len(seed)


def test_stored_locations_come_back_in_name_order(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.replace_all(
        (
            LocationOption(name="TAMBANG", latitude=-3.2, longitude=104.3),
            LocationOption(name="DEPO", latitude=-3.1, longitude=104.2),
        )
    )

    assert [option.name for option in repository.options()] == ["DEPO", "TAMBANG"]


def test_find_resolves_a_stored_point_case_and_whitespace_insensitively(tmp_path: Path) -> None:
    warehouse = LocationOption(name="WAREHOUSE", latitude=-3.536389, longitude=104.308056)
    repository = _repository(tmp_path)
    repository.replace_all((warehouse,))

    exact = repository.find("WAREHOUSE")
    loose = repository.find(" warehouse \n")

    assert exact == warehouse
    assert loose == exact


def test_find_returns_none_for_an_unlisted_name(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.replace_all((LocationOption(name="DEPO", latitude=-3.1, longitude=104.2),))

    assert repository.find("Somewhere Not In The Sheet") is None


def test_reimporting_drops_points_the_sheet_no_longer_has(tmp_path: Path) -> None:
    """The sheet is the source of truth, so a deleted point must not linger."""
    repository = _repository(tmp_path)
    repository.replace_all(
        (
            LocationOption(name="DEPO", latitude=-3.1, longitude=104.2),
            LocationOption(name="RETIRED SITE", latitude=-3.9, longitude=104.9),
        )
    )

    repository.replace_all((LocationOption(name="DEPO", latitude=-3.1, longitude=104.2),))

    assert [option.name for option in repository.options()] == ["DEPO"]
    assert repository.find("RETIRED SITE") is None
