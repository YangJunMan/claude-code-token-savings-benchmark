import json

import pytest

from token_bench.models import DEFAULT_MODELS_PATH, ModelsError, active_model


def _write(tmp_path, models):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"schema_version": 1, "models": models}), encoding="utf-8")
    return path


def test_returns_the_single_active_model(tmp_path):
    path = _write(tmp_path, [
        {"id": "old", "status": "frozen"},
        {"id": "new", "status": "active"},
    ])
    assert active_model(path) == "new"


@pytest.mark.parametrize("models", [
    [],
    [{"id": "a", "status": "frozen"}],
    [{"id": "a", "status": "active"}, {"id": "b", "status": "active"}],
    [{"id": "a", "status": "active"}, {"id": "a", "status": "frozen"}],
    [{"id": "a", "status": "retired"}],
])
def test_rejects_anything_but_exactly_one_active_model(tmp_path, models):
    with pytest.raises(ModelsError):
        active_model(_write(tmp_path, models))


def test_checked_in_models_json_is_valid():
    assert active_model(DEFAULT_MODELS_PATH)
