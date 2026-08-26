"""Shared test configuration.

Most tests here exercise domain and API behaviour rather than authentication,
and they build an application with no accounts in it. That used to work because
an empty users table meant "serve everyone as an administrator".

Production now defaults to the opposite — an empty users table locks everybody
out, so a deployment that loses its accounts fails closed instead of silently
opening (`ApplicationSettings.allow_unprovisioned_access`). Restoring the
permissive behaviour for the suite in one place keeps those tests focused on
what they are actually about, without weakening the production default.

Tests that care about the closed behaviour set the flag themselves, so this
does not hide it — see `test_unprovisioned_access.py`.
"""

import pytest


@pytest.fixture(autouse=True)
def allow_unprovisioned_access_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUEL_PREDICTOR_ALLOW_UNPROVISIONED_ACCESS", "true")
