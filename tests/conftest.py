"""Shared pytest configuration."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "corpus: corpus-wide test, run only with SR_SCENE_CORPUS=1 (needs lxml)")
