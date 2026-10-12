"""Shared pytest configuration."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "corpus: corpus-wide test (needs lxml), run by default; SR_SCENE_CORPUS=0 skips it")
