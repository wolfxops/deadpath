from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path_factory, monkeypatch):
    """Keep .deadpath/memory.json out of the fixtures directory during tests."""
    memory_dir = tmp_path_factory.mktemp("deadpath-memory")
    monkeypatch.setenv("DEADPATH_MEMORY_DIR", str(memory_dir))
    yield memory_dir
