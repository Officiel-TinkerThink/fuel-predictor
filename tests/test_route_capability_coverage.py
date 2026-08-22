"""Every real route must be either public or covered by ROUTE_CAPABILITIES.

The middleware in delivery/security.py only *enforces* a capability when
ROUTE_CAPABILITIES has an entry for a route; an authenticated caller reaching
a route with no entry is currently waved through regardless of role. That is
exactly how POST /dataset-versions/{id}/latih-kandidat-baseline went
unprotected until it was noticed by inspection while migrating pages (see
docs/production/implementation-progress.md). This test walks the app's real
route table so the next such gap fails a test instead of waiting to be
noticed by hand.
"""

from pathlib import Path

import pytest

from fuel_predictor.delivery.security import ROUTE_CAPABILITIES, _is_public, _required_capability
from fuel_predictor.main import create_app


def _declared_routes(tmp_path: Path) -> list[tuple[str, str]]:
    """(method, path) for every route FastAPI actually serves.

    Reads the generated OpenAPI schema rather than walking `app.routes`
    directly: this FastAPI version wraps included routers in an internal
    `_IncludedRouter` object instead of exposing flat `APIRoute` instances at
    the top level, so `app.routes` doesn't reflect the real route table. The
    schema is the stable, version-independent way to enumerate what's
    actually registered.
    """
    app = create_app(database_path=tmp_path / "operations.sqlite3")
    paths = app.openapi()["paths"]
    return [
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    ]


def test_every_non_public_route_has_a_route_capabilities_entry(tmp_path: Path) -> None:
    uncovered = [
        (method, path)
        for method, path in _declared_routes(tmp_path)
        if not _is_public(path) and _required_capability(method, path) is None
    ]
    assert uncovered == []


def test_every_route_capabilities_entry_matches_a_real_route(tmp_path: Path) -> None:
    declared = _declared_routes(tmp_path)
    stale = [
        (method, pattern)
        for method, pattern, _capability in ROUTE_CAPABILITIES
        if not any(
            method == declared_method and _pattern_matches(pattern, declared_path)
            for declared_method, declared_path in declared
        )
    ]
    assert stale == []


def _pattern_matches(pattern: str, path: str) -> bool:
    pattern_segments = [segment for segment in pattern.split("/") if segment]
    path_segments = [segment for segment in path.split("/") if segment]
    if len(pattern_segments) != len(path_segments):
        return False
    return all(
        pattern_segment == "*" or pattern_segment == path_segment
        for pattern_segment, path_segment in zip(pattern_segments, path_segments, strict=True)
    )


@pytest.mark.parametrize(
    ("method", "pattern", "capability"),
    ROUTE_CAPABILITIES,
    ids=[f"{method} {pattern}" for method, pattern, _capability in ROUTE_CAPABILITIES],
)
def test_route_capabilities_table_has_no_duplicate_entries(
    method: str, pattern: str, capability: object
) -> None:
    matches = [
        entry for entry in ROUTE_CAPABILITIES if entry[0] == method and entry[1] == pattern
    ]
    assert len(matches) == 1, (
        f"{method} {pattern} appears {len(matches)} times in ROUTE_CAPABILITIES; "
        "the first match wins silently, which hides the duplicate's real capability."
    )
