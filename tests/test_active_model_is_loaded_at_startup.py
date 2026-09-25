"""The active model is loaded when the app starts, not by its first user.

Loading it imports the model format's library, which takes seconds; the
first estimate - or the first overview an administrator opened - after every
deploy waited for it. The scorer now loads a model when asked to warm it
(before, "warming" only built a closure and loading still waited for the
first prediction), and the app warms the active model on startup.
"""

import logging
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from fuel_predictor.infrastructure.stored_model_scorer import StoredModelScorer
from fuel_predictor.main import _warm_active_model


class _Store:
    def __init__(self) -> None:
        self.loads: list[str] = []

    def train(self, model_version_id: str, operations: Sequence[Any]) -> tuple[str, float]:
        raise NotImplementedError

    def predict(self, artifact_uri: str, features: dict[str, str | float]) -> float:
        raise AssertionError("the scorer predicts through what it loaded")

    def load(self, artifact_uri: str) -> Any:
        self.loads.append(artifact_uri)
        return lambda features: 12.5


class _NoPackages:
    def exists(self, model_version: str) -> bool:
        return False

    def read_members(self, model_version: str) -> dict[str, bytes]:
        raise AssertionError


def _scorer(store: _Store) -> StoredModelScorer:
    return StoredModelScorer(store, _NoPackages(), None, None)  # type: ignore[arg-type]


def test_warming_loads_the_model_once_and_predicting_reuses_it() -> None:
    store = _Store()
    scorer = _scorer(store)

    scorer.warm("runs:/aktif/model")
    assert store.loads == ["runs:/aktif/model"]
    assert scorer.predict("runs:/aktif/model", {"total_distance_km": 30}) == 12.5
    assert store.loads == ["runs:/aktif/model"]


def test_startup_warms_the_active_model_and_nothing_without_one() -> None:
    store = _Store()
    scorer = _scorer(store)

    _warm_active_model(SimpleNamespace(get_active=lambda: None), scorer)  # type: ignore[arg-type]
    assert store.loads == []
    active = SimpleNamespace(artifact_uri="runs:/aktif/model")
    _warm_active_model(SimpleNamespace(get_active=lambda: active), scorer)  # type: ignore[arg-type]
    assert store.loads == ["runs:/aktif/model"]


def test_a_model_that_fails_to_load_does_not_stop_the_app_starting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Broken:
        def warm(self, artifact_uri: str) -> None:
            raise OSError("artefak hilang")

    active = SimpleNamespace(artifact_uri="runs:/hilang/model")
    with caplog.at_level(logging.WARNING):
        _warm_active_model(SimpleNamespace(get_active=lambda: active), Broken())  # type: ignore[arg-type]

    assert "Model aktif gagal dimuat saat aplikasi mulai" in caplog.text
