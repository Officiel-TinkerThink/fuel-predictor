"""SQLite must enforce foreign keys, because PostgreSQL always does.

SQLite ignores foreign keys unless each connection opts in. Production runs on
PostgreSQL, which does not. That gap let the suite accept dangling references
that made real requests fail with a 500 — a model package upload, and data
quality issues written against a dataset whose own row had not been renamed
yet. Both passed every test.

A test suite that accepts what production rejects is not testing production.
These pin the setting so it cannot be quietly dropped again.
"""

from pathlib import Path

import pytest
import sqlalchemy

from fuel_predictor.infrastructure.database import (
    build_engine,
    build_session_factory,
    create_schema_for_tests,
)


@pytest.fixture
def engine(tmp_path: Path) -> sqlalchemy.Engine:
    built = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'fk.sqlite3').as_posix()}")
    create_schema_for_tests(built)
    return built


def test_the_pragma_is_on_for_every_connection(engine: sqlalchemy.Engine) -> None:
    """Per-connection, not per-database — a new pooled connection must have it too."""
    for _ in range(3):
        with engine.connect() as connection:
            assert connection.execute(sqlalchemy.text("PRAGMA foreign_keys")).scalar_one() == 1


def test_a_dangling_reference_is_rejected(engine: sqlalchemy.Engine) -> None:
    """The behaviour the pragma buys, stated as a fact rather than a setting."""
    factory = build_session_factory(engine)

    with pytest.raises(sqlalchemy.exc.IntegrityError), factory.begin() as session:
        session.execute(
            sqlalchemy.text(
                "INSERT INTO data_quality_issues"
                " (dataset_version_id, sheet_name, row_number, original_headers,"
                "  reasons, raw_values)"
                " VALUES ('DSV-tidak-ada', 'CSV', 1, '{}', '[]', '{}')"
            )
        )


def test_a_model_version_may_name_a_dataset_this_deployment_does_not_have(
    engine: sqlalchemy.Engine,
) -> None:
    """The one reference that is deliberately not a foreign key (Alembic 20260827_13).

    An ingested package's manifest names a dataset from the *builder's*
    environment. Constraining it to ours made package upload fail with a 500 on
    PostgreSQL, so the column is provenance and carries no constraint — and
    enforcement being on must not bring that back.
    """
    factory = build_session_factory(engine)

    with factory.begin() as session:
        session.execute(
            sqlalchemy.text(
                "INSERT INTO model_versions"
                " (model_version_id, dataset_version_id, feature_version, algorithm,"
                "  artifact_uri, trained_at, training_row_count, uncertainty_liters,"
                "  lifecycle_status)"
                " VALUES ('MDL-luar', 'DSV-milik-pembuat', 'baseline-v1', 'linear_regression',"
                "  '/x', '2026-08-27T00:00:00+00:00', 0, 1.0, 'candidate')"
            )
        )

    with engine.connect() as connection:
        stored = connection.execute(
            sqlalchemy.text(
                "SELECT dataset_version_id FROM model_versions WHERE model_version_id = 'MDL-luar'"
            )
        ).scalar_one()
    assert stored == "DSV-milik-pembuat"
